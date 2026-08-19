from __future__ import annotations

import json

import pytest

from app.domain.models import ServerSpec
from app.repository.server_repository import ServerRepository


def make_servers():
    return [
        ServerSpec(id="s1", cpu_units_per_tick=10, mem_mb=1024, rate_limit_per_sec=2),
        ServerSpec(id="s2", cpu_units_per_tick=5, mem_mb=512, rate_limit_per_sec=1),
    ]


def test_save_then_load_round_trips(tmp_path):
    repo = ServerRepository(tmp_path / "servers.json")
    servers = make_servers()
    repo.save(servers)
    loaded = repo.load()
    assert loaded == servers


def test_save_is_atomic_no_temp_file_left_on_success(tmp_path):
    repo = ServerRepository(tmp_path / "servers.json")
    repo.save(make_servers())
    leftovers = list(tmp_path.glob(".servers-*"))
    assert leftovers == []


def test_save_failure_leaves_original_file_untouched(tmp_path, monkeypatch):
    path = tmp_path / "servers.json"
    repo = ServerRepository(path)
    repo.save(make_servers())
    original_bytes = path.read_bytes()

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure")

    monkeypatch.setattr(json, "dump", boom)
    with pytest.raises(RuntimeError):
        repo.save([ServerSpec(id="s3", cpu_units_per_tick=1, mem_mb=1, rate_limit_per_sec=1)])

    assert path.read_bytes() == original_bytes
    assert list(tmp_path.glob(".servers-*")) == []
