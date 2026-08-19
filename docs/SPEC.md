# Medsien Load Balancer Simulation Specification

## 1. Project objective

Build a deterministic, fully Dockerized load balancer simulation with:

- A Python backend and simulation engine
- A server-management dashboard
- A way to trigger simulation runs
- A deterministic `run.jsonl` trace
- Documentation of architecture, scheduling, assumptions, trade-offs, and AI usage

This is a discrete-time simulator, not a production HTTP reverse proxy.

## 2. Inputs

### `servers.json`

Contains:

- `tick_seconds`
- `servers[]`
- `server.id`
- `server.cpu_units_per_tick`
- `server.mem_mb`
- `server.rate_limit_per_sec`

Server IDs must be unique. CPU capacity must be positive. Memory must be non-negative. A zero rate limit is allowed as a disabled-for-starts configuration but must not cause an infinite simulation.

### `requests.csv`

Contains:

- `t`: arrival tick
- `request_id`
- `work_units`
- `mem_mb`

Request IDs must be unique. Arrival ticks must be non-negative. Work units must be positive. Memory must be non-negative.

## 3. Output

The simulator must write `run.jsonl`, with one JSON object per non-empty line.

Supported lifecycle events:

- `REQUEST_ARRIVED`
- `REQUEST_STARTED`
- `REQUEST_FINISHED`
- `REQUEST_DROPPED`

Every request must follow exactly one terminal lifecycle:

```text
ARRIVED -> STARTED -> FINISHED
ARRIVED -> DROPPED
```

Do not rely on validator gaps that permit an arrived request to remain unresolved.

## 4. Mandatory behavior

### Discrete time

- One tick equals one second for the provided validator.
- A request starting at tick `t` occupies the half-open interval `[t, finish_t)`.
- A server may start a new request at the exact tick its previous request finishes.

### Capacity constraints

- A request may start only on an eligible server.
- Memory must remain reserved for the full execution interval.
- Starts per server per tick must not exceed `rate_limit_per_sec`.
- A request must never run on more than one server.

### Overload policy

- Temporarily unschedulable requests enter a deterministic queue.
- A request that cannot ever run on any configured server is dropped deterministically.
- The simulation must terminate without silently abandoning queued requests.

### Determinism

Identical server input, request input, and simulation configuration must produce byte-identical `run.jsonl` output.

The implementation must explicitly define:

- Request ordering
- Server selection
- Same-tick event ordering
- Completion ordering
- JSON serialization order

## 5. Specification and validator conflict

The assignment execution model says:

- A server may execute multiple requests concurrently.
- CPU capacity is divided evenly across currently running requests each tick.
- Aggregate reserved memory must not exceed server memory.

The provided validator instead:

- Rejects overlapping execution intervals on the same server.
- Computes finish time as `start + ceil(work_units / cpu_units_per_tick)`.
- Does not model shared CPU allocation.
- Checks only whether an individual request fits server memory.

The supplied sample `run.jsonl` also uses non-overlapping server intervals.

### Mandatory compatibility policy

The submitted default mode must pass the unmodified provided validator. It therefore uses at most one active request per server.

This remains compatible with the PDF wording that a server *may* run requests concurrently; the default scheduling strategy intentionally chooses not to overlap them.

A true shared-CPU mode may be added only as a clearly separated optional strategy after mandatory completion or after clarification from Medsien. It must never replace the validator-compatible default output.

## 6. Server management dashboard

Mandatory operations:

- View servers
- Add a server
- Edit a server
- Delete a server

Dashboard changes must affect future simulation runs.

Recommended controls:

- Run simulation
- Select an allowed scheduling strategy
- View run summary
- Download `run.jsonl`

Frontend visual polish is secondary to correctness and usability.

## 7. Backend API

Recommended minimum API surface:

```text
GET    /api/servers
POST   /api/servers
PUT    /api/servers/{server_id}
DELETE /api/servers/{server_id}

POST   /api/simulations/run
GET    /api/simulations/latest
GET    /api/simulations/latest/metrics
GET    /api/simulations/latest/download
```

Exact paths may change during the approved architecture plan, but every mandatory capability must remain available.

## 8. Containerization

- The complete project must start with `docker compose up` or `docker compose up --build`.
- No manual host dependency installation may be required beyond Docker.
- Every required service must be represented in Docker Compose.
- Generated output must remain accessible to the evaluator.

## 9. Testing requirements

At minimum, cover:

- Provided golden example
- Provided validator integration
- Byte-for-byte repeated-run determinism
- Same-tick arrivals
- Queue waiting
- Drop of permanently impossible requests
- Memory eligibility
- Rate-limit enforcement
- Tie-breaking between servers
- Unsorted request input
- Duplicate IDs and invalid values
- A request requiring one tick
- Server availability at a previous request's finish tick
- CRUD changes affecting a future run
- Concurrent simulation trigger protection
- Docker smoke test

## 10. Bonus scope

Implement only after the mandatory quality gate passes.

### Performance metrics

- Total, started, finished, and dropped requests
- Average, P50, P95, and maximum wait
- Throughput
- Per-server request and work totals
- Explainable utilization estimate

### Visualization

- Event timeline or server execution timeline
- Queue-length history
- Filterable event list

A deterministic post-run visualization is preferred over real-time animation.

### Interchangeable strategies

Add at least two validator-compatible server-selection strategies, such as:

- Shortest predicted processing time
- Round robin
- First fit

### Auto-scaling decision module

To preserve validator compatibility, the initial bonus implementation should analyze completed-run metrics and recommend configuration changes for the next run. Applying a recommendation changes future server configuration, not an already running simulation.

## 11. Out of scope for the three-day build

- Authentication and authorization
- Kubernetes
- Production cloud deployment
- WebSockets or real-time streaming
- A mandatory external database
- Complex distributed locking
- Highly polished animation
- Mid-run capacity mutation in the validator-compatible mode

## 12. Definition of done

- All mandatory features work from Docker Compose.
- The unmodified provided validator accepts the generated sample trace.
- Repeatability is proven by an automated test.
- Core scheduling and lifecycle edge cases are tested.
- The dashboard performs server CRUD and triggers a run.
- `run.jsonl` can be inspected or downloaded.
- Architecture and trade-offs are documented.
- AI prompts, accepted suggestions, candidate decisions, and verification steps are recorded truthfully.
- The candidate can explain the tick loop, queue policy, tie-break rules, validator conflict, and Docker architecture.
