# Prompt 02: Day 1 — Simulation Engine (historical record)

**Provenance note:** No prompt file was created during Day 1 itself — the candidate's
instructions were delivered as chat turns to Claude Code, not as saved files. This
document is a **retrospective reconstruction from the session transcript**, written
during Day 2A so `docs/AI_USAGE.md`'s `prompts/` archive convention is honored
retroactively. Where the original wording is available in the transcript it is
quoted closely; anywhere this summarizes rather than quotes verbatim, that is
called out explicitly. Nothing here should be read as a literal file that existed
on disk during Day 1.

---

## Approval message 1 — Day 1 scope (Section 17 amendments)

The candidate approved the read-only architecture plan **for Day 1 implementation
only**, with binding amendments (summarized; the numbered structure below matches
the original instruction):

1. **Explicit request sorting** — never rely on CSV/append order; sort parsed
   requests by `(arrival_tick, request_id)`; same-tick arrivals processed by
   `request_id`.
2. **Pure domain boundary** — `SimulationEngine` must not read or write files;
   receives immutable domain input, returns `SimulationResult`. `JsonlTraceWriter`
   serializes events only. `SimulationService` owns temporary-file creation and
   atomic `os.replace()` publication.
3. **API decisions recorded for later milestones, not implemented Day 1**: Pydantic
   validation errors → 422; duplicate server ID → 409; missing server → 404;
   simulation already running → 409; invalid/empty runtime configuration → 400;
   server IDs immutable after creation; `run_at` removed from the mandatory
   `RunSummary`.
4. **Locking** — the simulation run lock must use non-blocking acquisition and
   `try/finally` release; Docker will use one Uvicorn worker; the simulation
   endpoint should later be a synchronous `def` route unless blocking work is
   explicitly moved to a thread.
5. **Required additional tests**: empty request input; empty server configuration;
   duplicate request ID; duplicate server ID; negative arrival; non-positive work
   units; non-positive CPU capacity; negative memory or rate limit; explicit
   sorting of unsorted CSV input; all-servers-rate-limit-zero → `ARRIVED` then
   `DROPPED`; a rate=0 preferred server skipped for another eligible server;
   no-future-progress protection; every request reaches `FINISHED` or `DROPPED`;
   no unknown event types generated; JSONL ends with exactly one trailing newline.
6. **Approved deviations** — D-013 (repository layout) approved only as
   standardized copies under `provided/`; never overwrite or mutate source files;
   stop and ask if expected files are missing. D-006's rate-limit clarification
   approved. D-009's single-worker limitation approved, to be documented later.
7. **Day 1 implementation scope**: backend package configuration, domain models,
   default scheduling strategy, pure simulation engine, CSV/JSON input adapters,
   deterministic JSONL writer, atomic trace publication in `SimulationService`,
   JSON server repository with atomic writes, FastAPI skeleton with `GET /health`
   only, unit and integration tests, one generated sample `run.jsonl`. Explicitly
   **not** implemented: server CRUD routes, simulation HTTP endpoint, React
   frontend, Docker, metrics service, visualization, auto-scaling, bonus
   strategies.

Final implementation clarifications attached to this approval (quoted closely from
the transcript):

> 1. Do not initialize Git, commit, push, move source fixtures, or modify
>    `provided/`. The Git baseline and standardized `provided/` copies have already
>    been created manually.
> 2. Do not use `assert` for runtime deadlock protection. Create an explicit domain
>    exception such as `SimulationDeadlockError` and raise it when waiting requests
>    remain but there is no future arrival or finish event.
> 3. Do not use floating-point division for runtime calculation. Use integer
>    ceiling division: `def ceil_div(a, b): return (a + b - 1) // b`.
> 4. Empty server input and empty request input must raise explicit domain/input
>    validation errors. Do not generate an empty trace.
>
> **Note — point 4 was refined before implementation, not applied as first quoted
> above:** a later clarification in the same approval turn distinguished the two
> cases. What was actually built: `SimulationEngine` accepts an empty request list
> and returns a valid, empty `SimulationResult` (zero events, zero summary values)
> — this is pure domain behavior, not an error. `SimulationService` is the layer
> that refuses to publish: it rejects an empty `requests.csv` with
> `EmptyRequestConfigurationError` before ever calling the engine, specifically
> because the supplied validator cannot parse a `run.jsonl` with zero events.
> Empty *server* configuration remains a validation error at both layers
> (`EmptyServerConfigurationError`) — a simulation cannot run with zero capacity.
>
> 5. The server-ID tie-break test must use an actual equal-runtime case, such as
>    two servers with equal CPU capacity. The lexicographically smaller server ID
>    must win.
> 6. Section 17's pure domain boundary overrides Section 8 (`SimulationEngine`
>    performs no filesystem I/O; `JsonlTraceWriter` performs deterministic
>    serialization only; `SimulationService` owns temporary files and atomic
>    `os.replace()` publication).
> 7. Day 1 scope remains exactly the approved Section 17 scope.

Before editing, the candidate required: current Git status, confirmation
`provided/` contains all expected files, and a complete list of files to be
created or modified — then implementation, stopping after the Day 1 completion
report. No Day 2 work permitted in this milestone.

## Approval message 2 — Day 1 correction pass

After independent review (38 tests passed, the sample and 200 randomized
simulations passed the real validator, scheduling algorithm judged correct), the
candidate requested a **correction pass only**, without changing the valid sample
trace or scheduling behavior:

1. Fix backend package installation — explicit `setuptools` build backend and
   package discovery so only `app*` is packaged and `pip install -e .` succeeds.
2. Reject an empty `requests.csv` at the adapter/service boundary with a specific
   domain error (`EmptyRequestConfigurationError`); the engine may retain its pure
   empty-input behavior, but `SimulationService.run()` must never publish an empty
   `run.jsonl` the supplied validator rejects.
3. Validate `servers.json`'s `tick_seconds`; reject any value other than 1 before
   running the simulation.
4. Validate that `requests.csv` contains all required columns; raise a clear
   domain/input error instead of leaking `KeyError`.
5. Make `load_requests()` explicitly return requests sorted by `(arrival_t, id)`,
   retaining the engine's own defensive sort.
6. Strengthen the terminal-state test: observed request IDs must exactly equal
   input request IDs; each request must have exactly one terminal event; the
   terminal event must be `FINISHED` or `DROPPED`.
7. Add an atomic trace publication failure test proving a failed publication
   leaves the previous `run.jsonl` unchanged and removes temporary files.
8. Add missing final newlines to source/config/test files.

Completion required: full pytest result, real `validate_run.py` result,
determinism result, clean package installation result, `git diff --check` result,
`git status`. Scope explicitly excluded CRUD/simulation routes, frontend, Docker,
locking, and all other Day 2 work.

---

Both milestones' actual verification output (test counts, validator results,
hashes) is reported in full in each milestone's own completion report in this
session. `docs/AI_USAGE.md` entries summarizing this work are added **after**
candidate review of those reports — they are not written as work proceeds, and
this document does not claim they already exist at the time this file was
written.
