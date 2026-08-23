from __future__ import annotations

from app.domain.models import EventType, ServerSpec, SimulationEvent
from app.domain.timeline import compute_timeline


def ev(t, event, rid, sid=None):
    return SimulationEvent(t=t, event=event, request_id=rid, server_id=sid)


def srv(id_, cpu=10, mem=1024, rate=1):
    return ServerSpec(id=id_, cpu_units_per_tick=cpu, mem_mb=mem, rate_limit_per_sec=rate)


# Identical to test_metrics.py's / test_queue_depth.py's SAMPLE_EVENTS fixture.
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


def test_canonical_sample_requests_lanes_intervals_and_queue_depth_match_hand_computation():
    result = compute_timeline(SAMPLE_EVENTS)

    assert result.total_requests == 4
    assert result.start_tick == 0
    assert result.end_tick == 4
    assert result.duration_ticks == 4

    by_id = {r.request_id: r for r in result.requests}
    assert [r.request_id for r in result.requests] == ["r1", "r2", "r3", "r4"]  # (arrival_tick, request_id) order
    assert by_id["r1"].status == "finished"
    assert (by_id["r1"].arrival_tick, by_id["r1"].start_tick, by_id["r1"].finish_tick, by_id["r1"].server_id) == (0, 0, 2, "s1")
    assert by_id["r1"].wait_ticks == 0
    assert (by_id["r3"].arrival_tick, by_id["r3"].start_tick, by_id["r3"].finish_tick) == (1, 2, 4)
    assert by_id["r3"].wait_ticks == 1

    assert [lane.server_id for lane in result.servers] == ["s1", "s2"]
    lanes = {lane.server_id: lane for lane in result.servers}
    assert [(iv.request_id, iv.start_tick, iv.finish_tick) for iv in lanes["s1"].intervals] == [
        ("r1", 0, 2),
        ("r3", 2, 4),
    ]
    assert [(iv.request_id, iv.start_tick, iv.finish_tick) for iv in lanes["s2"].intervals] == [
        ("r2", 0, 2),
        ("r4", 2, 3),
    ]

    assert [(p.tick, p.depth) for p in result.queue_depth] == [(0, 0), (1, 1), (2, 0)]


def test_dropped_request_appears_only_in_requests_and_events_no_lane_entry():
    events = (
        ev(0, EventType.ARRIVED, "r1"),
        ev(0, EventType.DROPPED, "r1"),
    )
    result = compute_timeline(events)

    assert len(result.requests) == 1
    dropped = result.requests[0]
    assert dropped.status == "dropped"
    assert (dropped.server_id, dropped.start_tick, dropped.finish_tick, dropped.wait_ticks) == (None, None, None, None)
    assert dropped.dropped_tick == 0
    assert result.servers == ()
    assert [e.event_type for e in result.events] == ["REQUEST_ARRIVED", "REQUEST_DROPPED"]


def test_exact_finish_tick_reuse_produces_adjacent_intervals_on_same_lane():
    # r1 occupies s1 [0,2); r2 queues, then starts at the exact tick r1 frees s1.
    events = (
        ev(0, EventType.ARRIVED, "r1"),
        ev(0, EventType.ARRIVED, "r2"),
        ev(0, EventType.STARTED, "r1", "s1"),
        ev(2, EventType.FINISHED, "r1", "s1"),
        ev(2, EventType.STARTED, "r2", "s1"),
        ev(4, EventType.FINISHED, "r2", "s1"),
    )
    result = compute_timeline(events)
    lane = result.servers[0]
    assert lane.server_id == "s1"
    assert [(iv.request_id, iv.start_tick, iv.finish_tick) for iv in lane.intervals] == [
        ("r1", 0, 2),
        ("r2", 2, 4),
    ]


def test_context_available_lists_idle_configured_server_with_empty_intervals():
    verified_servers = [srv("s1", cpu=10), srv("s2", cpu=5), srv("s3-idle")]
    result = compute_timeline(SAMPLE_EVENTS, verified_servers)

    assert result.context_available is True
    assert [lane.server_id for lane in result.servers] == ["s1", "s2", "s3-idle"]
    idle_lane = next(lane for lane in result.servers if lane.server_id == "s3-idle")
    assert idle_lane.intervals == ()
    assert idle_lane.cpu_units_per_tick == verified_servers[2].cpu_units_per_tick


def test_no_context_omits_cpu_units_and_lists_only_trace_seen_servers():
    result = compute_timeline(SAMPLE_EVENTS, None)
    assert result.context_available is False
    assert [lane.server_id for lane in result.servers] == ["s1", "s2"]
    assert all(lane.cpu_units_per_tick is None for lane in result.servers)


# A hand-constructed permutation of the exact same 12 SAMPLE_EVENTS, grouped
# by request rather than by tick-phase. This deliberately differs from the
# canonical persisted order (SAMPLE_EVENTS above) at the very first position
# where they diverge (index 1: ARRIVED r2 in canonical vs. STARTED r1 here),
# while still preserving ARRIVED -> STARTED -> FINISHED for every individual
# request — an arbitrary random.shuffle cannot make that guarantee (it can
# just as easily emit STARTED before ARRIVED for the same request, which no
# real trace could ever contain). This is what "non-canonical but still
# lifecycle-valid" actually means.
NON_CANONICAL_ORDER = (
    ev(0, EventType.ARRIVED, "r1"),
    ev(0, EventType.STARTED, "r1", "s1"),
    ev(2, EventType.FINISHED, "r1", "s1"),
    ev(0, EventType.ARRIVED, "r2"),
    ev(0, EventType.STARTED, "r2", "s2"),
    ev(2, EventType.FINISHED, "r2", "s2"),
    ev(1, EventType.ARRIVED, "r3"),
    ev(2, EventType.STARTED, "r3", "s1"),
    ev(4, EventType.FINISHED, "r3", "s1"),
    ev(2, EventType.ARRIVED, "r4"),
    ev(2, EventType.STARTED, "r4", "s2"),
    ev(3, EventType.FINISHED, "r4", "s2"),
)

assert set(NON_CANONICAL_ORDER) == set(SAMPLE_EVENTS)  # same 12 events, just reordered
assert NON_CANONICAL_ORDER != SAMPLE_EVENTS  # genuinely non-canonical


def test_derived_collections_are_deterministic_regardless_of_lifecycle_valid_input_order():
    canonical_result = compute_timeline(SAMPLE_EVENTS)
    reordered_result = compute_timeline(NON_CANONICAL_ORDER)

    assert reordered_result.requests == canonical_result.requests
    assert reordered_result.servers == canonical_result.servers


def test_raw_events_list_preserves_non_canonical_input_order_and_contiguous_sequence():
    result = compute_timeline(NON_CANONICAL_ORDER)

    assert [(e.tick, e.event_type, e.request_id, e.server_id) for e in result.events] == [
        (ev.t, ev.event.value, ev.request_id, ev.server_id) for ev in NON_CANONICAL_ORDER
    ]
    assert [e.sequence for e in result.events] == list(range(len(NON_CANONICAL_ORDER)))


def test_no_unsupported_event_types_leak_through():
    result = compute_timeline(SAMPLE_EVENTS)
    allowed = {e.value for e in EventType}
    assert all(e.event_type in allowed for e in result.events)
