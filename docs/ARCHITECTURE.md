# Architecture

This document describes the system as actually implemented — mandatory scope
only, unless a section is explicitly marked bonus/not implemented. It
complements `docs/DECISIONS.md` (the dated decision log) rather than
replacing it.

## 1. Layers and dependency direction

```
frontend (React/TS)
      │  relative /api/* over HTTP (same-origin via nginx)
      ▼
api (FastAPI routes, schemas, error mapping)
      │
      ▼
services (SimulationService, seeding) ── repository (ServerRepository)
      │                                          │
      ▼                                          ▼
domain (models, engine, strategies, summary) ◄── adapters (csv/json/jsonl parse+serialize)
```

Dependency direction is strictly inward: `domain` imports nothing from
`adapters`, `repository`, `services`, or `api` — no FastAPI, no filesystem, no
HTTP. `adapters` depend only on `domain`. `repository` depends on the JSON
adapter (`adapters/json_servers.py`, for parsing/serializing `servers.json`)
*plus* `domain` types and errors directly — it is not domain-only. `services`
compose `domain` + `adapters` + `repository`. `api` depends on `services`,
`repository`, `config.Settings`, its own `schemas`, and the specific `domain`
types/errors/summary it needs to map responses — including
`adapters.jsonl_trace.JsonlTraceWriter` directly in `routes_simulation.py`, to
reconstruct `GET /latest` from disk. Routes orchestrate; none of this layer
contains scheduling logic itself.

## 2. Pure `SimulationEngine` boundary

`SimulationEngine.simulate(servers, requests, strategy) -> SimulationResult`
takes immutable domain objects and returns an immutable result. It never
reads or writes a file, never imports FastAPI, and has no knowledge of paths.
This is what makes it unit-testable as pure function calls and independently
explainable without any web-framework plumbing. All I/O — loading input,
serializing the trace, atomic publication — is owned by `SimulationService`,
one layer up.

## 3. Tick processing phases

Each tick, in this exact order:

1. **Finishes** — release capacity for any server whose current request's
   `finish_tick == t`; emit `REQUEST_FINISHED`, ordered `(server_id, request_id)`.
2. **Arrivals** — register requests arriving at `t`; emit `REQUEST_ARRIVED`,
   ordered by `request_id`.
3. **Permanent drops** — for each new arrival, if no server could *ever* host
   it (regardless of current busy/idle state), emit `REQUEST_DROPPED`
   immediately; otherwise enqueue it.
4. **Scheduling** — single ordered pass over the waiting queue
   `(arrival_tick, request_id)`; a request with no currently-eligible server
   is skipped (not removed) so a later request isn't blocked by an earlier,
   temporarily-stuck one (bypass, D-005); emit `REQUEST_STARTED` in
   scheduling order.
5. **Termination check** — stop if nothing is arriving in the future, the
   queue is empty, and every server is idle.
6. **Jump to next relevant tick** — advance `t` to
   `min(next arrival, any busy server's finish_tick)`. A static per-server
   rejection (memory/rate) never resolves itself by waiting a tick, so no
   blind `t+1` step is needed — only a server freeing up or a new arrival can
   ever change eligibility.

## 4. Half-open execution intervals

A request starting at tick `t` occupies `[start, finish)`. A server may start
a new request at the exact tick its previous request finishes — `finish_tick`
of one request and `start_tick` of the next on the same server can be equal.

## 5. PDF vs. validator concurrency conflict

The assignment PDF describes CPU divided evenly across multiple concurrently
running requests per server. The supplied `validate_run.py` instead rejects
any overlapping `[start, finish)` interval on the same server and computes
`finish = start + ceil(work_units / cpu_units_per_tick)` as a closed-form
check, with no notion of shared CPU. These are incompatible, and the
validator is the mandatory acceptance gate — see §6.

## 6. Validator-compatible single-active-request default

The default (and only implemented) mode allows **at most one active request
per server**. Runtime is `ceil(work_units / cpu_units_per_tick)`;
`finish_tick = start_tick + runtime`. This is the model the unmodified
validator enforces and the one the supplied sample trace demonstrates. A
shared-CPU mode is explicitly out of scope for this submission (D-003).

