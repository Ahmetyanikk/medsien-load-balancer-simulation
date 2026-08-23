from __future__ import annotations

import pytest

from app.domain.autoscale import (
    HIGH_BUSY_RATIO,
    LIMITATIONS,
    LOW_BUSY_RATIO,
    MIN_SERVER_COUNT,
    REASON_CONTEXT_UNAVAILABLE,
    REASON_DROPPED_REQUESTS,
    REASON_HIGH_OCCUPANCY,
    REASON_HIGH_QUEUE_PRESSURE,
    REASON_INSUFFICIENT_DATA,
    REASON_LOW_OCCUPANCY_IDLE_CAPACITY,
    REASON_MINIMUM_SERVER_COUNT,
    REASON_STEADY_STATE,
    decide_scaling,
)
from app.domain.engine import SimulationEngine
from app.domain.metrics import ClusterMetrics, compute_metrics
from app.domain.models import RequestSpec, ServerSpec


def srv(id_, cpu=10, mem=1024, rate=1):
    return ServerSpec(id=id_, cpu_units_per_tick=cpu, mem_mb=mem, rate_limit_per_sec=rate)


def req(id_, t, work, mem):
    return RequestSpec(id=id_, arrival_t=t, work_units=work, mem_mb=mem)


def _assert_invariants(rec):
    if not rec.recommendation_available:
        assert rec.action is None
        assert rec.suggested_server_delta is None
        assert rec.removal_candidate_server_ids is None
    elif rec.action == "scale_up":
        assert rec.suggested_server_delta == 1
        assert rec.removal_candidate_server_ids is None
    elif rec.action == "scale_down":
        assert rec.suggested_server_delta == -1
        assert rec.removal_candidate_server_ids is not None
        assert len(rec.removal_candidate_server_ids) > 0
        assert list(rec.removal_candidate_server_ids) == sorted(rec.removal_candidate_server_ids)
    elif rec.action == "no_change":
        assert rec.suggested_server_delta is None
        assert rec.removal_candidate_server_ids is None
    else:
        pytest.fail(f"unexpected action: {rec.action!r}")
    assert rec.limitations == LIMITATIONS


# ---- primary scenarios, driven by the real engine + compute_metrics ----------


def test_canonical_sample_recommends_no_change_steady_state():
    servers = [srv("s1", cpu=10, mem=1024, rate=2), srv("s2", cpu=5, mem=512, rate=1)]
    requests = [
        req("r1", 0, 20, 200),
        req("r2", 0, 10, 100),
        req("r3", 1, 15, 300),
        req("r4", 2, 5, 100),
    ]
    result = SimulationEngine().simulate(servers, requests)
    cluster, _ = compute_metrics(result.events, servers)

    assert cluster.dropped == 0
    assert cluster.peak_queue_depth == 1
    assert cluster.configured_server_count == 2
    assert cluster.avg_cluster_busy_ratio == 0.875

    rec = decide_scaling(cluster)
    assert rec.recommendation_available is True
    assert rec.action == "no_change"
    assert rec.reason_codes == (REASON_STEADY_STATE,)
    _assert_invariants(rec)


def test_memory_incompatible_dropped_request_with_verified_context_recommends_scale_up():
    servers = [srv("s1", cpu=10, mem=100, rate=1)]
    requests = [req("r1", 0, 10, 500)]  # mem_mb exceeds every configured server
    result = SimulationEngine().simulate(servers, requests)
    cluster, _ = compute_metrics(result.events, servers)

    assert cluster.dropped == 1
    assert cluster.dropped_rate == 1.0

    rec = decide_scaling(cluster)
    assert rec.recommendation_available is True
    assert rec.action == "scale_up"
    assert rec.reason_codes == (REASON_DROPPED_REQUESTS,)
    assert "not guaranteed" in rec.explanation
    assert "guaranteed to resolve" in rec.explanation or "not guaranteed" in rec.explanation
    _assert_invariants(rec)


def test_one_server_two_jobs_same_tick_recommends_scale_up_with_both_reasons_in_order():
    servers = [srv("s1", cpu=10, mem=1000, rate=1)]
    requests = [req("r1", 0, 20, 10), req("r2", 0, 20, 10)]
    result = SimulationEngine().simulate(servers, requests)
    cluster, _ = compute_metrics(result.events, servers)

    assert cluster.peak_queue_depth == 1
    assert cluster.configured_server_count == 1
    assert cluster.avg_cluster_busy_ratio == 1.0

    rec = decide_scaling(cluster)
    assert rec.recommendation_available is True
    assert rec.action == "scale_up"
    assert rec.reason_codes == (REASON_HIGH_QUEUE_PRESSURE, REASON_HIGH_OCCUPANCY)  # exact required order
    _assert_invariants(rec)


