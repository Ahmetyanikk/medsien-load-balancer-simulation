Continue on the existing branch `bonus/day3b-visualization-autoscale` and implement Day 3B-2: the read-only Auto-scaling Recommendation bonus.

This is an implementation task, not another planning-only pass. The corrected Day 3B design and the policy below are approved.

Do not stage, commit, amend, reset, tag, push, change Git configuration, or alter the Git index. The candidate retains all Git control.

## 1. Preflight and stop conditions

Before editing, verify and report:

- Current branch is `bonus/day3b-visualization-autoscale`.
- HEAD remains `3c39ce7`.
- `git diff --cached --name-only` is empty.
- The working tree contains only the expected cumulative Day 3B-1 Timeline file set.
- No unrelated untracked files exist.
- `git diff --check` is clean.
- `backend/data/run.jsonl` and `provided/` have no diff.
- The canonical trace SHA-256 is:

  `225b3f69a060d1821c7756e40830a9274f595b516eeb74e3ff0bf0ca75201845`

The existing `A` appearances in short status may be intent-to-add working-tree entries from the existing Day 3B-1 diff. The authoritative staged-content check is `git diff --cached --name-only`, which must remain empty. Do not alter the index to “fix” the presentation.

If any unexpected file, staged content, branch mismatch, HEAD mismatch, or canonical-trace difference is found, stop and report it before editing.

## 2. Objective

Add a deterministic, explainable, read-only Auto-scaling Recommendation feature based solely on the already-computed `ClusterMetrics`.

The feature must:

- Recommend `scale_up`, `scale_down`, or `no_change`.
- Distinguish an actual `no_change` recommendation from an unavailable recommendation.
- Never mutate servers, traces, context, requests, or any other persisted state.
- Never provide an Apply button.
- Never automatically execute its recommendation.
- Reuse the existing `read_current_run()` boundary exactly once per API request.
- Reuse `compute_metrics()` and never independently reimplement metrics.
- Preserve every mandatory behavior, endpoint, strategy, trace, and validator guarantee.
- Preserve the authoritative one-active-request-per-server execution model confirmed by Medsien Engineering.

## 3. Frozen files and behavior

Do not modify:

- `backend/app/domain/engine.py`
- `backend/app/domain/models.py`
- `backend/app/domain/strategies.py`
- JSONL serialization/deserialization behavior
- `SimulationService.run()`
- run-context schema or publication semantics
- existing mandatory endpoint contracts
- existing Metrics or Timeline response values
- Dockerfiles or Compose topology
- dependency manifests or lockfiles
- anything under `provided/`
- `backend/data/run.jsonl`
- Day 3B-1 Timeline implementation files unless expressly allowlisted below
- shared-CPU behavior, CSV upload, streaming, authentication, database support, or automatic scaling

No new runtime dependency is allowed.

## 4. Exact file allowlist

New files:

- `backend/app/domain/autoscale.py`
- `backend/tests/test_autoscale.py`
- `backend/tests/test_api_autoscaling.py`
- `frontend/src/components/AutoScalePanel.tsx`
- `frontend/src/components/AutoScalePanel.test.tsx`
- `prompts/07_bonus_autoscaling.md`

Modified files:

