from __future__ import annotations

from app.domain.models import EventType, SimulationEvent
from app.domain.summary import summarize


def ev(t, event, rid, sid=None):
    return SimulationEvent(t=t, event=event, request_id=rid, server_id=sid)


def test_summarize_matches_day1_sample_walkthrough():
    events = (
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
    summary = summarize(events)
    assert (summary.total_requests, summary.started, summary.finished, summary.dropped) == (4, 4, 4, 0)
    # matches the real validate_run.py's own SUMMARY output for this exact trace
    assert summary.avg_wait_ticks == 0.25
    assert summary.p50_wait_ticks == 0
    assert summary.p95_wait_ticks == 1
    assert summary.max_wait_ticks == 1


def test_summarize_all_dropped_returns_none_stats():
    events = (
        ev(0, EventType.ARRIVED, "r1"),
        ev(0, EventType.DROPPED, "r1"),
    )
    summary = summarize(events)
    assert (summary.total_requests, summary.started, summary.finished, summary.dropped) == (1, 0, 0, 1)
    assert summary.avg_wait_ticks is None
    assert summary.p50_wait_ticks is None
    assert summary.p95_wait_ticks is None
    assert summary.max_wait_ticks is None


def test_summarize_empty_events():
    summary = summarize(())
    assert (summary.total_requests, summary.started, summary.finished, summary.dropped) == (0, 0, 0, 0)
    assert summary.avg_wait_ticks is None
