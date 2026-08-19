from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..adapters.jsonl_trace import JsonlTraceWriter
from ..config import Settings
from ..domain.errors import CorruptTraceError
from ..domain.summary import SimulationSummary, summarize
from ..services.simulation_service import SimulationService
from .dependencies import get_settings, get_simulation_service
from .schemas import RunSummary

router = APIRouter(prefix="/api/simulations", tags=["simulations"])


def _to_run_summary(summary: SimulationSummary) -> RunSummary:
    return RunSummary(status="completed", **asdict(summary))


@router.post("/run", response_model=RunSummary)
def run_simulation(
    settings: Settings = Depends(get_settings),
    service: SimulationService = Depends(get_simulation_service),
) -> RunSummary:
    result = service.run(settings.servers_path, settings.requests_path, settings.run_jsonl_path)
    return _to_run_summary(summarize(result.events))


@router.get("/latest", response_model=RunSummary)
def get_latest(settings: Settings = Depends(get_settings)) -> RunSummary:
    if not settings.run_jsonl_path.exists():
        raise HTTPException(status_code=404, detail="no simulation has been run yet")
    try:
        text = settings.run_jsonl_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        # Filesystem/decode concern only — schema and lifecycle validation stay in
        # JsonlTraceWriter.deserialize(); this is not duplicated here.
        raise CorruptTraceError(f"persisted trace is not valid UTF-8: {exc}") from exc
    events = JsonlTraceWriter().deserialize(text)
    return _to_run_summary(summarize(events))


@router.get("/latest/download")
def download_latest(settings: Settings = Depends(get_settings)) -> FileResponse:
    if not settings.run_jsonl_path.exists():
        raise HTTPException(status_code=404, detail="no simulation has been run yet")
    return FileResponse(
        path=settings.run_jsonl_path,
        filename="run.jsonl",
        media_type="application/x-ndjson",
    )
