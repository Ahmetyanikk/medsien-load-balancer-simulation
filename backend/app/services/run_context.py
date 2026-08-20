from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional, Sequence

from ..domain.errors import InvalidServerSpecError, RunContextPublicationError
from ..domain.models import ServerSpec

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

_REQUIRED_SERVER_FIELDS = frozenset({"id", "cpu_units_per_tick", "mem_mb", "rate_limit_per_sec"})


def _parse_verified_server(raw: object) -> Optional[ServerSpec]:
    """Strict schema validation for one server entry in a verified context
    snapshot. No int()/coercion of any kind: numeric fields must already be
    JSON numbers of Python type int (type(value) is int explicitly rejects
    bool, since bool is a subclass of int) — never a numeric string, float,
    or bool. Returns None (never raises) for any violation; the caller logs
    and degrades the whole context to unavailable rather than accepting a
    partially-valid snapshot.
    """
    if not isinstance(raw, dict):
        return None
    if set(raw.keys()) != _REQUIRED_SERVER_FIELDS:
        return None

    sid = raw["id"]
    if not isinstance(sid, str) or not sid.strip():
        return None

    cpu, mem, rate = raw["cpu_units_per_tick"], raw["mem_mb"], raw["rate_limit_per_sec"]
    if type(cpu) is not int or type(mem) is not int or type(rate) is not int:
        return None
    if cpu <= 0 or mem < 0 or rate < 0:
        return None

    try:
        return ServerSpec(id=sid, cpu_units_per_tick=cpu, mem_mb=mem, rate_limit_per_sec=rate)
    except InvalidServerSpecError:
        return None


def _atomic_write_json(path: Path, payload: dict) -> None:
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".run-context-", suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
        os.replace(tmp_path, path)
    except BaseException:
        # Clean up the temp file on ANY exception (not just OSError — a
        # non-serializable payload raises TypeError from json.dump, for
        # example), while always re-raising unchanged: this never swallows a
        # programming error, it only prevents a leaked .tmp file alongside one.
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def publish_pending(path: Path) -> None:
    """Step 4 of the publication sequence: invalidate any previous context
    BEFORE a new trace is published, so a stale "complete" context can never
    survive to (mis)describe a new trace it doesn't actually match — even
    when the new trace happens to produce identical bytes/hash to the old
    one (e.g. an added-but-never-used server changes the snapshot without
    changing the trace).

    Raises RunContextPublicationError on failure. The caller must not
    proceed to publish a new run.jsonl if this fails — the previous trace
    stays authoritative and untouched.
    """
    try:
        _atomic_write_json(path, {"schema_version": SCHEMA_VERSION, "status": "pending"})
    except OSError as exc:
        raise RunContextPublicationError(f"failed to publish pending run context marker: {exc}") from exc


def publish_complete(path: Path, *, trace_sha256: str, strategy: str, servers: Sequence[ServerSpec]) -> None:
    """Step 6: best-effort completion of the context. Raises OSError on
    failure — the caller must catch this, log it, and continue treating the
    run as successful (the mandatory trace has already been published by
    this point); readers will see the still-"pending" marker and correctly
    degrade to context_available=false.
    """
    payload = {
        "schema_version": SCHEMA_VERSION,
        "status": "complete",
        "trace_sha256": trace_sha256,
        "strategy": strategy,
        "servers": [
            {
                "id": s.id,
                "cpu_units_per_tick": s.cpu_units_per_tick,
                "mem_mb": s.mem_mb,
                "rate_limit_per_sec": s.rate_limit_per_sec,
            }
            for s in servers
        ],
    }
    _atomic_write_json(path, payload)


def load_verified(
    path: Path,
    trace_bytes: bytes,
    known_strategy_ids: frozenset[str],
) -> Optional[dict]:
    """Read-side verification. Returns {"strategy": str, "servers": list[ServerSpec]}
    when, and only when, the context can be trusted for exactly this trace.
    Never raises: every failure mode (missing file, malformed JSON, wrong
    schema_version, status != "complete", hash mismatch, unknown strategy,
    invalid server snapshot) degrades to None and is logged, not propagated
    as an HTTP error.

    Deliberately catches only exceptions that represent expected
    filesystem/deserialization failure modes (OSError, UnicodeDecodeError,
    json.JSONDecodeError) at the top level; the server snapshot itself is
    validated by explicit strict schema checks (_parse_verified_server), not
    by catching coercion exceptions — a genuine programming error elsewhere
    is not swallowed here.
    """
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        logger.info("run_context.json unreadable/malformed, degrading to context_available=false: %s", exc)
        return None

    if not isinstance(raw, dict):
        logger.info("run_context.json is not a JSON object, degrading to context_available=false")
        return None
    schema_version = raw.get("schema_version")
    # type(x) is int first: Python's bool is a subclass of int, so
    # `True != 1` is False (bool == int comparison succeeds) — comparing
    # equality alone would let {"schema_version": true} silently pass. No
    # coercion of strings/floats either.
    if type(schema_version) is not int or schema_version != SCHEMA_VERSION:
        logger.info("run_context.json schema_version unsupported (%r), degrading to context_available=false", schema_version)
        return None
    if raw.get("status") != "complete":
        logger.info("run_context.json status is not 'complete' (%r), degrading to context_available=false", raw.get("status"))
        return None

    trace_sha256 = raw.get("trace_sha256")
    if not isinstance(trace_sha256, str) or trace_sha256 != hashlib.sha256(trace_bytes).hexdigest():
        logger.info("run_context.json trace_sha256 mismatch, degrading to context_available=false")
        return None

    strategy = raw.get("strategy")
    if not isinstance(strategy, str) or strategy not in known_strategy_ids:
        logger.info("run_context.json strategy unrecognized (%r), degrading to context_available=false", strategy)
        return None

    servers_raw = raw.get("servers")
    if not isinstance(servers_raw, list) or not servers_raw:
        logger.info("run_context.json servers snapshot invalid or empty, degrading to context_available=false")
        return None

    servers: list[ServerSpec] = []
    seen_ids: set[str] = set()
    for entry in servers_raw:
        server = _parse_verified_server(entry)
        if server is None:
            logger.info("run_context.json servers snapshot failed strict validation, degrading to context_available=false: %r", entry)
            return None
        if server.id in seen_ids:
            logger.info(
                "run_context.json servers snapshot contains duplicate server id %r, degrading to context_available=false",
                server.id,
            )
            return None
        seen_ids.add(server.id)
        servers.append(server)

    return {"strategy": strategy, "servers": servers}
