from __future__ import annotations

from app.adapters.jsonl_trace import JsonlTraceWriter
from app.domain.models import EventType, SimulationEvent


def test_serialize_empty_events_returns_empty_string():
    assert JsonlTraceWriter().serialize(()) == ""


def test_serialize_field_order_and_server_id_omission():
    events = (
        SimulationEvent(0, EventType.ARRIVED, "r1"),
        SimulationEvent(0, EventType.STARTED, "r1", "s1"),
    )
    text = JsonlTraceWriter().serialize(events)
    lines = text.split("\n")
    assert lines[0] == '{"t":0,"event":"REQUEST_ARRIVED","request_id":"r1"}'
    assert lines[1] == '{"t":0,"event":"REQUEST_STARTED","request_id":"r1","server_id":"s1"}'


def test_serialize_ends_with_exactly_one_trailing_newline():
    events = (SimulationEvent(0, EventType.ARRIVED, "r1"),)
    text = JsonlTraceWriter().serialize(events)
    assert text.endswith("\n")
    assert not text.endswith("\n\n")


def test_serialize_never_emits_blank_lines():
    events = (
        SimulationEvent(0, EventType.ARRIVED, "r1"),
        SimulationEvent(0, EventType.ARRIVED, "r2"),
        SimulationEvent(1, EventType.STARTED, "r1", "s1"),
    )
    text = JsonlTraceWriter().serialize(events)
    body_lines = text.split("\n")[:-1]  # drop the trailing empty string after final \n
    assert all(line for line in body_lines)
    assert len(body_lines) == 3
