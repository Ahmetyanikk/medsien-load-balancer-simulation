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
contains scheduling logic itself. Day 3A's additions fit this same shape
without changing the direction: `domain/metrics.py` is pure domain code
(§26), `services/run_context.py` is I/O owned by the services layer
alongside `SimulationService` (§27), and `domain/strategies.py`'s registry
(§25) is pure domain code the API layer resolves a query-parameter string
through, exactly like every other domain type the API already imports.

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

`App` owns one piece of cross-panel shared state: a monotonic `runVersion`
counter, bumped after *any* successful run regardless of which panel
triggered it. `ServerList` remains fully independent of it (server CRUD is
unrelated to simulation runs). `RunPanel` and `MetricsPanel` both take
`runVersion` as a prop and refetch (`GET /latest`, `GET /latest/metrics`
respectively) whenever it changes, via a `useEffect` that lists it as a
dependency — this single dependency-array entry covers both the initial
mount fetch and every later cross-panel refresh, with no separate mount-only
effect needed. `RunPanel` and `StrategySelector` are the two panels that can
*produce* a new `runVersion`: each calls the `onRunCompleted` callback App
passes down exactly once a `POST /run` it triggered actually succeeds (never
on a failed run, so a preserved-previous-summary or preserved-previous-error
display is never spuriously invalidated).

`ServerList` owns the fetched list, which of at most one row is being
edited, a single `mutating` flag gating every Add/Edit/Delete control while
any mutation is in flight, and separate error state for form (create/edit)
vs. delete failures; it re-fetches from the backend after every successful
mutation rather than optimistically updating, and never sorts the response.
`ServerForm` is presentational plus local validation only — it emits
validated values via `onSubmit`; the actual API call lives in `ServerList`.
`RunPanel` owns the latest-run state (loading/none/error/ready, with 404
treated as the normal "none" case, not an error) and its own in-flight run
flag; a failed run preserves the last successful summary rather than
clearing it, mirroring the backend's own atomic-publish guarantee.
`StrategySelector` (bonus, §25) owns the fetched strategy list, the selected
strategy id (defaulted to whichever entry the backend marks `default: true`
— never a hardcoded id in the frontend), and its own in-flight/error state;
it never runs a simulation implicitly, only on an explicit click.
`MetricsPanel` (bonus, §26) owns the fetched metrics response and renders
trace-only values unconditionally — including the per-server table
(`server_id`, `requests_handled`, `busy_ticks`, `busy_time_ratio`), which
the API always returns regardless of `context_available` and the panel
always renders whenever `metrics.servers` is non-empty. Only the
context-only fields (`strategy_used`, `configured_server_count`,
`idle_configured_server_ids`, per-server `cpu_units_per_tick`,
`avg_cluster_busy_ratio`) are withheld and replaced with an explicit note
when `context_available: false` — the panel never hides trace-derived
detail just because context is unavailable, and never fabricates a
context-only value either.

