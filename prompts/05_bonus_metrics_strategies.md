# Prompt 05: Day 3A — Performance Metrics + Second Scheduling Strategy (approved implementation instruction, verbatim)

This is the exact candidate instruction that approved and scoped the Day 3A
implementation. Reproduced verbatim from the session transcript.

---

> Implement Day 3A only: performance metrics plus one additional validator-compatible scheduling strategy.
>
> The revised Day 3 plan is approved subject to every binding amendment below. Do not begin Day 3B visualization or autoscaling implementation.
>
> Current approved checkpoint:
>
> - HEAD: e1aa846
> - Tag: day2b2-complete
> - Working tree must be clean before implementation.
> - Existing mandatory behavior is frozen.
> - Existing expected gates:
>   - Backend: 112 tests
>   - Frontend: 38 tests
>   - Default trace SHA-256:
>     225b3f69a060d1821c7756e40830a9274f595b516eeb74e3ff0bf0ca75201845
>   - Real validator: VALID
> - Do not commit, tag, or push.
> - Do not modify provided files.
> - Before editing, report the exact files that will be created or modified.
> - Archive this instruction verbatim as prompts/05_bonus_metrics_strategies.md.
>
> ## 1. Day 3A scope
>
> Implement only:
>
> 1. Trace-derived performance metrics.
> 2. Context-enriched cluster and per-server metrics.
> 3. A second scheduling strategy.
> 4. Strategy selection through the simulation API.
> 5. Metrics and strategy controls in the frontend.
> 6. Required tests and documentation updates.
>
> Do not implement yet:
>
> - Timeline or event visualization.
> - Auto-scaling recommendation logic or UI.
> - Shared-CPU execution.
> - Live streaming.
> - Charts requiring new dependencies.
> - Any other bonus feature.
>
> ## 2. Regression-frozen behavior
>
> The following mandatory behavior must remain unchanged:
>
> - Default strategy semantics.
> - Tick phase order.
> - Queue bypass and drop semantics.
> - Half-open execution intervals.
> - JSONL serialization and field order.
> - Atomic run.jsonl publication.
> - Existing server CRUD and simulation API behavior.
> - Calling POST /api/simulations/run without a strategy parameter.
> - The canonical default trace bytes and SHA-256.
>
> Do not change domain/engine.py unless an objectively necessary integration issue is found. If that happens, stop and report before editing it.
>
> ## 3. Second strategy
>
> Keep the current strategy as:
>
> - id: fastest_finish
> - label: Fastest finish
> - default: true
>
> Add:
>
> - id: lowest_id
> - label: Lowest server ID
> - default: false
>
> Lowest-ID behavior:
>
> - Use the engine-provided eligible server set.
> - Select the eligible server with the lexicographically smallest server ID.
> - It must obey exactly the same memory, CPU, rate-limit, idle-server, queue, drop, and lifecycle rules as the default strategy.
> - It must remain validator-compatible.
> - Strategy implementations remain stateless and interchangeable.
> - Resolve strategies through an explicit registry. Unknown IDs must not silently fall back to the default.
>
> API:
>
> GET /api/simulations/strategies
> POST /api/simulations/run?strategy=fastest_finish
> POST /api/simulations/run?strategy=lowest_id
>
> Requirements:
>
> - No query parameter means fastest_finish.
> - Unknown strategy returns controlled JSON 422.
> - The no-parameter default run must remain byte-identical to the frozen baseline.
> - Tests must include an input where fastest_finish and lowest_id genuinely choose different servers.
> - Traces from both strategies must pass the real provided validator.
>
> ## 4. Metrics definitions
>
> Add a pure domain metrics module. It must not perform filesystem or HTTP operations.
>
> Trace-only metrics must remain available even without run context:
>
> - total_requests
> - started
> - finished
> - dropped
> - dropped_rate
> - duration_ticks
> - throughput_requests_per_tick
> - peak_queue_depth
> - avg_queue_depth
> - per-server observed execution:
>   - server_id
>   - requests_handled
>   - work_units_total when reconstructable from context, otherwise null
>   - busy_ticks
>   - busy_time_ratio relative to the simulation duration
>
> Queue depth definition:
>
> - Reconstruct queue depth from events.
> - At each tick:
>   depth = previous_depth + ARRIVED - STARTED - DROPPED
> - Record the depth after all events at that tick.
> - Average over every discrete tick in the inclusive range from first event tick through last event tick.
> - Missing ticks carry the previous queue depth.
> - The depth must never become negative.
> - Empty traces must be handled explicitly.
>
> For the provided sample, assert exactly:
>
> - duration_ticks = 4
> - throughput_requests_per_tick = 1.0
> - peak_queue_depth = 1
> - avg_queue_depth = 0.25
> - s1 busy_ticks = 4
> - s2 busy_ticks = 3
> - average cluster busy ratio = 0.875 when context is available
>
> Terminology:
>
> - Busy-time ratio is an occupancy and CPU-pressure proxy.
> - It is not literal CPU utilization.
> - Use this wording consistently in API schemas, UI, tests, README, and ARCHITECTURE.
>
> Context-enriched metrics:
>
> - configured server count
> - idle configured servers with zero handled requests
> - per-server work_units_total
> - per-server busy_time_ratio, including zero for configured but unused servers
> - average cluster busy ratio
> - strategy used
> - context_available
>
> When context is unavailable, malformed, pending, or mismatched:
>
> - Return trace-only metrics safely.
> - Set context_available=false.
> - Use null for values that cannot be derived honestly.
> - Never invent idle servers or strategy information.
>
> ## 5. Critical run-context publication rule
>
> The prior hash-only design is not sufficient.
>
> A normal sequential run can produce identical run.jsonl bytes with a different server snapshot. For example, adding an unused server may leave the trace unchanged. Therefore an old context with the same trace hash must never be trusted after a failed context publication.
>
> Use a versioned context schema with an explicit status:
>
> Pending marker:
>
> {
>   "schema_version": 1,
>   "status": "pending"
> }
>
> Complete context:
>
> {
>   "schema_version": 1,
>   "status": "complete",
>   "trace_sha256": "...",
>   "strategy": "fastest_finish",
>   "servers": [...]
> }
>
> Required publication sequence:
>
> 1. Load and snapshot requests and servers.
> 2. Run the pure engine.
> 3. Serialize the final trace bytes.
> 4. Atomically replace run_context.json with the pending marker.
> 5. Only after successful invalidation, atomically publish run.jsonl using the existing mandatory publication mechanism.
> 6. Attempt to atomically replace the pending marker with the complete context.
> 7. Return the successful RunSummary.
>
> Failure semantics:
>
> - If publishing the pending marker fails:
>   - Do not publish a new trace.
>   - Preserve the previous run.jsonl.
>   - Return a controlled JSON 500.
> - If trace publication fails after the pending marker:
>   - Preserve the previous run.jsonl through the existing atomic guarantee.
>   - Leave context unavailable or pending.
>   - Propagate the existing controlled failure behavior.
> - If complete-context publication fails after a successful trace publication:
>   - Log the expected publication error.
>   - Leave the pending marker in place.
>   - POST /run must still return 200 because the mandatory trace succeeded.
>   - Bonus endpoints must return context_available=false.
> - Do not replace a pending marker with the old context.
> - Readers may trust context only when:
>   - schema_version is supported
>   - status == "complete"
>   - trace_sha256 matches the exact persisted trace bytes
>   - strategy is recognized
>   - the server snapshot validates
> - Missing, malformed, pending, unsupported, or mismatched context must degrade safely.
> - Catch expected filesystem and serialization exceptions deliberately. Do not silently swallow programming errors.
> - Log degraded context publication clearly.
>
> This lifecycle must be documented as a new decision or a precise amendment to the proposed run-context decision.
>
> Required adversarial tests:
>
> 1. Successful trace and complete context publication.
> 2. Missing context gives context_available=false.
> 3. Malformed context gives context_available=false.
> 4. Pending context gives context_available=false.
> 5. Hash mismatch gives context_available=false.
> 6. Complete-context publication failure after trace success returns 200 and leaves context unavailable.
> 7. Pending-marker publication failure prevents new trace publication and preserves previous trace bytes.
> 8. Trace publication failure after pending invalidation preserves the previous trace and leaves context unavailable.
> 9. Most importantly:
>    - Existing complete context refers to a different server snapshot.
>    - Its trace hash is identical to the new run trace.
>    - Final complete-context publication is forced to fail.
>    - The old context must not be returned as valid.
>    - context_available must be false.
>
> The last test must model an ordinary identical-trace/different-idle-server situation, not manual file tampering.
>
> ## 6. Metrics API
>
> Add:
>
> GET /api/simulations/latest/metrics
>
> Behavior:
>
> - 404 if run.jsonl does not exist.
> - 500 controlled JSON if the trace itself is corrupt, consistent with GET /latest.
> - 200 with trace-only metrics when context is unavailable.
> - 200 with enriched metrics when complete matching context is available.
> - Never recompute metrics in the frontend.
>
> Keep GET /latest/download behavior unchanged as raw file download.
>
> ## 7. Frontend synchronization
>
> Add:
>
> - StrategySelector.tsx
> - MetricsPanel.tsx
> - Tests for both
>
> App owns a monotonic runVersion or equivalent successful-run generation value.
>
> Every successful run, whether started from:
>
> - the existing RunPanel default button, or
> - StrategySelector
>
> must notify App and increment runVersion.
>
> RunPanel:
>
> - Accept runVersion.
> - Refetch GET /latest when it changes.
> - Preserve the existing stale-response generation protection.
> - A stale or slower GET response must never overwrite a newer result.
> - Avoid an infinite effect loop.
> - It is acceptable for the successful POST response to render immediately and then be confirmed by GET /latest.
>
> MetricsPanel:
>
> - Fetch GET /latest/metrics on mount and whenever runVersion changes.
> - Treat 404 as a normal no-run state.
> - Show trace-only values even when context_available=false.
> - Clearly state that enriched context is unavailable until a successful context-producing run.
> - Render busy ratio as an occupancy/CPU-pressure proxy.
> - Include loading, empty, error, partial-context, and complete-context states.
> - Use the same monotonic generation-token pattern so stale responses cannot win.
>
> StrategySelector:
>
> - Fetch the available strategy registry from the backend.
> - Default selection must be fastest_finish.
> - Trigger POST /run?strategy=...
> - Disable controls while running.
> - Display 400, 409, 422, network, and generic errors clearly.
> - On success, notify App so RunPanel and MetricsPanel refresh.
> - Do not duplicate scheduling knowledge in the frontend.
>
> Do not implement Timeline or AutoScalePanel in this phase.
>
> ## 8. Expected file scope
>
> Expected new files:
>
> backend/app/domain/metrics.py
> backend/app/services/run_context.py
> backend/tests/test_metrics.py
> backend/tests/test_run_context.py
> frontend/src/components/MetricsPanel.tsx
> frontend/src/components/MetricsPanel.test.tsx
> frontend/src/components/StrategySelector.tsx
> frontend/src/components/StrategySelector.test.tsx
> prompts/05_bonus_metrics_strategies.md
>
> Expected modified files:
>
> backend/app/config.py
> backend/app/domain/strategies.py
> backend/app/domain/errors.py
> backend/app/services/simulation_service.py
> backend/app/api/schemas.py
> backend/app/api/routes_simulation.py
> backend/.gitignore
> backend/tests/test_engine.py
> backend/tests/test_simulation_service.py
> backend/tests/test_api_simulation.py
> frontend/src/api/client.ts
> frontend/src/App.tsx
> frontend/src/index.css
> frontend/src/components/RunPanel.tsx
> frontend/src/components/RunPanel.test.tsx
> docs/DECISIONS.md
> docs/ARCHITECTURE.md
> README.md
>
> backend/tests/conftest.py may be modified only if isolated run_context_path fixtures genuinely require it. Explain why in the completion report.
>
> Do not modify:
>
> backend/app/domain/engine.py
> backend/app/domain/models.py
> backend/app/adapters/jsonl_trace.py serialization behavior
> provided/**
> docker-compose.yml
> backend/Dockerfile
> frontend/Dockerfile
> frontend/nginx.conf
> backend/data/run.jsonl final committed bytes
> docs/AI_USAGE.md during implementation
> Day 3B component files
>
> If the necessary file list differs, stop before editing and explain the discrepancy.
>
> Add exactly this runtime ignore entry:
>
> data/run_context.json
>
> Do not ignore data/run.jsonl.
>
> ## 9. Documentation
>
> Update README.md, docs/ARCHITECTURE.md, and docs/DECISIONS.md during Day 3A.
>
> Document:
>
> - Both strategy IDs and default selection.
> - Strategy query parameter.
> - Metrics definitions and formulas.
> - End-of-tick queue-depth semantics.
> - Busy-time ratio as an occupancy/CPU-pressure proxy.
> - Trace-only versus context-enriched fields.
> - Pending and complete context lifecycle.
> - Atomic publication and degradation behavior.
> - Identical-trace/different-server-snapshot protection.
> - run_context.json is runtime metadata and ignored by Git.
> - Default mandatory behavior remains unchanged.
> - Day 3B features remain unimplemented.
> - On a fresh clone with only the committed sample trace, enriched context is unavailable until a new simulation is run.
>
> Do not edit docs/AI_USAGE.md yet. Include a truthful proposed entry in the completion report for candidate review.
>
> ## 10. Tests and verification
>
> Backend:
>
> - Run all existing and new tests.
> - Add exact sample metric assertions.
> - Add exact percentile/empty/boundary cases as relevant.
> - Test strategy registry and unknown strategy 422.
> - Test both strategies with an input that produces different assignments.
> - Run the real validator against both traces.
> - Verify default no-query trace hash remains canonical.
> - Verify repeated runs for each strategy are byte-identical.
> - Verify all context publication failure paths above.
> - Ensure blocking or concurrency tests use Events/timeouts rather than sleeps.
>
> Frontend:
>
> - Run npm ci.
> - Run all existing and new tests.
> - Run production TypeScript/Vite build.
> - Test successful refresh propagation from both run controls.
> - Test stale-response protection.
> - Test partial-context metrics rendering.
> - Test array-detail and string-detail API errors through the real client wrapper.
>
> Docker smoke/E2E is mandatory before declaring Day 3A complete:
>
> 1. docker compose config
> 2. docker compose build
> 3. docker compose up -d
> 4. Wait for both containers to become healthy without relying on a fixed sleep.
> 5. Exercise through nginx on port 3000:
>    - GET strategies
>    - POST default run
>    - GET latest
>    - GET metrics
>    - POST lowest_id run
>    - GET latest
>    - GET metrics
> 6. Run the real validator inside the backend container for both strategies.
> 7. Demonstrate context survival across backend restart.
> 8. Demonstrate pending/missing context degrades safely.
> 9. Run one final default simulation after all alternate-strategy checks.
> 10. Confirm the final backend/data/run.jsonl hash is exactly:
>     225b3f69a060d1821c7756e40830a9274f595b516eeb74e3ff0bf0ca75201845
> 11. Stop containers with docker compose down.
>
> A true clean-clone verification can be performed after candidate review and commit. Do not claim it was performed if the changes remain uncommitted.
>
> ## 11. Stop conditions
>
> Stop after Day 3A when all of these are true:
>
> - All backend tests pass.
> - All frontend tests pass.
> - Frontend production build passes.
> - Both strategies pass the real validator.
> - Default no-query trace remains byte-identical.
> - Metrics sample values are exact.
> - Context failure tests, especially identical-trace/different-snapshot, pass.
> - Docker smoke/E2E passes.
> - Final runtime trace is restored to the canonical default.
> - git diff --check passes.
> - Only approved Day 3A files are changed.
> - No Day 3B feature has been started.
> - Nothing is staged, committed, tagged, or pushed.
>
> ## 12. Completion report
>
> Report:
>
> 1. Every changed and created file.
> 2. Architecture and dependency-direction changes.
> 3. Exact strategy behavior.
> 4. Exact metric formulas.
> 5. Context pending/complete publication lifecycle.
> 6. Context failure behavior.
> 7. Backend test count and full result.
> 8. Frontend test count and full result.
> 9. Validator results for both strategies.
> 10. Default and alternate determinism results.
> 11. Final canonical hash.
> 12. Docker smoke/E2E results.
> 13. Whether real browser testing was performed.
> 14. git diff --check and git status.
> 15. Known limitations.
> 16. Proposed docs/AI_USAGE.md entry.
> 17. Confirmation that Day 3B was not started.
>
> Do not commit, tag, push, edit docs/AI_USAGE.md, or begin Day 3B.