def test_two_servers_sparse_jobs_recommends_scale_down_of_the_idle_one():
    servers = [srv("s1", cpu=10, mem=1000, rate=1), srv("s2", cpu=10, mem=1000, rate=1)]
    requests = [req("r1", 0, 10, 10), req("r2", 100, 10, 10)]
    result = SimulationEngine().simulate(servers, requests)
    cluster, server_metrics = compute_metrics(result.events, servers)

    # Deterministic tie-break (D-006): both requests land on s1; s2 stays idle.
    by_id = {m.server_id: m for m in server_metrics}
    assert by_id["s1"].requests_handled == 2
    assert by_id["s2"].requests_handled == 0
    assert cluster.peak_queue_depth == 0
    assert cluster.idle_configured_server_ids == ("s2",)
    assert cluster.avg_cluster_busy_ratio < LOW_BUSY_RATIO

    rec = decide_scaling(cluster)
    assert rec.recommendation_available is True
    assert rec.action == "scale_down"
    assert rec.reason_codes == (REASON_LOW_OCCUPANCY_IDLE_CAPACITY,)
    assert rec.removal_candidate_server_ids == ("s2",)
    assert "at most one" in rec.explanation
    _assert_invariants(rec)


def test_same_sparse_workload_with_only_one_configured_server_recommends_no_change_minimum_server_count():
    servers = [srv("s1", cpu=10, mem=1000, rate=1)]
    requests = [req("r1", 0, 10, 10), req("r2", 100, 10, 10)]
    result = SimulationEngine().simulate(servers, requests)
    cluster, _ = compute_metrics(result.events, servers)

    assert cluster.configured_server_count == 1
    assert cluster.peak_queue_depth == 0
    assert cluster.avg_cluster_busy_ratio < LOW_BUSY_RATIO

    rec = decide_scaling(cluster)
    assert rec.recommendation_available is True
    assert rec.action == "no_change"
    assert rec.reason_codes == (REASON_MINIMUM_SERVER_COUNT,)
    _assert_invariants(rec)


def test_empty_metrics_recommends_unavailable_insufficient_data():
    cluster, _ = compute_metrics(())
    assert cluster.total_requests == 0

    rec = decide_scaling(cluster)
    assert rec.recommendation_available is False
    assert rec.action is None
    assert rec.reason_codes == (REASON_INSUFFICIENT_DATA,)
    _assert_invariants(rec)


def test_trace_metrics_without_verified_context_recommends_unavailable_context_unavailable():
    servers = [srv("s1"), srv("s2")]
    requests = [req("r1", 0, 10, 10)]
    result = SimulationEngine().simulate(servers, requests)
    cluster, _ = compute_metrics(result.events, verified_servers=None)
    assert cluster.configured_server_count is None

    rec = decide_scaling(cluster)
    assert rec.recommendation_available is False
    assert rec.action is None
    assert rec.reason_codes == (REASON_CONTEXT_UNAVAILABLE,)
    _assert_invariants(rec)


# ---- precedence and boundary requirements -------------------------------------


def test_total_requests_zero_outranks_context_unavailability():
    cluster, _ = compute_metrics((), verified_servers=None)
    assert cluster.total_requests == 0
    assert cluster.configured_server_count is None

    rec = decide_scaling(cluster)
    assert rec.reason_codes == (REASON_INSUFFICIENT_DATA,)  # not context_unavailable


def test_context_unavailability_outranks_drops():
    servers = [srv("s1", cpu=10, mem=100, rate=1)]
    requests = [req("r1", 0, 10, 500)]  # dropped
    result = SimulationEngine().simulate(servers, requests)
    cluster, _ = compute_metrics(result.events, verified_servers=None)
    assert cluster.dropped_rate == 1.0
    assert cluster.configured_server_count is None

    rec = decide_scaling(cluster)
    assert rec.reason_codes == (REASON_CONTEXT_UNAVAILABLE,)  # not scale_up/dropped_requests
    assert rec.action is None


def test_drops_outrank_other_available_signals():
    # A trace that ALSO exhibits high queue+occupancy, but with a drop present too.
    cluster = ClusterMetrics(
        total_requests=5,
        started=4,
        finished=4,
        dropped=1,
        dropped_rate=0.2,
        duration_ticks=4,
        throughput_requests_per_tick=1.0,
        peak_queue_depth=3,
        avg_queue_depth=1.0,
        configured_server_count=1,
        idle_configured_server_ids=(),
        avg_cluster_busy_ratio=1.0,
    )
    rec = decide_scaling(cluster)
    assert rec.action == "scale_up"
    assert rec.reason_codes == (REASON_DROPPED_REQUESTS,)  # not high_queue_pressure/high_occupancy


