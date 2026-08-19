from __future__ import annotations

import threading

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import Settings
from app.domain.engine import SimulationEngine
from app.services.simulation_service import SimulationService


class _BlockingEngine(SimulationEngine):
    """Blocks inside simulate() until released, so the test can prove thread A holds
    the run lock before thread B ever fires (amendments 7 & 8: no time.sleep races,
    every wait has a timeout, and a stuck release fails loudly instead of hanging)."""

    def __init__(self, entered: threading.Event, release: threading.Event) -> None:
        self._entered = entered
        self._release = release

    def simulate(self, servers, requests, strategy=None):
        self._entered.set()
        if not self._release.wait(timeout=5):
            raise AssertionError("test setup failure: release was never signaled")
        return super().simulate(servers, requests, strategy)


def test_concurrent_run_requests_one_succeeds_one_gets_409(tmp_path, isolated_provided_dir):
    settings = Settings(data_dir=tmp_path / "data", provided_dir=isolated_provided_dir)
    entered = threading.Event()
    release = threading.Event()

    app = create_app(settings)
    with TestClient(app) as client:
        client.app.state.simulation_service = SimulationService(engine=_BlockingEngine(entered, release))

        results: dict[str, object] = {}

        def call_a() -> None:
            results["a"] = client.post("/api/simulations/run")

        thread_a = threading.Thread(target=call_a)
        thread_a.start()
        try:
            assert entered.wait(timeout=5), "thread A never entered the run lock's critical section"
            resp_b = client.post("/api/simulations/run")
            assert resp_b.status_code == 409
        finally:
            release.set()
            thread_a.join(timeout=5)

        assert not thread_a.is_alive(), "thread A did not finish — possible deadlock"
        assert results["a"].status_code == 200
