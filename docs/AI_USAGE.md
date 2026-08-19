# AI Usage and Verification Log

The assignment requires transparent documentation of AI assistance. Record actual usage only. Do not claim a test, review, or manual change that did not occur.

## Logging format

| Date | Task | Tool | Prompt summary or reference | AI contribution | Candidate decision or modification | Verification | Result |
|---|---|---|---|---|---|---|---|
| 2026-08-18 | Requirement and validator analysis | ChatGPT | Compared the assignment PDF, sample data, sample trace, and `validate_run.py` | Identified the concurrency and finish-time conflict between the PDF and validator | Chose a validator-compatible default mode with no per-server overlap, pending clarification | Inspected validator source and ran the supplied sample trace through it | Sample validated successfully; conflict recorded in specification |
| 2026-08-19 | AI-controlled delivery planning | ChatGPT | Designed a three-day milestone plan and a ChatGPT review plus Claude Code implementation workflow | Proposed source-of-truth files, quality gates, review checkpoints, and AI logging structure | Candidate selected Claude Code as implementation tool with ChatGPT for prompts and review | Candidate review pending; no application code generated in this step | Control pack created |
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
