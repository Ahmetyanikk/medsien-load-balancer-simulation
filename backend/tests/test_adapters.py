from __future__ import annotations

from pathlib import Path

import pytest

from app.adapters.csv_requests import load_requests
from app.adapters.json_servers import load_servers, to_json_payload
from app.domain.errors import (
    DuplicateRequestIdError,
    DuplicateServerIdError,
    EmptyServerConfigurationError,
    InvalidRequestSpecError,
    InvalidServerSpecError,
    MissingRequestColumnsError,
    UnsupportedTickSecondsError,
)


def write(path: Path, text: str) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


# ---- requests.csv ----------------------------------------------------------


def test_load_requests_parses_sample(requests_csv_path):
    reqs = load_requests(requests_csv_path)
    assert {r.id for r in reqs} == {"r1", "r2", "r3", "r4"}


def test_load_requests_empty_returns_empty_list(tmp_path):
    csv_path = write(tmp_path / "requests.csv", "t,request_id,work_units,mem_mb\n")
    assert load_requests(csv_path) == []


def test_load_requests_duplicate_id_raises(tmp_path):
    csv_path = write(
        tmp_path / "requests.csv",
        "t,request_id,work_units,mem_mb\n0,r1,10,100\n1,r1,5,50\n",
    )
    with pytest.raises(DuplicateRequestIdError):
        load_requests(csv_path)


def test_load_requests_negative_arrival_raises(tmp_path):
    csv_path = write(tmp_path / "requests.csv", "t,request_id,work_units,mem_mb\n-1,r1,10,100\n")
    with pytest.raises(InvalidRequestSpecError):
        load_requests(csv_path)


def test_load_requests_non_positive_work_units_raises(tmp_path):
    csv_path = write(tmp_path / "requests.csv", "t,request_id,work_units,mem_mb\n0,r1,0,100\n")
    with pytest.raises(InvalidRequestSpecError):
        load_requests(csv_path)


def test_load_requests_negative_mem_raises(tmp_path):
    csv_path = write(tmp_path / "requests.csv", "t,request_id,work_units,mem_mb\n0,r1,10,-1\n")
    with pytest.raises(InvalidRequestSpecError):
        load_requests(csv_path)


def test_load_requests_missing_required_column_raises(tmp_path):
    csv_path = write(tmp_path / "requests.csv", "t,request_id,work_units\n0,r1,10\n")
    with pytest.raises(MissingRequestColumnsError):
        load_requests(csv_path)


def test_load_requests_returns_sorted_by_arrival_then_id(tmp_path):
    csv_path = write(
        tmp_path / "requests.csv",
        "t,request_id,work_units,mem_mb\n2,rZ,5,10\n0,rB,5,10\n0,rA,5,10\n",
    )
    reqs = load_requests(csv_path)
    assert [r.id for r in reqs] == ["rA", "rB", "rZ"]


# ---- servers.json -----------------------------------------------------------


def test_load_servers_parses_sample(servers_json_path):
    servers = load_servers(servers_json_path)
    assert {s.id for s in servers} == {"s1", "s2"}


def test_load_servers_empty_raises(tmp_path):
    path = write(tmp_path / "servers.json", '{"tick_seconds":1,"servers":[]}')
    with pytest.raises(EmptyServerConfigurationError):
        load_servers(path)


def test_load_servers_duplicate_id_raises(tmp_path):
    path = write(
        tmp_path / "servers.json",
        '{"tick_seconds":1,"servers":['
        '{"id":"s1","cpu_units_per_tick":10,"mem_mb":100,"rate_limit_per_sec":1},'
        '{"id":"s1","cpu_units_per_tick":5,"mem_mb":50,"rate_limit_per_sec":1}'
        "]}",
    )
    with pytest.raises(DuplicateServerIdError):
        load_servers(path)


def test_load_servers_non_positive_cpu_raises(tmp_path):
    path = write(
        tmp_path / "servers.json",
        '{"tick_seconds":1,"servers":[{"id":"s1","cpu_units_per_tick":0,"mem_mb":100,"rate_limit_per_sec":1}]}',
    )
    with pytest.raises(InvalidServerSpecError):
        load_servers(path)


def test_load_servers_negative_mem_raises(tmp_path):
    path = write(
        tmp_path / "servers.json",
        '{"tick_seconds":1,"servers":[{"id":"s1","cpu_units_per_tick":10,"mem_mb":-1,"rate_limit_per_sec":1}]}',
    )
    with pytest.raises(InvalidServerSpecError):
        load_servers(path)


def test_load_servers_negative_rate_limit_raises(tmp_path):
    path = write(
        tmp_path / "servers.json",
        '{"tick_seconds":1,"servers":[{"id":"s1","cpu_units_per_tick":10,"mem_mb":100,"rate_limit_per_sec":-1}]}',
    )
    with pytest.raises(InvalidServerSpecError):
        load_servers(path)


def test_load_servers_tick_seconds_other_than_one_raises(tmp_path):
    path = write(
        tmp_path / "servers.json",
        '{"tick_seconds":2,"servers":[{"id":"s1","cpu_units_per_tick":10,"mem_mb":100,"rate_limit_per_sec":1}]}',
    )
    with pytest.raises(UnsupportedTickSecondsError):
        load_servers(path)


def test_to_json_payload_round_trips_through_load_servers(tmp_path, servers_json_path):
    servers = load_servers(servers_json_path)
    payload = to_json_payload(servers)
    assert payload["tick_seconds"] == 1
    assert [s["id"] for s in payload["servers"]] == [s.id for s in servers]
