from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from ..config import Settings
from ..repository.server_repository import ServerRepository
from ..services.seeding import seed_if_missing
from ..services.simulation_service import SimulationService
from .errors import register_exception_handlers
from .routes_servers import router as servers_router
from .routes_simulation import router as simulation_router


def create_app(settings: Settings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        seed_if_missing(settings)
        app.state.settings = settings
        app.state.server_repository = ServerRepository(settings.servers_path)
        app.state.simulation_service = SimulationService()
        yield

    app = FastAPI(title="Medsien Load Balancer Simulation", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(servers_router)
    app.include_router(simulation_router)
    register_exception_handlers(app)
    return app


app = create_app(Settings())
