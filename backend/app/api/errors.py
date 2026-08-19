from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ..domain.errors import (
    DomainError,
    DuplicateServerIdError,
    InvalidRuntimeConfigurationError,
    InvalidServerSpecError,
    ServerNotFoundError,
    SimulationAlreadyRunningError,
)


def _json_error(status_code: int):
    async def handler(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    return handler


def register_exception_handlers(app: FastAPI) -> None:
    """Domain exception -> HTTP status mapping.

    Starlette dispatches by walking the raised exception's MRO and using the most
    specific registered ancestor, so subclasses of InvalidRuntimeConfigurationError
    (Empty*ConfigurationError, UnsupportedTickSecondsError) get 400 via the one
    shared handler below, and anything else that's a DomainError but has no more
    specific handler (SimulationDeadlockError, CorruptTraceError,
    MissingRequestColumnsError, DuplicateRequestIdError, InvalidRequestSpecError)
    falls through to the generic 500 catch-all — never a bare traceback.
    """
    app.add_exception_handler(DuplicateServerIdError, _json_error(409))
    app.add_exception_handler(SimulationAlreadyRunningError, _json_error(409))
    app.add_exception_handler(ServerNotFoundError, _json_error(404))
    app.add_exception_handler(InvalidServerSpecError, _json_error(422))
    app.add_exception_handler(InvalidRuntimeConfigurationError, _json_error(400))
    app.add_exception_handler(DomainError, _json_error(500))
