from __future__ import annotations

import json
from pathlib import Path

from ..domain.errors import DuplicateServerIdError, EmptyServerConfigurationError
from ..domain.models import ServerSpec


def load_servers(path: Path) -> list[ServerSpec]:
    data = json.loads(path.read_text(encoding="utf-8"))
    servers: dict[str, ServerSpec] = {}
    for raw in data.get("servers", []):
        sid = raw["id"]
        if sid in servers:
            raise DuplicateServerIdError(f"duplicate server id in servers.json: {sid}")
        servers[sid] = ServerSpec(
            id=sid,
            cpu_units_per_tick=int(raw["cpu_units_per_tick"]),
            mem_mb=int(raw["mem_mb"]),
            rate_limit_per_sec=int(raw["rate_limit_per_sec"]),
        )
    if not servers:
        raise EmptyServerConfigurationError("servers.json contains no servers")
    return list(servers.values())


def to_json_payload(servers: list[ServerSpec], tick_seconds: int = 1) -> dict:
    """Pure dict-shape builder, reused by ServerRepository.save() to avoid duplicating
    the servers.json schema in two places."""
    return {
        "tick_seconds": tick_seconds,
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
