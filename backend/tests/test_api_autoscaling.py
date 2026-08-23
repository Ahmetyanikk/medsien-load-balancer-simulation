from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.main import create_app
from app.api.schemas import AutoScaleObservedOut, AutoScaleResponse
from app.config import Settings
from app.domain.autoscale import LIMITATIONS

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _observed(**overrides) -> AutoScaleObservedOut:
    defaults = dict(
        total_requests=4,
        dropped=0,
        dropped_rate=0.0,
        peak_queue_depth=1,
        avg_queue_depth=0.25,
        avg_cluster_busy_ratio=0.875,
        configured_server_count=2,
        idle_configured_server_ids=[],
    )
    defaults.update(overrides)
    return AutoScaleObservedOut(**defaults)


VALID_REASON_CODES = [
    "insufficient_data",
    "context_unavailable",
    "dropped_requests",
    "high_queue_pressure",
    "high_occupancy",
    "low_occupancy_idle_capacity",
    "minimum_server_count",
    "steady_state",
]


def test_autoscale_response_rejects_an_unknown_reason_code():
    with pytest.raises(ValidationError):
        AutoScaleResponse(
            context_available=True,
            recommendation_available=True,
            action="no_change",
            reason_codes=["not_a_real_reason_code"],
            explanation="x",
            suggested_server_delta=None,
            removal_candidate_server_ids=None,
            observed=_observed(),
            limitations=list(LIMITATIONS),
        )


def test_autoscale_response_accepts_the_complete_valid_reason_code_set():
    resp = AutoScaleResponse(
        context_available=True,
        recommendation_available=True,
        action="no_change",
        reason_codes=VALID_REASON_CODES,
        explanation="x",
        suggested_server_delta=None,
        removal_candidate_server_ids=None,
        observed=_observed(),
        limitations=list(LIMITATIONS),
    )
    assert resp.reason_codes == VALID_REASON_CODES


def test_no_trace_returns_404(isolated_client):
    resp = isolated_client.get("/api/simulations/latest/autoscaling")
    assert resp.status_code == 404


def test_corrupt_trace_returns_controlled_500(isolated_client):
    isolated_client.post("/api/simulations/run")
    settings = isolated_client.app.state.settings
    settings.run_jsonl_path.write_text("not json at all\n", encoding="utf-8")

    resp = isolated_client.get("/api/simulations/latest/autoscaling")
    assert resp.status_code == 500
    assert "detail" in resp.json()


def test_invalid_utf8_trace_bytes_return_controlled_500(isolated_client):
    isolated_client.post("/api/simulations/run")
    settings = isolated_client.app.state.settings
    settings.run_jsonl_path.write_bytes(b"\xff\xfe\x00invalid")

    resp = isolated_client.get("/api/simulations/latest/autoscaling")
    assert resp.status_code == 500
    assert "detail" in resp.json()


def test_verified_canonical_run_returns_no_change_steady_state(isolated_client):
    isolated_client.post("/api/simulations/run")
    resp = isolated_client.get("/api/simulations/latest/autoscaling")
    assert resp.status_code == 200
    body = resp.json()

    assert body["context_available"] is True
    assert body["recommendation_available"] is True
    assert body["action"] == "no_change"
    assert body["reason_codes"] == ["steady_state"]
    assert body["suggested_server_delta"] is None
    assert body["removal_candidate_server_ids"] is None
    assert body["observed"]["configured_server_count"] == 2
    assert body["observed"]["avg_cluster_busy_ratio"] == 0.875
    assert len(body["limitations"]) > 0


def test_missing_context_returns_recommendation_unavailable(isolated_client):
    isolated_client.post("/api/simulations/run")
    context_path = isolated_client.app.state.settings.run_context_path
    context_path.unlink()

    resp = isolated_client.get("/api/simulations/latest/autoscaling")
    assert resp.status_code == 200
    body = resp.json()
    assert body["context_available"] is False
    assert body["recommendation_available"] is False
    assert body["action"] is None
    assert body["reason_codes"] == ["context_unavailable"]
    assert body["suggested_server_delta"] is None
    assert body["removal_candidate_server_ids"] is None


