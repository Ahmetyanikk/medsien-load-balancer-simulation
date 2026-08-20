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

`GET /api/simulations/latest` validates and summarizes the persisted trace: it reads `run.jsonl` from disk on every call and reconstructs the summary via `JsonlTraceWriter.deserialize()` + `domain.summary.summarize()` — no sidecar summary file, no in-memory cache as source of truth. `GET /api/simulations/latest/download` does not do this — it only checks that the file exists, then streams the raw persisted bytes as-is; it never deserializes, validates, or recomputes anything. Both 404 only when the configured `run_jsonl_path` doesn't exist.

An **application-published** trace is always complete and valid: `SimulationService` only ever replaces `run.jsonl` after a fully successful run, via atomic `os.replace()` (D-010, unchanged), so there is no "in-progress" or partially-written state an application-generated file can ever be caught in.

That guarantee covers only what this application itself writes. **Presence of a file at `run_jsonl_path` does not by itself mean the file is valid** — it could be manually edited, corrupted on disk, or replaced out-of-band. `deserialize()` therefore performs explicit schema validation (every line: JSON object, correctly-typed `t`/`request_id`/`event`, `server_id` required and non-empty for `STARTED`/`FINISHED`) and lifecycle validation (no duplicate/out-of-order/contradictory events, every arrival resolved to exactly one terminal event, `FINISHED` server matches `STARTED` server, finish tick after start tick) before any summary is computed. A file that fails either check — including an empty or blank-only one — is rejected with `CorruptTraceError`, mapped to a controlled HTTP 500 with a JSON body, never a leaked traceback. This validation is specific to `GET /latest`: a corrupted file still downloads successfully (200, raw bytes) via `GET /latest/download`, which performs no validation at all — by design, since it exists to expose exactly what's on disk for evaluator inspection, not a validated view of it.

**Reasoning:** Survives process restarts and works identically whether the trace was produced by this process or a prior one, without adding a second persisted artifact that could drift out of sync with the trace itself. The added validation closes the gap between "this application never writes an invalid trace" and "any file that happens to exist at this path is safe to trust" — those are not the same claim.

## D-019: Bonus second scheduling strategy and explicit registry (Day 3A)

**Status:** Accepted

Adds `lowest_id` alongside the existing default `fastest_finish` (D-006,
unrenamed): among the engine-computed eligible-server set for a request,
pick the server with the lexicographically smallest id, ignoring predicted
runtime entirely. Both strategies are resolved through an explicit
`STRATEGY_REGISTRY: dict[str, SchedulingStrategy]` in `domain/strategies.py`
— the **only** source of truth for which strategy ids are valid; there is no
second hard-coded list anywhere. `get_strategy(name)` raises
`UnknownStrategyError` for any unregistered id — it never silently falls
back to the default. `POST /api/simulations/run` exposes this as an
optional `?strategy=` query parameter, typed as a plain `str` (default
`DEFAULT_STRATEGY_NAME`) — **not** a `Literal`-typed enum — resolved
exclusively through `get_strategy()`; the route itself catches
`UnknownStrategyError` and converts it to a controlled 422 JSON response at
the HTTP boundary, rather than letting it fall through to the generic
`DomainError` → 500 handler (an unrecognized user-supplied id is ordinary
bad request input, not an unreachable-state failure). Adding a future
registered strategy requires touching only `STRATEGY_REGISTRY` — no second
query-parameter allowlist to keep in sync with it.
`GET /api/simulations/strategies` is generated by iterating the same
registry, returning both ids with a display label and which one is the
default, so the frontend never hardcodes scheduling knowledge itself
(`docs/ARCHITECTURE.md` §25).

