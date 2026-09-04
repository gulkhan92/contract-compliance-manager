# ObliTrack — Contract Lifecycle & Obligation Management System

A SaaS platform that ingests signed contracts (PDF/DOCX), automatically
extracts every obligation, deadline, renewal window, and monetary milestone
using LLM-based structured extraction, tracks them in a compliance calendar,
and proactively alerts the responsible person before anything is missed.

```
Contract Intake → Clause/Obligation Extraction → Obligation Tracking DB
   → Compliance Calendar → Automated Alerting → Renewal/Renegotiation Workflow
```

The full engineering specification — problem statement, architecture,
schema, security model, API surface, and phased build plan — lives in
[`docs/CONTRACT_CLM_BUILD_PLAN.md`](docs/CONTRACT_CLM_BUILD_PLAN.md).

## Status

**Phase 0 — Project Scaffolding** is complete: FastAPI backend skeleton with
a health endpoint, React + Vite + TypeScript + Tailwind + shadcn/ui frontend
skeleton, Docker images for both, a `docker-compose.yml` wiring
Postgres+pgvector / api / worker / frontend, and CI running lint,
type-check, tests, and build on every push. See the build plan's §12 for the
remaining phases.

## Repository layout

```
backend/    FastAPI app (Python 3.13, async SQLAlchemy in later phases)
frontend/   React 18 + Vite + TypeScript + Tailwind + shadcn/ui
infra/      docker-compose.yml (postgres+pgvector, api, worker, frontend)
data/       git-ignored reference datasets (see data/README.md)
docs/       engineering specification and design docs
```

## Backend — local setup

```bash
cd backend
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt -r requirements-dev.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt -r requirements-dev.txt  # macOS/Linux

./.venv/Scripts/python -m uvicorn app.main:app --reload   # serves http://localhost:8000
./.venv/Scripts/python -m pytest                          # run tests
./.venv/Scripts/python -m ruff check .                    # lint
./.venv/Scripts/python -m mypy app                         # type-check
```

`requirements.txt` and `requirements-dev.txt` are fully pinned (`pip freeze`
output) for reproducible installs.

## Frontend — local setup

```bash
cd frontend
npm install
npm run dev         # serves http://localhost:5173
npm run test         # vitest
npm run lint          # oxlint
npm run typecheck    # tsc --noEmit
npm run build         # production build
```

## Running everything with Docker Compose

```bash
cp .env.example .env   # fill in real secrets — see comments in the file
cd infra
docker compose up --build
```

This starts Postgres (with the `pgvector` extension), the API, the worker
process, and the frontend, wired together via `infra/docker-compose.yml`.

## CI

GitHub Actions (`.github/workflows/ci.yml`) runs on every push and pull
request: backend lint (ruff) + type-check (mypy) + tests (pytest), and
frontend lint (oxlint) + type-check (tsc) + tests (vitest) + build. All
checks must pass before merging.

## Configuration

All configuration is environment-variable driven — see
[`.env.example`](.env.example) for the full list. Never commit `.env`.
