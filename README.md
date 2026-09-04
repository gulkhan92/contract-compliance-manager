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

- **Phase 0 — Project Scaffolding**: FastAPI backend skeleton with a health
  endpoint, React + Vite + TypeScript + Tailwind + shadcn/ui frontend
  skeleton, Docker images for both, a `docker-compose.yml` wiring
  Postgres+pgvector / api / worker / frontend, and CI running lint,
  type-check, tests, and build on every push.
- **Phase 1 — Data Layer**: async SQLAlchemy models for every table in the
  build plan's §5.3 schema, an Alembic migration history (enabling
  `pgvector` and creating HNSW cosine-similarity indexes), and a demo seed
  script that builds a realistic multi-status obligation calendar from the
  CUAD v1 dataset.
- **Phase 2 — Auth & RBAC**: register/login/refresh/logout, bcrypt password
  hashing, JWT access + refresh tokens (refresh tokens rotated on use and
  revocable via a `refresh_tokens` denylist table), `get_current_user` /
  `require_role(...)` FastAPI dependencies, rate limiting on auth endpoints,
  and audit-log entries on every state change.

See the build plan's §12 for the remaining phases.

## Repository layout

```
backend/    FastAPI app (Python 3.13, async SQLAlchemy + Alembic)
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
./.venv/Scripts/python -m mypy app scripts tests            # type-check
```

`requirements.txt` and `requirements-dev.txt` are fully pinned (`pip freeze`
output) for reproducible installs.

### Database — migrations & demo data

Requires a running Postgres with `pgvector` — either `docker compose up postgres`
from `infra/`, or a one-off container:

```bash
docker run -d --name oblitrack-pg -e POSTGRES_USER=oblitrack -e POSTGRES_PASSWORD=oblitrack \
  -e POSTGRES_DB=oblitrack -p 5432:5432 pgvector/pgvector:pg16
```

Then, from `backend/` with the venv active (`DATABASE_URL` defaults to
`postgresql+asyncpg://oblitrack:oblitrack@localhost:5432/oblitrack`, matching
the container above — override via `.env`/env var otherwise):

```bash
./.venv/Scripts/python -m alembic upgrade head        # apply all migrations
./.venv/Scripts/python -m alembic check                # verify models == migrations (no drift)
./.venv/Scripts/python -m alembic revision --autogenerate -m "..."   # after changing models

# Seed a demo org with sample contracts + a realistic obligation calendar,
# built from the CUAD v1 dataset (see data/README.md to fetch it):
./.venv/Scripts/python -m scripts.seed_demo_data --demo
./.venv/Scripts/python -m scripts.seed_demo_data --demo --limit 100 --reset
```

The `tests/db/` suite requires the database to be migrated first (`alembic
upgrade head`); each test runs inside a rolled-back transaction, so it never
leaves data behind.

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
request: backend lint (ruff) + type-check (mypy) against a real
Postgres+pgvector service container (migrations applied via `alembic
upgrade head`, checked for drift via `alembic check`) + tests (pytest), and
frontend lint (oxlint) + type-check (tsc) + tests (vitest) + build. All
checks must pass before merging.

## Configuration

All configuration is environment-variable driven — see
[`.env.example`](.env.example) for the full list. Never commit `.env`.
