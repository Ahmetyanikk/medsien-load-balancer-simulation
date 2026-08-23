from __future__ import annotations

import pytest

from app.domain.errors import CorruptTraceError
from app.domain.models import EventType, SimulationEvent
from app.domain.queue_depth import QueueDepthPoint, compute_queue_depth


def ev(t, event, rid, sid=None):
    return SimulationEvent(t=t, event=event, request_id=rid, server_id=sid)


# Identical to test_metrics.py's SAMPLE_EVENTS fixture.
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


def test_canonical_sample_matches_existing_metrics_values_exactly():
    result = compute_queue_depth(SAMPLE_EVENTS)
    assert result.start_tick == 0
    assert result.end_tick == 4
    assert result.duration_ticks == 4
    assert result.peak_depth == 1
    assert result.avg_depth == 0.25


def test_single_tick_trace_start_equals_end_no_division_error():
    events = (
        ev(5, EventType.ARRIVED, "r1"),
        ev(5, EventType.DROPPED, "r1"),
    )
    result = compute_queue_depth(events)
    assert result.start_tick == result.end_tick == 5
    assert result.duration_ticks == 0
    assert result.avg_depth is None
    assert len(result.points) == 1
    assert result.points[0].tick == 5
    assert result.points[0].depth == 0
    assert result.peak_depth == 0


def test_all_zero_depth_trace_returns_exactly_one_anchor_point():
    # Every arrival is immediately started in the same tick -> depth never
    # leaves zero anywhere in the trace.
    events = (
        ev(0, EventType.ARRIVED, "r1"),
        ev(0, EventType.STARTED, "r1", "s1"),
        ev(1, EventType.FINISHED, "r1", "s1"),
        ev(5, EventType.ARRIVED, "r2"),
        ev(5, EventType.STARTED, "r2", "s1"),
        ev(6, EventType.FINISHED, "r2", "s1"),
    )
    result = compute_queue_depth(events)
    assert result.points == (QueueDepthPoint(tick=0, depth=0),)
    assert result.peak_depth == 0


def test_finish_only_tick_does_not_change_depth_and_is_not_a_spurious_point():
    # Tick 3 has only a FINISHED (r4) with no arrived/started/dropped delta;
    # it must not appear as an extra point, but the surrounding interval must
    # still correctly span through it (exercised via the canonical sample's
    # avg_depth already matching 0.25 above). Here we assert points directly.
    result = compute_queue_depth(SAMPLE_EVENTS)
    ticks_with_points = [p.tick for p in result.points]
    assert 3 not in ticks_with_points


def test_negative_depth_raises_corrupt_trace_error():
    events = (
        ev(0, EventType.STARTED, "r1", "s1"),
        ev(1, EventType.FINISHED, "r1", "s1"),
    )
    with pytest.raises(CorruptTraceError):
        compute_queue_depth(events)


def test_sparse_huge_gap_produces_point_count_independent_of_tick_range():
    events = (
        ev(0, EventType.ARRIVED, "r1"),
        ev(1, EventType.STARTED, "r1", "s1"),
        ev(2, EventType.FINISHED, "r1", "s1"),
        ev(1_000_000, EventType.ARRIVED, "r2"),
        ev(1_000_000, EventType.STARTED, "r2", "s1"),
        ev(1_000_001, EventType.FINISHED, "r2", "s1"),
    )
    result = compute_queue_depth(events)
    assert result.duration_ticks == 1_000_001
    # A handful of points, not one per integer tick in a million-tick range.
    assert len(result.points) <= 6
    assert result.peak_depth == 1


# ---- dense reference cross-check -----------------------------------------
#
# Reproduces the exact pre-extraction dense per-integer-tick loop that used
# to live inline in compute_metrics(), as an independent reference
# implementation the sparse anchor-based compute_queue_depth() is checked
# against. This is deliberately a second, differently-shaped algorithm (O(range)
# instead of O(anchors)) — not a copy of compute_queue_depth() itself.


def _dense_reference(events):
    arrived_per_tick: dict[int, int] = {}
    started_per_tick: dict[int, int] = {}
    dropped_per_tick: dict[int, int] = {}

    for e in events:
        if e.event == EventType.ARRIVED:
            arrived_per_tick[e.t] = arrived_per_tick.get(e.t, 0) + 1
        elif e.event == EventType.STARTED:
            started_per_tick[e.t] = started_per_tick.get(e.t, 0) + 1
        elif e.event == EventType.DROPPED:
            dropped_per_tick[e.t] = dropped_per_tick.get(e.t, 0) + 1

    start_tick = min(e.t for e in events)
    end_tick = max(e.t for e in events)
    duration_ticks = end_tick - start_tick

    depth = 0
    depth_sum = 0
    peak_depth = 0
    for t in range(start_tick, end_tick + 1):
        depth = depth + arrived_per_tick.get(t, 0) - started_per_tick.get(t, 0) - dropped_per_tick.get(t, 0)
        depth_sum += depth
        if depth > peak_depth:
            peak_depth = depth
    avg_depth = (depth_sum / duration_ticks) if duration_ticks > 0 else None

    return duration_ticks, peak_depth, avg_depth


# A non-trivial queued trace: one server, r1 occupies it [0,2), r2 arrives at
# 0 but must wait for r1 to free the server, starting at 2 and finishing at 4.
QUEUED_TRACE = (
    ev(0, EventType.ARRIVED, "r1"),
    ev(0, EventType.ARRIVED, "r2"),
    ev(0, EventType.STARTED, "r1", "s1"),
    ev(2, EventType.FINISHED, "r1", "s1"),
    ev(2, EventType.STARTED, "r2", "s1"),
    ev(4, EventType.FINISHED, "r2", "s1"),
)

ALL_ZERO_TRACE = (
    ev(0, EventType.ARRIVED, "r1"),
    ev(0, EventType.STARTED, "r1", "s1"),
    ev(1, EventType.FINISHED, "r1", "s1"),
    ev(5, EventType.ARRIVED, "r2"),
    ev(5, EventType.STARTED, "r2", "s1"),
    ev(6, EventType.FINISHED, "r2", "s1"),
)


@pytest.mark.parametrize(
    "events",
    [
        pytest.param(SAMPLE_EVENTS, id="canonical-sample"),
        pytest.param(QUEUED_TRACE, id="non-trivial-queued"),
        pytest.param(ALL_ZERO_TRACE, id="all-zero-queue"),
    ],
)
def test_sparse_helper_matches_dense_reference_exactly(events):
    result = compute_queue_depth(events)
    dense_duration, dense_peak, dense_avg = _dense_reference(events)

    assert result.duration_ticks == dense_duration
    assert result.peak_depth == dense_peak
    assert result.avg_depth == dense_avg
