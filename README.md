# Medsien Load Balancer Simulation

A deterministic, discrete-time load balancer simulation with a server-management
dashboard, built for the Medsien take-home assignment. Given a fixed set of
servers and incoming requests, the backend simulates request scheduling
tick-by-tick and produces a byte-for-byte reproducible `run.jsonl` trace that
passes the assignment's supplied validator.

## Mandatory features

- Pure-Python, deterministic simulation engine (no FastAPI/HTTP/filesystem coupling)
- Server CRUD dashboard (React + TypeScript)
- Simulation trigger with a rendered result summary
- `run.jsonl` trace download
- Fully Dockerized: `docker compose up --build` is the only required step

## Prerequisites

Docker with Docker Compose (Compose v2 CLI, i.e. `docker compose`, not the
legacy standalone `docker-compose`). No host Python or Node installation is
required to run the application.

## Start the application

```
docker compose up --build
```

- Dashboard: http://localhost:3000
- Backend health check: http://localhost:8000/health
- API through the frontend's nginx proxy: http://localhost:3000/api/servers

Stop everything with:

```
docker compose down
```

This removes the containers but leaves `backend/data/` (and its contents) on
your host — see "Resetting runtime data" below.

## Using the dashboard

**Servers** — the left panel lists configured servers. "Add server" opens a
form for a new server (ID, CPU units/tick, memory in MB, rate limit/sec). Each
row has "Edit" (the three numeric fields only — the ID is immutable once
created) and "Delete" (asks for confirmation first). The list re-fetches from
the backend after every successful change, so it always reflects what's
actually stored.

**Simulation** — the right panel shows the most recent run's summary on load
(or "No simulation has been run yet" if none exists). Click "Run simulation"
to trigger a new run against the currently configured servers; the button is
disabled while a run is in progress. Once a summary exists, "Download
run.jsonl" downloads the trace directly.

## Downloading `run.jsonl` outside the dashboard

The trace is also directly visible on the host filesystem at
**`backend/data/run.jsonl`** (bind-mounted from the backend container), and via
the API at `http://localhost:3000/api/simulations/latest/download`.

## Running the official validator

The unmodified assignment validator ships inside the backend image at
`/app/provided/validate_run.py`, so it can be run against the current trace
without installing anything on the host:

```
docker compose exec -T backend python /app/provided/validate_run.py --servers /app/backend/data/servers.json --requests /app/backend/data/requests.csv --run /app/backend/data/run.jsonl
```

Expect `RESULT: VALID` and exit code 0.

## Development (non-Docker) test commands

These are for iterating on the source directly; they are not required to run
the application.

**Backend** (from `backend/`, in a virtual environment):
```
pip install -e ".[dev]"
pytest
```

**Frontend** (from `frontend/`):
```
npm ci
npm run test
npm run build
```

## First-boot seeding and resetting runtime data

On first startup, the backend copies `servers.json` and `requests.csv` from
`provided/` into `backend/data/` **only if those files don't already exist
there**. `seed_if_missing()` never copies `run.jsonl` — the repository already
contains a tracked sample `run.jsonl` at `backend/data/run.jsonl` from the
start; a successful simulation run atomically replaces that file (temp file +
`os.replace`), it is never "seeded" in the same sense as the other two.

To reset the server configuration or request set back to the supplied sample,
delete the specific file(s) you want re-seeded:

**Bash:**
```
rm -f backend/data/servers.json backend/data/requests.csv
docker compose restart backend
```

**PowerShell:**
```
Remove-Item backend/data/servers.json, backend/data/requests.csv -ErrorAction SilentlyContinue
docker compose restart backend
```

**Warning:** deleting either file causes it to be automatically re-seeded from
`provided/` on the backend's next startup — any dashboard edits you made to
`servers.json` will be lost. There is no undo. `backend/data/run.jsonl` is
never touched by this process either way.

## Known limitations

- **Single Uvicorn worker, hardcoded.** The server-configuration lock and the
  simulation-run lock are both process-local (Python `threading` primitives).
  A second worker process would not share them, silently defeating both the
  lost-update protection on server CRUD and the concurrent-run protection —
  so the backend intentionally always runs with `--workers 1`, not just by
  default.
- Out of scope for this submission: authentication/authorization, a database,
  multi-process/multi-node coordination, and all bonus features (performance
  metrics beyond the mandatory summary, event/timeline visualization,
  additional scheduling strategies, auto-scaling, shared-CPU execution mode).

## Architecture

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the simulation model,
determinism guarantees, locking design, Docker topology, and the full
mandatory-versus-bonus boundary.

## AI-assisted development

This project was built with AI assistance (Claude Code for implementation,
ChatGPT for planning and adversarial review) under the candidate's direct
scope approval and review at every step. See
[`docs/AI_USAGE.md`](docs/AI_USAGE.md) for the full, task-by-task log.
