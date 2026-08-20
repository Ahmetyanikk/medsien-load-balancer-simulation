from __future__ import annotations

import pytest

from app.domain.engine import SimulationEngine, _next_tick
from app.domain.errors import EmptyServerConfigurationError, SimulationDeadlockError, UnknownStrategyError
from app.domain.models import EventType, RequestSpec, ServerRuntimeState, ServerSpec
from app.domain.strategies import FastestFitStrategy, LowestIdStrategy, get_strategy


def srv(id_, cpu, mem, rate):
    return ServerSpec(id=id_, cpu_units_per_tick=cpu, mem_mb=mem, rate_limit_per_sec=rate)


def req(id_, t, work, mem):
    return RequestSpec(id=id_, arrival_t=t, work_units=work, mem_mb=mem)


SAMPLE_SERVERS = [srv("s1", 10, 1024, 2), srv("s2", 5, 512, 1)]
SAMPLE_REQUESTS = [
    req("r1", 0, 20, 200),
    req("r2", 0, 10, 100),
    req("r3", 1, 15, 300),
    req("r4", 2, 5, 100),
]


def events_by(result, event_type):
    return [e for e in result.events if e.event == event_type]


def index(result):
    """request_id -> list of (t, event, server_id) in emitted order, for readable asserts."""
    out: dict[str, list] = {}
    for e in result.events:
        out.setdefault(e.request_id, []).append((e.t, e.event, e.server_id))
    return out


# ---- empty input -------------------------------------------------------------


def test_empty_servers_raises():
    with pytest.raises(EmptyServerConfigurationError):
        SimulationEngine().simulate([], SAMPLE_REQUESTS)


def test_empty_requests_returns_successful_empty_result():
    result = SimulationEngine().simulate(SAMPLE_SERVERS, [])
    assert result.events == ()
    assert (result.total_requests, result.started, result.finished, result.dropped) == (0, 0, 0, 0)


# ---- manual sample walkthrough (also the "trace by hand" completion gate) ---


def test_sample_walkthrough_matches_manual_trace():
    result = SimulationEngine().simulate(SAMPLE_SERVERS, SAMPLE_REQUESTS)
    idx = index(result)

    assert idx["r1"] == [(0, EventType.ARRIVED, None), (0, EventType.STARTED, "s1"), (2, EventType.FINISHED, "s1")]
    assert idx["r2"] == [(0, EventType.ARRIVED, None), (0, EventType.STARTED, "s2"), (2, EventType.FINISHED, "s2")]
    assert idx["r3"] == [(1, EventType.ARRIVED, None), (2, EventType.STARTED, "s1"), (4, EventType.FINISHED, "s1")]
    assert idx["r4"] == [(2, EventType.ARRIVED, None), (2, EventType.STARTED, "s2"), (3, EventType.FINISHED, "s2")]

    assert (result.total_requests, result.started, result.finished, result.dropped) == (4, 4, 4, 0)


def test_terminal_state_coverage_is_exact():
    result = SimulationEngine().simulate(SAMPLE_SERVERS, SAMPLE_REQUESTS)
    idx = index(result)
    input_ids = {r.id for r in SAMPLE_REQUESTS}
    terminal_types = {EventType.FINISHED, EventType.DROPPED}

    # every input request appears, and nothing extra does
    assert set(idx.keys()) == input_ids

    for rid, events in idx.items():
        terminals = [ev for _, ev, _ in events if ev in terminal_types]
        assert len(terminals) == 1, f"{rid} has {len(terminals)} terminal events: {events}"
        assert events[-1][1] in terminal_types, f"{rid}'s last event was not terminal: {events}"


def test_no_unknown_event_types_emitted():
    result = SimulationEngine().simulate(SAMPLE_SERVERS, SAMPLE_REQUESTS)
    allowed = {EventType.ARRIVED, EventType.STARTED, EventType.FINISHED, EventType.DROPPED}
    assert all(e.event in allowed for e in result.events)


# ---- queue bypass (D-005) -----------------------------------------------------


