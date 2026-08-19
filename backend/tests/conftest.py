from pathlib import Path

import pytest

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