Every one of `ServerList`, `RunPanel`, `StrategySelector`, and `MetricsPanel`
protects its async effects with its own monotonic generation-token ref, so a
stale response — from a superseded React StrictMode double-invocation, or
simply an older request that happens to resolve after a newer one — can
never overwrite fresher state; the token is also bumped on effect cleanup so
an in-flight request from an unmounted instance can't apply itself either.
`api/client.ts` normalizes both response shapes the backend can return on
error (`{"detail": "<string>"}` from custom handlers, `{"detail": [...]}`
from FastAPI's own 422 validation) into one string before any component ever
sees it. The frontend never recomputes a metric or re-derives scheduling
behavior — every number and every strategy id/label shown is rendered
exactly as the backend returned it, with `null` values displayed as `N/A`.

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

**Implemented (bonus, Day 3A — §25–27):** a second, validator-compatible
scheduling strategy (`lowest_id`) selectable via `?strategy=` on `POST /run`
and a `GET /strategies` registry endpoint; a pure trace-derived and
context-enriched performance-metrics module exposed via
`GET /latest/metrics`; the `run_context.json` pending/complete publication
lifecycle that safely enables the context-enriched metrics without ever
risking a stale or mismatched context being trusted.

**Not implemented (bonus, out of scope for this submission):**
event/timeline visualization, an auto-scaling module, and a shared-CPU
execution mode. None of these are referenced anywhere in the running
application — no dead UI stubs, no half-built routes.

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
- `ServerMetrics.work_units_total` (§26) is always `null`. The
  `run_context.json` snapshot deliberately stores only servers, not the
  original per-request `work_units` — and that value cannot be exactly
  recovered from `(busy_ticks, cpu_units_per_tick)` alone, since
  `ceil(work_units / cpu_units_per_tick)` is lossy for any request whose
  runtime wasn't an exact multiple of its server's `cpu_units_per_tick`.
  Populating this field for real would require snapshotting requests too,
  which was deliberately deferred out of Day 3A scope.
- `run_context.json` is git-ignored, non-durable runtime metadata, but it is
  **not** universally best-effort: the `pending`-marker write (step 4, §27)
  is a mandatory safety prerequisite — if it fails, the run aborts before a
  new trace is even published and `POST /run` returns a controlled 500. Only
  the *final* `complete`-context write (step 6, after the trace has already
  been published successfully) is best-effort; a failure there is logged and
  swallowed, and `POST /run` still returns 200. A fresh clone (or a fresh
  volume with only the committed sample `run.jsonl`) has no
  `run_context.json` at all, so `GET /latest/metrics` correctly reports
  `context_available: false` — with trace-only fields still populated —
  until the next successful run.

## 25. Bonus: scheduling strategy registry (Day 3A)

`domain/strategies.py` defines an explicit `STRATEGY_REGISTRY: dict[str,
SchedulingStrategy]` (insertion-ordered, `fastest_finish` then `lowest_id`)
mapping a stable string id to a stateless strategy instance, each carrying
its own `name` and display `label` as class attributes, plus
`get_strategy(name)` which raises `UnknownStrategyError` for any id not in
the registry — **it never silently falls back to the default.**
`STRATEGY_REGISTRY` is the registry's **only** source of truth for valid
strategy ids; there is no second hard-coded list anywhere. Both routes that
deal with a strategy id resolve it exclusively through `get_strategy()`:

- `POST /api/simulations/run` takes `strategy` as a plain `str` query
  parameter (default `DEFAULT_STRATEGY_NAME`) — **not** a `Literal`-typed
  enum of hard-coded ids. The route calls `get_strategy(strategy)` and
  catches `UnknownStrategyError` itself, converting it to a controlled 422
  JSON response (`{"detail": "..."}`) at the HTTP boundary — deliberately
  *not* left to fall through to the generic `DomainError` → 500 handler,
  since an unrecognized user-supplied id is ordinary bad request input
  (422), not an unreachable-state failure (500). Adding a new registered
  strategy therefore requires touching only `STRATEGY_REGISTRY` — no second
  query-parameter allowlist to keep in sync.
- `GET /api/simulations/strategies` is generated by iterating
  `STRATEGY_REGISTRY.items()` directly — id and label come from the
  registry entry, `default` is computed as `strategy_id ==
  DEFAULT_STRATEGY_NAME`.

- `fastest_finish` (`FastestFitStrategy`, default) — unchanged from the
  mandatory scope (§9): `min(ceil(work_units / cpu_units_per_tick),
  server_id)` among eligible servers.
- `lowest_id` (`LowestIdStrategy`) — `min(server_id)` among eligible
  servers, ignoring predicted runtime entirely.

Both strategies receive the identical, engine-computed `eligible` set (idle,
sufficient memory, `start_capable`) — a strategy only decides *which* of
those already-eligible servers wins; it never re-derives eligibility itself.
This means `lowest_id` obeys every memory/rate-limit/idle rule the default
does and remains validator-compatible for the same reason the default is:
`SimulationEngine` itself is completely unmodified (§2) — only a new
`SchedulingStrategy` implementation and API-level wiring were added.
`POST /api/simulations/run` with no `strategy` query parameter is
byte-identical to before Day 3A (proven by a dedicated determinism test) —
strategy selection is strictly additive.

## 26. Bonus: performance metrics (Day 3A)

`domain/metrics.py` exposes a pure `compute_metrics(events, verified_servers=None)
-> (ClusterMetrics, tuple[ServerMetrics, ...])` — no filesystem or HTTP
access, consistent with the engine's own purity boundary (§2). It is called
from `GET /api/simulations/latest/metrics` after the persisted trace has
already gone through the same `JsonlTraceWriter.deserialize()` schema and
lifecycle validation `GET /latest` uses (§18) — metrics are never computed
from an unvalidated trace.

**Trace-only fields** (always available, independent of `run_context.json`):
`total_requests`, `started`, `finished`, `dropped`, `dropped_rate`,
`duration_ticks`, `throughput_requests_per_tick`, `peak_queue_depth`,
`avg_queue_depth`, and per-server `requests_handled`/`busy_ticks`/
`busy_time_ratio` (server ids in this mode are whatever ids the trace itself
mentions — there is no way to know about a configured-but-unused server
without the context snapshot).

**Queue depth**, reconstructed purely from event counts, at every integer
tick `t` in the inclusive range `[first event tick, last event tick]`:
`depth = previous_depth + ARRIVED(t) - STARTED(t) - DROPPED(t)`, with a tick
that has no events simply carrying the previous depth forward (every
per-tick counter defaults to 0). This running depth is never clamped at
zero: if it ever goes negative, that means the supplied event stream itself
is inconsistent (e.g. a `STARTED` counted with no corresponding `ARRIVED`),
so `compute_metrics()` raises `CorruptTraceError` (with the offending tick
and computed depth) instead of silently producing a misleadingly "valid"
metric from bad input — the same error `GET /latest`'s trace deserialization
already uses (§18), for the same reason: a controlled 500, never a leaked
traceback or a fabricated number. `avg_queue_depth` divides
the sum of these per-tick depths by `duration_ticks` — elapsed time, not the
number of samples — since the sample at the final tick represents an
instant, not an additional tick of elapsed duration. `duration_ticks =
last_event_tick - first_event_tick`; when that's `0` (all observed events
fall on one tick), `avg_queue_depth` and `throughput_requests_per_tick` are
both `null` rather than a division by zero.

