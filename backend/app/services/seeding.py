from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

from ..config import Settings
from ..domain.errors import SeedSourceMissingError


def _atomic_copy(source: Path, destination: Path) -> None:
    directory = destination.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix=".seed-", suffix=".tmp")
    try:
        os.close(fd)
        shutil.copyfile(source, tmp_path)
        os.replace(tmp_path, destination)
    except BaseException:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def seed_if_missing(settings: Settings) -> None:
    """Copy servers.json and requests.csv from provided/ into data/, only if missing.

    - Copies exactly these two files, by name — never a directory copy of provided/*.
    - Never touches run.jsonl, assignment.pdf, or validate_run.py.
    - Never overwrites an existing destination file, including an intentionally
      empty servers.json (dashboard-driven "delete all servers" state).
    - Never triggers a simulation run.
    - Publication is temp-file + os.replace, so a failed copy never leaves a
      partially-written destination.
    - A missing source is a controlled startup failure (SeedSourceMissingError),
      not a silent no-op or an unhandled exception.
    """
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    for filename, dest in (
        ("servers.json", settings.servers_path),
        ("requests.csv", settings.requests_path),
    ):
        if dest.exists():
            continue
        source = settings.provided_dir / filename
        if not source.exists():
            raise SeedSourceMissingError(f"cannot seed {dest}: source {source} does not exist")
        _atomic_copy(source, dest)
