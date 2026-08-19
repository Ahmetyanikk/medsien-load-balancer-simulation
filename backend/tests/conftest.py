import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]
PROVIDED_DIR = REPO_ROOT / "provided"


@pytest.fixture
def provided_dir() -> Path:
    return PROVIDED_DIR


@pytest.fixture
def servers_json_path() -> Path:
    return PROVIDED_DIR / "servers.json"


@pytest.fixture
def requests_csv_path() -> Path:
    return PROVIDED_DIR / "requests.csv"


@pytest.fixture
def sample_run_jsonl_path() -> Path:
    return PROVIDED_DIR / "run.jsonl"


@pytest.fixture
def validator_path() -> Path:
    return PROVIDED_DIR / "validate_run.py"


# ---- Day 2A: isolated API test fixtures ------------------------------------
#
# No test may ever instantiate create_app(Settings()) with the real defaults —
# that would run lifespan seeding against the real backend/data directory. Every
# API test gets its own tmp_path-backed Settings and its own throwaway copy of
# provided/ (read from the real provided/ once, never written back to it).


@pytest.fixture
def isolated_provided_dir(tmp_path: Path) -> Path:
    dest = tmp_path / "provided"
    dest.mkdir()
    shutil.copyfile(PROVIDED_DIR / "servers.json", dest / "servers.json")
    shutil.copyfile(PROVIDED_DIR / "requests.csv", dest / "requests.csv")
    return dest


@pytest.fixture
def isolated_settings(tmp_path: Path, isolated_provided_dir: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", provided_dir=isolated_provided_dir)


@pytest.fixture
def isolated_client(isolated_settings: Settings):
    app = create_app(isolated_settings)
    with TestClient(app) as client:
        yield client
