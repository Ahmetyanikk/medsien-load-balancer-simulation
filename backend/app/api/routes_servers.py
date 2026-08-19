from __future__ import annotations

from fastapi import APIRouter, Depends, Response

from ..domain.models import ServerSpec
from ..repository.server_repository import ServerRepository
from .dependencies import get_server_repository
from .schemas import ServerCreate, ServerOut, ServerUpdate

router = APIRouter(prefix="/api/servers", tags=["servers"])


def _to_out(s: ServerSpec) -> ServerOut:
    return ServerOut(
        id=s.id,
        cpu_units_per_tick=s.cpu_units_per_tick,
        mem_mb=s.mem_mb,
        rate_limit_per_sec=s.rate_limit_per_sec,
    )


@router.get("", response_model=list[ServerOut])
def list_servers(repo: ServerRepository = Depends(get_server_repository)) -> list[ServerOut]:
    return [_to_out(s) for s in repo.load()]


@router.post("", response_model=ServerOut, status_code=201)
def create_server(body: ServerCreate, repo: ServerRepository = Depends(get_server_repository)) -> ServerOut:
    spec = ServerSpec(
        id=body.id,
        cpu_units_per_tick=body.cpu_units_per_tick,
        mem_mb=body.mem_mb,
        rate_limit_per_sec=body.rate_limit_per_sec,
    )
    return _to_out(repo.create(spec))


@router.put("/{server_id}", response_model=ServerOut)
def update_server(
    server_id: str,
    body: ServerUpdate,
    repo: ServerRepository = Depends(get_server_repository),
) -> ServerOut:
    updated = repo.update(server_id, body.cpu_units_per_tick, body.mem_mb, body.rate_limit_per_sec)
    return _to_out(updated)


@router.delete("/{server_id}", status_code=204)
def delete_server(server_id: str, repo: ServerRepository = Depends(get_server_repository)) -> Response:
    repo.delete(server_id)
    return Response(status_code=204)
