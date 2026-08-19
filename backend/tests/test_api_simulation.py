from __future__ import annotations

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import Settings

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
