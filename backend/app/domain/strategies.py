from __future__ import annotations

from typing import Protocol, Sequence

from .errors import UnknownStrategyError
from .models import RequestSpec, ServerSpec


def ceil_div(a: int, b: int) -> int:
    return (a + b - 1) // b


class SchedulingStrategy(Protocol):
    name: str
    label: str

    def select_server(self, request: RequestSpec, eligible: Sequence[ServerSpec]) -> ServerSpec: ...


class FastestFitStrategy:
    """Default validator-compatible strategy (D-006).

    Among currently eligible servers, picks the one that finishes the request
    soonest; ties are broken by server id (lexicographically smallest wins).
    """

    name = "fastest_finish"
    label = "Fastest finish"

    def select_server(self, request: RequestSpec, eligible: Sequence[ServerSpec]) -> ServerSpec:
        return min(
            eligible,
            key=lambda s: (ceil_div(request.work_units, s.cpu_units_per_tick), s.id),
        )


class LowestIdStrategy:
    """Bonus strategy (Day 3A).

    Ignores predicted runtime entirely and picks the eligible server with the
    lexicographically smallest id. Eligibility itself (memory, CPU, rate
    limit, idle state) is entirely the engine's responsibility — the engine
    computes `eligible` and passes it in unchanged, so this strategy only
    decides which of those already-eligible servers wins. Server ids are
    already unique by construction (D-013/adapters), so there is no
    secondary tie-break to define.
    """

    name = "lowest_id"
    label = "Lowest server ID"

    def select_server(self, request: RequestSpec, eligible: Sequence[ServerSpec]) -> ServerSpec:
        return min(eligible, key=lambda s: s.id)


# Insertion order is deterministic (dict preserves it) and is what
# GET /api/simulations/strategies iterates in — fastest_finish first,
# lowest_id second, matching the documented response order.
STRATEGY_REGISTRY: dict[str, SchedulingStrategy] = {
    FastestFitStrategy.name: FastestFitStrategy(),
    LowestIdStrategy.name: LowestIdStrategy(),
}

DEFAULT_STRATEGY_NAME = FastestFitStrategy.name


def get_strategy(name: str) -> SchedulingStrategy:
    """Resolve a strategy id through the explicit registry.

    Unknown ids raise UnknownStrategyError rather than silently falling back
    to the default — the HTTP layer's Literal-typed query parameter is the
    primary defense against bad input (422 before this is ever reached), this
    is defense-in-depth for any direct caller.
    """
    try:
        return STRATEGY_REGISTRY[name]
    except KeyError:
        raise UnknownStrategyError(f"unknown strategy id: {name!r}") from None
