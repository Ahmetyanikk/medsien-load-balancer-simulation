from __future__ import annotations

from typing import Protocol, Sequence

from .models import RequestSpec, ServerSpec


def ceil_div(a: int, b: int) -> int:
    return (a + b - 1) // b


class SchedulingStrategy(Protocol):
    def select_server(self, request: RequestSpec, eligible: Sequence[ServerSpec]) -> ServerSpec: ...


class FastestFitStrategy:
    """Default validator-compatible strategy (D-006).

    Among currently eligible servers, picks the one that finishes the request
    soonest; ties are broken by server id (lexicographically smallest wins).
    """

    def select_server(self, request: RequestSpec, eligible: Sequence[ServerSpec]) -> ServerSpec:
        return min(
            eligible,
            key=lambda s: (ceil_div(request.work_units, s.cpu_units_per_tick), s.id),
        )
