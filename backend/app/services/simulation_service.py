from __future__ import annotations

import hashlib
import logging
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
from ..domain.strategies import DEFAULT_STRATEGY_NAME, SchedulingStrategy
from . import run_context

logger = logging.getLogger(__name__)


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
        context_path: Optional[Path] = None,
    ) -> SimulationResult:
        """context_path is opt-in: omitting it (the default) reproduces the
        exact pre-Day-3A behavior with no run_context.json touched at all, so
        every existing caller/test that doesn't pass it is unaffected. The
        real API route always passes it to enable the bonus metrics context.
        """
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

            if context_path is not None:
                # Step 4: invalidate any previous context before a new trace
                # exists, so a stale "complete" context can never survive to
                # (mis)describe it — raises and aborts before publishing a
                # new trace if this fails.
                run_context.publish_pending(context_path)

            # Step 5: existing mandatory atomic publication, unchanged.
            self._publish(output_path, text)

            if context_path is not None:
                # Step 6: best-effort. Must never turn a successful trace
                # publication into a failed run.
                strategy_name = strategy.name if strategy is not None else DEFAULT_STRATEGY_NAME
                trace_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
                try:
                    run_context.publish_complete(
                        context_path, trace_sha256=trace_sha256, strategy=strategy_name, servers=servers
                    )
                except OSError as exc:
                    logger.warning("failed to publish complete run context (bonus metrics degraded): %s", exc)

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
