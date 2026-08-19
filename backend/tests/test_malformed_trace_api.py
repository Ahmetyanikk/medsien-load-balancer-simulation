from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import Settings

ARRIVED = '{"t":0,"event":"REQUEST_ARRIVED","request_id":"r1"}\n'
STARTED = '{"t":0,"event":"REQUEST_STARTED","request_id":"r1","server_id":"s1"}\n'
FINISHED = '{"t":2,"event":"REQUEST_FINISHED","request_id":"r1","server_id":"s1"}\n'
DROPPED = '{"t":0,"event":"REQUEST_DROPPED","request_id":"r1"}\n'

# Every case must produce a controlled JSON 500 (CorruptTraceError -> the generic
# DomainError handler, or a route-level UTF-8 decode translation), never a leaked
# traceback and never a bare Python exception escaping to the test process.
MALFORMED_TRACE_CASES = [
    # --- structural / JSON-level -------------------------------------------------
    pytest.param("not json at all\n", id="invalid_json_syntax"),
    pytest.param("42\n", id="json_scalar_not_object"),
    pytest.param("[1,2,3]\n", id="json_list_not_object"),
    pytest.param("\n", id="empty_effective_content"),
    pytest.param("\n   \n\t\n", id="blank_only_file"),
    # --- t ------------------------------------------------------------------------
    pytest.param('{"event":"REQUEST_ARRIVED","request_id":"r1"}\n', id="missing_t"),
    pytest.param('{"t":"0","event":"REQUEST_ARRIVED","request_id":"r1"}\n', id="string_t"),
    pytest.param('{"t":true,"event":"REQUEST_ARRIVED","request_id":"r1"}\n', id="bool_t"),
    pytest.param('{"t":-1,"event":"REQUEST_ARRIVED","request_id":"r1"}\n', id="negative_t"),
    # --- request_id -----------------------------------------------------------------
    pytest.param('{"t":0,"event":"REQUEST_ARRIVED"}\n', id="missing_request_id"),
    pytest.param('{"t":0,"event":"REQUEST_ARRIVED","request_id":123}\n', id="non_string_request_id"),
    pytest.param('{"t":0,"event":"REQUEST_ARRIVED","request_id":""}\n', id="empty_request_id"),
    pytest.param('{"t":0,"event":"REQUEST_ARRIVED","request_id":"   "}\n', id="whitespace_only_request_id"),
    # --- server_id (on STARTED, where it's required) --------------------------------
    pytest.param(ARRIVED + '{"t":0,"event":"REQUEST_STARTED","request_id":"r1"}\n', id="started_missing_server_id"),
    pytest.param(
        ARRIVED + '{"t":0,"event":"REQUEST_STARTED","request_id":"r1","server_id":123}\n',
        id="started_non_string_server_id",
    ),
    pytest.param(
        ARRIVED + '{"t":0,"event":"REQUEST_STARTED","request_id":"r1","server_id":""}\n',
        id="started_empty_server_id",
    ),
    pytest.param(
        ARRIVED + '{"t":0,"event":"REQUEST_STARTED","request_id":"r1","server_id":"   "}\n',
        id="started_whitespace_only_server_id",
    ),
    # --- event ------------------------------------------------------------------------
    pytest.param('{"t":0,"event":"REQUEST_TELEPORTED","request_id":"r1"}\n', id="unknown_event"),
    # --- duplicates -----------------------------------------------------------------
    pytest.param(ARRIVED + ARRIVED, id="duplicate_arrived"),
    pytest.param(ARRIVED + STARTED + STARTED, id="duplicate_started"),
    pytest.param(ARRIVED + STARTED + FINISHED + FINISHED, id="duplicate_finished"),
    pytest.param(ARRIVED + DROPPED + DROPPED, id="duplicate_dropped"),
    # --- out-of-order lifecycle -------------------------------------------------------
    pytest.param(STARTED, id="started_without_arrived"),
    pytest.param(ARRIVED + FINISHED, id="finished_without_started"),
    pytest.param(DROPPED, id="dropped_without_arrived"),
    pytest.param(ARRIVED + DROPPED + STARTED, id="started_after_dropped"),
    pytest.param(ARRIVED + STARTED + DROPPED, id="dropped_after_started"),
    pytest.param(ARRIVED + STARTED + FINISHED + DROPPED, id="both_finished_and_dropped"),
    pytest.param(ARRIVED, id="unresolved_arrived"),
    # --- tick relationships -------------------------------------------------------------
    pytest.param(
        '{"t":5,"event":"REQUEST_ARRIVED","request_id":"r1"}\n'
        '{"t":3,"event":"REQUEST_STARTED","request_id":"r1","server_id":"s1"}\n',
        id="negative_wait",
    ),
    pytest.param(
        '{"t":5,"event":"REQUEST_ARRIVED","request_id":"r1"}\n'
        '{"t":3,"event":"REQUEST_DROPPED","request_id":"r1"}\n',
        id="dropped_before_arrived_tick",
    ),
    pytest.param(
        ARRIVED + '{"t":0,"event":"REQUEST_STARTED","request_id":"r1","server_id":"s1"}\n'
        '{"t":0,"event":"REQUEST_FINISHED","request_id":"r1","server_id":"s1"}\n',
        id="finish_tick_equal_to_start_tick",
    ),
    pytest.param(
        ARRIVED + '{"t":5,"event":"REQUEST_STARTED","request_id":"r1","server_id":"s1"}\n'
        '{"t":3,"event":"REQUEST_FINISHED","request_id":"r1","server_id":"s1"}\n',
        id="finish_tick_earlier_than_start_tick",
    ),
    pytest.param(
        ARRIVED + STARTED + '{"t":2,"event":"REQUEST_FINISHED","request_id":"r1","server_id":"s2"}\n',
        id="started_finished_server_mismatch",
    ),
]


