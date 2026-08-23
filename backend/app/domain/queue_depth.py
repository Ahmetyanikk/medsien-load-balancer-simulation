from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from .errors import CorruptTraceError
from .models import EventType, SimulationEvent


@dataclass(frozen=True)
class QueueDepthPoint:
    tick: int
    depth: int


@dataclass(frozen=True)
class QueueDepthResult:
    start_tick: int
    end_tick: int
    duration_ticks: int
    points: tuple[QueueDepthPoint, ...]
    peak_depth: int
    avg_depth: Optional[float]


def compute_queue_depth(events: Sequence[SimulationEvent]) -> QueueDepthResult:
    """Shared queue-depth engine for compute_metrics() and compute_timeline() —
    the single source of truth for this calculation so the two can never drift.

    Precondition: events is non-empty. Callers (compute_metrics, compute_timeline)
    each keep their own pre-existing empty-events guard before ever calling this.

    depth(t) = previous_depth + ARRIVED(t) - STARTED(t) - DROPPED(t), evaluated
    once per tick after all of that tick's events are applied (FINISHED never
    changes depth — a request already left "waiting" the moment it STARTED).
    Same-tick internal ordering among ARRIVED/STARTED/DROPPED doesn't affect
    this value: it's a per-tick net sum, not a sequential depletion.

    Instead of a dense per-integer-tick loop (unbounded cost on a huge/sparse
    max tick), this walks only the "anchor" ticks where depth can possibly
    change — any tick with a nonzero arrived/started/dropped count, plus the
    two boundary ticks (start_tick, end_tick) forced in even when they carry
    no such delta (e.g. a tick with only a FINISHED). Depth is constant between
    consecutive anchors, so avg_depth is an exact interval-weighted sum rather
    than a per-tick accumulation — equivalent to summing depth at every
    integer tick in [start_tick, end_tick] and dividing by duration_ticks (the
    old dense formula), since there is nothing between two anchors to differ.

    This equivalence holds for non-empty, lifecycle-complete input — every
    arrival resolved to exactly one terminal event (FINISHED or DROPPED), as
    JsonlTraceWriter.deserialize() already guarantees before either caller
    (compute_metrics, compute_timeline) is ever reached via the API. Under
    that guarantee, queue depth is always back to zero by end_tick, so the
    dense loop's final inclusive sample and this function's "hold until the
    next point" semantics agree everywhere. An arbitrary sequence with an
    unresolved arrival is outside this supported input contract (deserialize()
    itself would already reject it) and isn't a case either implementation
    needs to agree on.
    """
    arrived_per_tick: dict[int, int] = {}
    started_per_tick: dict[int, int] = {}
    dropped_per_tick: dict[int, int] = {}

    for ev in events:
        if ev.event == EventType.ARRIVED:
            arrived_per_tick[ev.t] = arrived_per_tick.get(ev.t, 0) + 1
        elif ev.event == EventType.STARTED:
            started_per_tick[ev.t] = started_per_tick.get(ev.t, 0) + 1
        elif ev.event == EventType.DROPPED:
            dropped_per_tick[ev.t] = dropped_per_tick.get(ev.t, 0) + 1

    start_tick = min(ev.t for ev in events)
    end_tick = max(ev.t for ev in events)

    delta_ticks = set(arrived_per_tick) | set(started_per_tick) | set(dropped_per_tick)
    anchor_ticks = sorted(delta_ticks | {start_tick, end_tick})

    depth = 0
    peak_depth = 0
    integral = 0
    anchor_depths: list[int] = []
    for i, t in enumerate(anchor_ticks):
        depth = depth + arrived_per_tick.get(t, 0) - started_per_tick.get(t, 0) - dropped_per_tick.get(t, 0)
        if depth < 0:
            raise CorruptTraceError(f"tick {t}: queue depth went negative ({depth}) — inconsistent event stream")
        anchor_depths.append(depth)
        if depth > peak_depth:
            peak_depth = depth
        if i > 0:
            interval_length = t - anchor_ticks[i - 1]
            integral += anchor_depths[i - 1] * interval_length

    duration_ticks = end_tick - start_tick
    avg_depth = (integral / duration_ticks) if duration_ticks > 0 else None

    points: list[QueueDepthPoint] = [QueueDepthPoint(tick=anchor_ticks[0], depth=anchor_depths[0])]
    for t, d in zip(anchor_ticks[1:], anchor_depths[1:]):
        if d != points[-1].depth:
            points.append(QueueDepthPoint(tick=t, depth=d))

    return QueueDepthResult(
        start_tick=start_tick,
        end_tick=end_tick,
        duration_ticks=duration_ticks,
        points=tuple(points),
        peak_depth=peak_depth,
        avg_depth=avg_depth,
    )