## 7. Queue order and bypass policy

Waiting requests are considered in `(arrival_tick, request_id)` order. A
later request may be scheduled ahead of an earlier one that currently has no
eligible server, so a temporarily-stuck request never idles capacity that
another request could use (D-005). The waiting list is built by simple
append — because each tick's new arrivals always have the largest
`arrival_tick` seen so far, this preserves the ordering invariant without a
resort.

## 8. Permanent drop policy

A request is dropped, not queued, if no configured server could *ever* host
it — insufficient memory on every server, or every server with enough memory
has `rate_limit_per_sec == 0` (not start-capable). Every request follows
exactly one terminal lifecycle: `ARRIVED → STARTED → FINISHED` or
`ARRIVED → DROPPED`. The engine's own termination check guarantees no request
is ever silently left unresolved (a guarantee the validator itself does not
enforce — see §18).

## 9. Server selection tie-break

Among currently eligible servers, pick
`min(ceil(work_units / cpu_units_per_tick), server_id)` — the fastest
finishing server, ties broken by the lexicographically smaller server ID
(D-006).

## 10. Determinism guarantees

Identical `servers.json`, `requests.csv`, and configuration produce a
byte-identical `run.jsonl`, verified by an automated repeated-run hash-compare
test. This depends on: explicit `(arrival_tick, request_id)` sorting at load
time (never trusting file order); canonical per-tick event-phase ordering;
stable JSONL field order (`t, event, request_id, server_id`, `server_id`
omitted when absent) with stable separators. The provided validator itself
does **not** check literal file order — it re-sorts every event by
`(t, event_name_string)` before validating — so this determinism is our own
policy for explainability and testability, not something the validator
requires.

## 11. `rate_limit_per_sec` behavior

In the single-active-request default mode, a server can only ever attempt one
start per tick regardless of its configured rate limit, because it becomes
non-idle the instant it starts something — the "server must be idle"
eligibility check already blocks a second start in the same tick before rate
matters at all. Consequently **`rate_limit_per_sec` values above 1 are
behaviorally inert** in this mode; only `rate_limit_per_sec == 0` changes
observable behavior (it permanently excludes that server from starting
anything). This is a deliberate, documented consequence of the mandatory
execution model, not an oversight — it would become meaningful again under a
(not implemented) shared-CPU mode.

## 12. Server snapshots

`SimulationService.run()` loads `servers.json` and `requests.csv` into
immutable domain objects *before* invoking the engine. A dashboard edit made
while a run is executing cannot affect that run — proven by a test that
blocks a run mid-flight, mutates the on-disk config, and confirms the
in-flight run used the original snapshot while the *next* run picks up the
change.

## 13. Atomic `servers.json` and `run.jsonl` publication

Both `ServerRepository._save_unlocked` and `SimulationService._publish` use
the same pattern: write to a temp file in the destination directory, then
`os.replace()` onto the final path. A failure partway through never corrupts
the previous, still-valid file, and a reader never observes a torn file. Both
are tested by injecting a failure mid-write and confirming the original
content survives untouched with no leaked temp file.

## 14. Locking

- **`ServerRepository`** — a `threading.RLock`, held for the entire
  read-modify-write cycle of `create`/`update`/`delete`/`save`. Plain `load()`
  is intentionally lock-free (safe because `os.replace()` already makes reads
  atomic). Proven with a deterministic instrumented test (no `time.sleep`)
  that asserts every write path only ever touches disk while holding the
  lock.
- **`SimulationService`** — a plain `threading.Lock`, acquired
  non-blocking at the top of `.run()`; a second concurrent call raises
  `SimulationAlreadyRunningError` → HTTP 409. This only serializes anything
  because the API resolves to one shared `SimulationService` instance
  (`app.state.simulation_service`), not a new instance per request.

## 15. Single-worker constraint

Both locks above are process-local. The backend Docker image hardcodes
`--workers 1` in its `CMD` — not left as a default a future edit could
casually change — because a second worker process would not share either
lock, silently reintroducing the lost-update and concurrent-run races both
were built to prevent.

