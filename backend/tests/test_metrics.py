from __future__ import annotations

import pytest

from app.domain.errors import CorruptTraceError
from app.domain.metrics import compute_metrics
from app.domain.models import EventType, ServerSpec, SimulationEvent


def ev(t, event, rid, sid=None):
    return SimulationEvent(t=t, event=event, request_id=rid, server_id=sid)


def srv(id_, cpu=10, mem=1024, rate=1):
    return ServerSpec(id=id_, cpu_units_per_tick=cpu, mem_mb=mem, rate_limit_per_sec=rate)


# Identical fixture to test_summary.py's sample walkthrough (same underlying
# Day 1 sample trace) so metric assertions here are directly comparable to
# the mandatory summary's own exact numbers.
SAMPLE_EVENTS = (
    ev(0, EventType.ARRIVED, "r1"),
    ev(0, EventType.ARRIVED, "r2"),
    ev(0, EventType.STARTED, "r1", "s1"),
    ev(0, EventType.STARTED, "r2", "s2"),
    ev(1, EventType.ARRIVED, "r3"),
    ev(2, EventType.FINISHED, "r1", "s1"),
    ev(2, EventType.FINISHED, "r2", "s2"),
    ev(2, EventType.ARRIVED, "r4"),
    ev(2, EventType.STARTED, "r3", "s1"),
    ev(2, EventType.STARTED, "r4", "s2"),
    ev(3, EventType.FINISHED, "r4", "s2"),
    ev(4, EventType.FINISHED, "r3", "s1"),
)


def test_sample_trace_only_metrics_match_exact_spec_values():
    cluster, servers = compute_metrics(SAMPLE_EVENTS)

    assert cluster.duration_ticks == 4
    assert cluster.throughput_requests_per_tick == 1.0
    assert cluster.peak_queue_depth == 1
    assert cluster.avg_queue_depth == 0.25
    assert (cluster.total_requests, cluster.started, cluster.finished, cluster.dropped) == (4, 4, 4, 0)
    assert cluster.dropped_rate == 0.0

    by_id = {m.server_id: m for m in servers}
    assert by_id["s1"].busy_ticks == 4
    assert by_id["s2"].busy_ticks == 3
    assert by_id["s1"].requests_handled == 2
    assert by_id["s2"].requests_handled == 2
    assert by_id["s1"].busy_time_ratio == 1.0  # 4/4
    assert by_id["s2"].busy_time_ratio == 0.75  # 3/4
    assert all(m.work_units_total is None for m in servers)


def test_sample_trace_context_available_avg_cluster_busy_ratio_is_exact():
    servers_snapshot = [srv("s1", cpu=10), srv("s2", cpu=5)]
    cluster, servers = compute_metrics(SAMPLE_EVENTS, servers_snapshot)

    assert cluster.avg_cluster_busy_ratio == 0.875  # (4+3)/(2*4)
    assert cluster.configured_server_count == 2
    assert cluster.idle_configured_server_ids == ()

    by_id = {m.server_id: m for m in servers}
    assert by_id["s1"].cpu_units_per_tick == 10
    assert by_id["s2"].cpu_units_per_tick == 5


def test_context_includes_idle_configured_server_with_zero_requests():
    servers_snapshot = [srv("s1"), srv("s2"), srv("s3-idle")]
    cluster, servers = compute_metrics(SAMPLE_EVENTS, servers_snapshot)

    assert cluster.idle_configured_server_ids == ("s3-idle",)
    by_id = {m.server_id: m for m in servers}
    assert by_id["s3-idle"].requests_handled == 0
    assert by_id["s3-idle"].busy_ticks == 0
    assert by_id["s3-idle"].busy_time_ratio == 0.0


def test_no_context_omits_enriched_fields_and_lists_only_trace_seen_servers():
    cluster, servers = compute_metrics(SAMPLE_EVENTS, None)

    assert cluster.configured_server_count is None
    assert cluster.idle_configured_server_ids is None
    assert cluster.avg_cluster_busy_ratio is None
    assert {m.server_id for m in servers} == {"s1", "s2"}
    assert all(m.cpu_units_per_tick is None for m in servers)


def test_empty_events_returns_zeroed_metrics_without_crashing():
    cluster, servers = compute_metrics(())
    assert cluster.total_requests == 0
    assert cluster.duration_ticks == 0
    assert cluster.throughput_requests_per_tick is None
    assert cluster.peak_queue_depth == 0
    assert cluster.avg_queue_depth is None
    assert cluster.dropped_rate is None
    assert servers == ()


def test_empty_events_with_context_reports_all_servers_idle():
    servers_snapshot = [srv("s1"), srv("s2")]
    cluster, servers = compute_metrics((), servers_snapshot)
    assert cluster.configured_server_count == 2
    assert cluster.idle_configured_server_ids == ("s1", "s2")
    assert servers == ()


def test_zero_duration_single_tick_trace_yields_null_rate_metrics():
    # A request that arrives, starts, and is dropped/finishes all within one
    # observed tick window has no elapsed duration to average or divide by.
    events = (
        ev(5, EventType.ARRIVED, "r1"),
        ev(5, EventType.DROPPED, "r1"),
    )
    cluster, servers = compute_metrics(events)
    assert cluster.duration_ticks == 0
    assert cluster.throughput_requests_per_tick is None
    assert cluster.avg_queue_depth is None
    assert cluster.peak_queue_depth == 0
    assert cluster.dropped == 1
    assert cluster.dropped_rate == 1.0


def test_same_tick_arrived_and_started_stays_exactly_zero_and_does_not_raise():
    events = (
        ev(0, EventType.ARRIVED, "r1"),
        ev(0, EventType.STARTED, "r1", "s1"),
        ev(1, EventType.FINISHED, "r1", "s1"),
    )
    cluster, _ = compute_metrics(events)
    assert cluster.peak_queue_depth == 0
    assert cluster.avg_queue_depth == 0.0


def test_started_without_a_corresponding_arrived_raises_corrupt_trace_error():
    # An inconsistent event stream (a STARTED that was never counted as an
    # ARRIVED) drives the running queue-depth sum negative — an invariant
    # failure that must raise, not silently clamp to zero.
    events = (
        ev(0, EventType.STARTED, "r1", "s1"),
        ev(1, EventType.FINISHED, "r1", "s1"),
    )
    with pytest.raises(CorruptTraceError):
        compute_metrics(events)