def test_bypass_later_request_starts_before_earlier_blocked_one():
    # s_small only fits small-mem requests; s_big fits everything but is occupied first tick.
    # id order at t=0 puts 'aaa_filler' ahead of 'zzz_blocked' in the (arrival_tick, id) queue,
    # so 'aaa_filler' claims s_big, leaving 'zzz_blocked' queued with no currently eligible
    # server (s_big busy, s_small too small). 'b' then arrives and must not be blocked by
    # 'zzz_blocked' still sitting ahead of it in the queue (D-005 bypass).
    servers = [srv("s_big", 10, 1000, 1), srv("s_small", 10, 50, 1)]
    requests = [
        req("aaa_filler", 0, 100, 500),  # claims s_big at t=0
        req("zzz_blocked", 0, 100, 500),  # only fits s_big; must wait, queued ahead of 'b'
        req("b", 1, 10, 10),  # fits s_small, arrives after 'zzz_blocked' but must not be blocked by it
    ]
    result = SimulationEngine().simulate(servers, requests)
    idx = index(result)
    blocked_start = next(t for t, ev, _ in idx["zzz_blocked"] if ev == EventType.STARTED)
    b_start = next(t for t, ev, _ in idx["b"] if ev == EventType.STARTED)
    assert b_start < blocked_start
    assert idx["b"][1] == (1, EventType.STARTED, "s_small")


# ---- drop (permanently impossible) -------------------------------------------


def test_drop_when_no_server_has_enough_memory():
    servers = [srv("s1", 10, 100, 1)]
    requests = [req("r1", 0, 10, 500)]
    result = SimulationEngine().simulate(servers, requests)
    idx = index(result)
    assert idx["r1"] == [(0, EventType.ARRIVED, None), (0, EventType.DROPPED, None)]
    assert result.dropped == 1


def test_drop_when_all_memory_capable_servers_have_rate_limit_zero():
    servers = [srv("s1", 10, 1000, 0), srv("s2", 10, 1000, 0)]
    requests = [req("r1", 0, 10, 100)]
    result = SimulationEngine().simulate(servers, requests)
    idx = index(result)
    assert idx["r1"] == [(0, EventType.ARRIVED, None), (0, EventType.DROPPED, None)]


def test_rate_limit_zero_preferred_server_is_skipped_for_eligible_one():
    # s_fast would score better (faster) but is start-incapable (rate=0); s_slow must be used.
    servers = [srv("s_fast", 100, 1000, 0), srv("s_slow", 1, 1000, 1)]
    requests = [req("r1", 0, 10, 100)]
    result = SimulationEngine().simulate(servers, requests)
    idx = index(result)
    started = next((t, ev, sid) for t, ev, sid in idx["r1"] if ev == EventType.STARTED)
    assert started[2] == "s_slow"


# ---- tie-break (genuine equal-runtime tie) ------------------------------------


def test_tie_break_equal_runtime_picks_lexicographically_smaller_server_id():
    servers = [srv("sB", 10, 1000, 1), srv("sA", 10, 1000, 1)]  # equal cpu -> equal runtime
    requests = [req("r1", 0, 20, 100)]  # ceil(20/10)=2 on both -> genuine tie
    result = SimulationEngine().simulate(servers, requests)
    idx = index(result)
    started = next((t, ev, sid) for t, ev, sid in idx["r1"] if ev == EventType.STARTED)
    assert started[2] == "sA"


# ---- timing edge cases ---------------------------------------------------------


def test_one_tick_request_work_equals_cpu():
    servers = [srv("s1", 10, 1000, 1)]
    requests = [req("r1", 0, 10, 100)]
    result = SimulationEngine().simulate(servers, requests)
    idx = index(result)
    assert idx["r1"] == [(0, EventType.ARRIVED, None), (0, EventType.STARTED, "s1"), (1, EventType.FINISHED, "s1")]


def test_server_available_at_exact_finish_tick_of_previous_request():
    servers = [srv("s1", 10, 1000, 1)]
    requests = [
        req("r1", 0, 20, 100),  # finishes at t=2
        req("r2", 1, 10, 100),  # must start at t=2, not later
    ]
    result = SimulationEngine().simulate(servers, requests)
    idx = index(result)
    r2_start = next(t for t, ev, _ in idx["r2"] if ev == EventType.STARTED)
    assert r2_start == 2


