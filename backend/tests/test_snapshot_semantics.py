from __future__ import annotations

import threading

from app.adapters.json_servers import load_servers
from app.domain.engine import SimulationEngine
from app.domain.models import EventType, ServerSpec
from app.repository.server_repository import ServerRepository
from app.services.simulation_service import SimulationService


class _BlockingEngine(SimulationEngine):
    def __init__(self, entered: threading.Event, release: threading.Event) -> None:
        self._entered = entered
        self._release = release

    def simulate(self, servers, requests, strategy=None):
        self._entered.set()
        if not self._release.wait(timeout=5):
            raise AssertionError("test setup failure: release was never signaled")
        return super().simulate(servers, requests, strategy)


def test_in_flight_run_uses_snapshot_next_run_uses_updated_config(tmp_path, servers_json_path, requests_csv_path):
    repo = ServerRepository(tmp_path / "servers.json")
    repo.save(load_servers(servers_json_path))  # original 2-server config: s1, s2

    entered = threading.Event()
    release = threading.Event()
    service = SimulationService(engine=_BlockingEngine(entered, release))

    results: dict[str, object] = {}

    def run_a() -> None:
        results["a"] = service.run(repo.path, requests_csv_path, tmp_path / "run_a.jsonl")

    thread_a = threading.Thread(target=run_a)
    thread_a.start()
    try:
        assert entered.wait(timeout=5), "run A never reached its blocking point after loading its snapshot"
        # mutate the on-disk config WHILE run A is blocked, after it already loaded its snapshot
        new_server = ServerSpec(id="s3", cpu_units_per_tick=100, mem_mb=99999, rate_limit_per_sec=10)
        repo.save(repo.load() + [new_server])
    finally:
        release.set()
        thread_a.join(timeout=5)

    assert not thread_a.is_alive(), "run A did not finish — possible deadlock"

    # run A must never have used s3 — it wasn't in the snapshot loaded before it blocked
    assert all(e.server_id != "s3" for e in results["a"].events)

    # a fresh run now sees the updated config and can (and, given s3's huge cpu
    # advantage, will) use s3
    result_b = service.run(repo.path, requests_csv_path, tmp_path / "run_b.jsonl")
    assert any(e.server_id == "s3" for e in result_b.events if e.event == EventType.STARTED)
