# Architecture and Behavior Decisions

This document records approved decisions. Claude Code must propose changes here before changing observable behavior.

## D-001: Technology stack

**Status:** Accepted

- Backend: Python and FastAPI
- Simulation tests: Pytest
- Frontend: React, TypeScript, and Vite
- Server configuration persistence: JSON file behind a repository interface
- Container orchestration: Docker Compose

**Reasoning:** This stack matches the candidate's experience, minimizes setup time, and keeps the three-day scope realistic. A separate database is unnecessary for the required CRUD and simulation behavior.

## D-002: Pure simulation domain

**Status:** Accepted

The simulation engine will have no FastAPI, HTTP, React, or filesystem-persistence dependency. Parsers and writers may be adapters around the domain.

**Reasoning:** The engine can be unit tested directly and discussed independently during the interview.

## D-003: Validator-compatible default execution

**Status:** Accepted pending any clarification from Medsien

The default submitted mode allows at most one active request per server.

Runtime is:

```text
ceil(request.work_units / server.cpu_units_per_tick)
```

Finish tick is:

```text
start_tick + runtime
```

**Reasoning:** This is the model enforced by the unmodified provided validator and demonstrated by the sample trace.

## D-004: Queue and drop policy

**Status:** Accepted

- A request that could run on at least one configured server waits when all eligible servers are temporarily unavailable.
- A request that can never start on any configured server is dropped.
- Zero-rate servers are not start-capable.
- The simulator must detect a no-future-progress state and terminate deterministically.

The JSONL trace will use only the required event fields unless an extension is explicitly approved.

## D-005: Request ordering

**Status:** Accepted

Waiting requests are considered in this deterministic order:

```text
(arrival_tick, request_id)
```

A later request may be considered if an earlier request cannot use any currently available server but remains runnable on a busy server. This avoids unnecessary idle capacity while preserving deterministic ordering.

This bypass behavior must be covered by a test and documented as a trade-off.

## D-006: Default server selection

**Status:** Accepted

For each request, filter to servers that:

- Are idle in validator-compatible mode
- Have sufficient memory
- Have positive CPU capacity
- Have remaining start-rate capacity for the current tick

Choose the minimum score:

```text
(ceil(work_units / cpu_units_per_tick), server_id)
```

This chooses the fastest eligible server, then resolves equal runtimes by server ID.

## D-007: Tick processing and event ordering

**Status:** Accepted

At tick `t`:

1. Finish work whose execution interval ends at `t`; release capacity.
2. Register requests arriving at `t`.
3. Drop newly arrived requests that can never run.
4. Schedule waiting requests using the approved strategy.
5. Advance to the next tick that can change state.

Canonical event emission order within each phase is deterministic:

- Finishes: `(server_id, request_id)`
- Arrivals: `request_id`
- Drops: `request_id`
- Starts: scheduling order, with deterministic request and server selection

The exact event order need not copy the hand-written sample trace; it must be documented, deterministic, lifecycle-correct, and validator-compatible.

## D-008: Stable JSONL serialization

**Status:** Accepted

JSON objects use stable field insertion order:

```text
t, event, request_id, server_id
```

`server_id` is omitted when it does not apply. Serialization uses stable separators and UTF-8 with one newline per event. Blank lines are not emitted.

## D-009: Configuration snapshots and writes

**Status:** Accepted

- Server CRUD writes configuration atomically.
- A simulation snapshots server configuration and request input at run start.
- Dashboard changes during a run affect only future runs.
- Concurrent run requests must not interleave writes to the same `run.jsonl`.

A simple process-level lock is sufficient for the take-home scope.

## D-010: Output replacement

**Status:** Accepted

The latest successful simulation deterministically overwrites `run.jsonl` using a temporary file and atomic replacement. Metrics are published only with the corresponding completed trace.

## D-011: Bonus scheduling strategies

**Status:** Accepted after mandatory completion

Use a strategy interface. The first bonus strategies should remain compatible with the provided validator, for example:

- Shortest predicted processing time
- Round robin

A shared-CPU concurrency strategy is a separate experimental mode and cannot become the default without validator clarification.

## D-012: Auto-scaling scope

**Status:** Accepted after mandatory completion

The initial auto-scaling module analyzes completed-run metrics and produces transparent recommendations for the next run. Applying a recommendation changes future server configuration.

**Reasoning:** Mid-run capacity changes would make the static provided validator unable to reproduce finish times reliably.

## D-013: Repository layout

**Status:** Accepted

Standardized copies of the Medsien-supplied fixtures live under `provided/` (`assignment.pdf`, `servers.json`, `requests.csv`, `run.jsonl`, `validate_run.py`). The originals are retained untouched; `provided/` is a copy, never a move.

**Reasoning:** Matches `CLAUDE.md`/`START_HERE.md`'s documented source-of-truth paths without ever mutating the files Medsien supplied.

## D-014: Runtime seeding

**Status:** Accepted