# ---- explicit sorting (independence from input order) -------------------------


def test_explicit_sort_independent_of_input_list_order():
    forward = SimulationEngine().simulate(SAMPLE_SERVERS, SAMPLE_REQUESTS)
    shuffled = list(reversed(SAMPLE_REQUESTS))
    backward = SimulationEngine().simulate(SAMPLE_SERVERS, shuffled)
    assert forward.events == backward.events


# ---- deadlock protection (isolated unit test of the guard itself) -------------


def test_next_tick_raises_deadlock_error_when_no_candidates():
    state = {"s1": ServerRuntimeState(server_id="s1", current=None)}
    waiting = [req("r1", 0, 10, 100)]
    with pytest.raises(SimulationDeadlockError):
        _next_tick(state, arrivals=[], arrival_ptr=0, waiting=waiting)


def test_next_tick_returns_min_of_finish_and_arrival_candidates():
    from app.domain.models import RunningRequest

    state = {
        "s1": ServerRuntimeState(server_id="s1", current=RunningRequest("x", "s1", 0, 5)),
        "s2": ServerRuntimeState(server_id="s2", current=None),
    }
    arrivals = [req("later", 3, 10, 100)]
    assert _next_tick(state, arrivals, arrival_ptr=0, waiting=[]) == 3


# ---- second strategy: lowest_id (Day 3A bonus) ---------------------------------


def test_default_behavior_unchanged_without_explicit_strategy_argument():
    result_explicit = SimulationEngine().simulate(SAMPLE_SERVERS, SAMPLE_REQUESTS, FastestFitStrategy())
    result_default = SimulationEngine().simulate(SAMPLE_SERVERS, SAMPLE_REQUESTS)
    assert result_explicit.events == result_default.events


def test_lowest_id_strategy_genuinely_differs_from_fastest_finish_for_same_input():
    # sA is slow but lowest id; sZ is fast but highest id.
    servers = [srv("sA", 1, 1000, 1), srv("sZ", 100, 1000, 1)]
    requests = [req("r1", 0, 100, 100)]

    fastest = SimulationEngine().simulate(servers, requests, FastestFitStrategy())
    lowest_id = SimulationEngine().simulate(servers, requests, LowestIdStrategy())

    fastest_server = next(sid for t, ev, sid in index(fastest)["r1"] if ev == EventType.STARTED)
    lowest_id_server = next(sid for t, ev, sid in index(lowest_id)["r1"] if ev == EventType.STARTED)

    assert fastest_server == "sZ"
    assert lowest_id_server == "sA"
    assert fastest_server != lowest_id_server


def test_lowest_id_strategy_obeys_the_same_eligibility_rules_as_default():
    # sA has the lowest id but rate_limit=0 (start-incapable); lowest_id must still skip it.
    servers = [srv("sA", 100, 1000, 0), srv("sB", 1, 1000, 1)]
    requests = [req("r1", 0, 10, 100)]
    result = SimulationEngine().simulate(servers, requests, LowestIdStrategy())
    started = next(sid for t, ev, sid in index(result)["r1"] if ev == EventType.STARTED)
    assert started == "sB"


def test_lowest_id_strategy_full_sample_walkthrough_stays_lifecycle_correct():
    result = SimulationEngine().simulate(SAMPLE_SERVERS, SAMPLE_REQUESTS, LowestIdStrategy())
    idx = index(result)
    input_ids = {r.id for r in SAMPLE_REQUESTS}
    assert set(idx.keys()) == input_ids
    for rid, events in idx.items():
        assert events[-1][1] in (EventType.FINISHED, EventType.DROPPED)


def test_strategy_registry_resolves_known_ids_and_rejects_unknown():
    assert get_strategy("fastest_finish").name == "fastest_finish"
    assert get_strategy("lowest_id").name == "lowest_id"
    with pytest.raises(UnknownStrategyError):
        get_strategy("not_a_real_strategy")
