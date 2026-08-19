# Claude Code Working Agreement

## Role

Act as an implementation engineer for the Medsien Load Balancer Simulation take-home project. The candidate remains the technical lead and final decision maker.

Do not make silent product, architecture, or scheduling decisions. Surface ambiguity and wait for approval when a decision would change observable behavior.

## Source-of-truth order

Read these sources before planning or implementation:

1. `provided/assignment.pdf`
2. `provided/validate_run.py`
3. `provided/servers.json`, `provided/requests.csv`, and `provided/run.jsonl`
4. `docs/SPEC.md`
5. `docs/DECISIONS.md`

The assignment PDF defines intended behavior. The provided validator defines the mandatory acceptance check for the submitted `run.jsonl`. Known conflicts are recorded in `docs/SPEC.md` and `docs/DECISIONS.md`; do not resolve them differently without explicit approval.

## General working rules

- Begin complex milestones in Plan mode.
- Do not edit files while the current task is read-only analysis or planning.
- Work on one bounded milestone at a time.
- State the files you intend to add or modify before implementation.
- Do not add a dependency without explaining why it is needed.
- Prefer simple, explicit, typed code over unnecessary abstractions.
- Keep business rules visible and testable.
- Never weaken tests to make an implementation pass.
- Never modify provided assignment files, fixtures, sample trace, or validator.
- Never commit, push, rewrite Git history, or open a pull request automatically.
- Never use destructive Git or filesystem commands.
- Never access or print secrets, credentials, `.env` contents, or unrelated files.
- Stop and ask if repository state conflicts with the requested milestone.

## Architecture boundaries

- The simulation engine must be pure Python and independent of FastAPI.
- API routes may orchestrate domain services but must not contain scheduling logic.
- React components must not reproduce backend scheduling or metrics logic.
- Server configuration persistence must be isolated behind a repository abstraction.
- Simulation input must be snapshotted at run start so dashboard changes affect future runs only.
- Generated traces and metrics must be derived from the same simulation result.

## Determinism rules

- Never depend on unordered set or dictionary traversal for observable output.
- Use documented request and server tie-break rules.
- Define a canonical event emission order.
- Serialize JSONL with stable field order and formatting.
- Repeating a run with identical server data, request data, and configuration must produce byte-identical `run.jsonl`.
- Add a repeatability test that compares exact output bytes or hashes.

## Mandatory quality gates

Do not begin bonus work until all of the following are true:

- Backend unit and integration tests pass.
- The provided example produces a valid `run.jsonl`.
- `provided/validate_run.py` exits successfully against the generated trace.
- Repeated runs produce byte-identical output.
- Server create, read, update, and delete operations work.
- Dashboard changes affect the next simulation run.
- The complete application starts using Docker Compose only.
- A clean-clone run has been documented.

## Verification expectations

After each implementation milestone, report:

1. Changed files
2. Important design choices
3. Commands executed
4. Test and validator results
5. Known limitations or follow-up risks
6. A concise explanation the candidate can repeat in an interview

Do not claim success when a required check was not run. Clearly distinguish passing checks from assumptions.

## AI usage log

After an approved milestone, propose a factual entry for `docs/AI_USAGE.md` containing:

- Task and prompt summary
- AI contribution
- Candidate decision or modification
- Verification performed
- Final result

Do not invent prompts, tests, or manual verification that did not happen.
