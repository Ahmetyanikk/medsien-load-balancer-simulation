from __future__ import annotations

import hashlib
import os
import subprocess
import sys

import pytest

from app.domain.errors import EmptyRequestConfigurationError
from app.domain.strategies import FastestFitStrategy, LowestIdStrategy
from app.services.simulation_service import SimulationService

CANONICAL_DAY1_TRACE_SHA256 = "225b3f69a060d1821c7756e40830a9274f595b516eeb74e3ff0bf0ca75201845"


def test_run_rejects_empty_requests_csv_without_publishing(tmp_path, servers_json_path):
    empty_csv = tmp_path / "requests.csv"
    empty_csv.write_text("t,request_id,work_units,mem_mb\n", encoding="utf-8")
    output = tmp_path / "run.jsonl"

    with pytest.raises(EmptyRequestConfigurationError):
        SimulationService().run(servers_json_path, empty_csv, output)

    assert not output.exists()


def test_publish_failure_leaves_previous_trace_unchanged_and_cleans_temp_files(tmp_path, monkeypatch):
    output = tmp_path / "run.jsonl"
    SimulationService._publish(output, '{"t":0,"event":"REQUEST_ARRIVED","request_id":"r1"}\n')
    original_bytes = output.read_bytes()

    def boom(*args, **kwargs):
        raise RuntimeError("simulated os.replace failure")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(RuntimeError):
        SimulationService._publish(output, '{"t":0,"event":"REQUEST_ARRIVED","request_id":"r2"}\n')

    assert output.read_bytes() == original_bytes
    assert list(output.parent.glob(".run-*")) == []


# ---- Day 3A: strategy selection does not disturb the frozen default trace -----


def test_no_strategy_argument_still_produces_the_canonical_default_trace(
    tmp_path, servers_json_path, requests_csv_path
):
    explicit = tmp_path / "explicit.jsonl"
    implicit = tmp_path / "implicit.jsonl"
    SimulationService().run(servers_json_path, requests_csv_path, explicit, strategy=FastestFitStrategy())
    SimulationService().run(servers_json_path, requests_csv_path, implicit)
    assert explicit.read_bytes() == implicit.read_bytes()
    assert hashlib.sha256(implicit.read_bytes()).hexdigest() == CANONICAL_DAY1_TRACE_SHA256
    assert hashlib.sha256(explicit.read_bytes()).hexdigest() == CANONICAL_DAY1_TRACE_SHA256


def test_repeated_run_same_alternate_strategy_is_byte_identical(tmp_path, servers_json_path, requests_csv_path):
    first = tmp_path / "first.jsonl"
    second = tmp_path / "second.jsonl"
    SimulationService().run(servers_json_path, requests_csv_path, first, strategy=LowestIdStrategy())
    SimulationService().run(servers_json_path, requests_csv_path, second, strategy=LowestIdStrategy())
    assert hashlib.sha256(first.read_bytes()).hexdigest() == hashlib.sha256(second.read_bytes()).hexdigest()


@pytest.mark.parametrize("strategy", [FastestFitStrategy(), LowestIdStrategy()])
def test_both_strategies_produce_validator_valid_traces(
    tmp_path, servers_json_path, requests_csv_path, validator_path, strategy
):
    output = tmp_path / f"run_{strategy.name}.jsonl"
    SimulationService().run(servers_json_path, requests_csv_path, output, strategy=strategy)

    proc = subprocess.run(
        [
            sys.executable,
            str(validator_path),
            "--servers",
            str(servers_json_path),
            "--requests",
            str(requests_csv_path),
            "--run",
            str(output),
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert proc.returncode == 0, f"validator failed for {strategy.name}:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    assert "RESULT: VALID" in proc.stdout
