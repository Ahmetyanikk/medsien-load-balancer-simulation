class DomainError(Exception):
    """Base class for all simulation domain errors."""


class InvalidServerSpecError(DomainError):
    """A server definition violates a domain invariant (positive CPU, non-negative mem/rate)."""


class InvalidRequestSpecError(DomainError):
    """A request definition violates a domain invariant (non-negative arrival, positive work, non-negative mem)."""


class DuplicateServerIdError(DomainError):
    """servers.json contains two servers with the same id."""


class DuplicateRequestIdError(DomainError):
    """requests.csv contains two requests with the same request_id."""


class EmptyServerConfigurationError(DomainError):
    """No servers were configured; a simulation cannot run with zero capacity."""


class EmptyRequestConfigurationError(DomainError):
    """requests.csv contains no requests.

    SimulationEngine itself treats an empty request list as a trivially valid
    simulation (pure domain behavior). SimulationService rejects it before
    running/publishing, because the supplied validator cannot parse an empty
    run.jsonl (it raises on zero events) — publishing one would produce an
    artifact the mandatory acceptance check can't even read.
    """


class MissingRequestColumnsError(DomainError):
    """requests.csv is missing one or more required columns (t, request_id, work_units, mem_mb)."""


class UnsupportedTickSecondsError(DomainError):
    """servers.json declares a tick_seconds other than 1.

    The provided validator hard-requires tick_seconds == 1; we fail fast with a
    clear domain error rather than let an incompatible config reach the engine.
    """


class SimulationDeadlockError(DomainError):
    """Waiting requests remain but no server is busy and no future arrival exists.

    Should be unreachable given the engine's can-ever-run prefilter at arrival time;
    raised instead of looping forever if that invariant is ever violated.
    """
