from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BASE_DIR.parent
DATA_DIR = BASE_DIR / "data"
PROVIDED_DIR = REPO_ROOT / "provided"

SERVERS_PATH = DATA_DIR / "servers.json"
REQUESTS_PATH = DATA_DIR / "requests.csv"
RUN_JSONL_PATH = DATA_DIR / "run.jsonl"
RUN_CONTEXT_PATH = DATA_DIR / "run_context.json"


@dataclass(frozen=True)
class Settings:
    """Injectable runtime paths. Production uses the module-level defaults above;
    tests construct their own Settings pointing at an isolated tmp_path so no test
    ever reads or writes the real backend/data directory."""

    data_dir: Path = DATA_DIR
    provided_dir: Path = PROVIDED_DIR

    @property
    def servers_path(self) -> Path:
        return self.data_dir / "servers.json"

    @property
    def requests_path(self) -> Path:
        return self.data_dir / "requests.csv"

    @property
    def run_jsonl_path(self) -> Path:
        return self.data_dir / "run.jsonl"

    @property
    def run_context_path(self) -> Path:
        return self.data_dir / "run_context.json"