**Reasoning:** D-011 anticipated this ("first bonus strategies should remain
compatible with the provided validator") without picking one; `lowest_id` is
the simplest strategy that (a) is trivially validator-compatible for the
same structural reason the default is — `SimulationEngine` itself is
completely unchanged, only a new `SchedulingStrategy.select_server`
implementation was added — and (b) reliably produces a *different*
scheduling outcome than the default on ordinary inputs (fast-but-high-id vs.
slow-but-low-id server), making it a genuinely interchangeable, observably
distinct strategy rather than a relabeled duplicate of D-006.

## D-020: Bonus metrics and the `run_context.json` pending/complete publication lifecycle (Day 3A)

**Status:** Accepted

Adds a pure `domain/metrics.py` (`compute_metrics`) exposed via
`GET /api/simulations/latest/metrics`, and a versioned, two-status
`run_context.json` sidecar (`services/run_context.py`) that lets metrics be
enriched with configured-server context (idle servers, per-server
`cpu_units_per_tick`, cluster-wide busy ratio, which strategy actually ran)
without ever risking a mismatched or stale enrichment. Full formulas, the
exact publication sequence, and failure semantics are in
`docs/ARCHITECTURE.md` §26–27; this entry records the decision and why the
schema is shaped the way it is.

An earlier, simpler design (hash-only: trust `run_context.json` whenever its
`trace_sha256` matches the current trace) was considered and rejected before
implementation: two different runs can produce **byte-identical**
`run.jsonl` bytes from **different** server snapshots — e.g. a run that adds
a server which never ends up hosting any request. Hash-matching alone
cannot detect that mismatch. The accepted design instead publishes a
`pending` marker that **unconditionally invalidates any previous `complete`
context before the new trace is even published**, then republishes
`complete` only as a best-effort final step after the trace itself has
already succeeded. This closes the gap structurally — there is no
sequencing in which a stale `complete` context can survive to be read back
against a new trace it doesn't describe — rather than by trying to make the
hash check itself smarter.

`busy_time_ratio`/`avg_cluster_busy_ratio` are documented and labeled
everywhere (schema, client types, UI, docs) as an **occupancy/CPU-pressure
proxy, not literal CPU utilization** — a request's final tick can consume
less than a full `cpu_units_per_tick` when `work_units` isn't an exact
multiple of it, which this metric cannot see.

`ServerMetrics.work_units_total` is always `null`: the context snapshot
deliberately stores only servers, not the original per-request
`work_units`, and that value is not exactly recoverable from
`(busy_ticks, cpu_units_per_tick)` alone (`ceil_div` is lossy). Populating it
for real would require a request snapshot too, which this decision
deliberately does not add — `run_context.json` stays scoped to what the
identical-trace/different-snapshot protection above actually needs.

`run_context.json` is git-ignored (`backend/.gitignore`); `run.jsonl` itself
is unaffected and remains tracked, unignored, and the sole mandatory
deliverable trace. `run_context.json` publication is **not** uniformly
best-effort, though — the two writes have different failure semantics:

- The `pending`-marker write (before the new trace is published) is a
  **mandatory safety prerequisite**: if it fails, `.run()` aborts before
  publishing any new trace at all, `RunContextPublicationError` propagates
  as a controlled 500, and the previous `run.jsonl` is left untouched.
- The final `complete`-context write (after the trace has already been
  published successfully) is the **only** best-effort step: a failure there
  is logged and swallowed, never surfaced as a failed run — `POST /run`
  still returns 200, and the metrics endpoint degrades to
  `context_available: false` with trace-only fields still populated.

**Reasoning:** D-010 already established atomic-replace-only publication for
`run.jsonl`; this extends the same atomicity discipline to a second
artifact while explicitly solving the one correctness gap a naive
hash-based version of it would have had, without weakening any mandatory
guarantee (D-009/D-010/D-016 are otherwise unchanged). Both
`run_context.json` writes happen inside the same non-blocking-locked
`.run()` call, but at different points in the sequence: the `pending` write
happens **before** the mandatory trace publish (and can abort it), while the
`complete` write happens **after** the mandatory trace publish has already
succeeded (and can never retroactively undo that success).

## Open questions

1. Will Medsien evaluate with the supplied serial validator or an updated shared-CPU validator?
2. Should uploaded request CSV files be retained, or is in-memory use sufficient? (Moot for the mandatory scope — there is no CSV-upload UI; `requests.csv` is seeded once per D-014 and has no CRUD surface.)
3. ~~Is `docker compose up` expected to generate a sample run automatically, or is a dashboard/API trigger sufficient?~~ Resolved by D-014: startup seeds configuration/request data only, and never auto-runs a simulation. A run is always dashboard/API-triggered.

Until clarified, use the simplest behavior that satisfies the PDF and unmodified validator without expanding scope.
