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

**Status:** Accepted — confirmed authoritative by Medsien Engineering (2026-08-21)

The default submitted mode allows at most one active request per server.

Runtime is:

```text
ceil(request.work_units / server.cpu_units_per_tick)
```

Finish tick is:

```text
start_tick + runtime
```

**Original reasoning (historical):** This is the model enforced by the unmodified provided validator and demonstrated by the sample trace. During planning, the assignment PDF's shared-CPU wording appeared to conflict with this validator-enforced model (`docs/SPEC.md` §5) — a server dividing CPU evenly across concurrent requests cannot also satisfy the validator's non-overlapping-interval check. The project adopted the serial, non-overlapping model as the working default pending clarification from Medsien, since it is the model the mandatory acceptance check (`validate_run.py`) actually enforces.

**Resolution (Medsien Engineering, 2026-08-21):** Medsien Engineering confirmed in writing that this serial, one-active-request-per-server model is the authoritative execution model for this case study — not a compromise held pending further review. Confirmed explicitly:

- `validate_run.py` is the authoritative correctness criterion for this case study.
- Each server processes at most one request at a time.
- A running request receives the server's full CPU capacity.
- Runtime remains `ceil_div(work_units, cpu_units_per_tick)`; same-server execution intervals must never overlap.
- The PDF's concurrency wording describes a more general system and is not the required model for this case study.
- The project's current validator-compatible default is exactly the intended implementation — no further change is required.

This decision is no longer pending. Shared-CPU execution remains unimplemented and out of scope (see D-011).

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

A shared-CPU execution mode would be a separate, optional experimental mode rather than another scheduling strategy. It remains unimplemented and is not required by the confirmed authoritative model (D-003).

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

## D-021: Bonus timeline visualization and shared queue-depth extraction (Day 3B-1)

**Status:** Accepted

Adds a pure `domain/timeline.py` (`compute_timeline`) exposed via
`GET /api/simulations/latest/timeline`: a deterministic, post-run-only
reconstruction of request lifecycles, per-server execution lanes, the raw
event feed, and queue depth over time, entirely from the already-validated
persisted `run.jsonl` trace plus the same optional verified `run_context.json`
snapshot D-020's metrics already use. Read-only: no filesystem/HTTP
dependency in the domain layer, and no new writes — Timeline never publishes
a trace, a context file, or any other artifact.

Two design choices distinguish it from D-020's `compute_metrics()`:

- The raw `events` field preserves the **exact persisted trace order**
  (each event carries a 0-based `sequence`, its literal position) rather
  than being re-sorted to any canonical order — a manually edited trace is
  shown in the order it is actually stored, not silently canonicalized. By
  contrast, `requests` (sorted `(arrival_tick, request_id)`, D-005's order),
  `servers`/lanes (sorted `server_id`), and each lane's `intervals` (sorted
  `(start_tick, request_id)`) **are** sorted, because that ordering is this
  API's own presentation decision, not a re-statement of the trace itself.
