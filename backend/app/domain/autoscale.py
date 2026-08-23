"""Pure, read-only auto-scaling recommendation policy.

`decide_scaling()` maps an already-computed `ClusterMetrics` (domain/metrics.py)
to a `scale_up` / `scale_down` / `no_change` recommendation, or an explicitly
distinct *unavailable* result when there isn't enough trustworthy evidence to
decide at all (see `docs/DECISIONS.md` D-022 for the full precedence
rationale). This module never mutates anything, never calls server CRUD,
never triggers a simulation run, and never applies its own suggestion —
every recommendation is advisory only.

`HIGH_BUSY_RATIO` (0.80) and `LOW_BUSY_RATIO` (0.20) are simple, explainable,
uncalibrated heuristic defaults chosen for this case study — not industry-
standard, production-calibrated, or empirically derived values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, Optional

from .metrics import ClusterMetrics

MIN_SERVER_COUNT = 1
HIGH_BUSY_RATIO = 0.80
LOW_BUSY_RATIO = 0.20

ActionType = Literal["scale_up", "scale_down", "no_change"]

# Stable, typed reason-code set — never renamed once shipped, since the
# frontend and tests key off these strings, not off explanation prose.
ReasonCode = Literal[
    "insufficient_data",
    "context_unavailable",
    "dropped_requests",
    "high_queue_pressure",
    "high_occupancy",
    "low_occupancy_idle_capacity",
    "minimum_server_count",
    "steady_state",
]

REASON_INSUFFICIENT_DATA: Final[ReasonCode] = "insufficient_data"
REASON_CONTEXT_UNAVAILABLE: Final[ReasonCode] = "context_unavailable"
REASON_DROPPED_REQUESTS: Final[ReasonCode] = "dropped_requests"
REASON_HIGH_QUEUE_PRESSURE: Final[ReasonCode] = "high_queue_pressure"
REASON_HIGH_OCCUPANCY: Final[ReasonCode] = "high_occupancy"
REASON_LOW_OCCUPANCY_IDLE_CAPACITY: Final[ReasonCode] = "low_occupancy_idle_capacity"
REASON_MINIMUM_SERVER_COUNT: Final[ReasonCode] = "minimum_server_count"
REASON_STEADY_STATE: Final[ReasonCode] = "steady_state"

_REASON_EXPLANATIONS: dict[ReasonCode, str] = {
    REASON_INSUFFICIENT_DATA: (
        "No requests were observed in this trace, so there is not enough evidence to recommend a change."
    ),
    REASON_CONTEXT_UNAVAILABLE: (
        "Configured-server context is unavailable or unverified, so queue-pressure and occupancy signals "
        "cannot be evaluated; no scaling decision is made without a verified server snapshot."
    ),
    REASON_DROPPED_REQUESTS: (
        "At least one request was dropped, which may indicate an incompatible capacity profile — for example, "
        "insufficient memory on every configured server — not merely an insufficient server count. Adding one "
        "identical server is not guaranteed to resolve this."
    ),
    REASON_HIGH_QUEUE_PRESSURE: "Peak queue depth reached or exceeded the configured server count.",
    REASON_HIGH_OCCUPANCY: (
        f"Average cluster occupancy is at or above the high-utilization threshold ({HIGH_BUSY_RATIO:.2f})."
    ),
    REASON_LOW_OCCUPANCY_IDLE_CAPACITY: (
        f"Average cluster occupancy is below the low-utilization threshold ({LOW_BUSY_RATIO:.2f}) and at least "
        "one configured server handled zero requests. Choose at most one removal candidate; this recommendation "
        "is never applied automatically."
    ),
    REASON_MINIMUM_SERVER_COUNT: (
        f"The cluster is already at the minimum server count ({MIN_SERVER_COUNT}); scale-down is not recommended."
    ),
    REASON_STEADY_STATE: "No scaling signal was triggered; the cluster appears to be operating in a steady state.",
}

LIMITATIONS: tuple[str, ...] = (
    "No work_units or memory-demand evidence is available to this recommendation.",
    "avg_cluster_busy_ratio is an occupancy/CPU-pressure proxy, not literal CPU utilization.",
    "dropped_rate is a dropped-request/error-pressure proxy, not a true application error rate.",
    "Only a single-step +1 or -1 recommendation is supported; there is no magnitude model.",
    "Thresholds are simple, explainable, uncalibrated heuristic defaults for this case study, not derived from "
    "production telemetry.",
    "Recommendations are never applied automatically.",
)


@dataclass(frozen=True)
class ScalingRecommendation:
    """Pure recommendation-only output. No filesystem/HTTP/repository/clock/
    environment access anywhere in this module, and no observed-metric fields
    duplicated here — callers read those directly off the same ClusterMetrics
    passed in, so 'observed' can never drift from compute_metrics()'s own
    output (domain/metrics.py, reused, never reimplemented)."""

    recommendation_available: bool
    action: Optional[ActionType]
    reason_codes: tuple[ReasonCode, ...]
    explanation: str
    suggested_server_delta: Optional[int]
    removal_candidate_server_ids: Optional[tuple[str, ...]]
    limitations: tuple[str, ...]


def _recommendation(
    *,
    available: bool,
    action: Optional[ActionType],
    reason_codes: tuple[ReasonCode, ...],
    delta: Optional[int],
    candidates: Optional[tuple[str, ...]],
) -> ScalingRecommendation:
    explanation = " ".join(_REASON_EXPLANATIONS[code] for code in reason_codes)
    return ScalingRecommendation(
        recommendation_available=available,
        action=action,
        reason_codes=reason_codes,
        explanation=explanation,
        suggested_server_delta=delta,
        removal_candidate_server_ids=candidates,
        limitations=LIMITATIONS,
    )


def decide_scaling(metrics: ClusterMetrics) -> ScalingRecommendation:
    """Pure, deterministic, first-match-wins policy over an already-computed
    ClusterMetrics (domain/metrics.py) — no independent metric computation,
    no filesystem/HTTP/repository/environment/clock access, no mutation of
    the input. See docs/DECISIONS.md D-022 for the full precedence rationale.
    """
    if metrics.total_requests == 0:
        return _recommendation(
            available=False, action=None, reason_codes=(REASON_INSUFFICIENT_DATA,), delta=None, candidates=None
        )

    if metrics.configured_server_count is None:
        # Intentionally precedes the drop rule: even a trace containing
        # drops must not produce a scaling decision without verified context.
        return _recommendation(
            available=False, action=None, reason_codes=(REASON_CONTEXT_UNAVAILABLE,), delta=None, candidates=None
        )

    if metrics.dropped_rate is not None and metrics.dropped_rate > 0:
        return _recommendation(
            available=True, action="scale_up", reason_codes=(REASON_DROPPED_REQUESTS,), delta=1, candidates=None
        )

    high_queue_and_occupancy = (
        metrics.peak_queue_depth >= metrics.configured_server_count
        and metrics.avg_cluster_busy_ratio is not None
        and metrics.avg_cluster_busy_ratio >= HIGH_BUSY_RATIO
    )
    if high_queue_and_occupancy:
        return _recommendation(
            available=True,
            action="scale_up",
            reason_codes=(REASON_HIGH_QUEUE_PRESSURE, REASON_HIGH_OCCUPANCY),
            delta=1,
            candidates=None,
        )

    low_occupancy = (
        metrics.dropped_rate == 0
        and metrics.peak_queue_depth == 0
        and metrics.avg_cluster_busy_ratio is not None
        and metrics.avg_cluster_busy_ratio < LOW_BUSY_RATIO
    )
    if low_occupancy:
        # A removal candidate must actually be idle — a >1-server cluster with
        # low overall occupancy but no single zero-request server has nothing
        # safe to suggest removing, so it falls through to steady_state below.
        if metrics.configured_server_count > MIN_SERVER_COUNT and metrics.idle_configured_server_ids:
            candidates = tuple(sorted(metrics.idle_configured_server_ids))  # type: ignore[arg-type]
            return _recommendation(
                available=True,
                action="scale_down",
                reason_codes=(REASON_LOW_OCCUPANCY_IDLE_CAPACITY,),
                delta=-1,
                candidates=candidates,
            )
        # At the minimum server count, "idle" is moot — a lone server that ran
        # every non-dropped request (the only way dropped_rate stays 0 with
        # one server) is never itself "idle", so this branch does not require
        # idle_configured_server_ids to be non-empty the way scale-down does.
        if metrics.configured_server_count == MIN_SERVER_COUNT:
            return _recommendation(
                available=True,
                action="no_change",
                reason_codes=(REASON_MINIMUM_SERVER_COUNT,),
                delta=None,
                candidates=None,
            )

    return _recommendation(
        available=True, action="no_change", reason_codes=(REASON_STEADY_STATE,), delta=None, candidates=None
    )
