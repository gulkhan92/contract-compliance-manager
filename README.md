# Contract Lifecycle Management Platform

**Contract Lifecycle & Obligation Management for legal and procurement teams.**

## Overview

Every contract a company signs comes with a set of promises baked into its
fine print, a renewal that auto-triggers unless someone objects in time, a
termination window that closes after sixty days, a payment milestone tied
to a date nobody put on a calendar. None of that lives anywhere a computer
can see it. It lives in a PDF, in someone's memory, or in a spreadsheet
that's already a version behind.

Contract Lifecycle & Obligation Management platform is a system I designed and am building to close that gap: it ingests a signed contract, extracts every obligation, deadline, and
monetary milestone it contains, and turns that into a live, queryable
compliance calendar with proactive alerts, so a missed renewal window
becomes something that gets caught weeks in advance, not something legal
finds out about after the fact.

This repository contains the engineering build of the system, developed incrementally in well-defined phases. Each phase represents a functional, tested increment, allowing the system to evolve progressively while maintaining stability, consistency, and a clear foundation for subsequent development.

## The Problem

Organizations sign hundreds of contracts a year — vendor agreements,
NDAs, leases, MSAs, licenses. Each one contains obligations buried in
dense, inconsistently formatted legal prose: renewal notice deadlines
("either party may terminate with 60 days' written notice before the
renewal date"), payment triggers, SLA commitments, compliance
requirements. Today, tracking that lives in people's memory, email
threads, or spreadsheets that go stale the moment they're created.

The cost of that gap is concrete: auto-renewals nobody wanted, termination
windows missed that lock a company into another year of unfavorable
terms, payment triggers missed that damage vendor relationships. It's a
data-extraction and monitoring problem wearing a legal-process costume —
which is exactly the kind of problem software is good at, if built
carefully enough to be trusted with legally binding dates.

## Who Has This Problem

- **Legal ops teams and in-house counsel**, who own contract risk but are
  tracking it manually across dozens or hundreds of active agreements.
- **Procurement and vendor managers**, who need to know when a vendor
  contract is coming up for renewal or renegotiation before it's too late
  to act.
- **SMBs without a dedicated legal function**, where contract tracking
  falls to whoever remembers to check — which is precisely how renewal
  windows get missed.

## What I Built

Contract Lifecycle & Obligation Management Platform mirrors the real CLM (Contract Lifecycle Management) workflow
used by enterprise tools like Ironclad and ContractPodAi — not a single
clause-classification demo, but the full pipeline:

```
Contract Intake → Clause/Obligation Extraction → Obligation Tracking DB
   → Compliance Calendar → Automated Alerting → Renewal/Renegotiation Workflow
```

**Delivered so far** (Phases 0–6 of the build — see
[Engineering Walkthrough](docs/ENGINEERING_WALKTHROUGH.md) for the full,
step-by-step account):

- **A production-shaped foundation** — FastAPI backend, React frontend,
  Dockerized end to end, CI enforcing lint/type-check/tests/security scans
  on every push, both container images hardened to run as non-root.
- **Multi-tenant auth & RBAC** — JWT access/refresh tokens with rotation
  and a revocation denylist, role-based access control, rate-limited auth
  endpoints, and an audit trail on every state-changing action.
- **A real document ingestion pipeline** — authenticated multipart
  upload with magic-byte file validation (not just trusting the file
  extension), PDF/DOCX parsing into paragraph-level chunks, and a
  deterministic pre-filter that flags obligation-bearing text before
  anything more expensive touches it.
- **Local semantic search & dedup** — every candidate paragraph is embedded on
  CPU via a locally-run sentence-transformer model (zero API cost, zero
  rate limit), stored in Postgres via `pgvector`, matched against a
  fixed reference set per obligation category, and cross-referenced with
  `clause_precedent_cache` to skip repeat LLM calls.
- **Batched structured LLM extraction** — dual-provider strategy (Groq primary,
  Gemini fallback) with quota-aware routing via `llm_usage_log`, Pydantic v2
  schema validation, 1-shot corrective retry, deterministic date arithmetic,
  and human-in-the-loop review gating.
- **Obligation & Review APIs** — complete CRUD with multi-tenant org isolation,
  role-based editing (`require_role`), human-in-the-loop triage/confirmation
  (`obligation.confirm`, `obligation.waive`, `obligation.edit`, `obligation.delete`),
  automatic date arithmetic (`computed_alert_date`, `status`), compliance
  calendar aggregation (`/calendar`), and audit trail generation on every mutation.


### Key Architectural Principles

- **Zero-Cost Funnel:** Ingested documents pass through deterministic regex filtering, local CPU embeddings (`bge-base-en-v1.5`), and `pgvector` deduplication before triggering any paid or rate-limited LLM API calls.
- **Strict Multi-Tenant Isolation:** Every relational query and vector similarity lookup is strictly filtered by the authenticated user's `organization_id` at the database level.
- **Quota-Aware Failover:** Dual LLM providers (Groq primary, Gemini fallback) with automated quota tracking and Pydantic v2 validation guarantee deterministic structured extractions.


## Results & Engineering Rigor

Numbers that are true today, not projections:

| | |
|---|---|
| **Automated tests** | 95, all passing, run against a real Postgres+pgvector instance in CI |
| **Type coverage** | `mypy --strict` clean across the entire backend (app, scripts, and tests) |
| **Dependency security** | Zero known vulnerabilities (`pip-audit` + `npm audit`), including the ML dependency tree |
| **Database schema** | 11 tables, fully migration-managed via Alembic, zero schema drift between models and migrations |
| **Container security** | Both Docker images verified running as non-root |
| **CI coverage** | Lint, type-check, tests, migration-drift check, dependency audit, and a Docker build smoke test — on every push |

The token-minimization design (regex pre-filter, then local semantic
similarity, then clause-level dedup — all before any paid LLM call) is
built and tested end-to-end through Phase 6, including dual-provider failover
(Groq primary, Gemini fallback), quota tracking, precedent cache reuse, and
full obligation lifecycle management with an immutable audit log.


## How to Run It

### Prerequisites

Python 3.13, Node 22+ (vitest 5 requires it), Docker (for Postgres+pgvector,
or run it directly).

### Backend

```bash
cd backend
python -m venv .venv
./.venv/Scripts/pip install -r requirements.txt -r requirements-dev.txt   # Windows
# source .venv/bin/activate && pip install -r requirements.txt -r requirements-dev.txt  # macOS/Linux

./.venv/Scripts/python -m uvicorn app.main:app --reload   # http://localhost:8000
./.venv/Scripts/python -m pytest                          # 76 tests
./.venv/Scripts/python -m ruff check .                     # lint
./.venv/Scripts/python -m mypy app scripts tests            # type-check
```

`requirements.txt` / `requirements-dev.txt` are fully pinned (`pip freeze`
output) for reproducible installs.

With a Postgres+pgvector instance running (see Docker Compose below, or
`docker run -d -e POSTGRES_USER=oblitrack -e POSTGRES_PASSWORD=oblitrack
-e POSTGRES_DB=oblitrack -p 5432:5432 pgvector/pgvector:pg16`):

```bash
./.venv/Scripts/python -m alembic upgrade head          # apply migrations
./.venv/Scripts/python -m scripts.seed_demo_data --demo   # optional: realistic demo data from CUAD
```

The first request that needs the embedding model (Phase 4) downloads and
caches `BAAI/bge-base-en-v1.5` (~440MB) from Hugging Face — a one-time
cost per machine. On a constrained or proxied network, prefix commands
with `HF_HUB_DISABLE_XET=1` to force a plain HTTP download instead of
Hugging Face's newer chunked-transfer backend.

### Frontend

```bash
cd frontend
npm install
npm run dev         # http://localhost:5173
npm run test          # vitest
npm run lint           # oxlint
npm run typecheck     # tsc --noEmit
npm run build          # production build
```

### Everything, via Docker Compose

```bash
cp .env.example .env   # fill in real secrets
cd infra
docker compose up --build
```

Starts Postgres (with `pgvector`), the API, the background worker, and the
frontend — wired together via `infra/docker-compose.yml`.

## Repository Layout

```
backend/    FastAPI app — Python 3.13, async SQLAlchemy + Alembic
frontend/   React 18 + Vite + TypeScript + Tailwind + shadcn/ui
infra/      docker-compose.yml (postgres+pgvector, api, worker, frontend)
data/       git-ignored reference datasets (see data/README.md)
docs/       engineering documentation
```

## Configuration

All configuration is environment-variable driven — see
[`.env.example`](.env.example) for the full list. Never commit `.env`.

## License

All rights reserved. See [`LICENSE`](LICENSE).
