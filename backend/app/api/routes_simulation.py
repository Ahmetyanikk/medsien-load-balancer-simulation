from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from ..adapters.jsonl_trace import JsonlTraceWriter
from ..config import Settings
from ..domain.autoscale import decide_scaling
from ..domain.errors import CorruptTraceError, UnknownStrategyError
from ..domain.metrics import compute_metrics
from ..domain.strategies import STRATEGY_REGISTRY, DEFAULT_STRATEGY_NAME, get_strategy
from ..domain.summary import SimulationSummary, summarize
from ..domain.timeline import compute_timeline
from ..services.simulation_service import SimulationService
from ..services.trace_reader import read_current_run
from .dependencies import get_settings, get_simulation_service
from .schemas import (
    AutoScaleObservedOut,
    AutoScaleResponse,
    MetricsResponse,
    QueueDepthPointOut,
    RunSummary,
    ServerMetricsOut,
    StrategiesResponse,
    StrategyInfo,
    TimelineEventOut,
    TimelineIntervalOut,
    TimelineRequestOut,
    TimelineResponse,
    TimelineServerLaneOut,
)

router = APIRouter(prefix="/api/simulations", tags=["simulations"])


def _to_run_summary(summary: SimulationSummary) -> RunSummary:
    return RunSummary(status="completed", **asdict(summary))


@router.post("/run", response_model=RunSummary)
def run_simulation(
    strategy: str = Query(default=DEFAULT_STRATEGY_NAME),
    settings: Settings = Depends(get_settings),
    service: SimulationService = Depends(get_simulation_service),
) -> RunSummary:
    # STRATEGY_REGISTRY is the single source of truth for valid strategy ids —
    # no second hard-coded list (Literal or otherwise) here. get_strategy()
    # is the one place that decides validity; an unknown id is a genuine
    # user-input error (422), deliberately caught here rather than left to
    # fall through to the generic DomainError -> 500 handler, which is meant
    # for "this shouldn't have happened" states, not bad request input.
    try:
        resolved_strategy = get_strategy(strategy)
    except UnknownStrategyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    result = service.run(
        settings.servers_path,
        settings.requests_path,
        settings.run_jsonl_path,
        strategy=resolved_strategy,
        context_path=settings.run_context_path,
    )
    return _to_run_summary(summarize(result.events))


@router.get("/strategies", response_model=StrategiesResponse)
def list_strategies() -> StrategiesResponse:
    # Generated from STRATEGY_REGISTRY (dict insertion order, deterministic)
    # so the registry stays the single source of truth for which strategies
    # exist — nothing here duplicates that list by hand.
    return StrategiesResponse(
        strategies=[
            StrategyInfo(id=strategy_id, label=strategy.label, default=(strategy_id == DEFAULT_STRATEGY_NAME))
            for strategy_id, strategy in STRATEGY_REGISTRY.items()
        ]
    )


@router.get("/latest", response_model=RunSummary)
def get_latest(settings: Settings = Depends(get_settings)) -> RunSummary:
    if not settings.run_jsonl_path.exists():
        raise HTTPException(status_code=404, detail="no simulation has been run yet")
    try:
        text = settings.run_jsonl_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        # Filesystem/decode concern only — schema and lifecycle validation stay in
        # JsonlTraceWriter.deserialize(); this is not duplicated here.
        raise CorruptTraceError(f"persisted trace is not valid UTF-8: {exc}") from exc
    events = JsonlTraceWriter().deserialize(text)
    return _to_run_summary(summarize(events))


@router.get("/latest/metrics", response_model=MetricsResponse)
def get_latest_metrics(settings: Settings = Depends(get_settings)) -> MetricsResponse:
    snapshot = read_current_run(settings)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="no simulation has been run yet")

    verified_servers = list(snapshot.servers) if snapshot.servers is not None else None
    cluster, servers = compute_metrics(snapshot.events, verified_servers)

    return MetricsResponse(
        context_available=snapshot.context_available,
        strategy_used=snapshot.strategy_used,
        total_requests=cluster.total_requests,
        started=cluster.started,
        finished=cluster.finished,
        dropped=cluster.dropped,
        dropped_rate=cluster.dropped_rate,
        duration_ticks=cluster.duration_ticks,
        throughput_requests_per_tick=cluster.throughput_requests_per_tick,
        peak_queue_depth=cluster.peak_queue_depth,
        avg_queue_depth=cluster.avg_queue_depth,
        configured_server_count=cluster.configured_server_count,
        idle_configured_server_ids=(
            list(cluster.idle_configured_server_ids) if cluster.idle_configured_server_ids is not None else None
        ),
        avg_cluster_busy_ratio=cluster.avg_cluster_busy_ratio,
        servers=[
            ServerMetricsOut(
                server_id=m.server_id,
                requests_handled=m.requests_handled,
                work_units_total=m.work_units_total,
                busy_ticks=m.busy_ticks,
                busy_time_ratio=m.busy_time_ratio,
                cpu_units_per_tick=m.cpu_units_per_tick,
            )
            for m in servers
        ],
    )


