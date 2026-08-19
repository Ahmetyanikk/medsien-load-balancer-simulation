from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import Settings


def _empty_client(tmp_path, isolated_provided_dir) -> TestClient:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "servers.json").write_text('{"tick_seconds":1,"servers":[]}', encoding="utf-8")
    settings = Settings(data_dir=data_dir, provided_dir=isolated_provided_dir)
    return TestClient(create_app(settings))


def test_list_servers_empty_returns_empty_list(tmp_path, isolated_provided_dir):
    with _empty_client(tmp_path, isolated_provided_dir) as client:
        resp = client.get("/api/servers")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_server_returns_201_and_is_listed(isolated_client):
    resp = isolated_client.post(
        "/api/servers", json={"id": "s3", "cpu_units_per_tick": 4, "mem_mb": 100, "rate_limit_per_sec": 1}
    )
    assert resp.status_code == 201
    assert resp.json() == {"id": "s3", "cpu_units_per_tick": 4, "mem_mb": 100, "rate_limit_per_sec": 1}
    listed = isolated_client.get("/api/servers").json()
    assert any(s["id"] == "s3" for s in listed)


def test_create_duplicate_id_returns_409(isolated_client):
    body = {"id": "s1", "cpu_units_per_tick": 4, "mem_mb": 100, "rate_limit_per_sec": 1}
    resp = isolated_client.post("/api/servers", json=body)  # s1 already exists from seeding
    assert resp.status_code == 409


def test_create_invalid_cpu_returns_422(isolated_client):
    body = {"id": "s3", "cpu_units_per_tick": 0, "mem_mb": 100, "rate_limit_per_sec": 1}
    resp = isolated_client.post("/api/servers", json=body)
    assert resp.status_code == 422


def test_create_empty_id_returns_422(isolated_client):
    body = {"id": "   ", "cpu_units_per_tick": 4, "mem_mb": 100, "rate_limit_per_sec": 1}
    resp = isolated_client.post("/api/servers", json=body)
    assert resp.status_code == 422


def test_create_extra_field_returns_422(isolated_client):
    body = {"id": "s3", "cpu_units_per_tick": 4, "mem_mb": 100, "rate_limit_per_sec": 1, "unexpected": "x"}
    resp = isolated_client.post("/api/servers", json=body)
    assert resp.status_code == 422


def test_update_unknown_server_returns_404(isolated_client):
    resp = isolated_client.put(
        "/api/servers/does-not-exist", json={"cpu_units_per_tick": 4, "mem_mb": 100, "rate_limit_per_sec": 1}
    )
    assert resp.status_code == 404


def test_update_valid_returns_200_id_unchanged(isolated_client):
    resp = isolated_client.put(
        "/api/servers/s1", json={"cpu_units_per_tick": 99, "mem_mb": 2048, "rate_limit_per_sec": 5}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "s1"
    assert body["cpu_units_per_tick"] == 99


def test_update_with_id_field_returns_422(isolated_client):
    resp = isolated_client.put(
        "/api/servers/s1",
        json={"id": "s1", "cpu_units_per_tick": 4, "mem_mb": 100, "rate_limit_per_sec": 1},
    )
    assert resp.status_code == 422


def test_delete_unknown_server_returns_404(isolated_client):
    resp = isolated_client.delete("/api/servers/does-not-exist")
    assert resp.status_code == 404


def test_delete_returns_204_with_empty_body(isolated_client):
    isolated_client.post(
        "/api/servers", json={"id": "temp", "cpu_units_per_tick": 1, "mem_mb": 1, "rate_limit_per_sec": 1}
    )
    resp = isolated_client.delete("/api/servers/temp")
    assert resp.status_code == 204
    assert resp.content == b""


def test_delete_last_server_allowed(isolated_client):
    isolated_client.delete("/api/servers/s1")
    isolated_client.delete("/api/servers/s2")
    resp = isolated_client.get("/api/servers")
    assert resp.status_code == 200
    assert resp.json() == []