## 16. First-boot seeding

`seed_if_missing()` copies exactly `servers.json` and `requests.csv` from
`provided/` into the runtime data directory, and only when the destination
file doesn't already exist. It never touches `run.jsonl`, never overwrites an
existing file (including a dashboard-driven empty `servers.json`), and never
triggers a simulation run. A missing source is a controlled startup failure
(`SeedSourceMissingError`), not a silent no-op (D-014).

## 17. Restart-safe latest-summary reconstruction

The two `GET` endpoints do genuinely different work, both stateless (no
sidecar summary file, no in-memory cache as source of truth) but not
equivalent:

- `GET /api/simulations/latest` reads `run.jsonl` from disk, decodes it as
  UTF-8, calls `JsonlTraceWriter.deserialize()` (schema + lifecycle
  validation, §18), and reconstructs `RunSummary` via
  `domain.summary.summarize()` — on every call.
- `GET /api/simulations/latest/download` only checks that the file exists
  and streams the persisted bytes back via `FileResponse`. It does **not**
  deserialize, validate, or recompute anything — it intentionally exposes the
  raw persisted artifact as-is, for evaluator inspection.

Both 404 only when the configured `run_jsonl_path` doesn't exist. Because
`SimulationService` only ever replaces `run.jsonl` after a fully successful
run, an application-published trace is always complete and valid; there is no
"in-progress" state a reader can ever observe (D-018).

## 18. Persisted trace validation

