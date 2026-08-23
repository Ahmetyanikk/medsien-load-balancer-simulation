from __future__ import annotations

import hashlib
import json

from app.config import Settings
from app.domain.errors import CorruptTraceError
from app.services.simulation_service import SimulationService
from app.services.trace_reader import read_current_run

import pytest


def _settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path / "data")


def test_missing_trace_returns_none(tmp_path):
    settings = _settings(tmp_path)
    assert read_current_run(settings) is None


def test_verified_context_populates_full_snapshot(tmp_path, servers_json_path, requests_csv_path):
    settings = _settings(tmp_path)
    settings.data_dir.mkdir(parents=True)
    SimulationService().run(
        servers_json_path,
        requests_csv_path,
        settings.run_jsonl_path,
        context_path=settings.run_context_path,
    )

    snapshot = read_current_run(settings)
    assert snapshot is not None
    assert snapshot.context_available is True
    assert snapshot.strategy_used == "fastest_finish"
    assert snapshot.servers is not None
    assert {s.id for s in snapshot.servers} == {"s1", "s2"}
    assert len(snapshot.events) > 0


def test_missing_context_file_degrades(tmp_path, servers_json_path, requests_csv_path):
    settings = _settings(tmp_path)
    settings.data_dir.mkdir(parents=True)
    SimulationService().run(servers_json_path, requests_csv_path, settings.run_jsonl_path)
    # No context_path was passed, so run_context.json was never written.

    snapshot = read_current_run(settings)
    assert snapshot is not None
    assert snapshot.context_available is False
    assert snapshot.strategy_used is None
    assert snapshot.servers is None


def test_pending_context_degrades(tmp_path, servers_json_path, requests_csv_path):
    from app.services import run_context

    settings = _settings(tmp_path)
    settings.data_dir.mkdir(parents=True)
    SimulationService().run(
        servers_json_path,
        requests_csv_path,
        settings.run_jsonl_path,
        context_path=settings.run_context_path,
    )
    run_context.publish_pending(settings.run_context_path)

    snapshot = read_current_run(settings)
    assert snapshot is not None
    assert snapshot.context_available is False
    assert snapshot.strategy_used is None
    assert snapshot.servers is None


def test_hash_mismatch_context_degrades(tmp_path, servers_json_path, requests_csv_path):
    from app.services import run_context
    from app.domain.models import ServerSpec

    settings = _settings(tmp_path)
    settings.data_dir.mkdir(parents=True)
    SimulationService().run(
        servers_json_path,
        requests_csv_path,
        settings.run_jsonl_path,
        context_path=settings.run_context_path,
    )
    run_context.publish_complete(
        settings.run_context_path,
        trace_sha256="0" * 64,
        strategy="fastest_finish",
        servers=[ServerSpec(id="s1", cpu_units_per_tick=10, mem_mb=1024, rate_limit_per_sec=2)],
    )

    snapshot = read_current_run(settings)
    assert snapshot is not None
    assert snapshot.context_available is False
    assert snapshot.strategy_used is None
    assert snapshot.servers is None


def test_crlf_trace_bytes_still_verify_against_exact_persisted_bytes(tmp_path, servers_json_path, requests_csv_path):
    from app.services import run_context
    from app.domain.models import ServerSpec

    settings = _settings(tmp_path)
    settings.data_dir.mkdir(parents=True)
    SimulationService().run(servers_json_path, requests_csv_path, settings.run_jsonl_path)

    original_bytes = settings.run_jsonl_path.read_bytes()
    crlf_bytes = original_bytes.replace(b"\n", b"\r\n")
    settings.run_jsonl_path.write_bytes(crlf_bytes)

    run_context.publish_complete(
        settings.run_context_path,
        trace_sha256=hashlib.sha256(crlf_bytes).hexdigest(),
        strategy="fastest_finish",
        servers=[
            ServerSpec(id="s1", cpu_units_per_tick=10, mem_mb=1024, rate_limit_per_sec=2),
            ServerSpec(id="s2", cpu_units_per_tick=5, mem_mb=512, rate_limit_per_sec=1),
        ],
    )

    snapshot = read_current_run(settings)
    assert snapshot is not None
    assert snapshot.context_available is True


def test_corrupt_trace_propagates_uncaught(tmp_path):
    settings = _settings(tmp_path)
    settings.data_dir.mkdir(parents=True)
    settings.run_jsonl_path.write_text("not json at all\n", encoding="utf-8")

    with pytest.raises(CorruptTraceError):
        read_current_run(settings)


def test_invalid_utf8_trace_bytes_raise_corrupt_trace_error_via_controlled_decode_path(tmp_path):
    # 0xFF is never a valid UTF-8 lead byte, so this exercises read_current_run's
    # own UnicodeDecodeError -> CorruptTraceError translation, not the JSON/
    # lifecycle validation inside JsonlTraceWriter.deserialize().
    settings = _settings(tmp_path)
    settings.data_dir.mkdir(parents=True)
    settings.run_jsonl_path.write_bytes(b"\xff\xfe\x00invalid")

    with pytest.raises(CorruptTraceError):
        read_current_run(settings)
