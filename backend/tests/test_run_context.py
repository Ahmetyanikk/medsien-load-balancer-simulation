from __future__ import annotations

import json

import pytest

from app.domain.errors import RunContextPublicationError
from app.domain.models import ServerSpec
from app.services import run_context
from app.services.simulation_service import SimulationService

KNOWN_STRATEGIES = frozenset({"fastest_finish", "lowest_id"})


def srv(id_, cpu=10, mem=1024, rate=1):
    return ServerSpec(id=id_, cpu_units_per_tick=cpu, mem_mb=mem, rate_limit_per_sec=rate)


def write_servers_json(path, servers):
    path.write_text(
        json.dumps(
            {
                "tick_seconds": 1,
                "servers": [
                    {
                        "id": s.id,
                        "cpu_units_per_tick": s.cpu_units_per_tick,
                        "mem_mb": s.mem_mb,
                        "rate_limit_per_sec": s.rate_limit_per_sec,
                    }
                    for s in servers
                ],
            }
        ),
        encoding="utf-8",
    )


def write_single_request_csv(path):
    path.write_text("t,request_id,work_units,mem_mb\n0,r1,10,100\n", encoding="utf-8")


# ---- run_context module: pure publish/load round-trip -------------------------


def test_publish_complete_then_load_verified_round_trips(tmp_path):
    context_path = tmp_path / "run_context.json"
    trace_bytes = b'{"t":0,"event":"REQUEST_ARRIVED","request_id":"r1"}\n'
    import hashlib

    run_context.publish_pending(context_path)
    run_context.publish_complete(
        context_path,
        trace_sha256=hashlib.sha256(trace_bytes).hexdigest(),
        strategy="fastest_finish",
        servers=[srv("s1")],
    )
    result = run_context.load_verified(context_path, trace_bytes, KNOWN_STRATEGIES)
    assert result is not None
    assert result["strategy"] == "fastest_finish"
    assert [s.id for s in result["servers"]] == ["s1"]


def test_atomic_write_cleans_up_temp_file_on_non_oserror_exception(tmp_path):
    context_path = tmp_path / "run_context.json"
    non_serializable = {"schema_version": 1, "status": "pending", "bad": object()}

    with pytest.raises(TypeError):
        run_context._atomic_write_json(context_path, non_serializable)

    assert not context_path.exists()
    assert list(tmp_path.glob(".run-context-*")) == []


# ---- required adversarial test 2: missing context ------------------------------


def test_missing_context_file_degrades_to_none(tmp_path):
    context_path = tmp_path / "run_context.json"
    assert run_context.load_verified(context_path, b"anything", KNOWN_STRATEGIES) is None


# ---- required adversarial test 3: malformed context ----------------------------


def test_malformed_json_context_degrades_to_none(tmp_path):
    context_path = tmp_path / "run_context.json"
    context_path.write_text("{not valid json", encoding="utf-8")
    assert run_context.load_verified(context_path, b"anything", KNOWN_STRATEGIES) is None


def test_context_missing_required_fields_degrades_to_none(tmp_path):
    context_path = tmp_path / "run_context.json"
    context_path.write_text(json.dumps({"schema_version": 1, "status": "complete"}), encoding="utf-8")
    assert run_context.load_verified(context_path, b"anything", KNOWN_STRATEGIES) is None


# ---- strict schema_version type validation (polish pass) ----------------------


def _write_full_valid_context(context_path, trace_bytes, schema_version_value):
    import hashlib

    context_path.write_text(
        json.dumps(
            {
                "schema_version": schema_version_value,
                "status": "complete",
                "trace_sha256": hashlib.sha256(trace_bytes).hexdigest(),
                "strategy": "fastest_finish",
                "servers": [{"id": "s1", "cpu_units_per_tick": 10, "mem_mb": 100, "rate_limit_per_sec": 1}],
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    "schema_version_value",
    [
        pytest.param(True, id="boolean-true"),
        pytest.param("1", id="numeric-string"),
        pytest.param(1.0, id="float"),
        pytest.param(2, id="unsupported-integer-version"),
    ],
)
def test_schema_version_strict_type_check_rejects_every_non_conforming_value(tmp_path, schema_version_value):
    context_path = tmp_path / "run_context.json"
    trace_bytes = b"trace"
    _write_full_valid_context(context_path, trace_bytes, schema_version_value)
    assert run_context.load_verified(context_path, trace_bytes, KNOWN_STRATEGIES) is None


def test_schema_version_exact_integer_one_is_accepted(tmp_path):
    context_path = tmp_path / "run_context.json"
    trace_bytes = b"trace"
    _write_full_valid_context(context_path, trace_bytes, 1)
    result = run_context.load_verified(context_path, trace_bytes, KNOWN_STRATEGIES)
    assert result is not None
    assert result["strategy"] == "fastest_finish"


def test_context_with_invalid_server_snapshot_degrades_to_none(tmp_path):
    import hashlib

    context_path = tmp_path / "run_context.json"
    trace_bytes = b"trace"
    context_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "complete",
                "trace_sha256": hashlib.sha256(trace_bytes).hexdigest(),
                "strategy": "fastest_finish",
                "servers": [{"id": "s1", "cpu_units_per_tick": -1, "mem_mb": 10, "rate_limit_per_sec": 1}],
            }
        ),
        encoding="utf-8",
    )
    assert run_context.load_verified(context_path, trace_bytes, KNOWN_STRATEGIES) is None


