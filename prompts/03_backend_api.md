# Prompt 03: Day 2A — Backend API (approved implementation instruction, verbatim)

This is the exact candidate instruction that approved and scoped the Day 2A
implementation (server CRUD API, simulation run/latest/download API, repository
and run locking, seeding, error mapping, and tests). Reproduced verbatim from the
session transcript, per the candidate's requirement that this file contain "this
exact approved Day 2A implementation instruction."

---

> Day 2A implementation is approved with the binding amendments below.
>
> Do not implement Day 2B. Do not create frontend, Docker, nginx, Compose,
> metrics, bonus strategies, visualization, autoscaling, or shared-CPU work. Do
> not commit or tag.
>
> Before editing:
> 1. Confirm git status is clean.
> 2. Confirm HEAD is ce03b29 and tag day1-complete points to it.
> 3. List every file to be created or modified.
> 4. Record the current SHA-256 of backend/data/run.jsonl.
> 5. Confirm automated tests will not write to the real backend/data directory.
>
> Implement the revised Day 2A plan with these mandatory corrections:
>
> 1. No automated test may instantiate default Settings() if doing so can run
>    lifespan seeding against the real backend/data directory.
>
>    To test the committed Day 1 trace behavior:
>    - create isolated temporary Settings
>    - copy backend/data/run.jsonl into that temporary data directory
>    - call GET /api/simulations/latest through the isolated app
>    - assert 200 and the expected summary
>
>    Never seed or modify the real backend/data directory during pytest.
>
> 2. Correct DECISIONS numbering:
>    - D-013 already belongs to the approved repository-layout decision:
>      standardized copies under provided/, originals retained and untouched
>    - D-014 runtime seeding
>    - D-015 CRUD repository locking
>    - D-016 simulation run locking
>    - D-017 PUT replacement and immutable IDs
>    - D-018 restart-safe latest reconstruction
>
>    Do not reuse D-013 for seeding.
>
> 3. Add explicit seeding tests in a new backend/tests/test_seeding.py:
>    - copies only servers.json and requests.csv when missing
>    - never creates or copies run.jsonl
>    - never overwrites an existing servers.json, including an intentionally
>      empty configuration
>    - never overwrites an existing requests.csv
>    - missing source produces a controlled startup failure
>
> 4. Seed publication should use a temporary file in the destination directory
>    plus os.replace(), rather than exposing a partially copied destination if
>    first-boot copying fails.
>
> 5. Add backend/tests/test_summary.py as an explicit new file rather than
>    leaving its location undecided.
>
> 6. Repository concurrency coverage must be capable of failing if the RLock is
>    removed. A barrier placed only before calling create() is merely a stress
>    test and is not sufficient by itself.
>
>    Add deterministic instrumentation around the load/save boundary, or an
>    equivalent controlled test, proving:
>    - all public writer methods acquire the shared repository lock
>    - two concurrent create operations cannot both perform stale
>      read-modify-write cycles
>    - both resulting servers remain persisted
>
> 7. Blocking concurrency and snapshot tests must:
>    - assert entered.wait(timeout=...) succeeded
>    - release blocking events in finally
>    - join threads with a timeout
>    - fail clearly instead of hanging the test suite
>
> 8. Keep the FastAPI create_app(Settings) factory and lifespan design.
>    - app = create_app(Settings()) remains only for Uvicorn
>    - all API tests use injected temporary Settings
>    - all filesystem routes remain synchronous def
>
> 9. Preserve the pure dependency direction:
>    - SimulationSummary is a frozen stdlib dataclass in domain
>    - domain imports no Pydantic or API types
>    - API maps SimulationSummary to RunSummary
>
> 10. Pydantic models must use extra="forbid".
>     - PUT with an id field returns 422
>     - IDs are trimmed and whitespace-only IDs return 422
>
> 11. Add httpx to dev dependencies and verify a clean editable installation.
>
> 12. Prompt and AI documentation:
>     - add prompts/02_simulation_engine.md as a clearly labelled historical
>       record of the actual Day 1 approved scope and correction prompts
>     - do not invent supposedly verbatim wording if it is unavailable; label
>       reconstructed material as a summary
>     - add prompts/03_backend_api.md containing this exact approved Day 2A
>       implementation instruction
>     - update docs/DECISIONS.md with D-013 through D-018
>     - do not edit docs/AI_USAGE.md yet
>     - completion report must propose truthful Day 1 and Day 2A AI_USAGE
>       entries for candidate review
>
> 13. Malformed latest trace returns a controlled 500 JSON response without
>     traceback disclosure.
>
> 14. A failed run must preserve the previous run.jsonl and previous
>     GET /latest result.
>
> 15. Snapshot semantics must prove:
>     - the in-flight run uses the server snapshot loaded before the repository
>       edit
>     - the next run uses the changed configuration
>
> 16. Preserve backend/data/run.jsonl byte-for-byte and preserve the Day 1
>     scheduling engine and strategy files unchanged.
>
> Completion gates:
> - all Day 1 and Day 2A pytest tests pass
> - real provided validator exits 0 against an API-triggered trace
> - deterministic run hash remains
>   225b3f69a060d1821c7756e40830a9274f595b516eeb74e3ff0bf0ca75201845
> - clean `pip install -e backend` succeeds
> - git diff --check succeeds
> - git status shows no unexpected runtime/generated files
> - backend/data/run.jsonl final hash equals its recorded pre-implementation hash
> - all 7 API endpoints are manually exercised with TestClient
> - no frontend or Docker files exist
> - no commit or tag is created
>
> At completion, stop and report:
> - every changed file
> - architecture and lock ownership
> - exact API behavior/status codes
> - complete tests and command output
> - validator output
> - determinism hash
> - package-install result
> - real backend/data preservation proof
> - known limitations
> - proposed AI_USAGE entries
> - git status
>
> Do not begin Day 2B.
