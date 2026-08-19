from __future__ import annotations

import pytest

from app.config import Settings
from app.domain.errors import SeedSourceMissingError
from app.services.seeding import seed_if_missing


def _settings(tmp_path, provided_dir) -> Settings:
    return Settings(data_dir=tmp_path / "data", provided_dir=provided_dir)


def test_seed_copies_servers_and_requests_when_missing(tmp_path, isolated_provided_dir):
    settings = _settings(tmp_path, isolated_provided_dir)
    seed_if_missing(settings)
    assert settings.servers_path.exists()
    assert settings.requests_path.exists()
    assert settings.servers_path.read_text(encoding="utf-8") == (isolated_provided_dir / "servers.json").read_text(encoding="utf-8")
    assert settings.requests_path.read_text(encoding="utf-8") == (isolated_provided_dir / "requests.csv").read_text(encoding="utf-8")


def test_seed_never_creates_run_jsonl(tmp_path, isolated_provided_dir):
    settings = _settings(tmp_path, isolated_provided_dir)
    seed_if_missing(settings)
    assert not settings.run_jsonl_path.exists()


def test_seed_never_overwrites_existing_servers_json_even_if_empty(tmp_path, isolated_provided_dir):
    settings = _settings(tmp_path, isolated_provided_dir)
    settings.data_dir.mkdir(parents=True)
    settings.servers_path.write_text('{"tick_seconds":1,"servers":[]}', encoding="utf-8")

    seed_if_missing(settings)

    assert settings.servers_path.read_text(encoding="utf-8") == '{"tick_seconds":1,"servers":[]}'


def test_seed_never_overwrites_existing_requests_csv(tmp_path, isolated_provided_dir):
    settings = _settings(tmp_path, isolated_provided_dir)
    settings.data_dir.mkdir(parents=True)
    custom = "t,request_id,work_units,mem_mb\n0,custom1,5,50\n"
    settings.requests_path.write_text(custom, encoding="utf-8")

    seed_if_missing(settings)

    assert settings.requests_path.read_text(encoding="utf-8") == custom


def test_seed_missing_source_raises_controlled_error(tmp_path):
    empty_provided = tmp_path / "empty_provided"
    empty_provided.mkdir()
    settings = _settings(tmp_path, empty_provided)

    with pytest.raises(SeedSourceMissingError):
        seed_if_missing(settings)