@router.get("/latest/timeline", response_model=TimelineResponse)
def get_latest_timeline(settings: Settings = Depends(get_settings)) -> TimelineResponse:
    snapshot = read_current_run(settings)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="no simulation has been run yet")

    verified_servers = list(snapshot.servers) if snapshot.servers is not None else None
    result = compute_timeline(snapshot.events, verified_servers)

    return TimelineResponse(
        context_available=result.context_available,
        strategy_used=snapshot.strategy_used,
        total_requests=result.total_requests,
        start_tick=result.start_tick,
        end_tick=result.end_tick,
        duration_ticks=result.duration_ticks,
        requests=[
            TimelineRequestOut(
                request_id=r.request_id,
                arrival_tick=r.arrival_tick,
                server_id=r.server_id,
                start_tick=r.start_tick,
                finish_tick=r.finish_tick,
                dropped_tick=r.dropped_tick,
                status=r.status,
                wait_ticks=r.wait_ticks,
            )
            for r in result.requests
        ],
        servers=[
            TimelineServerLaneOut(
                server_id=lane.server_id,
                cpu_units_per_tick=lane.cpu_units_per_tick,
                intervals=[
                    TimelineIntervalOut(request_id=iv.request_id, start_tick=iv.start_tick, finish_tick=iv.finish_tick)
                    for iv in lane.intervals
                ],
            )
            for lane in result.servers
        ],
        events=[
            TimelineEventOut(
                sequence=e.sequence,
                tick=e.tick,
                event_type=e.event_type,
                request_id=e.request_id,
                server_id=e.server_id,
            )
            for e in result.events
        ],
        queue_depth=[QueueDepthPointOut(tick=p.tick, depth=p.depth) for p in result.queue_depth],
    )


@router.get("/latest/autoscaling", response_model=AutoScaleResponse)
def get_latest_autoscaling(settings: Settings = Depends(get_settings)) -> AutoScaleResponse:
    snapshot = read_current_run(settings)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="no simulation has been run yet")

    verified_servers = list(snapshot.servers) if snapshot.servers is not None else None
    cluster, _ = compute_metrics(snapshot.events, verified_servers)
    recommendation = decide_scaling(cluster)

    return AutoScaleResponse(
        context_available=snapshot.context_available,
        recommendation_available=recommendation.recommendation_available,
        action=recommendation.action,
        reason_codes=list(recommendation.reason_codes),
        explanation=recommendation.explanation,
        suggested_server_delta=recommendation.suggested_server_delta,
        removal_candidate_server_ids=(
            list(recommendation.removal_candidate_server_ids)
            if recommendation.removal_candidate_server_ids is not None
            else None
        ),
        observed=AutoScaleObservedOut(
            total_requests=cluster.total_requests,
            dropped=cluster.dropped,
            dropped_rate=cluster.dropped_rate,
            peak_queue_depth=cluster.peak_queue_depth,
            avg_queue_depth=cluster.avg_queue_depth,
            avg_cluster_busy_ratio=cluster.avg_cluster_busy_ratio,
            configured_server_count=cluster.configured_server_count,
            idle_configured_server_ids=(
                list(cluster.idle_configured_server_ids) if cluster.idle_configured_server_ids is not None else None
            ),
        ),
        limitations=list(recommendation.limitations),
    )


@router.get("/latest/download")
def download_latest(settings: Settings = Depends(get_settings)) -> FileResponse:
    if not settings.run_jsonl_path.exists():
        raise HTTPException(status_code=404, detail="no simulation has been run yet")
    return FileResponse(
        path=settings.run_jsonl_path,
        filename="run.jsonl",
        media_type="application/x-ndjson",
    )
