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

## Open questions

1. Will Medsien evaluate with the supplied serial validator or an updated shared-CPU validator?
2. Should uploaded request CSV files be retained, or is in-memory use sufficient?
3. Is `docker compose up` expected to generate a sample run automatically, or is a dashboard/API trigger sufficient?

Until clarified, use the simplest behavior that satisfies the PDF and unmodified validator without expanding scope.