@pytest.mark.parametrize(
    "avg_busy,expect_high",
    [(HIGH_BUSY_RATIO, True), (HIGH_BUSY_RATIO - 0.01, False)],
)
def test_exact_high_threshold_boundary(avg_busy, expect_high):
    cluster = ClusterMetrics(
        total_requests=2,
        started=2,
        finished=2,
        dropped=0,
        dropped_rate=0.0,
        duration_ticks=4,
        throughput_requests_per_tick=0.5,
        peak_queue_depth=1,
        avg_queue_depth=0.5,
        configured_server_count=1,
        idle_configured_server_ids=(),
        avg_cluster_busy_ratio=avg_busy,
    )
    rec = decide_scaling(cluster)
    if expect_high:
        assert rec.action == "scale_up"
        assert rec.reason_codes == (REASON_HIGH_QUEUE_PRESSURE, REASON_HIGH_OCCUPANCY)
    else:
        assert rec.action != "scale_up"


def test_exact_low_threshold_equality_does_not_scale_down():
    cluster = ClusterMetrics(
        total_requests=2,
        started=2,
        finished=2,
        dropped=0,
        dropped_rate=0.0,
        duration_ticks=100,
        throughput_requests_per_tick=0.02,
        peak_queue_depth=0,
        avg_queue_depth=0.0,
        configured_server_count=2,
        idle_configured_server_ids=("s2",),
        avg_cluster_busy_ratio=LOW_BUSY_RATIO,  # exactly 0.20, not < 0.20
    )
    rec = decide_scaling(cluster)
    assert rec.action != "scale_down"
    assert rec.action == "no_change"
    assert rec.reason_codes == (REASON_STEADY_STATE,)


def test_queue_pressure_alone_does_not_scale_up():
    cluster = ClusterMetrics(
        total_requests=3,
        started=3,
        finished=3,
        dropped=0,
        dropped_rate=0.0,
        duration_ticks=4,
        throughput_requests_per_tick=0.75,
        peak_queue_depth=2,  # >= configured_server_count
        avg_queue_depth=1.0,
        configured_server_count=2,
        idle_configured_server_ids=(),
        avg_cluster_busy_ratio=0.5,  # below HIGH_BUSY_RATIO
    )
    rec = decide_scaling(cluster)
    assert rec.action != "scale_up"


def test_occupancy_alone_does_not_scale_up():
    # Mirrors the canonical sample's own shape: high occupancy, but queue never
    # reached the configured server count.
    cluster = ClusterMetrics(
        total_requests=4,
        started=4,
        finished=4,
        dropped=0,
        dropped_rate=0.0,
        duration_ticks=4,
        throughput_requests_per_tick=1.0,
        peak_queue_depth=1,
        avg_queue_depth=0.25,
        configured_server_count=2,
        idle_configured_server_ids=(),
        avg_cluster_busy_ratio=0.875,
        # peak_queue_depth(1) < configured_server_count(2)
    )
    rec = decide_scaling(cluster)
    assert rec.action != "scale_up"


def test_candidate_ids_are_sorted_from_deliberately_unsorted_input():
    cluster = ClusterMetrics(
        total_requests=1,
        started=1,
        finished=1,
        dropped=0,
        dropped_rate=0.0,
        duration_ticks=10,
        throughput_requests_per_tick=0.1,
        peak_queue_depth=0,
        avg_queue_depth=0.0,
        configured_server_count=4,
        idle_configured_server_ids=("s3", "s1", "s2"),  # deliberately unsorted
        avg_cluster_busy_ratio=0.01,
    )
    rec = decide_scaling(cluster)
    assert rec.action == "scale_down"
    assert rec.removal_candidate_server_ids == ("s1", "s2", "s3")


def test_repeated_calls_return_exactly_equal_results():
    servers = [srv("s1"), srv("s2")]
    requests = [req("r1", 0, 10, 10)]
    result = SimulationEngine().simulate(servers, requests)
    cluster, _ = compute_metrics(result.events, servers)

    first = decide_scaling(cluster)
    second = decide_scaling(cluster)
    assert first == second


def test_inputs_are_not_mutated():
    servers = [srv("s1"), srv("s2")]
    requests = [req("r1", 0, 10, 10)]
    result = SimulationEngine().simulate(servers, requests)
    cluster, _ = compute_metrics(result.events, servers)
    idle_before = cluster.idle_configured_server_ids

    decide_scaling(cluster)

    assert cluster.idle_configured_server_ids == idle_before  # unchanged (tuple, but assert anyway)


def test_fixed_limitations_are_deterministic_and_always_present():
    cluster_a, _ = compute_metrics(())
    cluster_b = ClusterMetrics(
        total_requests=1,
        started=1,
        finished=1,
        dropped=0,
        dropped_rate=0.0,
        duration_ticks=1,
        throughput_requests_per_tick=1.0,
        peak_queue_depth=0,
        avg_queue_depth=0.0,
        configured_server_count=1,
        idle_configured_server_ids=(),
        avg_cluster_busy_ratio=0.5,
    )
    rec_a = decide_scaling(cluster_a)
    rec_b = decide_scaling(cluster_b)
    assert rec_a.limitations == rec_b.limitations == LIMITATIONS
    assert len(LIMITATIONS) > 0


def test_min_server_count_constant_is_one():
    assert MIN_SERVER_COUNT == 1
