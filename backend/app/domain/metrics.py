from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from .errors import CorruptTraceError
from .models import EventType, ServerSpec, SimulationEvent


@dataclass(frozen=True)
class ServerMetrics:
    server_id: str
    requests_handled: int
    work_units_total: Optional[int]
    busy_ticks: int
    busy_time_ratio: Optional[float]
    cpu_units_per_tick: Optional[int]


@dataclass(frozen=True)
class ClusterMetrics:
    total_requests: int
    started: int
    finished: int
    dropped: int
    dropped_rate: Optional[float]
    duration_ticks: int
    throughput_requests_per_tick: Optional[float]
    peak_queue_depth: int
    avg_queue_depth: Optional[float]
    configured_server_count: Optional[int]
    idle_configured_server_ids: Optional[tuple[str, ...]]
    avg_cluster_busy_ratio: Optional[float]


def compute_metrics(
    events: Sequence[SimulationEvent],
    verified_servers: Optional[Sequence[ServerSpec]] = None,
) -> tuple[ClusterMetrics, tuple[ServerMetrics, ...]]:
    """Pure trace -> metrics. No filesystem or HTTP access.

    `verified_servers` is the already-hash-and-schema-verified server
    snapshot from run_context.json (see services/run_context.py), or None
    when no trustworthy context is available. Every context-enriched field
    is null/empty exactly when verified_servers is None — this function
    never distinguishes "missing" from "malformed" context; that
    degrade-to-None decision is made entirely by the caller before this is
    invoked.

    work_units_total is always None: the context snapshot stores only
    servers, not the original per-request work_units, and the value is not
    recoverable from (busy_ticks, cpu_units_per_tick) alone since
    ceil_div(work_units, cpu) is lossy for any request whose runtime wasn't
    an exact multiple of its server's cpu_units_per_tick. Populating this
    field for real would require snapshotting requests too, which Day 3A
    deliberately does not do.
    """
    context_available = verified_servers is not None

    if not events:
        return (
            ClusterMetrics(
                total_requests=0,
                started=0,
                finished=0,
                dropped=0,
                dropped_rate=None,
                duration_ticks=0,
                throughput_requests_per_tick=None,
                peak_queue_depth=0,
                avg_queue_depth=None,
                configured_server_count=len(verified_servers) if context_available else None,
                idle_configured_server_ids=tuple(s.id for s in verified_servers) if context_available else None,
                avg_cluster_busy_ratio=None,
            ),
            (),
        )

    arrived_ticks: dict[str, int] = {}
    started_at: dict[str, tuple[int, str]] = {}
    finished_count = 0
    dropped_count = 0

    per_server_busy: dict[str, int] = {}
    per_server_requests: dict[str, int] = {}

    arrived_per_tick: dict[int, int] = {}
    started_per_tick: dict[int, int] = {}
    dropped_per_tick: dict[int, int] = {}

    for ev in events:
        if ev.event == EventType.ARRIVED:
            arrived_ticks[ev.request_id] = ev.t
            arrived_per_tick[ev.t] = arrived_per_tick.get(ev.t, 0) + 1
        elif ev.event == EventType.STARTED:
            started_at[ev.request_id] = (ev.t, ev.server_id)  # type: ignore[assignment]
            started_per_tick[ev.t] = started_per_tick.get(ev.t, 0) + 1
            per_server_requests[ev.server_id] = per_server_requests.get(ev.server_id, 0) + 1  # type: ignore[index]
        elif ev.event == EventType.FINISHED:
            finished_count += 1
            start_t, sid = started_at[ev.request_id]
            per_server_busy[sid] = per_server_busy.get(sid, 0) + (ev.t - start_t)
        elif ev.event == EventType.DROPPED:
            dropped_count += 1
            dropped_per_tick[ev.t] = dropped_per_tick.get(ev.t, 0) + 1

    total_requests = len(arrived_ticks)
    dropped_rate = (dropped_count / total_requests) if total_requests else None

    start_tick = min(ev.t for ev in events)
    end_tick = max(ev.t for ev in events)
    duration_ticks = end_tick - start_tick

    throughput_requests_per_tick = (finished_count / duration_ticks) if duration_ticks > 0 else None

    # Queue-depth sweep: depth = previous_depth + ARRIVED - STARTED - DROPPED at
    # each integer tick in the inclusive [start_tick, end_tick] range; missing
    # ticks carry the previous depth forward automatically since every counter
    # defaults to 0. avg_queue_depth divides the summed depths by elapsed
    # duration_ticks (not by the number of samples) since the final sample is
    # an instant, not an additional tick of elapsed time.
    #
    # A negative running depth is never clamped to zero — it means the event
    # stream itself is inconsistent (e.g. a STARTED with no matching ARRIVED
    # ever counted), which is an invariant failure in the supplied trace, not
    # a normal condition to paper over silently.
    depth = 0
    depth_sum = 0
    peak_depth = 0
    for t in range(start_tick, end_tick + 1):
        depth = depth + arrived_per_tick.get(t, 0) - started_per_tick.get(t, 0) - dropped_per_tick.get(t, 0)
        if depth < 0:
            raise CorruptTraceError(f"tick {t}: queue depth went negative ({depth}) — inconsistent event stream")
        depth_sum += depth
        if depth > peak_depth:
            peak_depth = depth
    avg_queue_depth = (depth_sum / duration_ticks) if duration_ticks > 0 else None

    if context_available:
        server_ids = [s.id for s in verified_servers]  # type: ignore[union-attr]
        cpu_by_id = {s.id: s.cpu_units_per_tick for s in verified_servers}  # type: ignore[union-attr]
    else:
        server_ids = sorted(set(per_server_requests) | set(per_server_busy))
        cpu_by_id = {}

    server_metrics = tuple(
        ServerMetrics(
            server_id=sid,
            requests_handled=per_server_requests.get(sid, 0),
            work_units_total=None,
            busy_ticks=per_server_busy.get(sid, 0),
            busy_time_ratio=(per_server_busy.get(sid, 0) / duration_ticks) if duration_ticks > 0 else None,
            cpu_units_per_tick=cpu_by_id.get(sid) if context_available else None,
        )
        for sid in server_ids
    )

    if context_available and duration_ticks > 0 and server_metrics:
        avg_cluster_busy_ratio = sum(m.busy_ticks for m in server_metrics) / (len(server_metrics) * duration_ticks)
    else:
        avg_cluster_busy_ratio = None

    idle_ids = (
        tuple(m.server_id for m in server_metrics if m.requests_handled == 0) if context_available else None
    )

    cluster = ClusterMetrics(
        total_requests=total_requests,
        started=len(started_at),
        finished=finished_count,
        dropped=dropped_count,
        dropped_rate=dropped_rate,
        duration_ticks=duration_ticks,
        throughput_requests_per_tick=throughput_requests_per_tick,
        peak_queue_depth=peak_depth,
        avg_queue_depth=avg_queue_depth,
        configured_server_count=len(verified_servers) if context_available else None,  # type: ignore[arg-type]
        idle_configured_server_ids=idle_ids,
        avg_cluster_busy_ratio=avg_cluster_busy_ratio,
    )
    return cluster, server_metrics