For the provided sample trace: `duration_ticks = 4`,
`throughput_requests_per_tick = 1.0`, `peak_queue_depth = 1`,
`avg_queue_depth = 0.25`, `s1.busy_ticks = 4`, `s2.busy_ticks = 3` — asserted
exactly in `tests/test_metrics.py`.

**`busy_time_ratio` / `avg_cluster_busy_ratio` terminology:** these are an
**occupancy / CPU-pressure proxy, not literal CPU utilization** — a
request's final tick can consume less than a full `cpu_units_per_tick` when
`work_units` isn't an exact multiple of it, and this metric has no way to
see that. This wording is used consistently in the Pydantic schema field
descriptions, the TypeScript client types, the `MetricsPanel` UI copy, and
here.

**Context-enriched fields** (only when `run_context.json` verifies against
the current trace — §27): `configured_server_count`,
`idle_configured_server_ids` (configured servers with zero handled
requests — impossible to know without the snapshot), per-server
`cpu_units_per_tick`, `avg_cluster_busy_ratio` (`Σ busy_ticks / (server_count
× duration_ticks)`), and `strategy_used`. When context is unavailable,
malformed, still-pending, or doesn't match the current trace, the response
sets `context_available: false` and every context-enriched field to `null`
— it never fabricates an idle-server list or a strategy name, and it never
fails the request; trace-only fields remain fully populated either way.

## 27. Bonus: `run_context.json` pending/complete publication lifecycle (Day 3A)

An earlier, simpler design considered publishing `run_context.json` as a
single atomic write containing the trace hash and server snapshot, trusted
whenever its `trace_sha256` matched the current `run.jsonl`. That design has
a real gap: two different runs can produce **byte-identical** `run.jsonl`
trace bytes from **different** server snapshots — for example, a run that
adds a server which never ends up hosting any request changes the
snapshot without changing a single event in the trace. Hash-matching alone
cannot distinguish that from the snapshot the hash was actually generated
from, so `services/run_context.py` instead uses a **versioned, two-status
schema**:

```json
{"schema_version": 1, "status": "pending"}
```
```json
{
  "schema_version": 1,
  "status": "complete",
  "trace_sha256": "<sha256 of the exact published run.jsonl bytes>",
  "strategy": "fastest_finish",
  "servers": [{"id": "s1", "cpu_units_per_tick": 10, "mem_mb": 1024, "rate_limit_per_sec": 2}]
}
```

