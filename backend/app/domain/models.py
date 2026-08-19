from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from .errors import InvalidRequestSpecError, InvalidServerSpecError


@dataclass(frozen=True)
class ServerSpec:
    id: str
    cpu_units_per_tick: int
    mem_mb: int
    rate_limit_per_sec: int

    def __post_init__(self) -> None:
        if not self.id:
            raise InvalidServerSpecError("server id must be non-empty")
        if self.cpu_units_per_tick <= 0:
            raise InvalidServerSpecError(f"server '{self.id}': cpu_units_per_tick must be positive")
        if self.mem_mb < 0:
            raise InvalidServerSpecError(f"server '{self.id}': mem_mb must be non-negative")
        if self.rate_limit_per_sec < 0:
            raise InvalidServerSpecError(f"server '{self.id}': rate_limit_per_sec must be non-negative")

    @property
    def start_capable(self) -> bool:
        return self.rate_limit_per_sec > 0


@dataclass(frozen=True)
class RequestSpec:
    id: str
    arrival_t: int
    work_units: int
    mem_mb: int

    def __post_init__(self) -> None:
        if not self.id:
            raise InvalidRequestSpecError("request id must be non-empty")
        if self.arrival_t < 0:
            raise InvalidRequestSpecError(f"request '{self.id}': arrival_t must be non-negative")
        if self.work_units <= 0:
            raise InvalidRequestSpecError(f"request '{self.id}': work_units must be positive")
        if self.mem_mb < 0:
            raise InvalidRequestSpecError(f"request '{self.id}': mem_mb must be non-negative")


class EventType(str, Enum):
    ARRIVED = "REQUEST_ARRIVED"
    STARTED = "REQUEST_STARTED"
    FINISHED = "REQUEST_FINISHED"
    DROPPED = "REQUEST_DROPPED"


@dataclass(frozen=True)
class SimulationEvent:
    t: int
    event: EventType
    request_id: str
    server_id: Optional[str] = None


@dataclass(frozen=True)
class RunningRequest:
    request_id: str
    server_id: str
    start_tick: int
    finish_tick: int


@dataclass
class ServerRuntimeState:
    server_id: str
    current: Optional[RunningRequest] = None

    @property
    def is_idle(self) -> bool:
        return self.current is None


@dataclass(frozen=True)
class SimulationResult:
    events: tuple[SimulationEvent, ...]
    total_requests: int
    started: int
    finished: int
    dropped: int
