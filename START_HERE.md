# Medsien Take-Home Control Pack

This pack establishes the source of truth and review workflow before Claude Code writes implementation code.

## 1. Copy the pack into the repository

Preserve this structure:

```text
CLAUDE.md
START_HERE.md
docs/
  SPEC.md
  DECISIONS.md
  AI_USAGE.md
prompts/
  01_architecture_plan.md
provided/
  assignment.pdf
  servers.json
  requests.csv
  run.jsonl
  validate_run.py
```

Copy the files supplied by Medsien into `provided/`. Keep their contents unchanged. The PDF may be copied as `assignment.pdf`; the other filenames should match the names above.

## 2. Create a Git checkpoint

Before using Claude Code:

```bash
git init
git add CLAUDE.md START_HERE.md docs prompts provided
git commit -m "Add assignment specification and AI control workflow"
```

Do not commit secrets, virtual environments, dependency folders, generated caches, or machine-specific settings.

## 3. Start Claude Code in Plan mode

From the repository root:

```bash
claude --permission-mode plan
```

Paste the complete contents of `prompts/01_architecture_plan.md` into Claude Code.

Claude must produce a read-only plan. It must not create the application yet.

## 4. Review before implementation

Bring Claude's proposed plan back for review. Check it against:

- The assignment PDF
- The provided validator
- `docs/SPEC.md`
- `docs/DECISIONS.md`
- The three-day delivery scope

Only after the plan is approved should an implementation prompt be prepared.

## 5. Milestone workflow

Use this loop for every implementation milestone:

1. Define one bounded goal.
2. Ask Claude for a plan before editing.
3. Approve or revise the plan.
4. Let Claude implement only that milestone.
5. Run tests and the provided validator.
6. Review the diff and understand the important code.
7. Record AI usage in `docs/AI_USAGE.md`.
8. Commit the verified milestone.

Suggested milestones:

1. Pure Python simulation engine and tests
2. FastAPI server CRUD and simulation API
3. React dashboard and simulation controls
4. Docker Compose and end-to-end verification
5. Metrics, trace visualization, and scheduling strategies
6. Auto-scaling recommendation module
7. Documentation and final clean-clone review

## Non-negotiable rule

Do not accept code that cannot be explained during the follow-up interview.
