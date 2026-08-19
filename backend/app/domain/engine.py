from __future__ import annotations

from typing import Optional, Sequence

from .errors import EmptyServerConfigurationError, SimulationDeadlockError
from .models import (
    EventType,
    RequestSpec,
    RunningRequest,
    ServerRuntimeState,
    ServerSpec,
    SimulationEvent,
    SimulationResult,
)
from .strategies import FastestFitStrategy, SchedulingStrategy, ceil_div


def _can_ever_run(request: RequestSpec, servers: Sequence[ServerSpec]) -> bool:
    """A request is permanently impossible if no server could ever host it,
    independent of current busy/idle state (D-004)."""
    return any(s.mem_mb >= request.mem_mb and s.start_capable for s in servers)


def _eligible_servers(
    request: RequestSpec,
    servers: Sequence[ServerSpec],
    state: dict[str, ServerRuntimeState],
) -> list[ServerSpec]:
    return [
        s
        for s in servers
        if state[s.id].is_idle and s.mem_mb >= request.mem_mb and s.start_capable
    ]


def _next_tick(
    state: dict[str, ServerRuntimeState],
    arrivals: Sequence[RequestSpec],
    arrival_ptr: int,
    waiting: Sequence[RequestSpec],
) -> int:
    """Jump to the next tick where state can change: a server freeing up or a new arrival.

    A static per-server rejection (mem/rate) never resolves itself by waiting a tick, so
    those two events are the only things that can ever change eligibility.
    """
    candidates = [st.current.finish_tick for st in state.values() if st.current]
    if arrival_ptr < len(arrivals):
        candidates.append(arrivals[arrival_ptr].arrival_t)
    if not candidates:
        raise SimulationDeadlockError(
            f"waiting requests {[r.id for r in waiting]} remain but no server is busy "
            "and no future arrival exists"
        )
    return min(candidates)


_EMPTY_RESULT = SimulationResult(events=(), total_requests=0, started=0, finished=0, dropped=0)


class SimulationEngine:
    """Pure simulation domain. No filesystem, HTTP, or persistence dependency (D-002)."""

    def simulate(
        self,
        servers: Sequence[ServerSpec],
        requests: Sequence[RequestSpec],
        strategy: Optional[SchedulingStrategy] = None,
    ) -> SimulationResult:
        if not servers:
            raise EmptyServerConfigurationError("no servers configured")
        if not requests:
            return _EMPTY_RESULT

        strategy = strategy or FastestFitStrategy()
        state: dict[str, ServerRuntimeState] = {s.id: ServerRuntimeState(server_id=s.id) for s in servers}

        # Explicit deterministic sort — never rely on input file/append order.
        arrivals = sorted(requests, key=lambda r: (r.arrival_t, r.id))
        arrival_ptr = 0
        waiting: list[RequestSpec] = []
        events: list[SimulationEvent] = []
        started = finished = dropped = 0

        t = arrivals[0].arrival_t

        while True:
            # 1. Completions — release capacity, deterministic order (server_id, request_id)
            done = sorted(
                (sid, st.current) for sid, st in state.items() if st.current and st.current.finish_tick == t
            )
            for sid, running in done:
                events.append(SimulationEvent(t, EventType.FINISHED, running.request_id, sid))
                state[sid].current = None
                finished += 1

            # 2. Arrivals at t, ordered by request_id
            arriving: list[RequestSpec] = []
            while arrival_ptr < len(arrivals) and arrivals[arrival_ptr].arrival_t == t:
                arriving.append(arrivals[arrival_ptr])
                arrival_ptr += 1
            arriving.sort(key=lambda r: r.id)
            for req in arriving:
                events.append(SimulationEvent(t, EventType.ARRIVED, req.id))

            # 3. Drop permanently-impossible arrivals, else enqueue (append preserves
            #    (arrival_tick, request_id) order without a resort — new arrivals always
            #    have the largest arrival_tick seen so far).
            for req in arriving:
                if not _can_ever_run(req, servers):
                    events.append(SimulationEvent(t, EventType.DROPPED, req.id))
                    dropped += 1
                else:
                    waiting.append(req)

            # 4. Schedule — single pass over waiting, in order; bypass (don't remove) on failure
            still_waiting: list[RequestSpec] = []
            for req in waiting:
                eligible = _eligible_servers(req, servers, state)
                if not eligible:
                    still_waiting.append(req)
                    continue
                chosen = strategy.select_server(req, eligible)
                finish_t = t + ceil_div(req.work_units, chosen.cpu_units_per_tick)
                state[chosen.id].current = RunningRequest(req.id, chosen.id, t, finish_t)
                events.append(SimulationEvent(t, EventType.STARTED, req.id, chosen.id))
                started += 1
            waiting = still_waiting

            # 5. Termination
            if arrival_ptr >= len(arrivals) and not waiting and all(st.is_idle for st in state.values()):
                break

            # 6. Advance to next relevant tick
            t = _next_tick(state, arrivals, arrival_ptr, waiting)

        return SimulationResult(
            events=tuple(events),
            total_requests=len(requests),
            started=started,
            finished=finished,
            dropped=dropped,
        )
