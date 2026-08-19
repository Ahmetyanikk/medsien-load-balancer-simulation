from __future__ import annotations

from fastapi import Request

from ..config import Settings
from ..repository.server_repository import ServerRepository
from ..services.simulation_service import SimulationService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_server_repository(request: Request) -> ServerRepository:
    return request.app.state.server_repository


def get_simulation_service(request: Request) -> SimulationService:
    return request.app.state.simulation_service
