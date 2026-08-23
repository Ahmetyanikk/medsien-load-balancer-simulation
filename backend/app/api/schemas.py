from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..domain.autoscale import ReasonCode


class ServerCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    cpu_units_per_tick: int = Field(gt=0)
    mem_mb: int = Field(ge=0)
    rate_limit_per_sec: int = Field(ge=0)

    @field_validator("id")
    @classmethod
    def _trimmed_nonempty_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("id must not be empty or whitespace-only")
        return v


class ServerUpdate(BaseModel):
    """No id field: the path parameter is the sole identity. Combined with
    extra="forbid", sending "id" in the body is structurally rejected (422)."""

    model_config = ConfigDict(extra="forbid")

    cpu_units_per_tick: int = Field(gt=0)
    mem_mb: int = Field(ge=0)
    rate_limit_per_sec: int = Field(ge=0)


class ServerOut(BaseModel):
    id: str
    cpu_units_per_tick: int
    mem_mb: int
    rate_limit_per_sec: int


class RunSummary(BaseModel):
    status: Literal["completed"]
    total_requests: int
    started: int
    finished: int
    dropped: int
    avg_wait_ticks: Optional[float]
    p50_wait_ticks: Optional[int]
    p95_wait_ticks: Optional[int]
    max_wait_ticks: Optional[int]


class StrategyInfo(BaseModel):
    id: str
    label: str
    default: bool


class StrategiesResponse(BaseModel):
    strategies: list[StrategyInfo]


class ServerMetricsOut(BaseModel):
    server_id: str
    requests_handled: int
    work_units_total: Optional[int]
    busy_ticks: int
    busy_time_ratio: Optional[float] = Field(
        description="Occupancy/CPU-pressure proxy, not literal CPU utilization: a "
        "request's final tick can consume less than a full cpu_units_per_tick when "
        "work_units isn't an exact multiple of it."
    )
    cpu_units_per_tick: Optional[int]


class MetricsResponse(BaseModel):
    context_available: bool
    strategy_used: Optional[str]
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
    idle_configured_server_ids: Optional[list[str]]
    avg_cluster_busy_ratio: Optional[float] = Field(
        description="Occupancy/CPU-pressure proxy, not literal CPU utilization."
    )
    servers: list[ServerMetricsOut]


class TimelineRequestOut(BaseModel):
    request_id: str
    arrival_tick: int
    server_id: Optional[str]
    start_tick: Optional[int]
    finish_tick: Optional[int]
    dropped_tick: Optional[int]
    status: Literal["finished", "dropped"]
    wait_ticks: Optional[int]


class TimelineIntervalOut(BaseModel):
    request_id: str
    start_tick: int
    finish_tick: int


class TimelineServerLaneOut(BaseModel):
    server_id: str
    cpu_units_per_tick: Optional[int]
    intervals: list[TimelineIntervalOut]


class TimelineEventOut(BaseModel):
    sequence: int = Field(description="0-based index in the persisted trace's own event order — not re-sorted.")
    tick: int
    event_type: str
    request_id: str
    server_id: Optional[str]


class QueueDepthPointOut(BaseModel):
    tick: int
    depth: int


class TimelineResponse(BaseModel):
    context_available: bool
    strategy_used: Optional[str]
    total_requests: int
    start_tick: int
    end_tick: int
    duration_ticks: int
    requests: list[TimelineRequestOut]
    servers: list[TimelineServerLaneOut]
    events: list[TimelineEventOut] = Field(
        description="Persisted trace order, unsorted — see `sequence` for each event's literal position."
    )
    queue_depth: list[QueueDepthPointOut] = Field(
        description="Sparse change points: depth holds constant between consecutive points."
    )


class AutoScaleObservedOut(BaseModel):
    """Mirrors the corresponding GET /latest/metrics fields exactly — never
    independently reinterpreted or recomputed here."""

    total_requests: int
    dropped: int
    dropped_rate: Optional[float] = Field(
        description="Dropped-request/error-pressure proxy, not a true application error rate."
    )
    peak_queue_depth: int
    avg_queue_depth: Optional[float]
    avg_cluster_busy_ratio: Optional[float] = Field(
        description="Occupancy/CPU-pressure proxy, not literal CPU utilization."
    )
    configured_server_count: Optional[int]
    idle_configured_server_ids: Optional[list[str]]


class AutoScaleResponse(BaseModel):
    """Read-only auto-scaling recommendation for the current trace.

    `HIGH_BUSY_RATIO` (0.80) and `LOW_BUSY_RATIO` (0.20) — the thresholds the
    policy behind this response applies to `observed.avg_cluster_busy_ratio`
    — are simple, explainable, uncalibrated heuristic defaults for this case
    study, not production standards or empirically calibrated values.
    """

    context_available: bool
    recommendation_available: bool
    action: Optional[Literal["scale_up", "scale_down", "no_change"]]
    reason_codes: list[ReasonCode]
    explanation: str
    suggested_server_delta: Optional[int]
    removal_candidate_server_ids: Optional[list[str]]
    observed: AutoScaleObservedOut
    limitations: list[str] = Field(
        description="Fixed, always-present caveats: no work_units/memory evidence, proxy metrics, "
        "single-step delta only, uncalibrated thresholds, never applied automatically."
    )
