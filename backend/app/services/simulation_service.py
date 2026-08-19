from __future__ import annotations

import os
import tempfile
import threading
from pathlib import Path
from typing import Optional

from ..adapters.csv_requests import load_requests
from ..adapters.json_servers import load_servers
from ..adapters.jsonl_trace import JsonlTraceWriter
from ..domain.engine import SimulationEngine
from ..domain.errors import EmptyRequestConfigurationError, SimulationAlreadyRunningError
from ..domain.models import SimulationResult
from ..domain.strategies import SchedulingStrategy


class SimulationService:
    """Owns all I/O around a run: loading input, invoking the pure engine, serializing,
    and atomically publishing the trace (D-002/D-010/§17). The engine and writer never
    touch the filesystem themselves.

    A non-blocking Lock (D-016) protects .run() against concurrent HTTP-triggered
    calls: the route must resolve to ONE shared SimulationService instance
    (app.state.simulation_service) for this to serialize anything — a fresh instance
    per call would have a fresh, always-unlocked lock.
    """

    def __init__(self, engine: Optional[SimulationEngine] = None, writer: Optional[JsonlTraceWriter] = None) -> None:
        self._engine = engine or SimulationEngine()
        self._writer = writer or JsonlTraceWriter()
        self._lock = threading.Lock()

    def run(
        self,
        servers_path: Path,
        requests_path: Path,
        output_path: Path,
        strategy: Optional[SchedulingStrategy] = None,
    ) -> SimulationResult:
        if not self._lock.acquire(blocking=False):
            raise SimulationAlreadyRunningError("a simulation is already running")
        try:
            servers = load_servers(servers_path)
            requests = load_requests(requests_path)
            if not requests:
                raise EmptyRequestConfigurationError(
                    f"{requests_path} contains no requests; refusing to publish an empty "
                    "run.jsonl (the supplied validator cannot parse zero events)"
                )
            result = self._engine.simulate(servers, requests, strategy)
            text = self._writer.serialize(result.events)
            self._publish(output_path, text)
            return result
        finally:
            self._lock.release()

    @staticmethod
    def _publish(output_path: Path, text: str) -> None:
        directory = output_path.parent
        directory.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".run-", suffix=".jsonl.tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            os.replace(tmp_path, output_path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise
