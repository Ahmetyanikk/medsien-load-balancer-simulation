from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from ..adapters.json_servers import load_servers, to_json_payload
from ..domain.models import ServerSpec


class ServerRepository:
    """JSON-file-backed server configuration store with atomic writes (D-009).

    Locking for concurrent CRUD requests is an HTTP-layer concern, added when the
    CRUD routes are built (Day 2) — not needed for this repository's own file-write
    atomicity, which os.replace() already guarantees.
    """

    def __init__(self, path: Path, tick_seconds: int = 1) -> None:
        self._path = path
        self._tick_seconds = tick_seconds

    def load(self) -> list[ServerSpec]:
        return load_servers(self._path)

    def save(self, servers: list[ServerSpec]) -> None:
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
