from __future__ import annotations

import csv
from pathlib import Path

from ..domain.errors import DuplicateRequestIdError, MissingRequestColumnsError
from ..domain.models import RequestSpec

REQUIRED_COLUMNS = {"t", "request_id", "work_units", "mem_mb"}


def load_requests(path: Path) -> list[RequestSpec]:
    """Parse requests.csv, returned explicitly sorted by (arrival_t, id).

    Returns [] for a header-only (empty) file — that is not an error at this layer;
    the engine treats zero requests as a trivially valid simulation. SimulationService
    is the layer that rejects an empty requests.csv, since it's the one responsible
    for publishing a run.jsonl the supplied validator can actually parse.
    """
    requests: dict[str, RequestSpec] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not REQUIRED_COLUMNS.issubset(reader.fieldnames or []):
            raise MissingRequestColumnsError(
                f"requests.csv must contain columns {sorted(REQUIRED_COLUMNS)}, "
                f"got {reader.fieldnames}"
            )
        for row in reader:
            rid = row["request_id"].strip()
            if rid in requests:
                raise DuplicateRequestIdError(f"duplicate request_id in requests.csv: {rid}")
            requests[rid] = RequestSpec(
                id=rid,
                arrival_t=int(row["t"]),
                work_units=int(row["work_units"]),
                mem_mb=int(row["mem_mb"]),
            )
    return sorted(requests.values(), key=lambda r: (r.arrival_t, r.id))