- Queue depth is extracted into a new shared `domain/queue_depth.py`
  (`compute_queue_depth`), used identically by both `compute_metrics()` and
  `compute_timeline()`, so the two can never disagree. It replaces the
  previous dense per-integer-tick loop with a sparse anchor-tick walk —
  bounded by the number of ticks with an actual arrival/start/drop delta,
  plus the two boundary ticks — instead of one entry per integer tick in
  `[start_tick, end_tick]`. This is behavior-preserving for the input
  contract this function is ever actually called with: non-empty,
  lifecycle-complete traces where every arrival is resolved to exactly one
  terminal event, exactly what `JsonlTraceWriter.deserialize()` already
  guarantees before either caller (`compute_metrics`, `compute_timeline`) is
  reached via the API. Under that guarantee, queue depth is always back to
  zero by `end_tick`, so the old dense loop's inclusive final sample and the
  new sparse interval-weighted sum agree exactly — an arbitrary sequence with
  an unresolved arrival is outside this contract and isn't a case either
  implementation needs to agree on. A direct dense-reference cross-check test
  (`test_queue_depth.py`) reproduces the old per-integer-tick loop
  independently and asserts exact equality on lifecycle-complete fixtures,
  and every pre-existing `test_metrics.py` assertion (including the canonical
  sample's `peak_queue_depth == 1`, `avg_queue_depth == 0.25`) stays green
  unmodified.

A new shared `services/trace_reader.py` (`read_current_run` /
`CurrentRunSnapshot`) extracts the "read trace bytes once, decode,
deserialize, verify context" sequence that `get_latest_metrics` already had
inlined — used by the refactored (behavior-preserving) `/latest/metrics` and
the new `/latest/timeline` route, so a third near-duplicate copy of that
sequence was never written.

The frontend `TimelinePanel` renders three coordinated SVG views sharing one
tick→pixel scale: a server-lane Gantt of running intervals; a per-request
lifecycle strip showing a diagonally-striped waiting segment
`[arrival,start)` and a solid running segment `[start,finish)` (a texture
distinction, not a color-only one) plus circle/triangle/square glyph markers
at the arrival/start/finish ticks and a distinct `×` for a dropped request;
and a queue-depth step chart with visible `0`/peak numeric scale labels. A
six-item static legend spells out Arrived/Started/Finished/Dropped/Waiting/
Running next to each glyph or swatch. Three always-present plain HTML tables
back this up: a filterable event list (by request ID, server, and event
type, in the API's own `sequence` order), an unconditional accessible
requests table that is the real source of truth for assistive technology
(not a hover-only supplement), and a semantic "Tick / Depth" table listing
every sparse `queue_depth` point — the same sparse representation as the
chart, never one row per integer tick. Every SVG has a **fixed intrinsic
viewBox width**, independent of the trace's largest tick — proportional
positioning within a bounded canvas, never `width = f(end_tick)` — a
`role="img"` with a data-derived `aria-label`, and both a `<title>` and a
`<desc>` explaining what that chart encodes, so a huge or sparse max tick
compresses features instead of growing the page and no chart's meaning
depends on a hover tooltip.

**Reasoning:** SPEC §10 lists an event/server timeline and queue-length
history as a bonus. A post-run-only reconstruction from the already-published
trace keeps this consistent with D-010/D-018's atomic-publish-then-read
model — no WebSockets, no live tick streaming, no second persisted artifact.
Reusing `compute_queue_depth` rather than writing a second inline
implementation removes the only realistic way Metrics and Timeline could
ever silently disagree about queue depth. This is a bonus feature only: it
does not change simulation correctness, the canonical `run.jsonl`, any
existing endpoint's contract, or any mandatory behavior. Shared-CPU execution
remains unimplemented and is not required by it (D-003/D-011).

## D-022: Auto-scaling recommendation policy (Day 3B-2)

**Status:** Accepted

Adds a pure `domain/autoscale.py` (`decide_scaling`) exposed via
`GET /api/simulations/latest/autoscaling`: a deterministic, first-match-wins
policy over the already-computed `ClusterMetrics` (D-020/§26), recommending
exactly one of `scale_up`, `scale_down`, or `no_change` — or an explicitly
distinct **unavailable** state when there isn't enough trustworthy evidence
to decide at all. It is advisory only: it never mutates `servers.json`, the
trace, or `run_context.json`, never calls server CRUD, and never triggers a
run. Applying any suggested change remains a manual, future-run edit through
the existing server-CRUD surface (D-009).

**Available vs. unavailable, not "no_change" as a stand-in for either.**
`no_change` means the policy had sufficient information (a real trace and a
verified server snapshot) and concluded capacity should stay as-is.
*Unavailable* means the policy lacks that information entirely — either no
requests were observed (`insufficient_data`) or the configured-server context
is missing, pending, malformed, or hash-mismatched (`context_unavailable`).
Conflating the two would misrepresent "we don't know" as a real decision;
the response carries a separate `recommendation_available` boolean precisely
so the two can never be confused, and the frontend renders a distinctly
labeled "Recommendation unavailable" state rather than ever falling back to
a "No change" badge.

**Precedence — exact order, first match wins:**

1. `total_requests == 0` → unavailable, `insufficient_data`.
2. `configured_server_count is None` → unavailable, `context_unavailable`.
   This is checked **before** the drop rule — a deliberate, non-obvious
   choice: a trace with real drops but no verified context still reports
   unavailable, never a fabricated `scale_up`, because the alternative would
   mean the drop signal alone can bypass the same trust requirement every
   other signal in this policy is held to.
3. `dropped_rate > 0` → `scale_up` (delta `+1`, `dropped_requests`). In this
   engine, a drop only ever happens when a request could *never* run on any
   configured server (D-004) — a strong, self-contained signal. The
   explanation deliberately does not claim an identical additional server is
   guaranteed to fix it, since the real cause may be an incompatible
   capacity profile (e.g. no server has enough memory), not merely an
   insufficient count.
4. `peak_queue_depth >= configured_server_count` **and**
   `avg_cluster_busy_ratio >= 0.80` (both required) → `scale_up` (delta
   `+1`, `["high_queue_pressure", "high_occupancy"]`). Neither signal alone
   is sufficient — the canonical sample is high-occupancy (`0.875`) but
   never queue-constrained (`peak_queue_depth(1) < configured_server_count
   (2)`), and correctly resolves to `no_change`, not `scale_up`: efficiently
   busy servers are not by themselves evidence that more capacity is needed.
5. Zero drops, zero queue, low occupancy (`< 0.20`), more than one
   configured server, and a non-empty idle-server list → `scale_down` (delta
   `-1`, `low_occupancy_idle_capacity`), naming the idle server ids —
   **sorted ascending by `decide_scaling` itself**, never trusted from
   whatever order the `run_context.json` snapshot happens to preserve — as
   removal candidates, with the explanation stating the user should choose
   at most one and that nothing is ever applied automatically.
6. The same zero-drop/zero-queue/low-occupancy shape at exactly the minimum
   server count (`1`) → `no_change` (`minimum_server_count`), deliberately
   **not** requiring a non-empty idle list the way rule 5 does — at the
   minimum count, "idle" is meaningless, since a lone server that ran every
   non-dropped request (the only way `dropped_rate` stays `0` with one
   server) can never itself be idle; requiring it would make this branch
   permanently unreachable.
7. Otherwise → `no_change` (`steady_state`).

**Thresholds (`HIGH_BUSY_RATIO = 0.80`, `LOW_BUSY_RATIO = 0.20`,
`MIN_SERVER_COUNT = 1`)** are documented everywhere (schema, module
docstring, README, this entry) as simple, explainable, uncalibrated
heuristic defaults for this case study — never as industry-standard,
production-calibrated, or empirically derived values, since none of that
evidence exists for a take-home case study.

**Two policy shapes were considered.** A weighted composite score (summing
normalized drop-rate/queue-ratio/occupancy signals into one scalar and
thresholding the scalar) was rejected: the weights themselves would be just
as uncalibrated as the current thresholds but far less explainable ("why
0.4 and not 0.6") and far harder to test exhaustively (multi-variable
boundaries instead of single-condition ones). The accepted layered
precedence keeps every rule a single, independently justifiable condition,
each with its own isolated boundary test.

**Reasoning:** SPEC §10 names CPU, queue length, and error rate as
auto-scaling decision inputs; D-020 already computes trace-only and
context-enriched versions of exactly those three signals (`dropped_rate` as
the error-pressure proxy, queue depth, `avg_cluster_busy_ratio` as the
CPU-pressure proxy). This decision reuses them directly rather than
recomputing anything, and keeps the module a pure function over already-
validated data — no filesystem, HTTP, repository, environment, or clock
access — so it is exhaustively unit-testable and independently explainable,
matching D-002's engine-purity precedent and D-012's original scope framing
("analyzes completed-run metrics and recommends... applying a recommendation
changes future server configuration").

## Open questions

- Should uploaded request CSV files be retained, or is in-memory use sufficient? (Moot for the mandatory scope — there is no CSV-upload UI; `requests.csv` is seeded once per D-014 and has no CRUD surface.)

This remaining question does not affect the mandatory submission: it concerns a bonus-adjacent, not-yet-built feature (CSV upload), not any implemented or required behavior.

## Resolved questions

- **Original question 1:** ~~Will Medsien evaluate with the supplied serial validator or an updated shared-CPU validator?~~ Resolved 2026-08-21: Medsien Engineering confirmed in writing that the supplied serial `validate_run.py` is the authoritative correctness criterion for this case study, and that the current validator-compatible implementation is exactly the intended solution. See D-003.
- **Original question 3:** ~~Is `docker compose up` expected to generate a sample run automatically, or is a dashboard/API trigger sufficient?~~ Resolved by D-014: startup seeds configuration/request data only, and never auto-runs a simulation. A run is always dashboard/API-triggered.
