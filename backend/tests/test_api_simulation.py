from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import Settings
from app.domain.strategies import STRATEGY_REGISTRY

BACKEND_DIR = Path(__file__).resolve().parents[1]

EXPECTED_SAMPLE_SUMMARY = {
    "status": "completed",
    "total_requests": 4,
    "started": 4,
    "finished": 4,
    "dropped": 0,
    "avg_wait_ticks": 0.25,
    "p50_wait_ticks": 0,
    "p95_wait_ticks": 1,
    "max_wait_ticks": 1,
}


def test_run_against_seeded_sample_returns_expected_summary(isolated_client):
    resp = isolated_client.post("/api/simulations/run")
    assert resp.status_code == 200
    assert resp.json() == EXPECTED_SAMPLE_SUMMARY


def test_run_with_empty_servers_returns_400(isolated_client):
    isolated_client.delete("/api/servers/s1")
    isolated_client.delete("/api/servers/s2")
    resp = isolated_client.post("/api/simulations/run")
    assert resp.status_code == 400


def test_latest_before_any_run_returns_404(isolated_client):
    resp = isolated_client.get("/api/simulations/latest")
    assert resp.status_code == 404


def test_latest_after_run_matches_run_response(isolated_client):
    run_resp = isolated_client.post("/api/simulations/run")
    latest_resp = isolated_client.get("/api/simulations/latest")
    assert latest_resp.status_code == 200
    assert latest_resp.json() == run_resp.json()


def test_download_before_any_run_returns_404(isolated_client):
    resp = isolated_client.get("/api/simulations/latest/download")
    assert resp.status_code == 404


def test_download_after_run_matches_published_file(isolated_client):
    isolated_client.post("/api/simulations/run")
    resp = isolated_client.get("/api/simulations/latest/download")
    assert resp.status_code == 200
    run_jsonl_path = isolated_client.app.state.settings.run_jsonl_path
    assert resp.content == run_jsonl_path.read_bytes()


def test_failed_run_preserves_previous_trace_and_latest(isolated_client):
    first = isolated_client.post("/api/simulations/run")
    assert first.status_code == 200
    latest_before = isolated_client.get("/api/simulations/latest")
    download_before = isolated_client.get("/api/simulations/latest/download")

    isolated_client.delete("/api/servers/s1")
    isolated_client.delete("/api/servers/s2")
    failed = isolated_client.post("/api/simulations/run")
    assert failed.status_code == 400

    latest_after = isolated_client.get("/api/simulations/latest")
    assert latest_after.status_code == 200
    assert latest_after.json() == latest_before.json()

    download_after = isolated_client.get("/api/simulations/latest/download")
    assert download_after.content == download_before.content


