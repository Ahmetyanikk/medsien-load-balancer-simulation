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


class SimulationDeadlockError(DomainError):
    """Waiting requests remain but no server is busy and no future arrival exists.

    Should be unreachable given the engine's can-ever-run prefilter at arrival time;
    raised instead of looping forever if that invariant is ever violated.
    """