Presence of a file at `run_jsonl_path` does **not** by itself mean it's
valid — it could be manually edited or corrupted. `deserialize()` performs
explicit schema validation on every line (JSON object; correctly-typed,
non-negative `t`; non-empty, non-whitespace `request_id`; a valid `EventType`;
non-empty, non-whitespace `server_id` required for `STARTED`/`FINISHED`) and
lifecycle validation across the whole trace (no duplicate/out-of-order/
contradictory events — including `STARTED` after `DROPPED` and vice versa —
every arrival resolved to exactly one terminal event, `FINISHED`'s server
matching `STARTED`'s, finish tick strictly after start tick). Any failure —
including an empty or blank-only file, or a non-UTF-8 one — raises
`CorruptTraceError`, mapped to a controlled HTTP 500 JSON response, never a
leaked traceback. This is deliberately stricter than the supplied validator,
which has no check that every arrived request resolves to a terminal
event — the engine's own guarantee (§8) is what actually prevents an
application-generated trace from ever triggering this path; it exists to
protect the API against tampered or corrupted files, not against the
engine's own output. This protection is specific to `GET /latest`: a
manually corrupted trace produces a controlled 500 there, but the raw bytes
can still be fetched successfully via `GET /latest/download`, which performs
no validation at all (§17) — by design, since it exists to expose exactly
what's on disk, not a validated view of it.

## 19. Frontend component and state ownership

`App` is a static layout (`<ServerList/><RunPanel/>`) with no shared state —
the two panels are fully independent since `POST /run` takes no body.
`ServerList` owns the fetched list, which of at most one row is being edited,
a single `mutating` flag gating every Add/Edit/Delete control while any
mutation is in flight, and separate error state for form (create/edit) vs.
delete failures; it re-fetches from the backend after every successful
mutation rather than optimistically updating, and never sorts the response.
`ServerForm` is presentational plus local validation only — it emits
validated values via `onSubmit`; the actual API call lives in `ServerList`.
`RunPanel` owns the latest-run state (loading/none/error/ready, with 404
treated as the normal "none" case, not an error) and the in-flight run flag;
a failed run preserves the last successful summary rather than clearing it,
mirroring the backend's own atomic-publish guarantee. Both `ServerList` and
`RunPanel` protect their initial-load effects with a monotonic
generation-token ref, so a stale response — from a superseded React
StrictMode double-invocation, or simply an older request that happens to
resolve after a newer one — can never overwrite fresher state; the token is
also bumped on effect cleanup so an in-flight request from an unmounted
instance can't apply itself either. `api/client.ts` normalizes both response
shapes the backend can return on error (`{"detail": "<string>"}` from custom
handlers, `{"detail": [...]}` from FastAPI's own 422 validation) into one
string before any component ever sees it. The frontend never recomputes a
metric — every number shown is rendered exactly as the backend returned it,
with `null` wait values displayed as `N/A`.

## 20. nginx and Docker Compose topology

```
Browser → nginx (frontend container, :80 → host :3000)
            ├─ location /api/  → proxy_pass http://backend:8000/api/;  (prefix preserved)
            └─ location /      → static SPA, try_files fallback
          → FastAPI (backend container, :8000, --workers 1)
```

Same-origin relative `/api/*` URLs from the browser mean no CORS
configuration is needed anywhere. `docker-compose.yml` builds both images
from the **repository root** as build context (required so the backend
Dockerfile can `COPY provided/`, a sibling of `backend/`); the frontend
service `depends_on: backend: condition: service_healthy`.

## 21. Container path contract

`backend/app/config.py`'s `Settings`/`BASE_DIR`/`PROVIDED_DIR`/`DATA_DIR` are
computed from `Path(__file__).resolve()` — unchanged from Day 1/2A. The
Docker image is built specifically to make that computation resolve
correctly:

| Host source | Container path |
|---|---|
| `backend/app/` | `/app/backend/app/` |
| `backend/pyproject.toml` | `/app/backend/pyproject.toml` |
| `provided/` | `/app/provided/` |
| (runtime, bind-mounted) | `/app/backend/data/` |

Given `config.py` lives at `/app/backend/app/config.py`,
`Path(__file__).resolve().parent.parent` = `/app/backend`, its `.parent` =
`/app`, and `PROVIDED_DIR = /app/provided`, `DATA_DIR = /app/backend/data` —
exactly this contract, with **zero changes to `config.py`**. This only holds
because the backend image installs with `pip install -e` (editable): a
regular install would copy `app/` into site-packages, and `__file__` would
resolve there instead, silently breaking every path in this table.

## 22. Persistent bind mount

`./backend/data:/app/backend/data` is a host bind mount, not a Docker-managed
volume — `backend/data/run.jsonl` (committed) and any seeded/edited
`servers.json`/`requests.csv` are directly visible and inspectable on the
host. Host bind-mounted files survive **both** `docker compose down` and
`docker compose down -v`: the `-v` flag removes named and anonymous Docker
volumes, and this project defines no named volume anywhere — `backend/data`
is a plain host directory, entirely outside what `-v` can affect. A container
restart, or a full `down`/`up` cycle either way, sees the same files it left
behind.

## 23. Mandatory vs. bonus boundary

**Implemented (mandatory):** simulation engine, default scheduling strategy,
server CRUD, simulation trigger, run summary, trace download, Docker Compose
deployment, determinism, atomic writes, both locks, seeding, restart-safe
summary reconstruction, persisted-trace validation.

**Not implemented (bonus, out of scope for this submission):** a metrics
endpoint or metrics UI beyond the mandatory summary fields, event/timeline
visualization, additional scheduling strategies, an auto-scaling module, and
a shared-CPU execution mode. None of these are referenced anywhere in the
running application — no dead UI stubs, no half-built routes.

## 24. Assumptions, trade-offs, and known limitations

- Single Uvicorn worker is a hard requirement of the current locking design,
  not a scalability choice — documented in §14–15 and the README.
- The validator's own gaps (e.g. no check that every arrived request
  resolves) are not relied upon anywhere; the engine's own termination
  invariant and the API's trace-validation layer are the actual guarantees.
- No database, no auth, no multi-node coordination — a JSON file behind
  `ServerRepository` fully covers the mandatory CRUD scope without the extra
  moving parts a database would add for zero benefit at this scale.
- Backend dependency versions use compatibility ceilings in `pyproject.toml`
  (e.g. `fastapi<1.0`, `pydantic<3.0`), not a fully deterministic lockfile —
  a deliberate, take-home-appropriate middle ground; the frontend's
  `package-lock.json` (consumed via `npm ci`) is the one fully deterministic
  dependency source in this repository.
