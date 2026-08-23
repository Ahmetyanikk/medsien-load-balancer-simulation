from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..adapters.jsonl_trace import JsonlTraceWriter
from ..config import Settings
from ..domain.errors import CorruptTraceError
from ..domain.models import ServerSpec, SimulationEvent
from ..domain.strategies import STRATEGY_REGISTRY
from . import run_context


@dataclass(frozen=True)
class CurrentRunSnapshot:
    """Everything a read-only trace-derived endpoint (metrics/timeline/
    autoscaling) needs from the currently persisted run, read once."""

    events: tuple[SimulationEvent, ...]
    context_available: bool
    strategy_used: Optional[str]
    servers: Optional[tuple[ServerSpec, ...]]


def read_current_run(settings: Settings) -> Optional[CurrentRunSnapshot]:
    """Shared boundary for every read-only trace-derived route.

    Reads run.jsonl bytes exactly once and reuses those exact bytes for both
    UTF-8 decoding (schema/lifecycle validation via JsonlTraceWriter.deserialize())
    and SHA-256 hashing (context verification via run_context.load_verified()) —
    never read_text() followed by re-encoding, which risks a universal-newline
    translation (CRLF -> LF) silently changing what gets hashed relative to what
    was actually persisted.

    Returns None only when settings.run_jsonl_path doesn't exist — callers 404.
    A malformed/corrupt trace raises CorruptTraceError, left uncaught here, so it
    propagates to the existing generic DomainError -> 500 handler unchanged.
    """
    if not settings.run_jsonl_path.exists():
        return None

    trace_bytes = settings.run_jsonl_path.read_bytes()
    try:
        text = trace_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise CorruptTraceError(f"persisted trace is not valid UTF-8: {exc}") from exc
    events = JsonlTraceWriter().deserialize(text)

    context = run_context.load_verified(
        settings.run_context_path, trace_bytes, known_strategy_ids=frozenset(STRATEGY_REGISTRY)
    )

    return CurrentRunSnapshot(
        events=events,
        context_available=context is not None,
        strategy_used=context["strategy"] if context else None,
        servers=tuple(context["servers"]) if context else None,
    )
