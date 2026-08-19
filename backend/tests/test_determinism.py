from __future__ import annotations

import hashlib

from app.services.simulation_service import SimulationService


def sha256_of(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_repeated_runs_produce_byte_identical_output(tmp_path, servers_json_path, requests_csv_path):
    out_a = tmp_path / "run_a.jsonl"
    out_b = tmp_path / "run_b.jsonl"

    SimulationService().run(servers_json_path, requests_csv_path, out_a)
    SimulationService().run(servers_json_path, requests_csv_path, out_b)

    assert out_a.read_bytes() == out_b.read_bytes()
    assert sha256_of(out_a) == sha256_of(out_b)


def test_output_independent_of_csv_row_order(tmp_path, servers_json_path, requests_csv_path):
    canonical_out = tmp_path / "canonical.jsonl"
    SimulationService().run(servers_json_path, requests_csv_path, canonical_out)

    original_lines = requests_csv_path.read_text(encoding="utf-8").splitlines()
    header, rows = original_lines[0], original_lines[1:]
    shuffled_csv = tmp_path / "requests_shuffled.csv"
    shuffled_csv.write_text("\n".join([header] + list(reversed(rows))) + "\n", encoding="utf-8")

    shuffled_out = tmp_path / "shuffled.jsonl"
    SimulationService().run(servers_json_path, shuffled_csv, shuffled_out)

    assert canonical_out.read_bytes() == shuffled_out.read_bytes()