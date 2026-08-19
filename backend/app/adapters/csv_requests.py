from __future__ import annotations

import csv
from pathlib import Path

from ..domain.errors import DuplicateRequestIdError
from ..domain.models import RequestSpec


def load_requests(path: Path) -> list[RequestSpec]:
    """Parse requests.csv. Returns [] for a header-only (empty) file — that is not
    an error, the engine treats zero requests as a trivially valid simulation."""
    requests: dict[str, RequestSpec] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
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
    return list(requests.values())