def test_latest_returns_committed_day1_trace_via_isolated_settings(tmp_path, isolated_provided_dir):
    """Mandatory correction 1 / 6: never instantiate create_app(Settings()) with real
    defaults. Instead build isolated Settings and copy the real, committed
    backend/data/run.jsonl into that isolated data dir, proving the 'clean clone
    already has a valid trace' behavior without ever touching real backend/data."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    real_run_jsonl = BACKEND_DIR / "data" / "run.jsonl"
    shutil.copyfile(real_run_jsonl, data_dir / "run.jsonl")

    settings = Settings(data_dir=data_dir, provided_dir=isolated_provided_dir)
    with TestClient(create_app(settings)) as client:
        resp = client.get("/api/simulations/latest")

    assert resp.status_code == 200
    assert resp.json() == EXPECTED_SAMPLE_SUMMARY


# Malformed/corrupted-trace -> controlled 500 cases now live in the dedicated,
# parameterized test_malformed_trace_api.py (10 cases: structural + lifecycle).


# ---- Day 3A: strategy selection and metrics ------------------------------------


def test_strategies_endpoint_lists_both_with_correct_default(isolated_client):
    resp = isolated_client.get("/api/simulations/strategies")
    assert resp.status_code == 200
    strategies = {s["id"]: s for s in resp.json()["strategies"]}
    assert strategies["fastest_finish"] == {"id": "fastest_finish", "label": "Fastest finish", "default": True}
    assert strategies["lowest_id"] == {"id": "lowest_id", "label": "Lowest server ID", "default": False}


def test_strategies_endpoint_ids_exactly_equal_registry_keys_with_one_default(isolated_client):
    from app.domain.strategies import DEFAULT_STRATEGY_NAME, STRATEGY_REGISTRY

    resp = isolated_client.get("/api/simulations/strategies")
    body = resp.json()["strategies"]

    assert [s["id"] for s in body] == list(STRATEGY_REGISTRY.keys())
    defaults = [s for s in body if s["default"] is True]
    assert len(defaults) == 1
    assert defaults[0]["id"] == DEFAULT_STRATEGY_NAME


def test_run_without_strategy_query_param_matches_frozen_default_summary(isolated_client):
    resp = isolated_client.post("/api/simulations/run")
    assert resp.status_code == 200
    assert resp.json() == EXPECTED_SAMPLE_SUMMARY


def test_run_without_strategy_query_param_resolves_default_strategy_name(isolated_client):
    from app.domain.strategies import DEFAULT_STRATEGY_NAME

    isolated_client.post("/api/simulations/run")
    metrics = isolated_client.get("/api/simulations/latest/metrics")
    assert metrics.json()["strategy_used"] == DEFAULT_STRATEGY_NAME


def test_run_with_explicit_default_strategy_query_param_is_identical(isolated_client):
    implicit = isolated_client.post("/api/simulations/run")
    explicit = isolated_client.post("/api/simulations/run?strategy=fastest_finish")
    assert explicit.status_code == 200
    assert explicit.json() == implicit.json()


def test_run_with_lowest_id_strategy_succeeds(isolated_client):
    resp = isolated_client.post("/api/simulations/run?strategy=lowest_id")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


@pytest.mark.parametrize("strategy_id", list(STRATEGY_REGISTRY.keys()))
def test_every_registered_strategy_id_is_accepted_by_post_run(isolated_client, strategy_id):
    resp = isolated_client.post(f"/api/simulations/run?strategy={strategy_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


def test_run_with_unknown_strategy_returns_422_with_json_detail_string(isolated_client):
    resp = isolated_client.post("/api/simulations/run?strategy=not_a_real_strategy")
    assert resp.status_code == 422
    body = resp.json()
    assert isinstance(body["detail"], str)
    assert "not_a_real_strategy" in body["detail"]


def test_metrics_before_any_run_returns_404(isolated_client):
    resp = isolated_client.get("/api/simulations/latest/metrics")
    assert resp.status_code == 404


def test_metrics_after_api_triggered_run_reports_context_available(isolated_client):
    isolated_client.post("/api/simulations/run")
    resp = isolated_client.get("/api/simulations/latest/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["context_available"] is True
    assert body["strategy_used"] == "fastest_finish"
    assert body["duration_ticks"] == 4
    assert body["avg_queue_depth"] == 0.25
    assert body["peak_queue_depth"] == 1
    server_ids = {s["server_id"] for s in body["servers"]}
    assert server_ids == {"s1", "s2"}


def test_metrics_reflects_lowest_id_strategy_used(isolated_client):
    isolated_client.post("/api/simulations/run?strategy=lowest_id")
    resp = isolated_client.get("/api/simulations/latest/metrics")
    assert resp.status_code == 200
    assert resp.json()["strategy_used"] == "lowest_id"


def test_metrics_context_verified_against_exact_crlf_persisted_bytes(isolated_client):
    """§2 correction: the metrics route must hash the exact persisted bytes,
    not a read_text()-decoded-then-re-encoded copy that could silently lose
    a CRLF -> LF universal-newline translation along the way."""
    import hashlib

    from app.domain.models import ServerSpec
    from app.services import run_context

    isolated_client.post("/api/simulations/run")
    settings = isolated_client.app.state.settings

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

    resp = isolated_client.get("/api/simulations/latest/metrics")
    assert resp.status_code == 200
    assert resp.json()["context_available"] is True


def test_metrics_reflects_trace_only_when_context_file_is_absent(isolated_client):
    isolated_client.post("/api/simulations/run")
    context_path = isolated_client.app.state.settings.run_context_path
    context_path.unlink()

    resp = isolated_client.get("/api/simulations/latest/metrics")
    assert resp.status_code == 200
    body = resp.json()
    assert body["context_available"] is False
    assert body["strategy_used"] is None
    assert body["configured_server_count"] is None
    # trace-only fields remain populated even without context
    assert body["duration_ticks"] == 4
    assert body["total_requests"] == 4