def test_pending_context_returns_recommendation_unavailable(isolated_client):
    from app.services import run_context

    isolated_client.post("/api/simulations/run")
    context_path = isolated_client.app.state.settings.run_context_path
    run_context.publish_pending(context_path)

    resp = isolated_client.get("/api/simulations/latest/autoscaling")
    assert resp.status_code == 200
    body = resp.json()
    assert body["context_available"] is False
    assert body["recommendation_available"] is False
    assert body["reason_codes"] == ["context_unavailable"]


def test_hash_mismatched_context_returns_recommendation_unavailable(isolated_client):
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

    resp = isolated_client.get("/api/simulations/latest/autoscaling")
    assert resp.status_code == 200
    body = resp.json()
    assert body["context_available"] is False
    assert body["recommendation_available"] is False
    assert body["reason_codes"] == ["context_unavailable"]


def test_dropped_trace_without_verified_context_returns_context_unavailable_not_scale_up(
    tmp_path, isolated_provided_dir
):
    # A memory-incompatible request (guaranteed drop) run through an isolated
    # settings instance with no context ever published.
    settings = Settings(data_dir=tmp_path / "data", provided_dir=isolated_provided_dir)
    settings.data_dir.mkdir(parents=True)
    import json as _json

    (settings.data_dir / "servers.json").write_text(
        _json.dumps({"tick_seconds": 1, "servers": [{"id": "s1", "cpu_units_per_tick": 10, "mem_mb": 100, "rate_limit_per_sec": 1}]}),
        encoding="utf-8",
    )
    (settings.data_dir / "requests.csv").write_text("t,request_id,work_units,mem_mb\n0,r1,10,500\n", encoding="utf-8")

    with TestClient(create_app(settings)) as client:
        run_resp = client.post("/api/simulations/run")
        assert run_resp.status_code == 200
        assert run_resp.json()["dropped"] == 1

        # POST /run always publishes context; to genuinely exercise "no
        # verified context" through the real API, invalidate it afterward —
        # same pattern as test_missing_context_returns_recommendation_unavailable.
        settings.run_context_path.unlink()

        resp = client.get("/api/simulations/latest/autoscaling")
        assert resp.status_code == 200
        body = resp.json()
        assert body["recommendation_available"] is False
        assert body["reason_codes"] == ["context_unavailable"]
        assert body["action"] != "scale_up"


def test_verified_dropped_trace_returns_scale_up_dropped_requests(tmp_path, isolated_provided_dir):
    settings = Settings(data_dir=tmp_path / "data", provided_dir=isolated_provided_dir)
    settings.data_dir.mkdir(parents=True)
    import json as _json

    (settings.data_dir / "servers.json").write_text(
        _json.dumps({"tick_seconds": 1, "servers": [{"id": "s1", "cpu_units_per_tick": 10, "mem_mb": 100, "rate_limit_per_sec": 1}]}),
        encoding="utf-8",
    )
    (settings.data_dir / "requests.csv").write_text("t,request_id,work_units,mem_mb\n0,r1,10,500\n", encoding="utf-8")

    with TestClient(create_app(settings)) as client:
        run_resp = client.post("/api/simulations/run")
        assert run_resp.status_code == 200

        resp = client.get("/api/simulations/latest/autoscaling")
        assert resp.status_code == 200
        body = resp.json()
        assert body["context_available"] is True
        assert body["recommendation_available"] is True
        assert body["action"] == "scale_up"
        assert body["reason_codes"] == ["dropped_requests"]
        assert body["suggested_server_delta"] == 1
        assert body["removal_candidate_server_ids"] is None