On FastAPI startup (`lifespan`), `seed_if_missing()` copies exactly `servers.json` and `requests.csv` from `provided/` into the runtime data directory, only when the destination file doesn't already exist. It never touches `run.jsonl`, `assignment.pdf`, or `validate_run.py`, never overwrites an existing destination file (including a dashboard-driven empty `servers.json`), and never triggers a simulation run. A missing source file is a controlled startup failure (`SeedSourceMissingError`), not a silent no-op.

**Reasoning:** `requests.csv` has no CRUD UI in mandatory scope, so it needs a fixed runtime location; `servers.json` needs an initial value on first boot. Copy-if-missing keeps dashboard edits (including "delete all servers") durable across restarts. Resolves open question 3 below.

## D-015: CRUD repository locking

**Status:** Accepted

`ServerRepository` uses a `threading.RLock`. Every write path — `save()`, `create()`, `update()`, `delete()` — acquires the lock for its entire read-modify-write cycle via private `_load_unlocked`/`_save_unlocked` helpers; no public method writes without going through it. `load()` stays lock-free by design: `os.replace()` already guarantees a reader never observes a torn file, so plain reads don't need to serialize against writers.

**Reasoning:** A read-modify-write sequence (load current list, check duplicate, append, save) is not atomic just because the final `save()` is — two concurrent `create()` calls could both read the same pre-mutation snapshot and the second `save()` would silently discard the first's addition. The lock closes that lost-update window. Single-process assumption only (see D-016's `--workers 1` note, which applies identically here).

## D-016: Simulation run locking

**Status:** Accepted

`SimulationService` holds a `threading.Lock`, acquired non-blocking (`acquire(blocking=False)`) at the top of `.run()`, released in `finally`. A second concurrent call while one is in flight raises `SimulationAlreadyRunningError`, mapped to HTTP 409. This only serializes anything because the API resolves to **one shared `SimulationService` instance** (`app.state.simulation_service`), not a new instance per request. Valid only under a single Uvicorn worker (`--workers 1`) — a process-local lock cannot coordinate across worker processes; this is a known, documented take-home-scope limitation, not solved here.

**Reasoning:** Prevents two concurrently triggered runs from interleaving writes to the same `run.jsonl`, per the original concurrent-run-protection requirement.

## D-017: PUT replacement and immutable server IDs

**Status:** Accepted

`PUT /api/servers/{server_id}` is a full replacement of the three mutable fields (`cpu_units_per_tick`, `mem_mb`, `rate_limit_per_sec`); no partial-patch semantics. The request body schema has no `id` field at all — the path parameter is the sole identity — and uses `extra="forbid"`, so sending `id` in the body is a structural 422, not a policy check.

**Reasoning:** Simplest REST-consistent choice for this scope; server IDs are identity, never mutated, matching how the domain model and every downstream reference (running-request records, event traces) treat them.

## D-018: Restart-safe `GET /api/simulations/latest`

**Status:** Accepted (amended)

`GET /api/simulations/latest` and `.../download` are stateless: they read the persisted `run.jsonl` from disk and reconstruct the summary via `JsonlTraceWriter.deserialize()` + `domain.summary.summarize()` on every call. No sidecar summary file, no in-memory cache as source of truth. 404 only when the configured `run_jsonl_path` doesn't exist.

An **application-published** trace is always complete and valid: `SimulationService` only ever replaces `run.jsonl` after a fully successful run, via atomic `os.replace()` (D-010, unchanged), so there is no "in-progress" or partially-written state an application-generated file can ever be caught in.

That guarantee covers only what this application itself writes. **Presence of a file at `run_jsonl_path` does not by itself mean the file is valid** — it could be manually edited, corrupted on disk, or replaced out-of-band. `deserialize()` therefore performs explicit schema validation (every line: JSON object, correctly-typed `t`/`request_id`/`event`, `server_id` required and non-empty for `STARTED`/`FINISHED`) and lifecycle validation (no duplicate/out-of-order/contradictory events, every arrival resolved to exactly one terminal event, `FINISHED` server matches `STARTED` server, finish tick after start tick) before any summary is computed. A file that fails either check — including an empty or blank-only one — is rejected with `CorruptTraceError`, mapped to a controlled HTTP 500 with a JSON body, never a leaked traceback.

**Reasoning:** Survives process restarts and works identically whether the trace was produced by this process or a prior one, without adding a second persisted artifact that could drift out of sync with the trace itself. The added validation closes the gap between "this application never writes an invalid trace" and "any file that happens to exist at this path is safe to trust" — those are not the same claim.

## Open questions

1. Will Medsien evaluate with the supplied serial validator or an updated shared-CPU validator?
2. Should uploaded request CSV files be retained, or is in-memory use sufficient? (Moot for the mandatory scope — there is no CSV-upload UI; `requests.csv` is seeded once per D-014 and has no CRUD surface.)
3. ~~Is `docker compose up` expected to generate a sample run automatically, or is a dashboard/API trigger sufficient?~~ Resolved by D-014: startup seeds configuration/request data only, and never auto-runs a simulation. A run is always dashboard/API-triggered.

Until clarified, use the simplest behavior that satisfies the PDF and unmodified validator without expanding scope.
