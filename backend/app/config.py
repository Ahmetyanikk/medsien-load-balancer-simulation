from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
SERVERS_PATH = DATA_DIR / "servers.json"
RUN_JSONL_PATH = DATA_DIR / "run.jsonl"