# ---- strict server-snapshot schema validation (correction pass) ---------------


def _write_context_with_servers(context_path, trace_bytes, servers_payload):
    import hashlib

    context_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "complete",
                "trace_sha256": hashlib.sha256(trace_bytes).hexdigest(),
                "strategy": "fastest_finish",
                "servers": servers_payload,
            }
        ),
        encoding="utf-8",
    )


VALID_SERVER = {"id": "s1", "cpu_units_per_tick": 10, "mem_mb": 100, "rate_limit_per_sec": 1}


@pytest.mark.parametrize(
    "servers_payload",
    [
        pytest.param(["not-an-object"], id="non-object-entry"),
        pytest.param([{**VALID_SERVER, "id": 1}], id="integer-server-id"),
        pytest.param([{**VALID_SERVER, "id": "   "}], id="blank-server-id"),
        pytest.param([{**VALID_SERVER, "cpu_units_per_tick": "10"}], id="numeric-string-cpu"),
        pytest.param([{**VALID_SERVER, "cpu_units_per_tick": True}], id="boolean-cpu"),
        pytest.param([{**VALID_SERVER, "mem_mb": True}], id="boolean-mem"),
        pytest.param([{**VALID_SERVER, "rate_limit_per_sec": False}], id="boolean-rate"),
        pytest.param([{**VALID_SERVER, "cpu_units_per_tick": 10.0}], id="float-cpu"),
        pytest.param([{**VALID_SERVER, "mem_mb": 100.5}], id="float-mem"),
        pytest.param([{k: v for k, v in VALID_SERVER.items() if k != "mem_mb"}], id="missing-field"),
        pytest.param([{**VALID_SERVER, "region": "us-east"}], id="unexpected-extra-field"),
        pytest.param(
            [VALID_SERVER, {**VALID_SERVER, "cpu_units_per_tick": 5}],
            id="duplicate-server-id",
        ),
        pytest.param([{**VALID_SERVER, "cpu_units_per_tick": 0}], id="cpu-not-positive-boundary"),
        pytest.param([{**VALID_SERVER, "mem_mb": -1}], id="mem-negative-boundary"),
        pytest.param([{**VALID_SERVER, "rate_limit_per_sec": -1}], id="rate-negative-boundary"),
    ],
)
def test_strict_server_snapshot_validation_rejects_every_malformed_case(tmp_path, servers_payload):
    context_path = tmp_path / "run_context.json"
    trace_bytes = b"trace"
    _write_context_with_servers(context_path, trace_bytes, servers_payload)
    assert run_context.load_verified(context_path, trace_bytes, KNOWN_STRATEGIES) is None


def test_strict_server_snapshot_validation_accepts_exact_boundary_values(tmp_path):
    context_path = tmp_path / "run_context.json"
    trace_bytes = b"trace"
    boundary_servers = [
        {"id": "s1", "cpu_units_per_tick": 1, "mem_mb": 0, "rate_limit_per_sec": 0},
    ]
    _write_context_with_servers(context_path, trace_bytes, boundary_servers)
    result = run_context.load_verified(context_path, trace_bytes, KNOWN_STRATEGIES)
    assert result is not None
    assert result["servers"][0].cpu_units_per_tick == 1
    assert result["servers"][0].mem_mb == 0
    assert result["servers"][0].rate_limit_per_sec == 0


# ---- required adversarial test 4: pending context ------------------------------


def test_pending_status_context_degrades_to_none(tmp_path):
    context_path = tmp_path / "run_context.json"
    run_context.publish_pending(context_path)
    assert run_context.load_verified(context_path, b"anything", KNOWN_STRATEGIES) is None


# ---- required adversarial test 5: hash mismatch --------------------------------


def test_trace_hash_mismatch_degrades_to_none(tmp_path):
    context_path = tmp_path / "run_context.json"
    run_context.publish_complete(
        context_path, trace_sha256="0" * 64, strategy="fastest_finish", servers=[srv("s1")]
    )
    assert run_context.load_verified(context_path, b"actual trace bytes", KNOWN_STRATEGIES) is None


def test_unrecognized_strategy_degrades_to_none(tmp_path):
    import hashlib

    context_path = tmp_path / "run_context.json"
    trace_bytes = b"trace"
    run_context.publish_complete(
        context_path,
        trace_sha256=hashlib.sha256(trace_bytes).hexdigest(),
        strategy="not_a_real_strategy",
        servers=[srv("s1")],
    )
    assert run_context.load_verified(context_path, trace_bytes, KNOWN_STRATEGIES) is None


# ---- SimulationService integration: full publication sequence -----------------


