# Prompt 01: Read-Only Architecture and Execution Plan

You are planning the Medsien Load Balancer Simulation take-home project.

## Mode

This is a read-only planning task.

- Do not create, edit, rename, or delete any file.
- Do not install dependencies.
- Do not initialize application scaffolding.
- Do not commit or push anything.
- You may inspect repository files and run read-only commands.
- End after presenting the plan and questions. Wait for explicit approval before implementation.

## Read these sources completely

Read in this order:

1. `CLAUDE.md`
2. `docs/SPEC.md`
3. `docs/DECISIONS.md`
4. `docs/AI_USAGE.md`
5. `provided/assignment.pdf`
6. `provided/validate_run.py`
7. `provided/servers.json`
8. `provided/requests.csv`
9. `provided/run.jsonl`

Treat the provided files as immutable.

## Goal

Produce an implementation-ready architecture and three-day execution plan for the complete mandatory project, with bonus work isolated behind the mandatory quality gate.

The plan must preserve candidate control, pass the unmodified provided validator, and keep the simulation logic explainable in a live follow-up interview.

## Required analysis

### 1. Repository inventory

- Confirm which expected files are present or missing.
- Identify any filename or layout mismatch.
- Do not fix mismatches in this task.

### 2. Requirement matrix

Create a compact table containing:

- Requirement
- Source
- Mandatory or bonus
- Proposed component
- Verification method
- Risk or ambiguity

### 3. Independent validator review

Verify the documented PDF-versus-validator conflict yourself from the source.

Explain:

- Concurrency behavior
- Finish-time calculation
- Memory validation
- Rate-limit validation
- Lifecycle validation
- Event sorting behavior
- Validator gaps that the implementation must not exploit

If your finding differs from `docs/SPEC.md`, report the disagreement rather than silently changing the policy.

### 4. Proposed architecture

Propose a minimal architecture using the accepted stack:

- Pure Python simulation domain
- Input and output adapters
- Server configuration repository
- FastAPI application services and routes
- React TypeScript frontend
- Docker Compose

Show dependency direction and explain why scheduling logic remains outside FastAPI routes.

### 5. Proposed repository tree

Provide a concrete but minimal file tree.

Avoid speculative files and unnecessary abstraction. Mark which files belong to:

- Mandatory backend
- Mandatory frontend
- Tests
- Docker/runtime
- Documentation
- Bonus features

### 6. Domain model

Propose the minimum domain models and important fields for:

- Server specification
- Request specification
- Server runtime state
- Running request
- Simulation event
- Simulation result
- Scheduling strategy

For each model, explain whether it should be immutable or mutable and why.

### 7. Tick algorithm

Provide precise pseudocode for the validator-compatible default mode.

The pseudocode must cover:

- Completion and capacity release
- Same-tick arrivals
- Permanent impossibility and drop behavior
- Queue traversal and deterministic bypass behavior
- Server eligibility
- Rate-limit tracking
- Start and finish tick calculation
- Progress detection and termination
- Stable event ordering
- Stable JSONL serialization

Manually walk through the supplied four-request example and show the resulting assignments and finish ticks. Do not assume that output line order must exactly match the sample; explain what must match semantically and what the validator enforces.

### 8. API and persistence plan

Propose:

- Request and response shapes
- Validation rules
- HTTP status behavior
- Atomic server configuration writes
- Simulation snapshots
- Concurrent run protection
- Atomic trace publication
- How the evaluator downloads or inspects `run.jsonl`

Do not introduce a database unless you can demonstrate a mandatory need.

### 9. Frontend plan

Keep the mandatory dashboard functional and small:

- Server list
- Add, edit, and delete
- Run simulation
- Result summary
- Trace download

Separate bonus visualization and metrics from the mandatory UI.

### 10. Test matrix

Provide test cases grouped by:

- Parsers and validation
- Simulation lifecycle
- Scheduling and tie-breaks
- Queue and drop behavior
- Determinism
- Provided validator integration
- API CRUD and run endpoints
- Persistence and concurrency safety
- Frontend behavior
- Docker smoke test

For the highest-risk tests, give exact input and expected event behavior.

### 11. Docker plan

Explain:

- Backend image
- Frontend build and serving approach
- API proxying
- Persistent configuration and output volumes
- Health checks
- Startup command
- Clean-clone verification

### 12. Three-day milestone plan

Create a realistic schedule with mandatory completion frozen before bonus work:

- Day 1: simulation engine, tests, validator, and backend foundation
- Day 2: API, dashboard, Docker, mandatory end-to-end gate
- Day 3: selected bonuses, documentation, and clean-clone final review

For each block, define a measurable stop condition.

### 13. Risks and questions

Rank the top risks by severity and likelihood.

Separate:

- Questions that should be sent to Medsien
- Decisions already resolved in `docs/DECISIONS.md`
- Questions that can wait until implementation

## Output format

Return these sections:

1. Executive summary
2. Repository inventory
3. Requirement matrix
4. Validator findings
5. Architecture and dependency direction
6. Proposed file tree
7. Domain model
8. Tick algorithm and sample walkthrough
9. API and persistence plan
10. Frontend plan
11. Test matrix
12. Docker plan
13. Three-day milestones
14. Ranked risks
15. Blocking questions
16. Proposed amendments to `docs/DECISIONS.md`, if any

Do not write implementation code beyond short interfaces or pseudocode needed to make the plan precise.

Stop after the plan. Wait for approval.
