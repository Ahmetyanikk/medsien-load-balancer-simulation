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
