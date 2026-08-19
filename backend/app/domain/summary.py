from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

from .models import EventType, SimulationEvent


@dataclass(frozen=True)
class SimulationSummary:
    """Pure stdlib dataclass — no Pydantic, no API dependency (D-002 extended to
    this layer). The API maps this to the Pydantic RunSummary response model."""

    total_requests: int
    started: int
    finished: int
    dropped: int
    avg_wait_ticks: Optional[float]
    p50_wait_ticks: Optional[int]
    p95_wait_ticks: Optional[int]
    max_wait_ticks: Optional[int]


def _percentile(sorted_vals: list[int], p: float) -> Optional[int]:
    if not sorted_vals:
        return None
    idx = math.ceil(p * len(sorted_vals)) - 1
    idx = max(0, min(idx, len(sorted_vals) - 1))
    return sorted_vals[idx]


def summarize(events: tuple[SimulationEvent, ...]) -> SimulationSummary:
    """Reconstructs the mandatory RunSummary fields purely from a trace's own events —
    no original requests.csv needed. Mirrors validate_run.py's own wait/percentile
    definitions exactly (wait = STARTED.t - ARRIVED.t, dropped requests excluded from
    wait stats) so our numbers agree with what the evaluator's own tool reports.
    """
    arrived: dict[str, int] = {}
    started: dict[str, int] = {}
    finished_count = 0
    dropped_count = 0

    for ev in events:
        if ev.event == EventType.ARRIVED:
            arrived[ev.request_id] = ev.t
        elif ev.event == EventType.STARTED:
            started[ev.request_id] = ev.t
        elif ev.event == EventType.FINISHED:
            finished_count += 1
        elif ev.event == EventType.DROPPED:
            dropped_count += 1

    waits = sorted(started[rid] - arrived[rid] for rid in started if rid in arrived)

    return SimulationSummary(
        total_requests=len(arrived),
        started=len(started),
        finished=finished_count,
        dropped=dropped_count,
        avg_wait_ticks=(sum(waits) / len(waits)) if waits else None,
        p50_wait_ticks=_percentile(waits, 0.50),
        p95_wait_ticks=_percentile(waits, 0.95),
        max_wait_ticks=max(waits) if waits else None,
    )
