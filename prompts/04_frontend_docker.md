# Prompt 04: Day 2B-2 — Docker, Compose, Documentation, E2E Verification (approved implementation instruction, verbatim)

This is the exact candidate instruction that approved and scoped the Day 2B-2
implementation (Docker images, Compose, nginx, dependency bounds,
README/ARCHITECTURE documentation, and end-to-end verification). Reproduced
verbatim from the session transcript.

---

> # Day 2B-2 Implementation: Docker, Compose, Documentation, and E2E Verification
>
> Implement only Day 2B-2.
>
> Day 1, Day 2A, and Day 2B-1 are frozen checkpoints. Do not alter their application behavior.
>
> Do not implement bonus features.
> Do not commit, amend, tag, push, stage, or change Git configuration.
> The candidate retains full control of Git operations.
>
> ## 0. Mandatory preflight
>
> Before editing anything, run and report:
>
> git rev-parse --short HEAD
> git tag --points-at HEAD
> git status --porcelain
> git log --oneline --decorate -5
>
> Required state:
>
> - HEAD is tagged day2b1-complete.
> - day2a-complete still exists at commit 254f3b3.
> - day1-complete still exists.
> - Working tree is clean, excluding ignored node_modules/dist/runtime files.
>
> If HEAD is not tagged day2b1-complete or the working tree has unexpected changes, stop and ask. Do not continue by guessing.
>
> Also record:
>
> - SHA-256 of backend/data/run.jsonl
> - Whether backend/data/servers.json exists
> - Whether backend/data/requests.csv exists
> - Current Docker and Docker Compose versions
> - Current backend and frontend test baselines
>
> Expected run.jsonl hash:
>
> 225b3f69a060d1821c7756e40830a9274f595b516eeb74e3ff0bf0ca75201845
>
> Before editing, list every file that will be created or modified.
>
> ## 1. Allowed file scope
>
> New files:
>
> backend/Dockerfile
> frontend/Dockerfile
> frontend/nginx.conf
> docker-compose.yml
> .dockerignore
> README.md
> docs/ARCHITECTURE.md
> prompts/04_frontend_docker.md
>
> Modified files:
>
> backend/.gitignore
> backend/pyproject.toml
> docs/AI_USAGE.md
>
> Do not modify:
>
> backend/app/**
> backend/tests/**
> frontend/src/**
> frontend/package.json
> frontend/package-lock.json
> frontend/tsconfig.json
> frontend/vite.config.ts
> provided/**
> backend/data/run.jsonl content
> docs/SPEC.md
> docs/DECISIONS.md
> CLAUDE.md
> START_HERE.md
>
> If implementation reveals a genuine need to modify anything outside the allowed scope, stop and request approval first.
>
> Do not add a new DECISIONS entry unless a genuinely new architectural decision appears. Do not silently amend existing decisions.
>
> As the first allowed documentation edit, archive this complete instruction verbatim in prompts/04_frontend_docker.md. It must be clearly labeled as the candidate-approved Day 2B-2 implementation instruction.
>
> ## 2. Backend Docker image
>
> Create backend/Dockerfile with these constraints:
>
> - Base image: python:3.12-slim
> - Build context: repository root
> - Runtime layout must preserve the existing config.py path contract:
>   - /app/backend/app
>   - /app/backend/data
>   - /app/provided
> - Selective COPY only:
>   - backend/pyproject.toml
>   - backend/app/
>   - provided/
> - Do not copy backend/tests, backend/data, local virtual environments, caches, or repository metadata into the image.
> - Install with:
>
>   pip install --no-cache-dir -e /app/backend
>
> - Editable installation is intentional and required. Do not replace it with a regular pip install because app.config derives runtime paths from __file__.
> - Install runtime dependencies only. Do not install the [dev] extra.
> - Set:
>   - PYTHONUNBUFFERED=1
>   - PYTHONDONTWRITEBYTECODE=1
> - Create /app/backend/data if needed.
> - WORKDIR must be /app/backend.
> - Expose port 8000.
> - Use a Python urllib-based health check against http://localhost:8000/health. Do not install curl solely for health checking.
> - CMD must run:
>
>   uvicorn app.api.main:app --host 0.0.0.0 --port 8000 --workers 1
>
> - --workers 1 is mandatory and must remain hardcoded because repository and simulation locks are process-local.
> - The image must contain /app/provided/validate_run.py so the evaluator can run the official validator inside the container.
>
> After building, prove that pytest and httpx are not installed in the runtime image.
>
> ## 3. Frontend Docker image and nginx
>
> Create frontend/Dockerfile using a multi-stage build.
>
> Build stage:
>
> - Base image: node:24-alpine
> - Build context: repository root
> - WORKDIR /app
> - Copy package.json and package-lock.json first.
> - Run npm ci.
> - Copy the frontend source.
> - Run npm run build.
> - Do not run npm install.
> - Do not modify package-lock.json.
> - Do not install packages globally.
>
> Runtime stage:
>
> - Base image: nginx:alpine
> - Copy only the generated dist output and frontend/nginx.conf.
> - No Node runtime or source files in the final image.
> - Add a frontend health check using the BusyBox wget available in nginx:alpine.
>
> frontend/nginx.conf requirements:
>
> - Serve the Vite production build from /usr/share/nginx/html.
> - Proxy /api/ to the backend service.
> - Preserve the /api prefix using matching paths:
>
>   location /api/ {
>       proxy_pass http://backend:8000/api/;
>   }
>
> - Add standard proxy headers:
>   - Host
>   - X-Real-IP
>   - X-Forwarded-For
>   - X-Forwarded-Proto
> - Serve index.html through try_files for the SPA fallback.
> - Do not add CORS. The browser uses same-origin relative /api URLs through nginx.
> - Do not add a router or modify frontend source code.
>
> ## 4. Docker Compose
>
> Create docker-compose.yml using modern Compose syntax without an obsolete version field.
>
> Backend service:
>
> - Build context: .
> - Dockerfile: backend/Dockerfile
> - Host port 8000 mapped to container port 8000.
> - Bind mount:
>
>   ./backend/data:/app/backend/data
>
> - Add a health check for /health.
> - Preserve the single-worker backend command.
> - Do not add databases, Redis, queues, or unrelated services.
>
> Frontend service:
>
> - Build context: .
> - Dockerfile: frontend/Dockerfile
> - Host port 3000 mapped to container port 80.
> - Depend on backend with condition: service_healthy.
> - Add an HTTP health check.
>
> Expected URLs:
>
> - Dashboard: http://localhost:3000
> - Backend health: http://localhost:8000/health
> - API through nginx: http://localhost:3000/api/servers
>
> The required startup command must remain:
>
> docker compose up --build
>
> No host Python or Node installation may be required for normal application startup.
>
> ## 5. Docker build context
>
> Create a root .dockerignore that excludes at least:
>
> - .git
> - .idea
> - .venv and virtual environments
> - Python caches and pyc files
> - pytest caches
> - egg-info
> - frontend/node_modules
> - frontend/dist
> - backend/data
> - local diff files
> - zip archives
> - editor and OS metadata
>
> Do not exclude provided/, backend/app/, backend/pyproject.toml, frontend source, package.json, or package-lock.json.
>
> ## 6. Runtime-generated files
>
> Modify backend/.gitignore to ignore exactly these runtime-seeded files:
>
> data/servers.json
> data/requests.csv
>
> Do not ignore:
>
> data/run.jsonl
>
> The committed deterministic trace must remain visible to Git and must retain its current SHA-256.
>
> Existing seeding behavior must remain unchanged:
>
> - Copy servers.json and requests.csv only when missing.
> - Never overwrite an existing runtime configuration.
> - Never seed or auto-run run.jsonl.
> - Never modify provided files.
>
> ## 7. Backend dependency bounds
>
> Inspect the existing backend/pyproject.toml before editing.
>
> Retain all current lower bounds and add only sensible compatibility ceilings that prevent accidental future major-version upgrades. For example:
>
> - FastAPI below 1.0
> - Pydantic below 3.0
> - Uvicorn below 1.0
> - pytest below its next unsupported major
> - httpx below 1.0
>
> Do not describe these ranges as a fully deterministic lockfile. They are compatibility bounds only.
>
> Do not add requirements.txt, Poetry, pip-tools, uv, or another dependency-management system.
>
> Run the complete backend test suite after changing the bounds and perform a clean editable installation in a temporary virtual environment.
>
> ## 8. README.md
>
> Write a concise evaluator-focused README containing:
>
> - Project purpose
> - Mandatory feature summary
> - Prerequisite: Docker with Docker Compose
> - One-command startup:
>
>   docker compose up --build
>
> - Dashboard and backend URLs
> - Server create/edit/delete instructions
> - How to run a simulation
> - How to download run.jsonl
> - Host-visible location: backend/data/run.jsonl
> - Exact official-validator command executed inside the container
> - Backend and frontend development test commands
> - How to stop containers
> - How first-boot seeding works
> - How to reset servers.json and requests.csv safely
> - Explicit warning that deleting runtime configuration files causes them to be re-seeded on the next startup
> - Single-Uvicorn-worker limitation and why it exists
> - Known out-of-scope items: authentication, database, multi-process coordination, bonus modules
> - Link to docs/ARCHITECTURE.md
> - A short AI-assisted-development disclosure pointing to docs/AI_USAGE.md
>
> Do not claim browser testing, clean-clone testing, or a verification result that was not actually performed.
>
> ## 9. docs/ARCHITECTURE.md
>
> Document:
>
> - Layer and dependency direction
> - Pure SimulationEngine boundary
> - Tick processing phases:
>   1. finishes
>   2. arrivals
>   3. permanent drops
>   4. scheduling
>   5. termination check
>   6. jump to next relevant tick
> - Half-open execution intervals
> - PDF versus validator concurrency conflict
> - Validator-compatible single-active-request default
> - Queue order and bypass policy
> - Permanent drop policy
> - Server selection tie-break
> - Determinism guarantees
> - rate_limit_per_sec behavior, including why values above 1 are inert in the mandatory single-active mode
> - Server snapshots
> - Atomic servers.json and run.jsonl publication
> - CRUD RLock and simulation Lock ownership
> - Single-worker constraint
> - First-boot seeding
> - Restart-safe latest-summary reconstruction
> - Persisted trace validation
> - Frontend component and state ownership
> - nginx and Docker Compose topology
> - Exact container path contract
> - Persistent bind mount
> - Mandatory versus bonus boundary
> - Assumptions, trade-offs, and known limitations
>
> Keep documentation aligned with the actual implementation. Do not describe unimplemented metrics, strategies, visualization, or autoscaling as complete.
>
> ## 10. docs/AI_USAGE.md
>
> After implementation and verification succeed, append one truthful entry covering Day 2B-1 and Day 2B-2.
>
> Distinguish roles clearly:
>
> - ChatGPT: architecture planning, adversarial diff review, correction-pass design, Docker/E2E prompt review
> - Claude Code: frontend implementation, race-condition corrections, Docker/Compose implementation, documentation, and command execution
> - Candidate: scope approval, architectural decisions, review, Git control, acceptance, and any manual browser verification
>
> Include:
>
> - prompts/04_frontend_docker.md
> - Frontend test result
> - Backend test result
> - Docker Compose result
> - Official validator result
> - Deterministic trace hash
> - Whether browser verification was actually performed
> - Whether true post-commit clean-clone verification is still pending
>
> Do not claim the candidate manually authored AI-generated code.
> Do not claim a verification step that did not occur.
>
> ## 11. Data-safety requirements before E2E
>
> Before starting containers:
>
> - Inspect backend/data/servers.json and requests.csv if they already exist.
> - If they contain user-edited data that differs from the supplied fixtures, stop and ask before overwriting or resetting anything.
> - Do not silently delete runtime files.
> - Use a unique temporary server ID for E2E CRUD.
> - Delete only that temporary server afterward.
> - Ensure the final server configuration is semantically equivalent to the provided sample before checking the expected trace hash.
> - Download temporary verification artifacts into a temporary directory, not the repository.
>
> ## 12. Verification matrix
>
> Run and report the exact commands and complete outcomes.
>
> ### Backend regression
>
> - Clean temporary virtual environment
> - pip install -e backend[dev]
> - Complete pytest suite
> - pip check
>
> All existing backend tests must remain green.
>
> ### Frontend regression
>
> From frontend/:
>
> - npm ci
> - npm ls react react-dom vite vitest --all
> - npm run test
> - npm run build
> - npm audit result
>
> All 38 frontend tests must remain green.
> TypeScript and Vite production build must succeed.
> The dependency tree must still contain one deduplicated Vite installation.
>
> ### Docker
>
> Run:
>
> docker compose config
> docker compose build --no-cache
> docker compose up -d
>
> Wait for both health checks to become healthy. Do not use blind fixed sleeps as the primary readiness mechanism.
>
> Verify:
>
> - GET http://localhost:8000/health returns 200.
> - GET http://localhost:3000 returns 200.
> - GET http://localhost:3000/api/servers returns 200.
> - Backend Settings resolve to:
>   - /app/provided
>   - /app/backend/data
> - Backend image does not contain backend/tests.
> - Backend runtime does not contain pytest or httpx.
> - Frontend final image does not contain Node or frontend source.
> - Backend runs with one Uvicorn worker.
>
> ### Proxy E2E
>
> Perform all application calls through port 3000 where applicable:
>
> 1. List servers.
> 2. Create a uniquely named temporary server.
> 3. Update it.
> 4. Delete it.
> 5. Confirm the authoritative server list is restored.
> 6. Trigger a simulation.
> 7. Fetch /api/simulations/latest.
> 8. Download run.jsonl to a temporary directory.
> 9. Confirm downloaded bytes match the published backend/data/run.jsonl.
>
> Record HTTP status codes and relevant response bodies.
>
> ### Official validator inside Docker
>
> Run the unmodified supplied validator inside the backend container:
>
> docker compose exec -T backend python /app/provided/validate_run.py --servers /app/backend/data/servers.json --requests /app/backend/data/requests.csv --run /app/backend/data/run.jsonl
>
> Required result:
>
> - Exit code 0
> - RESULT: VALID
> - Summary matches the known four-request sample
>
> ### Determinism
>
> Compute the host-side SHA-256 of backend/data/run.jsonl after the API-triggered container run.
>
> Required hash:
>
> 225b3f69a060d1821c7756e40830a9274f595b516eeb74e3ff0bf0ca75201845
>
> If it differs, stop and report the failure. Do not update the expected hash or normalize the output to hide the difference.
>
> ### Restart persistence
>
> Before restarting:
>
> - Capture GET /api/servers.
> - Capture GET /api/simulations/latest.
>
> Then:
>
> docker compose restart backend
>
> Wait for backend health, then repeat both requests through the nginx proxy.
>
> The server configuration and latest summary must be identical before and after restart.
>
> ### Cleanup and repository check
>
> Run:
>
> docker compose down
> git diff --check
> git status --short
>
> Confirm:
>
> - No pyc, cache, egg-info, node_modules, dist, or temporary download artifacts are tracked.
> - Runtime servers.json and requests.csv are ignored.
> - run.jsonl remains tracked and byte-identical.
> - Only the approved Day 2B-2 files changed.
>
> ## 13. Browser and clean-clone honesty
>
> Automated curl/proxy verification is not the same as visual browser verification.
>
> If no real browser interaction was performed, say so and provide the candidate with a short manual checklist:
>
> - Dashboard loads
> - Add/edit/delete server works
> - Run button shows summary
> - Refresh restores latest summary
> - Download link downloads run.jsonl
> - Layout remains usable at a narrow viewport
>
> A true clean-clone test cannot honestly include uncommitted Day 2B-2 changes. Do not claim one.
>
> For this pass:
>
> - Perform the complete current-tree Docker build and E2E verification.
> - State that true clean-clone verification is deferred until after candidate review and commit.
> - Do not create a commit merely to perform that test.
>
> ## 14. Stop conditions
>
> Stop after Day 2B-2 implementation and report.
>
> Do not:
>
> - begin bonus metrics, strategies, visualization, or autoscaling
> - alter simulation scheduling behavior
> - modify frontend application source
> - commit, tag, push, or stage
> - claim unperformed browser or clean-clone testing
>
> ## 15. Completion report
>
> The final report must include:
>
> - Every created and modified file
> - Docker architecture and path explanation
> - Dependency-bound changes
> - Backend test output
> - Frontend test/build output
> - Docker Compose build and health results
> - Complete proxy CRUD/run/download walkthrough
> - Official validator output and exit code
> - Determinism hash
> - Restart-persistence proof
> - Runtime image inspection
> - README and architecture-document coverage
> - AI_USAGE entry added
> - Browser verification status
> - Clean-clone verification status
> - git diff --check
> - git status --short
> - Known limitations
>
> Do not commit or tag. Stop and wait for candidate review.