- `backend/app/api/schemas.py`
- `backend/app/api/routes_simulation.py`
- `frontend/src/api/client.ts`
- `frontend/src/App.tsx`
- `frontend/src/index.css`
- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/DECISIONS.md`
- `docs/AI_USAGE.md`
- `backend/tests/test_api_timeline.py`, but only to correct the inaccurate comment identified in section 12 below

No other file may be changed without stopping and requesting approval.

Archive this implementation instruction verbatim in `prompts/07_bonus_autoscaling.md` and add it to the prompt inventory in `docs/AI_USAGE.md`.

## 5. Exact domain policy

Create `backend/app/domain/autoscale.py`.

Use immutable domain types and a pure function equivalent to:

`decide_scaling(metrics: ClusterMetrics) -> ScalingRecommendation`

It must have no filesystem, HTTP, repository, environment, clock, or global mutable-state access.

Constants:

```python
MIN_SERVER_COUNT = 1
HIGH_BUSY_RATIO = 0.80
LOW_BUSY_RATIO = 0.20
```

This is the literal continuation of the same Day 3B-2 implementation instruction. Append it directly after the received `LOW_BUSY_RATIO = 0.20` line when creating `prompts/07_bonus_autoscaling.md`. Do not reconstruct any text that was not actually received.

Both thresholds must be documented as:

“Simple, explainable, uncalibrated heuristic defaults for this case study.”

Never describe them as industry standards, production-calibrated thresholds, or empirically derived values.

### First-match-wins precedence

1. If `total_requests == 0`:

   - `recommendation_available = false`
   - `action = null`
   - `reason_codes = ["insufficient_data"]`
   - `suggested_server_delta = null`
   - `removal_candidate_server_ids = null`

2. If context is unavailable, represented by `configured_server_count is None`:

   - `recommendation_available = false`
   - `action = null`
   - `reason_codes = ["context_unavailable"]`
   - delta and removal candidates are null

   This rule intentionally precedes the drop rule. Even a trace containing drops must not produce a scaling decision without verified context.

3. If `dropped_rate > 0`:

   - `recommendation_available = true`
   - `action = "scale_up"`
   - `suggested_server_delta = 1`
   - `reason_codes = ["dropped_requests"]`
   - removal candidates null

   The explanation must state that dropped requests may indicate an incompatible capacity profile, such as insufficient memory on every server. It must not claim that adding one identical server is guaranteed to fix the problem.

4. If both conditions hold:

   - `peak_queue_depth >= configured_server_count`
   - `avg_cluster_busy_ratio >= HIGH_BUSY_RATIO`

   Return:

   - `recommendation_available = true`
   - `action = "scale_up"`
   - `suggested_server_delta = 1`
   - reason codes in this exact order:
     `["high_queue_pressure", "high_occupancy"]`

   Queue pressure alone must not trigger this rule. High occupancy alone must not trigger it either.

5. If all conditions hold:

   - `dropped_rate == 0`
   - `peak_queue_depth == 0`
   - `avg_cluster_busy_ratio < LOW_BUSY_RATIO`
   - `configured_server_count > MIN_SERVER_COUNT`
   - `idle_configured_server_ids` is non-empty

   Return:

   - `recommendation_available = true`
   - `action = "scale_down"`
   - `suggested_server_delta = -1`
   - `reason_codes = ["low_occupancy_idle_capacity"]`
   - `removal_candidate_server_ids` equals the idle IDs sorted ascending

   The explanation must say that the user should choose at most one candidate and that the recommendation is never applied automatically.

6. For the same low-occupancy shape when `configured_server_count == MIN_SERVER_COUNT`:

   - `recommendation_available = true`
   - `action = "no_change"`
   - `suggested_server_delta = null`
   - `reason_codes = ["minimum_server_count"]`
   - candidates null

7. Otherwise:

   - `recommendation_available = true`
   - `action = "no_change"`
   - `suggested_server_delta = null`
   - `reason_codes = ["steady_state"]`
   - candidates null

### Boundary requirements

- Exactly `0.80` satisfies the high threshold.
- Exactly `0.20` does not satisfy the low threshold.
- The canonical sample must produce `no_change / steady_state`: its occupancy is `0.875`, but `peak_queue_depth = 1` is less than `configured_server_count = 2`.
- Drops outrank every available scaling signal.
- Insufficient data and unavailable context outrank drops.
- `suggested_server_delta` is `1` or `-1` only for actual scale actions.
- It is null, never `0`, for `no_change` and unavailable recommendations.
- Removal candidates are non-null only for `scale_down`.
- Sort removal candidates inside `decide_scaling`; never rely on input order.

Stable reason-code set:

```text
insufficient_data
context_unavailable
dropped_requests
high_queue_pressure
high_occupancy
low_occupancy_idle_capacity
minimum_server_count
steady_state
```

Build explanations deterministically from fixed templates keyed by reason code. Tests should assert stable reason codes and essential safety wording rather than coupling every test to an entire prose sentence.

## 6. Fixed limitations

Every recommendation response must contain the same deterministic limitations list explaining:

No work_units or memory-demand evidence is available to the recommendation layer.
avg_cluster_busy_ratio is an occupancy/CPU-pressure proxy, not literal CPU utilization.
dropped_rate is a dropped-request/error-pressure proxy, not a true application error rate.
Only a single-step +1 or -1 recommendation is supported; there is no magnitude model.
Thresholds are uncalibrated case-study defaults, not derived from production telemetry.
Recommendations are never applied automatically.

## 7. Exact API contract

Add:

GET /api/simulations/latest/autoscaling

The route must:

Call read_current_run(settings) exactly once.
Return the existing normal 404 response when no trace exists.
Allow malformed, invalid-UTF-8, or corrupt traces to reach the existing controlled DomainError 500 handler.
Call compute_metrics(snapshot.events, snapshot.servers).
Pass the resulting ClusterMetrics to decide_scaling().
Perform no writes, repository mutations, server mutations, or simulation run.
Return HTTP 200 with an unavailable recommendation when context is missing, pending, malformed, or hash-mismatched.

Use this response shape:

{
  "context_available": true,
  "recommendation_available": true,
  "action": "no_change",
  "reason_codes": ["steady_state"],
  "explanation": "Deterministic human-readable explanation.",
  "suggested_server_delta": null,
  "removal_candidate_server_ids": null,
  "observed": {
    "total_requests": 4,
    "dropped": 0,
    "dropped_rate": 0.0,
    "peak_queue_depth": 1,
    "avg_queue_depth": 0.25,
    "avg_cluster_busy_ratio": 0.875,
    "configured_server_count": 2,
    "idle_configured_server_ids": []
  },
  "limitations": [
    "..."
  ]
}

Types and invariants:

action: "scale_up" | "scale_down" | "no_change" | null
reason_codes: list of the stable typed literals above
suggested_server_delta: int | null
removal_candidate_server_ids: list[str] | null
Nullable observed fields remain nullable exactly as in MetricsResponse.
If recommendation_available is false, action, delta, and candidates must all be null.
scale_up always has delta 1 and null candidates.
scale_down always has delta -1 and a non-empty sorted candidate list.
no_change always has null delta and null candidates.

Every field under observed must equal the corresponding field from GET /api/simulations/latest/metrics for the same persisted trace. Do not independently reinterpret or recompute those values.

Do not add strategy_used merely for symmetry. It is not part of the approved Auto-scaling response contract.

Do not change the existing MetricsResponse shape or values. Put proxy caveat descriptions on the new Auto-scaling schema and in documentation.

## 8. Domain tests

Create comprehensive deterministic tests in backend/tests/test_autoscale.py.

Use real valid engine output and compute_metrics() for primary scenarios whenever possible. Do not create physically impossible metrics merely to make a branch fire. Synthetic ClusterMetrics instances are allowed only for exact threshold and isolated branch tests.

Required primary scenarios:

Canonical sample:
dropped 0
peak queue 1
configured servers 2
average busy ratio 0.875
result no_change
reason steady_state
Memory-incompatible dropped request with verified context:
result scale_up
reason dropped_requests
explanation does not promise that an identical server will fix it
One server with two jobs arriving at tick 0:
peak queue 1
configured count 1
busy ratio 1.0
result scale_up
both high-pressure reason codes in the required order
Two identical servers with jobs at ticks 0 and 100:
deterministic tie-breaking sends both to s1
s2 remains idle
peak queue 0
low occupancy
result scale_down
candidate ["s2"]
The same sparse workload with only one configured server:
result no_change
reason minimum_server_count
Empty metrics:
result unavailable
reason insufficient_data
Trace metrics without verified context:
result unavailable
reason context_unavailable

Also test:

total_requests == 0 outranks context unavailability.
Context unavailability outranks drops.
Exact high-threshold equality at 0.80.
Exact low-threshold equality at 0.20 does not scale down.
Queue pressure alone does not scale up.
Occupancy alone does not scale up.
Drops outrank other available signals.
Candidate IDs are sorted from deliberately unsorted input.
Repeated calls return exactly equal results.
Inputs are not mutated.
Every result obeys all action/delta/candidate invariants.
Fixed limitations are deterministic and always present.

No sleeps, timers, random shuffles, or probabilistic tests.

## 9. API tests

Create backend/tests/test_api_autoscaling.py.

Required coverage:

Missing trace returns 404.
Corrupt lifecycle or schema returns controlled 500.
Invalid UTF-8 returns controlled 500.
Verified canonical run returns 200 and no_change / steady_state.
Missing context returns recommendation unavailable.
Pending context returns recommendation unavailable.
Hash-mismatched context returns recommendation unavailable.
A trace with dropped requests but no verified context still returns context_unavailable, not scale_up.
A verified dropped trace returns scale_up / dropped_requests.
Repeated GET calls return identical bodies.
A fresh TestClient(create_app(settings)) reconstructs the identical response after a simulated restart.
Every observed field equals the corresponding /latest/metrics field exactly.
HTTP responses obey all availability/action/reason/delta/candidate invariants.

Strict read-only proof:

Before and after an Auto-scaling GET, capture and compare:

GET /api/servers response
servers.json bytes and mtime_ns
run.jsonl bytes and mtime_ns
run_context.json bytes and mtime_ns

All values must remain identical. Do not use sleeps as evidence.

## 10. Frontend

Create AutoScalePanel.tsx and AutoScalePanel.test.tsx.

Add the panel to the existing bonus area without disturbing Server CRUD, RunPanel, MetricsPanel, StrategySelector, or TimelinePanel.

The panel must:

Accept runVersion.
Refetch after successful simulation runs.
Use the established monotonic generationRef stale-response protection.
Handle loading, 404/no-run, API/network error, available recommendation, and unavailable recommendation states.
Render unavailable as clearly labeled Recommendation unavailable.
Never render unavailable as No change.
Render available action badges with both icon and text:
Scale up
Scale down
No change
Never rely on color alone.
Render the explanation verbatim.
Render every observed value and use N/A for null.
Explain the occupancy and dropped-rate proxy meanings.
Render removal candidates only when non-null.
Always state that recommendations are not applied automatically and that server configuration changes must be made through the Servers panel for future runs.
Render the fixed limitations.
Include no Apply button, mutation callback, CRUD request, simulation trigger, or automatic action.
Remain usable at narrow viewport widths.
Add no charting or UI dependency.

Frontend tests must cover:

loading
404/no-run
generic error
recommendation unavailable and absence of No change
scale-up badge
scale-down badge and candidates
no-change badge
observed null values shown as N/A
proxy caveats
fixed limitations
unconditional “not applied automatically” statement
candidates absent when null
no Apply button
runVersion refresh
stale-response protection using deferred promises without timers

All existing frontend tests must remain green.

## 11. Documentation

### README.md

Document:

Timeline and Auto-scaling bonus features.
/latest/autoscaling.
The first-match policy at a concise user-facing level.
Unavailable versus no-change semantics.
The three possible actions.
Read-only behavior and absence of automatic application.
Proxy and threshold limitations.
Canonical sample result: no_change / steady_state.

### docs/ARCHITECTURE.md

Add a dedicated Auto-scaling section covering:

pure domain boundary
trace_reader -> compute_metrics -> decide_scaling data flow
exact policy precedence
threshold boundary semantics
stable reason codes
why context unavailability precedes drops
no state mutation
fixed limitations
frontend refresh and stale-response behavior
why this is a recommendation system rather than an autoscaler

### docs/DECISIONS.md

Add D-022 for the Auto-scaling Recommendation policy and its trade-offs.

### docs/AI_USAGE.md

Correct the existing Day 3B-1 tool/role attribution to ChatGPT + Claude Code.
Correct the chronology: physically impossible Auto-scaling planning fixtures were identified during ChatGPT’s review of the initial plan, before Timeline implementation. Do not claim they were discovered during post-implementation review.
Preserve the actual Day 3B-1 totals: backend 220/220 and frontend 77/77.
Do not alter unrelated historical rows.
Add an honest Day 3B-2 entry distinguishing:
ChatGPT: policy and plan review, implementation-instruction design, with resulting diff review still pending.
Claude Code: implementation, tests, documentation, and command execution.
Candidate: scope approval, acceptance, browser verification, and complete Git control.
Do not claim browser or post-commit clean-clone verification occurred unless it actually occurs.
State that Claude Code did not stage, commit, tag, or push.
Add prompts/07_bonus_autoscaling.md to the prompt archive inventory.

## 12. Carry-over comment correction

In backend/tests/test_api_timeline.py, correct the inaccurate synthetic sparse-helper regression comment.

The old helper always calculated peak using max(point.depth). Omitting the final interval affected the average but did not cause the peak to miss the final point.

Change only that comment. Do not alter the test logic or Timeline behavior.

## 13. Verification gates

### Backend

Run:

python -m pytest -q
python -m pytest --collect-only -q

No external environment variable should be required.

The pre-Day-3B-2 baseline is 220 backend tests. Report the actual final count, not an anticipated count.

### Frontend

Run:

npm ci
npm run test -- --run
npm run build

The pre-Day-3B-2 baseline is 77 frontend tests. Report the actual final count.

### Validator and determinism

Run both fastest_finish and lowest_id.
Validate both traces with the real, unmodified provided/validate_run.py.
Finish by running the implicit/default strategy again.

Confirm the final canonical SHA-256 is exactly:

225b3f69a060d1821c7756e40830a9274f595b516eeb74e3ff0bf0ca75201845

Confirm backend/data/run.jsonl and provided/ have no diff.

### Docker and proxy E2E

Run:

docker compose config
docker compose build --no-cache
docker compose up -d --wait

Then:

Confirm both services become healthy using bounded readiness checks, not fixed sleeps.
Exercise through nginx on port 3000:
/api/simulations/latest/metrics
/api/simulations/latest/timeline
/api/simulations/latest/autoscaling
default simulation run
lowest_id simulation run
Confirm Timeline still works.
Confirm Auto-scaling returns canonical no_change / steady_state.
Confirm /api/servers is unchanged before and after Auto-scaling GET.
Validate both strategies inside the backend container.
Perform one final default run and reconfirm the canonical hash.
Run docker compose down at the end.

This is a clean Docker rebuild of the current working tree, not a post-commit clean-clone test. Do not claim that a true post-commit clean-clone verification occurred.

### Git and repository hygiene

Run and report:

git diff --check
Direct final-newline verification for all new files
git diff --exit-code -- backend/data/run.jsonl provided
git diff --cached --name-only, which must remain empty
Final git status --short

Confirm there are no:

.pyc files
cache directories
build outputs
downloaded traces
temporary fixtures
Docker-generated stray data
terminal-output files
Git configuration changes

## 14. Completion report and review artifact

At completion, stop and report:

Exact created and modified file list.
Exact policy implementation and precedence.
Response contract and invariants.
Domain-test scenarios and results.
API-test scenarios and read-only proof.
Frontend behavior and test results.
Backend test and collection totals.
Frontend test and build totals.
Both validator results.
Docker and proxy results.
Canonical hash.
Documentation changes.
Known limitations.
Final Git status.
Explicit confirmation that nothing was staged, committed, tagged, or pushed.

Also create a complete cumulative review diff named:

day3b-final.diff

Place it outside the repository working tree, in the repository parent or scratch location.

It must include:

all tracked modifications
all existing Day 3B-1 intent-to-add files
every new untracked Day 3B-2 file

A plain git diff --output=... is insufficient while any new file remains ??. Combine the normal working-tree diff with read-only git diff --no-index output for every untracked new file.

Do not use git add, including git add -N, to make untracked files appear in the diff. Do not modify the index.

Stop after the report and cumulative diff. Do not begin browser acceptance, commit, merge, tag, push, or another bonus feature.