def _write_trace_and_get_latest(tmp_path: Path, isolated_provided_dir: Path, content: str):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "run.jsonl").write_text(content, encoding="utf-8")
    settings = Settings(data_dir=data_dir, provided_dir=isolated_provided_dir)
    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        return client.get("/api/simulations/latest")


def _assert_controlled_500(resp) -> None:
    assert resp.status_code == 500
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert "detail" in body
    assert "Traceback" not in resp.text
    assert "traceback" not in resp.text.lower()


@pytest.mark.parametrize("trace_content", MALFORMED_TRACE_CASES)
def test_malformed_or_corrupt_trace_returns_controlled_500(trace_content, tmp_path, isolated_provided_dir):
    resp = _write_trace_and_get_latest(tmp_path, isolated_provided_dir, trace_content)
    _assert_controlled_500(resp)


def test_invalid_utf8_bytes_returns_controlled_500(tmp_path, isolated_provided_dir):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    # 0xFF is not valid anywhere in UTF-8; write raw bytes, not text, to force a
    # genuine decode failure rather than a JSON parse failure.
    (data_dir / "run.jsonl").write_bytes(b'{"t":0,"event":"REQUEST_ARRIVED","request_id":"r1"}\xff\xfe\n')
    settings = Settings(data_dir=data_dir, provided_dir=isolated_provided_dir)

    with TestClient(create_app(settings), raise_server_exceptions=False) as client:
        resp = client.get("/api/simulations/latest")

    _assert_controlled_500(resp)


# --- positive regressions: valid lifecycles must still succeed --------------------


def test_valid_finished_lifecycle_returns_200(tmp_path, isolated_provided_dir):
    content = ARRIVED + STARTED + FINISHED
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "run.jsonl").write_text(content, encoding="utf-8")
    settings = Settings(data_dir=data_dir, provided_dir=isolated_provided_dir)

    with TestClient(create_app(settings)) as client:
        resp = client.get("/api/simulations/latest")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_requests"] == 1
    assert body["started"] == 1
    assert body["finished"] == 1
    assert body["dropped"] == 0


def test_valid_dropped_lifecycle_returns_200(tmp_path, isolated_provided_dir):
    content = ARRIVED + DROPPED
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "run.jsonl").write_text(content, encoding="utf-8")
    settings = Settings(data_dir=data_dir, provided_dir=isolated_provided_dir)

    with TestClient(create_app(settings)) as client:
        resp = client.get("/api/simulations/latest")

    assert resp.status_code == 200
    body = resp.json()
    assert body["total_requests"] == 1
    assert body["started"] == 0
    assert body["finished"] == 0
    assert body["dropped"] == 1
    assert body["avg_wait_ticks"] is None
