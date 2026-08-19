from __future__ import annotations

import json
from typing import Sequence

from ..domain.errors import CorruptTraceError
from ..domain.models import EventType, SimulationEvent

_VALID_EVENT_VALUES = {e.value for e in EventType}
_REQUIRES_SERVER_ID = {EventType.STARTED, EventType.FINISHED}


def _parse_line(line: str, lineno: int) -> SimulationEvent:
    try:
        obj = json.loads(line)
    except json.JSONDecodeError as exc:
        raise CorruptTraceError(f"line {lineno}: invalid JSON: {exc}") from exc

    if not isinstance(obj, dict):
        raise CorruptTraceError(f"line {lineno}: expected a JSON object, got {type(obj).__name__}")

    t = obj.get("t")
    if not isinstance(t, int) or isinstance(t, bool):
        raise CorruptTraceError(f"line {lineno}: 't' must be an integer")
    if t < 0:
        raise CorruptTraceError(f"line {lineno}: 't' must be non-negative")

    event_raw = obj.get("event")
    if not isinstance(event_raw, str) or event_raw not in _VALID_EVENT_VALUES:
        raise CorruptTraceError(f"line {lineno}: 'event' must be one of {sorted(_VALID_EVENT_VALUES)}")
    event = EventType(event_raw)

    # Whitespace-only is rejected but a valid id's original characters (including
    # any incidental surrounding whitespace) are never normalized/stripped.
    request_id = obj.get("request_id")
    if not isinstance(request_id, str) or not request_id.strip():
        raise CorruptTraceError(f"line {lineno}: 'request_id' must be a non-empty, non-whitespace string")

    server_id = obj.get("server_id")
    if server_id is not None and (not isinstance(server_id, str) or not server_id.strip()):
        raise CorruptTraceError(f"line {lineno}: 'server_id' must be a non-empty, non-whitespace string or absent")
    if event in _REQUIRES_SERVER_ID and not server_id:
        raise CorruptTraceError(f"line {lineno}: '{event.value}' requires a non-empty 'server_id'")

    return SimulationEvent(t=t, event=event, request_id=request_id, server_id=server_id)


def _validate_lifecycle(events: Sequence[SimulationEvent]) -> None:
    """Cross-event lifecycle validation for a *reconstructed* trace, applied before
    it is ever handed to summarize(). Stricter than the supplied validate_run.py in
    one respect (it also rejects a request that arrived but never resolved to
    FINISHED/DROPPED) because an authoritative RunSummary can't be computed from an
    unresolved trace; an application-generated trace can never violate any of these
    checks by construction (Day 1's engine guarantees exactly one ARRIVED followed
    by exactly one terminal event per request), so this only ever rejects a
    manually modified or otherwise corrupted file.
    """
    arrived: dict[str, SimulationEvent] = {}
    started: dict[str, SimulationEvent] = {}
    finished: dict[str, SimulationEvent] = {}
    dropped: dict[str, SimulationEvent] = {}

    for ev in events:
        rid = ev.request_id
        if ev.event == EventType.ARRIVED:
            if rid in arrived:
                raise CorruptTraceError(f"duplicate REQUEST_ARRIVED for '{rid}'")
            arrived[rid] = ev

        elif ev.event == EventType.STARTED:
            if rid in started:
                raise CorruptTraceError(f"duplicate REQUEST_STARTED for '{rid}'")
            if rid in dropped:
                raise CorruptTraceError(f"REQUEST_STARTED after REQUEST_DROPPED for '{rid}'")
            if rid not in arrived:
                raise CorruptTraceError(f"REQUEST_STARTED without REQUEST_ARRIVED for '{rid}'")
            if ev.t < arrived[rid].t:
                raise CorruptTraceError(f"negative wait for '{rid}': started before it arrived")
            started[rid] = ev

        elif ev.event == EventType.FINISHED:
            if rid in finished:
                raise CorruptTraceError(f"duplicate REQUEST_FINISHED for '{rid}'")
            if rid in dropped:
                raise CorruptTraceError(f"both REQUEST_FINISHED and REQUEST_DROPPED for '{rid}'")
            if rid not in started:
                raise CorruptTraceError(f"REQUEST_FINISHED without REQUEST_STARTED for '{rid}'")
            start_ev = started[rid]
            if ev.server_id != start_ev.server_id:
                raise CorruptTraceError(
                    f"server mismatch for '{rid}': started on '{start_ev.server_id}', "
                    f"finished on '{ev.server_id}'"
                )
            if ev.t <= start_ev.t:
                raise CorruptTraceError(f"finish tick not after start tick for '{rid}'")
            finished[rid] = ev

        elif ev.event == EventType.DROPPED:
            if rid in dropped:
                raise CorruptTraceError(f"duplicate REQUEST_DROPPED for '{rid}'")
            if rid in finished:
                raise CorruptTraceError(f"both REQUEST_FINISHED and REQUEST_DROPPED for '{rid}'")
            if rid in started:
                raise CorruptTraceError(f"REQUEST_DROPPED after REQUEST_STARTED for '{rid}'")
            if rid not in arrived:
                raise CorruptTraceError(f"REQUEST_DROPPED without REQUEST_ARRIVED for '{rid}'")
            if ev.t < arrived[rid].t:
                raise CorruptTraceError(f"REQUEST_DROPPED tick before REQUEST_ARRIVED tick for '{rid}'")
            dropped[rid] = ev

    for rid in arrived:
        if rid not in finished and rid not in dropped:
            raise CorruptTraceError(f"unresolved REQUEST_ARRIVED for '{rid}' (no FINISHED or DROPPED)")


class JsonlTraceWriter:
    """Pure serialize/deserialize for SimulationEvent <-> JSONL text.

    No filesystem I/O — SimulationService owns writing and atomic publication
    (D-002/§17). deserialize() performs explicit schema and lifecycle validation
    itself and only ever raises CorruptTraceError — callers (the API route) must
    not need to catch arbitrary exceptions.
    """

    def serialize(self, events: tuple[SimulationEvent, ...]) -> str:
        if not events:
            return ""
        lines = []
        for ev in events:
            obj = {"t": ev.t, "event": ev.event.value, "request_id": ev.request_id}
            if ev.server_id is not None:
                obj["server_id"] = ev.server_id
            lines.append(json.dumps(obj, separators=(",", ":")))
        return "\n".join(lines) + "\n"

    def deserialize(self, text: str) -> tuple[SimulationEvent, ...]:
        events: list[SimulationEvent] = []
        for lineno, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            events.append(_parse_line(line, lineno))

        if not events:
            raise CorruptTraceError("trace contains no events")

        _validate_lifecycle(events)
        return tuple(events)
