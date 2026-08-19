from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from ..adapters.json_servers import load_servers_allow_empty, to_json_payload
from ..domain.errors import DuplicateServerIdError, ServerNotFoundError
from ..domain.models import ServerSpec


class ServerRepository:
    """JSON-file-backed server configuration store.

    load() is intentionally lock-free: os.replace() already guarantees a reader
    never observes a torn file, so plain reads don't need to serialize against
    writers. Every write path — save(), create(), update(), delete() — acquires
    the same RLock for its *entire* read-modify-write cycle via the private
    _load_unlocked/_save_unlocked helpers, so two concurrent CRUD calls can never
    produce a lost update (D-015).
    """

    def __init__(self, path: Path, tick_seconds: int = 1) -> None:
        self._path = path
        self._tick_seconds = tick_seconds
        self._lock = threading.RLock()

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> list[ServerSpec]:
        return self._load_unlocked()

    def save(self, servers: list[ServerSpec]) -> None:
        with self._lock:
            self._save_unlocked(servers)

    def create(self, server: ServerSpec) -> ServerSpec:
        with self._lock:
            servers = self._load_unlocked()
            if any(s.id == server.id for s in servers):
                raise DuplicateServerIdError(f"server id already exists: {server.id}")
            self._save_unlocked(servers + [server])
            return server

    def update(self, server_id: str, cpu_units_per_tick: int, mem_mb: int, rate_limit_per_sec: int) -> ServerSpec:
        with self._lock:
            servers = self._load_unlocked()
            idx = next((i for i, s in enumerate(servers) if s.id == server_id), None)
            if idx is None:
                raise ServerNotFoundError(f"no server with id: {server_id}")
            updated = ServerSpec(
                id=server_id,
                cpu_units_per_tick=cpu_units_per_tick,
                mem_mb=mem_mb,
                rate_limit_per_sec=rate_limit_per_sec,
            )
            servers[idx] = updated
            self._save_unlocked(servers)
            return updated

    def delete(self, server_id: str) -> None:
        with self._lock:
            servers = self._load_unlocked()
            if not any(s.id == server_id for s in servers):
                raise ServerNotFoundError(f"no server with id: {server_id}")
            self._save_unlocked([s for s in servers if s.id != server_id])

    def _load_unlocked(self) -> list[ServerSpec]:
        return load_servers_allow_empty(self._path)

    def _save_unlocked(self, servers: list[ServerSpec]) -> None:
        payload = to_json_payload(servers, self._tick_seconds)
        directory = self._path.parent
        directory.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".servers-", suffix=".json.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp_path, self._path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
