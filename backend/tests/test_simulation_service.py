from __future__ import annotations

import os

import pytest

from app.domain.errors import EmptyRequestConfigurationError
from app.services.simulation_service import SimulationService


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