`SimulationService.run()` (when called with a `context_path`, which the real
API route always supplies — every pre-Day-3A test/caller that omits it gets
byte-for-byte the same behavior as before, with `run_context.json` never
touched at all) follows this sequence:

1. Load and snapshot `servers.json`/`requests.csv`.
2. Run the pure engine (unchanged, §2).
3. Serialize the final trace bytes (unchanged writer, §10).
4. **Atomically replace `run_context.json` with the `pending` marker** —
   *before* the new trace is published. This unconditionally invalidates
   any previous `complete` context first, so a stale context can never
   survive to (mis)describe a new trace it doesn't match, even one with an
   identical hash. If this write fails, the run aborts here:
   `RunContextPublicationError` propagates as a controlled 500, no new
   trace is published, and the previous `run.jsonl` is untouched.
5. Atomically publish the new `run.jsonl` (the existing, unchanged §13
   mechanism). A failure here propagates exactly as it always has — the
   previous trace survives via the same atomic-replace guarantee, and
   `run_context.json` is left at `pending` (context degrades safely).
6. **Best-effort**: atomically replace the `pending` marker with the
   `complete` context (trace hash, strategy id, server snapshot). A failure
   here is logged and swallowed — the mandatory trace has already succeeded
   by this point, so `POST /run` still returns `200`; readers see the
   still-`pending` file and correctly report `context_available: false`.
7. Return the successful result.

**Read-side verification** (`run_context.load_verified`) trusts a context
only when *all* of: `schema_version` is supported, `status == "complete"`,
`trace_sha256` matches a fresh SHA-256 of the exact trace bytes being served,
`strategy` is a currently-registered id (§25), and every entry in `servers`
passes strict schema validation. The route (`routes_simulation.py`) reads
`run.jsonl` with `read_bytes()` once and reuses those exact bytes for both
UTF-8 decoding (for `deserialize()`) and hashing (for `load_verified()`) —
never `read_text()` followed by re-encoding, which risks universal-newline
translation (e.g. CRLF → LF) silently changing what gets hashed relative to
what was actually persisted.

Server-entry validation is strict, not coercive: each entry must be a JSON
object with *exactly* the four required fields (`id`, `cpu_units_per_tick`,
`mem_mb`, `rate_limit_per_sec` — an extra or missing field is rejected, not
ignored); `id` must be a non-empty, non-whitespace string; the three numeric
fields must each satisfy `type(value) is int` (a numeric string, a float, or
a bool — `bool` is a subclass of `int` in Python — is rejected, never
coerced with `int(...)`); `cpu_units_per_tick > 0`; `mem_mb >= 0`;
`rate_limit_per_sec >= 0`; and server ids must be unique within the
snapshot. Only after every one of these checks does the entry become a
`ServerSpec`.

Any other condition — missing file, malformed JSON, wrong schema version,
`pending` status, hash mismatch, unrecognized strategy, any server-entry
schema violation, a duplicate server id — degrades to `None` (logged, never
raised) and the caller reports `context_available: false`. Only expected
filesystem/deserialization exceptions are caught this way at the top level
(`OSError`, `UnicodeDecodeError`, `json.JSONDecodeError`); the server
snapshot itself is checked with explicit type/value comparisons rather than
by catching a coercion exception — a genuine programming error elsewhere is
not silently swallowed.

The step-4-before-step-5 ordering is what actually closes the
identical-trace/different-snapshot gap: because the *old* context is
stomped to `pending` before the *new* trace even exists, there is no
sequencing in which a stale `complete` context can ever be read back
against a new trace it doesn't describe — proven by a dedicated adversarial
test that runs once with one server, once with an added-but-unused second
server (genuinely identical resulting trace bytes), forces the second run's
final `complete`-context publish to fail, and asserts the first run's
context is never returned as valid for the second run's trace.
`run_context.json` is git-ignored (`backend/.gitignore`) as optional runtime
metadata from the evaluator/artifact perspective — `run.jsonl` itself
remains tracked and is never ignored. Its own publication, however, is not
uniformly best-effort: the `pending`-marker write (step 4) is a **mandatory
prerequisite** for publishing a new trace at all, and its failure aborts the
run with a controlled 500 before any new `run.jsonl` is written. Only the
final `complete`-context write (step 6, after the trace has already
succeeded) is best-effort.
