# AI Usage and Verification Log

The assignment requires transparent documentation of AI assistance. Record actual usage only. Do not claim a test, review, or manual change that did not occur.

## Logging format

| Date | Task | Tool | Prompt summary or reference | AI contribution | Candidate decision or modification | Verification | Result |
|---|---|---|---|---|---|---|---|
| 2026-08-18 | Requirement and validator analysis | ChatGPT | Compared the assignment PDF, sample data, sample trace, and `validate_run.py` | Identified the concurrency and finish-time conflict between the PDF and validator | Chose a validator-compatible default mode with no per-server overlap, pending clarification | Inspected validator source and ran the supplied sample trace through it | Sample validated successfully; conflict recorded in specification |
| 2026-08-19 | AI-controlled delivery planning | ChatGPT | Designed a three-day milestone plan and a ChatGPT review plus Claude Code implementation workflow | Proposed source-of-truth files, quality gates, review checkpoints, and AI logging structure | Candidate selected Claude Code as implementation tool with ChatGPT for prompts and review | Candidate review pending; no application code generated in this step | Control pack created |
| 2026-08-19 | Day 1: simulation engine, adapters, repository, tests, correction pass | ChatGPT + Claude Code | `prompts/02_simulation_engine.md` | ChatGPT: independent assignment/validator analysis, architecture critique of the initial Day 1 implementation (ran 38 unit/integration tests, fed the sample and 200 randomized simulations through the real `validate_run.py`, reviewed the diff), and designed the correction-pass prompt (packaging fix, empty-`requests.csv` rejection boundary, `tick_seconds` validation, required-column validation, explicit sort, strengthened terminal-state test, atomic-publish-failure test, trailing newlines). Claude Code: implemented `backend/app/{domain,adapters,repository,services,api}`, authored and ran all tests, ran the real validator and determinism/package-install checks, wrote the completion reports. | Candidate approved both the initial Day 1 scope and the correction pass; set every hard constraint (integer `ceil_div`, explicit `SimulationDeadlockError` over `assert`, empty-input contract, genuine equal-runtime tie-break test, `provided/` copy-only with originals untouched, no git operations delegated); reviewed Claude Code's diffs and reports before approving each step; did not author any of the generated code by hand. | `pytest` 43/43, real `validate_run.py` exit 0 on the generated sample ("RESULT: VALID"), SHA-256 repeat-run determinism (`225b3f69a060d1821c7756e40830a9274f595b516eeb74e3ff0bf0ca75201845`), clean `pip install -e backend`, `git diff --check` clean — all executed and reported by Claude Code, reviewed by the candidate. | Day 1 mandatory backend foundation complete, frozen at Git tag `day1-complete` (commit `ce03b29`). No commit or tag created by Claude Code itself — Git remained under candidate control throughout. |
| 2026-08-19 | Day 2A: server CRUD + simulation API, locking, seeding, malformed-trace hardening | ChatGPT + Claude Code | `prompts/03_backend_api.md` | ChatGPT: adversarial review of the Day 2A plan and each successive implementation pass — flagged the empty-server-config vs. empty-request-input asymmetry, the CRUD read-modify-write lost-update window, the `time.sleep`-based concurrency test's weakness, the missing schema/lifecycle validation on reconstructed traces (including the ARRIVED→DROPPED→STARTED and ARRIVED→STARTED→DROPPED contradictions that a first hardening pass missed), the non-UTF-8-trace gap, and — via its independent diff review — identified a stale `docs/DAY2_PLAN.md` file that Claude Code's own file-list summary had omitted; designed all three correction-pass prompts (mandatory amendments, first hardening pass, this final pass), including the parameterized malformed-trace test list and the deterministic lock-instrumentation requirement. Claude Code: implemented the `create_app`/`lifespan` factory, RLock-protected repository CRUD, non-blocking run lock, pure `SimulationSummary`, strict two-file seeding, `JsonlTraceWriter` schema+lifecycle validation (including the STARTED/DROPPED-ordering fixes and UTF-8 decode translation), error-to-status mapping, all associated tests (112 total after this final pass, 37 of them in the dedicated malformed/corrupted-trace file), and ran every verification command. | Candidate approved Day 2A scope and all three correction passes; mandated isolated-`Settings`-only testing (never touching real `backend/data`), corrected the `docs/DECISIONS.md` numbering, required non-sleep-based deterministic concurrency proof, required timeout-guarded blocking tests, approved PUT-full-replace/500-on-corrupt-trace/seeding-scope policy choices; reviewed ChatGPT's diff-review finding on the stale `docs/DAY2_PLAN.md` file and approved its removal; reviewed Claude Code's diffs and reports at each step; retained Git and command-execution control throughout — Claude Code never committed or tagged anything. | `pytest` 112/112 (including 37 malformed/corrupted-trace and positive-lifecycle cases, plus a deterministic lock-instrumentation test), real `validate_run.py` exit 0 on an API-triggered trace, SHA-256 determinism unchanged (`225b3f69a060d1821c7756e40830a9274f595b516eeb74e3ff0bf0ca75201845`) even through the full HTTP/lock/summary pipeline across all three passes, clean `pip install -e backend[dev]` (incl. `httpx`), `git diff --check` clean, real `backend/data/run.jsonl` hash unchanged before/after every pass, manual 7-endpoint + `/health` walk. | Day 2A backend complete, including two corrective hardening passes. No Day 2B (frontend/Docker). Claude Code did not commit or tag; Git actions remained under candidate control. |
| YYYY-MM-DD |  |  |  |  |  |  |  |

## Prompt archive

Store substantial prompts under `prompts/` with stable filenames. Reference the filename from the table instead of duplicating long prompt text here.

Recommended naming:

```text
prompts/01_architecture_plan.md
prompts/02_simulation_engine.md
prompts/03_backend_api.md
prompts/04_frontend_dashboard.md
prompts/05_docker_e2e.md
prompts/06_bonus_features.md
prompts/07_final_review.md
```

## What to record

For each material AI-assisted milestone, record:

- What information the AI received
- What it was asked to produce
- Which suggestions were accepted or rejected
- What the candidate changed manually
- Tests, validator commands, diff review, or manual verification performed
- Remaining limitations

## Verification evidence

Prefer concrete evidence such as:

```text
pytest result
provided validator result
repeated-run hash comparison
frontend test or build result
docker compose build result
clean-clone startup result
manual API/dashboard scenario
git diff review
```

## Final AI-use summary template

```markdown
AI tools were used for requirement analysis, planning, bounded implementation,
test generation, and code review. The candidate retained ownership of architecture
and observable behavior. AI-generated changes were accepted only after diff review,
automated tests, validation with the supplied script, and manual explanation of the
relevant logic. The supplied validator and fixtures were not modified.
```
