from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from fastapi.testclient import TestClient

from app.adapters.jsonl_trace import JsonlTraceWriter
from app.api.main import create_app
from app.config import Settings

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _peak_and_avg_from_sparse_points(points: list[dict], end_tick: int) -> tuple[int, Optional[float]]:
    """Independent test-side reconstruction of peak/average depth from the
    *response's* sparse queue_depth points — deliberately not a call into
    production code, so this genuinely cross-checks the API's output against
    domain/queue_depth.py's algorithm rather than comparing an implementation
    to itself. Same interval-weighted-sum logic compute_queue_depth() uses:
    depth holds constant between consecutive points, and the value after the
    last point extends through end_tick (never included as its own interval)."""
    if not points:
        return 0, None
    peak = max(p["depth"] for p in points)
    integral = 0
    for i in range(len(points) - 1):
        integral += points[i]["depth"] * (points[i + 1]["tick"] - points[i]["tick"])
    integral += points[-1]["depth"] * (end_tick - points[-1]["tick"])
    duration = end_tick - points[0]["tick"]
    avg = (integral / duration) if duration > 0 else None
    return peak, avg


def test_peak_and_avg_helper_includes_the_final_interval_through_end_tick():
    # Synthetic sparse points with a non-zero final depth: [0,2) depth 0,
    # [2,5) depth 3 (the final interval, extending to end_tick=5). The old
    # helper's peak was never affected by the bug (it already took
    # max(point.depth) over every point, including the last); only the
    # average was wrong, since the final interval's contribution to the
    # integral was dropped — omitting it would compute avg as 0/5 = 0.0
    # instead of the correct 1.8. This deterministically fails under the old
    # (buggy) helper on the average alone.
    points = [{"tick": 0, "depth": 0}, {"tick": 2, "depth": 3}]
    peak, avg = _peak_and_avg_from_sparse_points(points, end_tick=5)
    assert peak == 3
    assert avg == 1.8  # (0*2 + 3*3) / 5


def test_no_trace_returns_404(isolated_client):
    resp = isolated_client.get("/api/simulations/latest/timeline")
    assert resp.status_code == 404


def test_valid_trace_returns_200_with_expected_canonical_shape(isolated_client):
    isolated_client.post("/api/simulations/run")
    resp = isolated_client.get("/api/simulations/latest/timeline")
    assert resp.status_code == 200
    body = resp.json()

    assert body["context_available"] is True
    assert body["strategy_used"] == "fastest_finish"
    assert body["total_requests"] == 4
    assert (body["start_tick"], body["end_tick"], body["duration_ticks"]) == (0, 4, 4)

    request_ids = [r["request_id"] for r in body["requests"]]
    assert request_ids == ["r1", "r2", "r3", "r4"]  # (arrival_tick, request_id) order

    server_ids = [s["server_id"] for s in body["servers"]]
    assert server_ids == ["s1", "s2"]

    assert body["queue_depth"] == [{"tick": 0, "depth": 0}, {"tick": 1, "depth": 1}, {"tick": 2, "depth": 0}]

    sequences = [e["sequence"] for e in body["events"]]
    assert sequences == list(range(len(sequences)))


def test_corrupt_trace_returns_controlled_500(isolated_client):
    isolated_client.post("/api/simulations/run")
    settings = isolated_client.app.state.settings
    settings.run_jsonl_path.write_text("not json at all\n", encoding="utf-8")

    resp = isolated_client.get("/api/simulations/latest/timeline")
    assert resp.status_code == 500
    assert "detail" in resp.json()


def test_trace_only_response_when_context_file_is_absent(isolated_client):
    isolated_client.post("/api/simulations/run")
    context_path = isolated_client.app.state.settings.run_context_path
    context_path.unlink()

    resp = isolated_client.get("/api/simulations/latest/timeline")
    assert resp.status_code == 200
    body = resp.json()
    assert body["context_available"] is False
    assert body["strategy_used"] is None
    # trace-derived fields remain fully populated without context
    assert body["total_requests"] == 4
    assert [s["server_id"] for s in body["servers"]] == ["s1", "s2"]


def test_strategy_used_present_only_with_verified_context(isolated_client):
    isolated_client.post("/api/simulations/run?strategy=lowest_id")
    resp = isolated_client.get("/api/simulations/latest/timeline")
    assert resp.status_code == 200
    assert resp.json()["strategy_used"] == "lowest_id"


