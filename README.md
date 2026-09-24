# ObliTrack — Enterprise Contract Lifecycle & Obligation Management Platform

[![Python](https://img.shields.io/badge/Python-3.13-blue.svg?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18-61DAFB.svg?logo=react&logoColor=black)](https://react.dev)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16%20%2B%20pgvector-336791.svg?logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![Docker](https://img.shields.io/badge/Docker-Multi--stage%20Non--root-2496ED.svg?logo=docker&logoColor=white)](https://docker.com)
[![Code Style](https://img.shields.io/badge/Code%20Style-Ruff-black.svg)](https://github.com/astral-sh/ruff)
[![Type Checked](https://img.shields.io/badge/Type%20Check-Mypy%20Strict-blue.svg)](https://mypy-lang.org)

**ObliTrack** is an enterprise-grade Contract Lifecycle Management (CLM) and Compliance Platform engineered for legal, procurement, and risk operations teams. It automatically ingests signed agreements, parses complex legal prose, extracts deadline-driven commitments, and generates an auditable, proactive compliance calendar — eliminating costly auto-renewals, overlooked termination windows, and missed milestone penalties.

---

## Executive Summary & Business Problem

Organizations execute hundreds of legally binding contracts annually — including Master Services Agreements (MSAs), Statements of Work (SOWs), Non-Disclosure Agreements (NDAs), commercial leases, software licenses, and vendor contracts. Crucial commitments remain trapped in unstructured PDF and DOCX attachments:

- **Renewal Notification Windows**: "Agreement automatically renews for successive 1-year terms unless either party gives written notice at least 60 days prior to the expiration date."
- **Termination for Convenience**: Strict timelines and formal notice delivery protocols.
- **Financial & Payment Milestones**: Net-30 payment triggers, price escalation clauses, and clawbacks.
- **SLA & Audit Rights**: Annual certification deadlines, security audit windows, and compliance covenants.

When obligations are tracked through spreadsheets or human memory, deadlines are inevitably missed. The financial and operational fallout is severe: unwanted multi-year contract renewals, lost leverage in renegotiation windows, and breach-of-contract liabilities.

**ObliTrack** bridges this gap by transforming static contract files into structured, queryable, and automated operational schedules backed by human-in-the-loop review and deterministic calendar math.

---

## System Architecture & End-to-End Pipeline

ObliTrack mirrors modern enterprise legal workflows through a cost-optimized, multi-stage processing funnel:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          1. Document Intake                                  │
│  - Authenticated Multipart Upload (PDF / DOCX)                              │
│  - Magic-Byte Content Validation (libmagic / zip structure verification)     │
│  - SHA-256 Checksum De-duplication & S3-compatible Persistent Storage       │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          2. Zero-Cost Funnel                                │
│  - Hierarchical Paragraph-Level Chunking & Section Heading Tracking         │
│  - Deterministic Regex Filter (dates, durations, currencies, legal triggers) │
│  - Local CPU Semantic Embedding via BAAI/bge-base-en-v1.5 (Zero Token Cost) │
│  - pgvector Cosine Precedent Cache Lookup (Similarity >= 0.97 skips LLM)     │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     3. Quota-Aware Dual-LLM Router                          │
│  - Primary: Groq API (openai/gpt-oss-20b / llama-3.3-70b-versatile)          │
│  - Failover: Google Gemini API (gemini-2.5-flash-lite)                     │
│  - Daily Token/Request Quota Tracking via llm_usage_log                     │
│  - Strict JSON Schema Constraints + 1-Shot Self-Healing Corrective Retry    │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                     4. Deterministic Date Arithmetic                        │
│  - Plain-Python Calendar Engine: computed_alert_date = trigger - notice_days │
│  - Automatic Status Lifecycle (upcoming → at_risk → overdue)                │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                5. Multi-Tenant Review, Calendar & Auditing                  │
│  - Human-in-the-Loop Review Triage (One-click confirm, edit, waive)         │
│  - Paragraph-Level Source Traceability (source_chunk_id, raw_source_text)   │
│  - Rolling Compliance Calendar Aggregations (/calendar)                     │
│  - Executive Dashboard Snapshot & Currency-Segmented Exposure               │
│  - Immutable Audit Logging on every state modification                       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Core Capabilities & Architectural Pillars

### 1. Zero-Cost Ingestion & Semantic Funnel
- **Regex & Keyword Pre-Filtering**: 70%+ of boilerplate contract clauses (definitions, recitals, notary blocks) are discarded before any model inference.
- **Local CPU Embeddings**: Surviving candidate chunks are embedded locally using `BAAI/bge-base-en-v1.5` (768-dimensional normalized vectors). Zero API calls, zero cost, and zero rate-limit exposure.
- **Org-Scoped Precedent Cache**: Clauses with $\ge 0.97$ cosine similarity to previously reviewed organizational clauses reuse cached extractions immediately, avoiding redundant LLM processing.

### 2. Resilient Dual-Provider LLM Orchestration
- **Dual Providers**: Routes first to high-speed Groq execution; automatically falls back to Google Gemini on rate limits (HTTP 429), server errors, or quota exhaustion.
- **Active Quota Accounting**: Pre-flight inspection against `llm_usage_log` guarantees requests stay within configured daily usage thresholds.
- **Pydantic v2 Schema Enforcement**: Extractions are strictly constrained to 12 CUAD-aligned obligation categories (`RENEWAL`, `TERMINATION_NOTICE`, `PAYMENT_MILESTONE`, `SLA_COMMITMENT`, etc.) with one automatic corrective retry on validation errors.

### 3. Deterministic Date Arithmetic
- **Zero Hallucination on Dates**: Critical deadline calculations are never delegated to probabilistic LLMs. Python's calendar math strictly calculates `computed_alert_date = trigger_date - notice_period_days`.
- **Dynamic Status Derivation**: Deadlines transition systematically between `upcoming`, `at_risk`, and `overdue` states based on the passage of time and configurable advance warning windows.

### 4. Human-in-the-Loop Review & Source Traceability
- **Confidence Triage**: Obligations with confidence score $< 0.7$ or high-consequence categories (`RENEWAL`, `TERMINATION_NOTICE`) flag the parent contract as `needs_review`.
- **Paragraph Traceability**: Every extracted obligation stores its `source_chunk_id` and `raw_source_text`, allowing legal counsel to view the exact contract sentence and section heading behind any extracted obligation.
- **Unified Review Endpoint**: A single idempotent PATCH endpoint handles one-click confirmations, field corrections, and waivers.

### 5. Multi-Tenant Security & Enterprise RBAC
- **Tenant Isolation**: Every database query and vector similarity search strictly enforces `organization_id` boundaries. Cross-tenant queries return HTTP 404 to eliminate ID enumeration vulnerabilities.
- **Role-Based Access Control**:
  - `admin`: Full configuration, user provisioning, contract intake, and review capabilities.
  - `legal_ops`: Contract upload, manual obligation creation, triage, editing, and deletion.
  - `viewer`: Read-only access to contracts, compliance calendars, and executive summaries.
- **Immutable Audit Trail**: Every creation, modification, confirmation, waiver, and deletion writes a comprehensive record to `audit_logs` tracking timestamp, user, action, and JSON change diffs.

---

## Phased Implementation Progress

ObliTrack is built through disciplined, incremental phases accompanied by full integration tests and architectural documentation.

| Phase | Milestone | Scope & Deliverables | Status |
| :--- | :--- | :--- | :---: |
| **Phase 0** | **Foundation & Tooling** | FastAPI, React/Vite, Docker, Alembic, GitHub Actions CI, security hardening | ✅ Complete |
| **Phase 1** | **Database & Tenant Models** | PostgreSQL 16 + pgvector schema, multi-tenant models, migrations | ✅ Complete |
| **Phase 2** | **Multi-Tenant Auth & RBAC** | JWT access/refresh token rotation, denylist revocation, role dependencies | ✅ Complete |
| **Phase 3** | **Document Ingestion** | Magic-byte file validation, PDF/DOCX chunking, regex pre-filtering | ✅ Complete |
| **Phase 4** | **Semantic Funnel & Cache** | Local CPU embeddings (`bge-base-en-v1.5`), pgvector precedent cache | ✅ Complete |
| **Phase 5** | **Structured LLM Extraction** | Dual-provider router (Groq + Gemini), quota tracking, corrective retry | ✅ Complete |
| **Phase 6** | **Obligation & Review APIs** | CRUD endpoints, human review triage, calendar math, audit trail, dashboard | ✅ Complete |
| **Phase 7** | **Scheduler & Alert Engine** | APScheduler background worker, automated scans, email notifications | 🔄 Next |
| **Phase 8** | **Frontend Application** | React dashboard, review queue, compliance calendar, chunk viewer | 📋 Queued |
| **Phase 9** | **Semantic Clause Search** | Org-wide hybrid retrieval (BM25 + vector search) across contracts | 📋 Queued |

*For in-depth architectural decisions, performance benchmarks, and implementation notes, see the [Engineering Walkthrough](docs/ENGINEERING_WALKTHROUGH.md).*

---

## Engineering Rigor & Quality Metrics

All metrics reflect current automated test suite results running against live PostgreSQL + pgvector containers:

| Dimension | Standard & Verification | Result |
| :--- | :--- | :--- |
| **Automated Test Suite** | 270+ integration and unit tests run with transactional rollback | **100% Passing** |
| **Static Type Coverage** | `mypy --strict` enforcing full type annotations across backend | **Clean (0 errors)** |
| **Code Formatting & Linting** | `ruff check` and `ruff format` across app, scripts, and tests | **Clean (0 warnings)** |
| **Dependency Hygiene** | `pip-audit` and `npm audit` checking full transitive dependency trees | **0 Known CVEs** |
| **Database Migrations** | Strict Alembic migration checks verifying zero schema-model drift | **Clean (11 tables)** |
| **Container Security** | Multi-stage Docker containers verified executing as non-root users | **Verified** |

---

## Technology Stack

| Layer | Technologies |
| :--- | :--- |
| **Backend API** | Python 3.13, FastAPI, Pydantic v2, Starlette, Uvicorn |
| **Database & ORM** | PostgreSQL 16, pgvector, SQLAlchemy 2.0 (AsyncIO), Alembic, asyncpg |
| **NLP & Vectors** | Hugging Face `sentence-transformers`, `BAAI/bge-base-en-v1.5` (768-dim) |
| **LLM Inference** | Groq Cloud API (`openai/gpt-oss-20b`, `llama-3.3`), Google Gemini REST API |
| **Document Parsing** | PyPDF, python-docx, pure-Python magic-byte validator |
| **Frontend SPA** | React 18, Vite, TypeScript, Tailwind CSS, Lucide Icons, TanStack Query |
| **Infrastructure** | Docker, Docker Compose, GitHub Actions CI/CD |

---

## Getting Started

### Prerequisites
- **Python**: `3.13+`
- **Node.js**: `22+`
- **Docker & Docker Compose** (for PostgreSQL + pgvector)

---

### Option A: Complete Platform via Docker Compose (Recommended)

1. **Clone the repository and copy the environment template**:
   ```bash
   git clone https://github.com/gulkhan92/contract-compliance-manager.git
   cd contract-compliance-manager
   cp .env.example .env
   ```

2. **Supply your API keys in `.env`**:
   ```env
   GROQ_API_KEY=your_groq_api_key_here
   GEMINI_API_KEY=your_gemini_api_key_here
   JWT_SECRET_KEY=your_secure_random_secret_here
   ```

3. **Build and launch all services**:
   ```bash
   cd infra
   docker compose up --build
   ```

   - **Backend API**: `http://localhost:8000`
   - **Interactive API Docs (Swagger)**: `http://localhost:8000/docs`
   - **Frontend UI**: `http://localhost:5173`
   - **PostgreSQL + pgvector**: `localhost:5432`

---

### Option B: Local Backend Development

1. **Start the database container**:
   ```bash
   cd infra
   docker compose up -d postgres
   ```

2. **Initialize Python environment**:
   ```bash
   cd ../backend
   python -m venv .venv

   # Windows
   .\.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt

   # macOS / Linux
   source .venv/bin/activate && pip install -r requirements.txt -r requirements-dev.txt
   ```

3. **Run database migrations and seed realistic demo data**:
   ```bash
   # Run migrations
   .\.venv\Scripts\python -m alembic upgrade head

   # Seed realistic contracts & obligations from CUAD dataset
   .\.venv\Scripts\python -m scripts.seed_demo_data --demo
   ```

4. **Run test suite and quality checks**:
   ```bash
   .\.venv\Scripts\python -m pytest tests/api/test_obligations.py -v   # Run Phase 6 obligation tests
   .\.venv\Scripts\python -m pytest                                   # Run full test suite (270+ tests)
   .\.venv\Scripts\python -m ruff check app tests                     # Lint check
   .\.venv\Scripts\python -m mypy app tests                           # Strict type check
   ```

5. **Start the development server**:
   ```bash
   .\.venv\Scripts\python -m uvicorn app.main:app --reload --port 8000
   ```

---

### Option C: Local Frontend Development

```bash
cd frontend
npm install
npm run dev         # Launches Vite dev server at http://localhost:5173
npm run test        # Executes Vitest unit tests
npm run typecheck   # Type verification via tsc --noEmit
npm run lint        # Code analysis via oxlint / eslint
```

---

## Repository Layout

```
contract-compliance-manager/
├── backend/
│   ├── alembic/                # Database migration revisions
│   ├── app/
│   │   ├── api/                # FastAPI routers (v1 endpoints)
│   │   │   ├── v1/
│   │   │   │   ├── auth.py         # Authentication & token endpoints
│   │   │   │   ├── contracts.py    # Contract upload & lifecycle endpoints
│   │   │   │   ├── obligations.py  # Phase 6 CRUD, review & calendar endpoints
│   │   │   │   ├── dashboard.py    # Executive metrics & aggregations
│   │   │   │   └── admin.py        # Audit logs & user administration
│   │   ├── core/               # Security, JWT tokens, config, rate limiting
│   │   ├── db/                 # Models, enums, database session managers
│   │   ├── schemas/            # Pydantic v2 schemas for requests & responses
│   │   └── services/           # Extraction, LLM providers, embeddings, ingestion
│   ├── scripts/                # Seeding and evaluation utilities
│   ├── tests/                  # Pytest test suite (api, unit, services)
│   └── pyproject.toml          # Ruff, Mypy, and Pytest configuration
├── frontend/                   # React 18 + TypeScript + Vite SPA
├── infra/                      # Docker Compose & container configurations
├── docs/                       # Technical architecture & engineering walkthroughs
└── README.md                   # Project overview & documentation
```

---

## Security & Disclosure

- **Multi-Tenant Protection**: Strict database-level isolation guarantees zero cross-organization data leakage.
- **Principle of Least Privilege**: Containers run with unprivileged user accounts (`UID 10001`).
- **Secrets Management**: No default secrets are permitted in production configurations; runtime validates JWT and database secrets before startup.

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