def test_successful_run_publishes_complete_context(tmp_path, servers_json_path, requests_csv_path):
    output = tmp_path / "run.jsonl"
    context_path = tmp_path / "run_context.json"
    SimulationService().run(servers_json_path, requests_csv_path, output, context_path=context_path)

    raw = json.loads(context_path.read_text(encoding="utf-8"))
    assert raw["status"] == "complete"
    import hashlib

    assert raw["trace_sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert raw["strategy"] == "fastest_finish"


# ---- required adversarial test 7: pending-marker publish failure --------------


def test_pending_marker_publish_failure_prevents_new_trace_and_preserves_previous(
    tmp_path, servers_json_path, requests_csv_path, monkeypatch
):
    output = tmp_path / "run.jsonl"
    context_path = tmp_path / "run_context.json"
    service = SimulationService()

    # First, a real successful run establishes a previous trace.
    service.run(servers_json_path, requests_csv_path, output, context_path=context_path)
    previous_bytes = output.read_bytes()

    def boom(path):
        raise RunContextPublicationError("simulated pending-marker publish failure")

    monkeypatch.setattr(run_context, "publish_pending", boom)

    with pytest.raises(RunContextPublicationError):
        service.run(servers_json_path, requests_csv_path, output, context_path=context_path)

    assert output.read_bytes() == previous_bytes


# ---- required adversarial test 8: trace publish failure after pending ---------


def test_trace_publish_failure_after_pending_preserves_previous_trace_and_context_unavailable(
    tmp_path, servers_json_path, requests_csv_path, monkeypatch
):
    output = tmp_path / "run.jsonl"
    context_path = tmp_path / "run_context.json"
    service = SimulationService()

    service.run(servers_json_path, requests_csv_path, output, context_path=context_path)
    previous_bytes = output.read_bytes()

    def boom(*args, **kwargs):
        raise RuntimeError("simulated trace publish failure")

    monkeypatch.setattr(SimulationService, "_publish", staticmethod(boom))

    with pytest.raises(RuntimeError):
        service.run(servers_json_path, requests_csv_path, output, context_path=context_path)

    assert output.read_bytes() == previous_bytes
    assert run_context.load_verified(context_path, previous_bytes, KNOWN_STRATEGIES) is None


# ---- required adversarial test 6: complete-context publish failure ------------


def test_complete_context_publish_failure_after_trace_success_still_returns_result(
    tmp_path, servers_json_path, requests_csv_path, monkeypatch
):
    output = tmp_path / "run.jsonl"
    context_path = tmp_path / "run_context.json"
    service = SimulationService()

    def boom(*args, **kwargs):
        raise OSError("simulated complete-context publish failure")

    monkeypatch.setattr(run_context, "publish_complete", boom)

    result = service.run(servers_json_path, requests_csv_path, output, context_path=context_path)

    assert result.total_requests >= 0  # run genuinely succeeded, not raised
    assert output.exists()
    trace_bytes = output.read_bytes()
    assert run_context.load_verified(context_path, trace_bytes, KNOWN_STRATEGIES) is None


# ---- required adversarial test 9 (most important): identical trace bytes, ------
# ---- different server snapshot, forced final-publish failure ------------------


def test_identical_trace_different_snapshot_forced_publish_failure_never_trusts_stale_context(
    tmp_path, monkeypatch
):
    """Models an ordinary sequential-run scenario, not manual file tampering:

    Run 1 uses servers=[s1] and completes normally, publishing a genuine
    complete context describing that one-server snapshot.

    Run 2 uses servers=[s1, s2] where s2 is deliberately never eligible to
    receive the only request (s1 always wins on score), so the two runs
    produce byte-identical run.jsonl trace bytes despite a different
    configured server snapshot. Run 2's final complete-context publish is
    forced to fail.

    Because publish_pending() unconditionally invalidates the context BEFORE
    the new (identical-hash) trace is even published, the old run's complete
    context can never survive to be mistakenly re-trusted for run 2's trace,
    even though the hash alone would otherwise match it.
    """
    servers_path = tmp_path / "servers.json"
    requests_path = tmp_path / "requests.csv"
    output = tmp_path / "run.jsonl"
    context_path = tmp_path / "run_context.json"
    write_single_request_csv(requests_path)

    write_servers_json(servers_path, [srv("s1", cpu=10)])
    service = SimulationService()
    service.run(servers_path, requests_path, output, context_path=context_path)
    trace_after_run1 = output.read_bytes()

    write_servers_json(servers_path, [srv("s1", cpu=10), srv("s2", cpu=1)])

    def boom(*args, **kwargs):
        raise OSError("simulated complete-context publish failure on run 2")

    monkeypatch.setattr(run_context, "publish_complete", boom)
    service.run(servers_path, requests_path, output, context_path=context_path)

    trace_after_run2 = output.read_bytes()
    assert trace_after_run2 == trace_after_run1  # confirms the identical-bytes premise

    result = run_context.load_verified(context_path, trace_after_run2, KNOWN_STRATEGIES)
    assert result is None  # never returns the stale run-1 (s1-only) context