def test_repeated_get_calls_return_identical_bodies(isolated_client):
    isolated_client.post("/api/simulations/run")
    first = isolated_client.get("/api/simulations/latest/autoscaling")
    second = isolated_client.get("/api/simulations/latest/autoscaling")
    assert first.json() == second.json()


def test_restart_reconstruction_matches_immediate_response(isolated_client):
    run_resp = isolated_client.post("/api/simulations/run")
    assert run_resp.status_code == 200
    immediate = isolated_client.get("/api/simulations/latest/autoscaling")

    settings = isolated_client.app.state.settings
    with TestClient(create_app(settings)) as fresh_client:
        reconstructed = fresh_client.get("/api/simulations/latest/autoscaling")

    assert immediate.status_code == reconstructed.status_code == 200
    assert immediate.json() == reconstructed.json()


def test_restart_from_committed_sample_trace_is_context_unavailable(tmp_path, isolated_provided_dir):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    real_run_jsonl = BACKEND_DIR / "data" / "run.jsonl"
    shutil.copyfile(real_run_jsonl, data_dir / "run.jsonl")

    settings = Settings(data_dir=data_dir, provided_dir=isolated_provided_dir)
    with TestClient(create_app(settings)) as client:
        resp = client.get("/api/simulations/latest/autoscaling")

    assert resp.status_code == 200
    body = resp.json()
    assert body["context_available"] is False
    assert body["recommendation_available"] is False


def test_observed_fields_exactly_equal_metrics_endpoint(isolated_client):
    isolated_client.post("/api/simulations/run")
    autoscaling = isolated_client.get("/api/simulations/latest/autoscaling").json()
    metrics = isolated_client.get("/api/simulations/latest/metrics").json()

    observed = autoscaling["observed"]
    assert observed["total_requests"] == metrics["total_requests"]
    assert observed["dropped"] == metrics["dropped"]
    assert observed["dropped_rate"] == metrics["dropped_rate"]
    assert observed["peak_queue_depth"] == metrics["peak_queue_depth"]
    assert observed["avg_queue_depth"] == metrics["avg_queue_depth"]
    assert observed["avg_cluster_busy_ratio"] == metrics["avg_cluster_busy_ratio"]
    assert observed["configured_server_count"] == metrics["configured_server_count"]
    assert observed["idle_configured_server_ids"] == metrics["idle_configured_server_ids"]


def test_response_invariants_hold_for_the_canonical_run(isolated_client):
    isolated_client.post("/api/simulations/run")
    body = isolated_client.get("/api/simulations/latest/autoscaling").json()

    if not body["recommendation_available"]:
        assert body["action"] is None
        assert body["suggested_server_delta"] is None
        assert body["removal_candidate_server_ids"] is None
    elif body["action"] == "scale_up":
        assert body["suggested_server_delta"] == 1
        assert body["removal_candidate_server_ids"] is None
    elif body["action"] == "scale_down":
        assert body["suggested_server_delta"] == -1
        assert body["removal_candidate_server_ids"]
        assert body["removal_candidate_server_ids"] == sorted(body["removal_candidate_server_ids"])
    elif body["action"] == "no_change":
        assert body["suggested_server_delta"] is None
        assert body["removal_candidate_server_ids"] is None


# ---- strict read-only proof ----------------------------------------------------


def test_autoscaling_get_is_strictly_read_only(isolated_client):
    isolated_client.post("/api/simulations/run")
    settings = isolated_client.app.state.settings

    watched_paths = [settings.servers_path, settings.run_jsonl_path, settings.run_context_path]
    before_files = [(p.read_bytes(), p.stat().st_mtime_ns) for p in watched_paths]
    before_servers_response = isolated_client.get("/api/servers").json()

    resp = isolated_client.get("/api/simulations/latest/autoscaling")
    assert resp.status_code == 200

    after_files = [(p.read_bytes(), p.stat().st_mtime_ns) for p in watched_paths]
    after_servers_response = isolated_client.get("/api/servers").json()

    assert before_files == after_files
    assert before_servers_response == after_servers_response
