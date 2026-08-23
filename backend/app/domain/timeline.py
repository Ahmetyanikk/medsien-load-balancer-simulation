from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Sequence

from .models import EventType, ServerSpec, SimulationEvent
from .queue_depth import QueueDepthPoint, compute_queue_depth


@dataclass(frozen=True)
class TimelineInterval:
    request_id: str
    start_tick: int
    finish_tick: int


@dataclass(frozen=True)
class TimelineServerLane:
    server_id: str
    cpu_units_per_tick: Optional[int]
    intervals: tuple[TimelineInterval, ...]


@dataclass(frozen=True)
class TimelineRequest:
    request_id: str
    arrival_tick: int
    server_id: Optional[str]
    start_tick: Optional[int]
    finish_tick: Optional[int]
    dropped_tick: Optional[int]
    status: Literal["finished", "dropped"]
    wait_ticks: Optional[int]


@dataclass(frozen=True)
class TimelineEvent:
    sequence: int
    tick: int
    event_type: str
    request_id: str
    server_id: Optional[str]


@dataclass(frozen=True)
class TimelineResult:
    context_available: bool
    total_requests: int
    start_tick: int
    end_tick: int
    duration_ticks: int
    requests: tuple[TimelineRequest, ...]
    servers: tuple[TimelineServerLane, ...]
    events: tuple[TimelineEvent, ...]
    queue_depth: tuple[QueueDepthPoint, ...]


def compute_timeline(
    events: Sequence[SimulationEvent],
    verified_servers: Optional[Sequence[ServerSpec]] = None,
) -> TimelineResult:
    """Pure trace -> post-run timeline. No filesystem or HTTP access, same
    purity boundary as compute_metrics() (domain/metrics.py).

    Two independent design choices distinguish this from compute_metrics():

    - The raw `events` output preserves the exact input order (with a
      `sequence` index marking that literal position) rather than being
      re-sorted — a manually edited trace is shown in the order it's actually
      stored, not silently canonicalized. `requests`/`servers`/`intervals`
      ARE sorted, because their order is our own presentation decision, not a
      re-statement of the trace.
    - Queue-depth is delegated entirely to the shared compute_queue_depth()
      helper (domain/queue_depth.py), the same one compute_metrics() uses, so
      the two can never disagree on peak/average/duration.

    verified_servers has the same meaning as in compute_metrics(): the
    already-hash-and-schema-verified server snapshot from run_context.json,
    or None when no trustworthy context is available.
    """
    context_available = verified_servers is not None

    if not events:
        # Unreachable via the real API (an empty trace is rejected by
        # JsonlTraceWriter.deserialize() before this function is ever called),
        # kept only so direct callers get a well-defined result, mirroring
        # compute_metrics()'s own empty-events guard.
        idle_lanes = (
            tuple(
                TimelineServerLane(server_id=s.id, cpu_units_per_tick=s.cpu_units_per_tick, intervals=())
                for s in sorted(verified_servers, key=lambda s: s.id)
            )
            if context_available
            else ()
        )
        return TimelineResult(
            context_available=context_available,
            total_requests=0,
            start_tick=0,
            end_tick=0,
            duration_ticks=0,
            requests=(),
            servers=idle_lanes,
            events=(),
            queue_depth=(),
        )

    queue_result = compute_queue_depth(events)

    arrived: dict[str, int] = {}
    started: dict[str, tuple[int, str]] = {}
    finished: dict[str, int] = {}
    dropped: dict[str, int] = {}

    for ev in events:
        if ev.event == EventType.ARRIVED:
            arrived[ev.request_id] = ev.t
        elif ev.event == EventType.STARTED:
            started[ev.request_id] = (ev.t, ev.server_id)  # type: ignore[assignment]
        elif ev.event == EventType.FINISHED:
            finished[ev.request_id] = ev.t
        elif ev.event == EventType.DROPPED:
            dropped[ev.request_id] = ev.t

    requests: list[TimelineRequest] = []
    for rid, arrival_tick in arrived.items():
        if rid in dropped:
            requests.append(
                TimelineRequest(
                    request_id=rid,
                    arrival_tick=arrival_tick,
                    server_id=None,
                    start_tick=None,
                    finish_tick=None,
                    dropped_tick=dropped[rid],
                    status="dropped",
                    wait_ticks=None,
                )
            )
        else:
            start_tick, server_id = started[rid]
            requests.append(
                TimelineRequest(
                    request_id=rid,
                    arrival_tick=arrival_tick,
                    server_id=server_id,
                    start_tick=start_tick,
                    finish_tick=finished[rid],
                    dropped_tick=None,
                    status="finished",
                    wait_ticks=start_tick - arrival_tick,
                )
            )
    requests.sort(key=lambda r: (r.arrival_tick, r.request_id))

    intervals_by_server: dict[str, list[TimelineInterval]] = {}
    for r in requests:
        if r.status == "finished":
            intervals_by_server.setdefault(r.server_id, []).append(  # type: ignore[arg-type]
                TimelineInterval(request_id=r.request_id, start_tick=r.start_tick, finish_tick=r.finish_tick)  # type: ignore[arg-type]
            )

    if context_available:
        lane_ids = sorted(s.id for s in verified_servers)  # type: ignore[union-attr]
        cpu_by_id = {s.id: s.cpu_units_per_tick for s in verified_servers}  # type: ignore[union-attr]
    else:
        lane_ids = sorted(intervals_by_server.keys())
        cpu_by_id = {}

    servers = tuple(
        TimelineServerLane(
            server_id=sid,
            cpu_units_per_tick=cpu_by_id.get(sid) if context_available else None,
            intervals=tuple(
                sorted(intervals_by_server.get(sid, ()), key=lambda iv: (iv.start_tick, iv.request_id))
            ),
        )
        for sid in lane_ids
    )

    timeline_events = tuple(
        TimelineEvent(sequence=i, tick=ev.t, event_type=ev.event.value, request_id=ev.request_id, server_id=ev.server_id)
        for i, ev in enumerate(events)
    )

    return TimelineResult(
        context_available=context_available,
        total_requests=len(arrived),
        start_tick=queue_result.start_tick,
        end_tick=queue_result.end_tick,
        duration_ticks=queue_result.duration_ticks,
        requests=tuple(requests),
        servers=servers,
        events=timeline_events,
        queue_depth=queue_result.points,
    )