def test_restart_reconstruction_from_committed_sample_trace_is_trace_only(tmp_path, isolated_provided_dir):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    real_run_jsonl = BACKEND_DIR / "data" / "run.jsonl"
    shutil.copyfile(real_run_jsonl, data_dir / "run.jsonl")

    settings = Settings(data_dir=data_dir, provided_dir=isolated_provided_dir)
    with TestClient(create_app(settings)) as client:
        resp = client.get("/api/simulations/latest/timeline")

    assert resp.status_code == 200
    body = resp.json()
    assert body["context_available"] is False
    assert body["total_requests"] == 4


def test_response_equality_between_immediate_run_and_disk_reconstruction(isolated_client):
    run_resp = isolated_client.post("/api/simulations/run")
    assert run_resp.status_code == 200
    immediate = isolated_client.get("/api/simulations/latest/timeline")

    settings = isolated_client.app.state.settings
    with TestClient(create_app(settings)) as fresh_client:
        reconstructed = fresh_client.get("/api/simulations/latest/timeline")

    assert immediate.status_code == reconstructed.status_code == 200
    assert immediate.json() == reconstructed.json()


def test_timeline_queue_reconstruction_from_sparse_points_matches_metrics_endpoint(isolated_client):
    isolated_client.post("/api/simulations/run")
    timeline = isolated_client.get("/api/simulations/latest/timeline").json()
    metrics = isolated_client.get("/api/simulations/latest/metrics").json()

    assert timeline["duration_ticks"] == metrics["duration_ticks"]
    peak, avg = _peak_and_avg_from_sparse_points(timeline["queue_depth"], timeline["end_tick"])
    assert peak == metrics["peak_queue_depth"]
    assert avg == metrics["avg_queue_depth"]


def test_api_events_array_exactly_equals_deserialized_persisted_trace(isolated_client):
    isolated_client.post("/api/simulations/run")
    settings = isolated_client.app.state.settings
    trace_bytes = settings.run_jsonl_path.read_bytes()
    persisted_events = JsonlTraceWriter().deserialize(trace_bytes.decode("utf-8"))

    body_events = isolated_client.get("/api/simulations/latest/timeline").json()["events"]

    assert len(body_events) == len(persisted_events)
    for i, (api_ev, persisted_ev) in enumerate(zip(body_events, persisted_events)):
        assert api_ev["sequence"] == i
        assert api_ev["tick"] == persisted_ev.t
        assert api_ev["event_type"] == persisted_ev.event.value
        assert api_ev["request_id"] == persisted_ev.request_id
        assert api_ev["server_id"] == persisted_ev.server_id


def test_pending_context_degrades_same_as_missing(isolated_client):
    from app.services import run_context

    isolated_client.post("/api/simulations/run")
    context_path = isolated_client.app.state.settings.run_context_path
    run_context.publish_pending(context_path)

    resp = isolated_client.get("/api/simulations/latest/timeline")
    assert resp.status_code == 200
    body = resp.json()
    assert body["context_available"] is False
    assert body["strategy_used"] is None
    assert body["total_requests"] == 4


def test_hash_mismatched_context_degrades_same_as_missing(isolated_client):
    from app.domain.models import ServerSpec
    from app.services import run_context

    isolated_client.post("/api/simulations/run")
    context_path = isolated_client.app.state.settings.run_context_path
    run_context.publish_complete(
        context_path,
        trace_sha256="0" * 64,
        strategy="fastest_finish",
        servers=[ServerSpec(id="s1", cpu_units_per_tick=10, mem_mb=1024, rate_limit_per_sec=2)],
    )

    resp = isolated_client.get("/api/simulations/latest/timeline")
    assert resp.status_code == 200
    body = resp.json()
    assert body["context_available"] is False
    assert body["strategy_used"] is None
    assert body["total_requests"] == 4


def test_invalid_utf8_trace_bytes_return_controlled_json_500(isolated_client):
    isolated_client.post("/api/simulations/run")
    settings = isolated_client.app.state.settings
    settings.run_jsonl_path.write_bytes(b"\xff\xfe\x00invalid")

    resp = isolated_client.get("/api/simulations/latest/timeline")
    assert resp.status_code == 500
    assert "detail" in resp.json()


def test_timeline_get_is_strictly_read_only(isolated_client):
    isolated_client.post("/api/simulations/run")
    settings = isolated_client.app.state.settings

    watched_paths = [settings.run_jsonl_path, settings.run_context_path, settings.servers_path]
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in watched_paths]

    resp = isolated_client.get("/api/simulations/latest/timeline")
    assert resp.status_code == 200

    after = [(p.read_bytes(), p.stat().st_mtime_ns) for p in watched_paths]
    assert before == after
