from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
