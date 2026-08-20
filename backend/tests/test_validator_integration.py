from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app.services.simulation_service import SimulationService

BACKEND_DATA_DIR = Path(__file__).resolve().parents[1] / "data"
SAMPLE_RUN_OUTPUT = BACKEND_DATA_DIR / "run.jsonl"


def test_generated_sample_passes_real_validator(servers_json_path, requests_csv_path, validator_path):
    """Generates the mandatory sample run.jsonl deliverable at backend/data/run.jsonl
    and runs the real, unmodified provided/validate_run.py against it."""
    BACKEND_DATA_DIR.mkdir(parents=True, exist_ok=True)
    SimulationService().run(servers_json_path, requests_csv_path, SAMPLE_RUN_OUTPUT)

    proc = subprocess.run(
        [
            sys.executable,
            str(validator_path),
            "--servers",
            str(servers_json_path),
            "--requests",
            str(requests_csv_path),
            "--run",
            str(SAMPLE_RUN_OUTPUT),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )

    assert proc.returncode == 0, f"validator failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    assert "RESULT: VALID" in proc.stdout
