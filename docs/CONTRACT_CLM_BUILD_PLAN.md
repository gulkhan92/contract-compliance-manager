# Legal Contract Lifecycle & Obligation Management System — Master Build Plan

**Document purpose:** This is a complete, self-contained engineering specification for building this application end-to-end, in phases, without needing further product clarification along the way. Follow the phases in order. Do not skip the schema/security/testing steps to "move faster" — this is a production-grade SaaS deliverable, not a prototype.

---

## 1. Project Overview

**Name (working title):** ObliTrack — Contract Lifecycle & Obligation Management System

**One-line pitch:** A SaaS platform that ingests signed contracts (PDF/DOCX), automatically extracts every obligation, deadline, renewal window, and monetary milestone using LLM-based structured extraction, stores them in a compliance calendar, and proactively alerts the responsible person before anything is missed.

**Who it's for:** Legal ops teams, in-house counsel, procurement/vendor managers, and SMBs who currently track contract deadlines in spreadsheets and miss auto-renewal windows or termination notice periods.

**What makes this "real" software, not a toy classifier:**
This is not a single clause-classification demo. It mirrors the actual CLM (Contract Lifecycle Management) workflow used by tools like Ironclad and ContractPodAi:

```
Contract Intake  →  Clause/Obligation Extraction  →  Obligation Tracking DB
      →  Compliance Calendar  →  Automated Alerting  →  Renewal/Renegotiation Workflow
```

Every one of these six stages must exist as a working feature, not just the extraction step.

---

## 2. Problem Statement

Organizations sign hundreds of contracts a year (vendor agreements, NDAs, leases, MSAs, licenses). Each contract contains buried, unstructured obligations: renewal notice deadlines (e.g., "either party may terminate with 60 days' written notice before the renewal date"), payment milestones, SLA commitments, and compliance requirements. Today, this tracking lives in people's memory, email threads, or ad-hoc spreadsheets that go stale. The result: auto-renewals nobody wanted, missed termination windows that lock a company into unfavorable terms for another year, and missed payment triggers that damage vendor relationships.

**The system must solve three sub-problems:**
1. **Extraction accuracy** — reliably pull structured obligations (who, what, when, how much, trigger condition) out of long, inconsistently formatted legal prose, with a human-in-the-loop review step because legal extraction is never 100% automatable.
2. **Never-miss tracking** — turn extracted dates into a live, queryable calendar with configurable lead-time alerts (e.g., "alert 90/60/30/7 days before auto-renewal").
3. **Cost-efficient at scale** — do this using free-tier LLM APIs without blowing through rate limits, by minimizing what gets sent to the LLM in the first place.

---

## 3. Core Design Principle: Minimize LLM Token Usage Per Contract

This is a first-class architectural requirement, not an afterthought. Free-tier LLM quotas (Groq: ~1,000 requests/day, ~200K tokens/day on `openai/gpt-oss-20b`; Gemini free tier: single/low-digit to low-teens RPM and a few hundred to ~1,500 RPD depending on model) mean a naive "send the whole contract to the LLM" approach will exhaust quota after a handful of contracts. CUAD's own analysis shows labeled/important clauses make up only **~10% of a contract's text on average** — the rest is boilerplate, recitals, and signature blocks. We exploit this.

**The extraction pipeline must follow this exact cost funnel (cheapest filters first, LLM last):**

1. **Deterministic pre-filter (zero LLM cost):** Parse the document into paragraphs/sections. Run regex + `dateutil`/`dateparser` based candidate detection for anything that looks like a date, a duration ("30 days", "90 days prior", "net 60"), a currency amount, or renewal/termination/indemnity/payment keywords. This flags candidate paragraphs and immediately discards obvious boilerplate (definitions, recitals, notarization blocks, signature pages).
2. **Local embedding similarity filter (zero LLM cost, free open-source model):** Embed every remaining paragraph with a locally-run HuggingFace sentence-transformer (see §5). Compare against a small fixed set of reference embeddings representing each CUAD-derived obligation category ("renewal clause", "termination for convenience", "payment milestone", "notice period", etc.). Keep only paragraphs above a similarity threshold. This is a second free filter that further narrows what reaches the LLM, and doubles as the semantic search / "precedent clause lookup" feature exposed later in the product.
3. **Deduplication via embeddings (zero LLM cost):** Many contracts reuse boilerplate templates. Before calling the LLM, hash-compare and embedding-compare each candidate paragraph against previously-extracted paragraphs (org-wide, stored in pgvector). If a near-duplicate (cosine similarity above threshold, e.g. 0.97) was already extracted before, **reuse the cached structured result** instead of re-calling the LLM.
4. **Single batched, schema-constrained LLM call per contract (LLM cost — minimized):** All surviving candidate paragraphs for one contract are concatenated (with paragraph IDs) into **one** prompt (or as few as fit in context) that asks the LLM to return **all** obligations across **all** categories in one JSON response validated against a Pydantic schema — never one call per clause type, never one call per paragraph. This is the single biggest token-saving decision: extracting 10 obligation types in 1 call instead of 10 calls avoids repeating system-prompt + document context 10 times.
5. **Deterministic post-processing (zero LLM cost):** All calendar math (adding notice periods to renewal dates, computing "alert 30 days before X"), status transitions, and reminder scheduling is done in plain Python (`dateutil.relativedelta`), never delegated to the LLM.

**Dual-provider failover (also a cost/availability strategy):**
- **Primary:** Groq `openai/gpt-oss-20b` — extremely fast, generous free daily token budget, used for the batched structured-extraction call.
- **Secondary / fallback:** Google Gemini (`gemini-2.5-flash` or `gemini-2.5-flash-lite`, whichever the account's live quota favors) — used automatically when Groq returns a 429 (rate limit) or is unavailable, and for the optional plain-language contract summary feature (kept as a single short call).
- The app must track today's used-quota per provider in the database (`llm_usage_log` table) and pick whichever provider has headroom **before** making a call, rather than trying-and-catching-429 on every request. Fall back to the other provider automatically, and if both are exhausted, queue the job for retry with a "pending — quota exhausted" status instead of failing silently.
- Both providers are called through a single internal `LLMProvider` abstraction (strategy pattern) so swapping/adding a third provider later is a one-file change.

---

## 4. Tech Stack (100% free / open-source)

| Layer | Technology | Why |
|---|---|---|
| Backend framework | **FastAPI** (Python 3.11+) | Async, automatic OpenAPI docs, Pydantic-native (perfect for schema-constrained LLM output validation) |
| Language | **Python 3.11+** | |
| Database | **PostgreSQL 16 + pgvector extension** | Relational integrity for obligations/dates/users + native vector similarity search for clause dedup and precedent lookup, in one database (no separate vector DB service to run/pay for) |
| ORM | **SQLAlchemy 2.0 (async) + Alembic** | Migrations, type-safe models |
| Auth | **JWT (access + refresh tokens) via `python-jose`, password hashing via `passlib[bcrypt]`** | Stateless auth, refresh-token rotation |
| Authorization | Custom **RBAC** (Role-Based Access Control): `Admin`, `LegalOps`, `Viewer` roles, enforced via FastAPI dependencies | |
| Background jobs / scheduler | **APScheduler** (in-process, `AsyncIOScheduler`, `SQLAlchemyJobStore` for persistence) | Free, no separate broker/service needed (Celery would require Redis/RabbitMQ as extra infra — APScheduler is sufficient for a scheduled daily "scan obligations, send alerts" job and is simpler to self-host for free) |
| Document parsing | **PyMuPDF (`fitz`)** for PDF text/section extraction, **python-docx** for DOCX | Both free, open-source |
| Embeddings | **`BAAI/bge-base-en-v1.5`** (or `BAAI/bge-small-en-v1.5` for lower-resource environments) via **`sentence-transformers`**, run locally on CPU | Free, open-source, strong MTEB retrieval scores, no API cost or rate limit, runs entirely offline — this is what makes the dedup/pre-filter step in §3 free |
| Structured extraction LLM | **Groq API — `openai/gpt-oss-20b`** (primary) | Free tier, ~1,000 req/day, ~200K tokens/day, very fast (>750 tok/s) |
| Fallback / secondary LLM | **Google Gemini API — `gemini-2.5-flash-lite`** (fallback), `gemini-2.5-flash` optional for summaries | Free tier, generous TPM, large context window as backup capacity |
| LLM output validation | **Pydantic v2** schemas + Groq/Gemini JSON-mode / function-calling | Guarantees structured, parseable extraction output every time |
| Email alerting | **SMTP via a free-tier provider** (e.g. a personal Gmail SMTP app-password for dev, or any free-tier transactional email provider — see §11 for provider notes) sent through Python `aiosmtplib` | Free at low volume |
| Frontend framework | **React 18 + Vite + TypeScript** | |
| Frontend styling | **Tailwind CSS + shadcn/ui** | Free, professional-looking components fast |
| Frontend data/state | **TanStack Query (React Query)** for server state, **Zustand** for light client state | |
| Charts (dashboard) | **Recharts** | Free |
| API contract | OpenAPI schema auto-generated by FastAPI, consumed by frontend via **`openapi-typescript`** codegen | Keeps FE/BE types in sync automatically |
| Containerization | **Docker + docker-compose** (api, worker/scheduler, postgres+pgvector, frontend) | Free, reproducible local + deploy environment |
| Testing (backend) | **pytest, pytest-asyncio, httpx.AsyncClient, factory_boy** | |
| Testing (frontend) | **Vitest + React Testing Library** | |
| CI | **GitHub Actions** (free for public/limited private minutes) | Lint, type-check, test, build on every PR |
| Secrets management | **`.env` + `pydantic-settings`**, never committed | |

> Paid-tier alternatives exist for every free component above (e.g., managed Postgres, Celery+Redis, SendGrid, Vercel Pro, Groq/Gemini paid tiers for higher throughput) — those are intentionally **not** included in this plan per your instruction to keep the build 100% free-tier. If you want them listed, ask separately; do not add them into this file.

---

## 5. Data & Schema Foundations

### 5.1 Reference dataset — CUAD
Use the **Contract Understanding Atticus Dataset (CUAD) v1** (510 contracts, 13,000+ expert annotations, 41 clause categories, CC BY 4.0 license, available on Hugging Face as `theatticusproject/cuad-qa` and at atticusprojectai.org) for:
- Building the fixed set of reference/anchor embeddings per obligation category used in the local pre-filter (§3 step 2).
- Validating extraction quality (precision/recall against ground-truth spans) before trusting the pipeline on real uploads.
- **Not** for fine-tuning a model from scratch — that's out of scope for a free-tier build. Instead, CUAD is used as (a) an evaluation/validation set and (b) a source of realistic sample contracts to seed the demo/staging environment.

Map CUAD's 41 categories down to a smaller, product-relevant **obligation taxonomy** (this is what the LLM extraction schema targets):
`RENEWAL`, `TERMINATION_NOTICE`, `PAYMENT_MILESTONE`, `SLA_COMMITMENT`, `INDEMNIFICATION`, `CONFIDENTIALITY`, `NON_COMPETE`, `LIMITATION_OF_LIABILITY`, `GOVERNING_LAW`, `AUDIT_RIGHTS`, `DATA_PROTECTION`, `OTHER_OBLIGATION`.

### 5.2 Synthetic obligation calendar for demo
Since CUAD gives clause text but not a live obligation calendar, generate a synthetic set of "obligation calendar" rows (future dates relative to today, varied lead times, varied statuses: upcoming/at-risk/overdue/resolved) from the extracted CUAD clauses, so the dashboard has a realistic multi-month view to demo without waiting on real user uploads. Seed this via an `scripts/seed_demo_data.py` script, not hardcoded into migrations.

### 5.3 Core PostgreSQL schema (build via Alembic migrations — do not hand-write DDL)

```
organizations
  id (uuid, pk), name, created_at

users
  id (uuid, pk), org_id (fk), email (unique), hashed_password,
  role (enum: admin, legal_ops, viewer), full_name, is_active, created_at

contracts
  id (uuid, pk), org_id (fk), uploaded_by (fk users),
  title, counterparty_name, contract_type (enum, CUAD-derived: NDA, MSA, Lease, License, Employment, Vendor, Other),
  original_filename, storage_path, file_hash (sha256, for exact-duplicate detection),
  status (enum: processing, needs_review, active, expired, terminated, error),
  effective_date, original_expiration_date, governing_law, contract_value, currency,
  extraction_confidence (float, 0-1), created_at, updated_at

contract_chunks
  id (uuid, pk), contract_id (fk), paragraph_index, section_heading,
  raw_text, embedding (vector(768)),         -- pgvector column
  is_boilerplate (bool), passed_prefilter (bool)

obligations
  id (uuid, pk), contract_id (fk), source_chunk_id (fk contract_chunks, nullable),
  category (enum: RENEWAL, TERMINATION_NOTICE, PAYMENT_MILESTONE, SLA_COMMITMENT,
            INDEMNIFICATION, CONFIDENTIALITY, NON_COMPETE, LIMITATION_OF_LIABILITY,
            GOVERNING_LAW, AUDIT_RIGHTS, DATA_PROTECTION, OTHER_OBLIGATION),
  description (text, LLM-generated plain-English summary of the obligation),
  responsible_party (text),                  -- "us" / counterparty name / specific role
  trigger_date (date, nullable),              -- the actual deadline/renewal/payment date
  notice_period_days (int, nullable),         -- e.g. 60 for "60 days written notice"
  computed_alert_date (date, nullable),       -- trigger_date - notice_period_days, computed in Python
  monetary_amount (numeric, nullable), currency (text, nullable),
  recurrence (enum: none, monthly, quarterly, annually),
  status (enum: upcoming, at_risk, overdue, resolved, waived),
  confidence_score (float),
  is_human_reviewed (bool, default false),
  assigned_to (fk users, nullable),
  raw_source_text (text),                     -- exact clause text this was extracted from, for auditability
  created_at, updated_at

alerts
  id (uuid, pk), obligation_id (fk), alert_type (enum: email, in_app),
  scheduled_for (timestamptz), sent_at (timestamptz, nullable),
  status (enum: pending, sent, failed, cancelled), recipient_user_id (fk users)

extraction_jobs
  id (uuid, pk), contract_id (fk), status (enum: queued, running, succeeded, failed),
  llm_provider_used (enum: groq, gemini), tokens_used_estimate (int),
  started_at, finished_at, error_message (text, nullable)

llm_usage_log
  id (uuid, pk), provider (enum: groq, gemini), date (date),
  requests_used (int), tokens_used (int), last_updated_at
  -- one row per provider per day; incremented after every call; read before every call to pick provider

clause_precedent_cache
  id (uuid, pk), org_id (fk), text_hash (sha256), embedding (vector(768)),
  category, cached_extraction (jsonb), hit_count (int), created_at
  -- powers the dedup step in §3.3 and the "precedent lookup" UI feature

audit_log
  id (uuid, pk), org_id (fk), user_id (fk, nullable), action, entity_type, entity_id,
  metadata (jsonb), ip_address, created_at
```

Add a pgvector **ivfflat** or **HNSW** index on `contract_chunks.embedding` and `clause_precedent_cache.embedding` for fast similarity search once data volume grows.

---

## 6. Security, Authentication & Authorization (must not be an afterthought)

1. **Password storage:** bcrypt via `passlib`, never plaintext, never reversible encryption.
2. **Auth flow:** JWT access token (short-lived, 15 min) + JWT refresh token (long-lived, 7 days, stored as httpOnly secure cookie, rotated on use, revocable via a `refresh_tokens` denylist table).
3. **Authorization:** every endpoint declares required role via a FastAPI dependency (`require_role("admin")` etc.); all data access is additionally scoped by `org_id` extracted from the JWT — never trust an `org_id` passed in a request body/query. This is a strict multi-tenant boundary: every SQL query touching `contracts`, `obligations`, etc. must filter by the authenticated user's `org_id`.
4. **Transport security:** enforce HTTPS in production (reverse proxy/deployment concern, documented in §11), `Secure`/`HttpOnly`/`SameSite=strict` cookies.
5. **Input validation:** all request/response bodies are Pydantic models with explicit types and length limits; uploaded files are validated by MIME type + magic-byte sniffing, not just filename extension; enforce a max upload size (e.g., 20MB).
6. **File storage:** uploaded contracts stored outside the web root, filenames randomized (UUID), original filename kept only as metadata — prevents path traversal and overwrite attacks.
7. **Secrets:** all API keys (Groq, Gemini, SMTP, DB URL, JWT signing secret) loaded from environment variables via `pydantic-settings`; `.env` in `.gitignore`; provide `.env.example` with dummy values.
8. **Rate limiting:** basic IP + user-based rate limiting on auth endpoints (`slowapi`, free) to prevent credential stuffing/brute force.
9. **Sensitive-field handling:** `contract_value`/`monetary_amount` and counterparty PII are not logged in plaintext application logs; the `audit_log` table records **who accessed/modified what and when** (required for any real legal-ops tool — auditability is a compliance feature, not optional polish).
10. **CORS:** explicit allow-list of the deployed frontend origin only, never `*` in production.
11. **Dependency hygiene:** `pip-audit` / `npm audit` run in CI to catch known-vulnerable packages before merge.

---

## 7. LLM Extraction Contract (the Pydantic schema the model must fill)

Define this schema once, share it between the extraction prompt (as JSON-schema instructions) and the response parser — never let the LLM free-write:

```python
class ExtractedObligation(BaseModel):
    category: ObligationCategory
    description: str                      # plain-English, 1-2 sentences
    responsible_party: str
    trigger_date: Optional[date]
    notice_period_days: Optional[int]
    monetary_amount: Optional[float]
    currency: Optional[str]
    recurrence: RecurrenceType
    source_paragraph_id: str               # links back to contract_chunks.id
    confidence: float                      # model's own confidence, 0-1

class ContractExtractionResult(BaseModel):
    contract_type_guess: ContractType
    counterparty_name_guess: Optional[str]
    effective_date_guess: Optional[date]
    expiration_date_guess: Optional[date]
    obligations: list[ExtractedObligation]
```

The extraction prompt instructs the model: *"Given the following numbered candidate paragraphs from a contract, return ONLY valid JSON matching this schema. Do not invent obligations not supported by the text. If a paragraph has no obligation, omit it. Always cite `source_paragraph_id`."* Validate the raw LLM response against this Pydantic model on receipt; on validation failure, retry once with a corrective follow-up message ("your last output failed schema validation because X, return corrected JSON") before falling back to the secondary provider.

Every extracted obligation with `confidence < 0.7` OR any obligation touching `TERMINATION_NOTICE`/`RENEWAL` (the highest-stakes categories) is flagged `is_human_reviewed = false` and surfaced in a **Review Queue** UI — this system assists a human, it does not silently auto-trust the LLM for legally binding dates.

---

## 8. Backend API Surface (FastAPI routers)

```
POST   /api/v1/auth/register
POST   /api/v1/auth/login
POST   /api/v1/auth/refresh
POST   /api/v1/auth/logout

GET    /api/v1/contracts                 # list, filterable by status/type/expiring-within
POST   /api/v1/contracts                 # upload (multipart), enqueues extraction_job
GET    /api/v1/contracts/{id}
DELETE /api/v1/contracts/{id}
GET    /api/v1/contracts/{id}/status     # poll extraction job status

GET    /api/v1/obligations               # filter by category/status/date-range/assignee
GET    /api/v1/obligations/{id}
PATCH  /api/v1/obligations/{id}          # human review: edit/confirm/waive
GET    /api/v1/obligations/calendar      # aggregated view for the "expiring in 30/60/90 days" dashboard

GET    /api/v1/alerts
PATCH  /api/v1/alerts/{id}/dismiss

GET    /api/v1/dashboard/summary         # counts: at-risk, overdue, upcoming this month, total active value

GET    /api/v1/precedents/search?q=      # semantic search over clause_precedent_cache (pgvector)

GET    /api/v1/admin/llm-usage           # today's Groq/Gemini quota usage, for ops visibility
GET    /api/v1/audit-log                 # admin-only
```

All list endpoints support pagination (`limit`/`offset` or cursor) and are `org_id`-scoped as described in §6.

---

## 9. Scheduler / Alerting Design

- **APScheduler `AsyncIOScheduler`** with a `SQLAlchemyJobStore`, started as part of the FastAPI app lifespan (or as a separate `worker` process in docker-compose sharing the same DB — preferred for production isolation from the web process).
- **Daily job (`scan_and_alert`, runs once every 24h, e.g. 06:00 UTC):**
  1. Query all `obligations` where `computed_alert_date <= today` and `status = 'upcoming'` and no `alert` already sent for today.
  2. Update obligation `status` to `at_risk` (if within lead window) or `overdue` (if `trigger_date < today`).
  3. Create `alerts` rows and send email via `aiosmtplib` to the `assigned_to` user (fallback to org admins if unassigned).
  4. Log every send attempt (success/failure) — never fail the whole batch job because one email failed; isolate per-obligation try/except.
- **Configurable lead times per obligation category** (default: 90/60/30/7 days for RENEWAL and TERMINATION_NOTICE; 14/3 days for PAYMENT_MILESTONE) stored as org-level settings, editable in the UI (Admin only).
- This entire step is **LLM-free** — pure date arithmetic and DB writes, reinforcing the token-minimization principle.

---

## 10. Frontend (React) — Key Views

1. **Auth pages:** login, register, forgot-password (stub is fine for MVP, don't fake email delivery — either fully implement or clearly mark not-yet-implemented in UI).
2. **Dashboard (home):** KPI cards (contracts active, expiring in 30 days, overdue obligations, total contract value under management), and the flagship **"Contracts expiring in 30 days"** live table — this is the single view that must look and feel like real legal-ops software.
3. **Contract list + upload:** drag-and-drop upload, status pill (processing/needs review/active/error), search/filter by type/counterparty/status.
4. **Contract detail page:** original document viewer (render PDF inline), side panel of extracted obligations tied to highlighted source paragraphs (click an obligation → jump to/highlight its source text — this traceability is what makes the tool trustworthy to a lawyer).
5. **Review Queue:** dedicated view of all low-confidence / high-stakes obligations awaiting human confirmation, with quick approve/edit/reject actions.
6. **Compliance Calendar:** month/list view of all obligations by `computed_alert_date`, color-coded by status/category, filterable by assignee.
7. **Precedent Search:** semantic search box over historical clauses (pgvector-backed) — "find how we've handled indemnification caps before."
8. **Admin settings:** users/roles management, per-category lead-time configuration, LLM usage/quota dashboard (surfacing `llm_usage_log`).
9. **Audit log viewer** (admin-only).

Use shadcn/ui `Table`, `Dialog`, `Badge`, `Tabs`, `Calendar` primitives; Recharts for any trend charts on the dashboard. All API calls go through a typed API client generated from the OpenAPI schema — no hand-written fetch strings scattered through components.

---

## 11. Deployment Notes (free-tier only, for local reference — not required for MVP grading but keep in mind while structuring config)

Structure the app via `docker-compose.yml` with services: `postgres` (using the `pgvector/pgvector:pg16` image), `api`, `worker` (scheduler), `frontend`. Use environment variables for all connection strings so the same compose file works locally and can be pointed at a free-tier managed Postgres (e.g., a provider offering a free Postgres instance with the pgvector extension enabled) without code changes. Keep this section infra-agnostic in the code itself — no vendor-specific SDKs baked into the app logic.

---

## 12. Step-by-Step Development Plan (execute phases in order; each phase should end in a working, tested increment)

### Phase 0 — Project Scaffolding
- Monorepo layout: `/backend`, `/frontend`, `/infra` (docker-compose, Alembic), `/docs`.
- `backend`: FastAPI app skeleton, `pydantic-settings` config, health-check endpoint, Dockerfile.
- `frontend`: Vite + React + TS + Tailwind + shadcn init, Dockerfile.
- `docker-compose.yml` wiring postgres(+pgvector) + api + frontend + worker.
- `.env.example` with every required variable documented (DB URL, JWT secret, GROQ_API_KEY, GEMINI_API_KEY, SMTP settings).
- GitHub Actions CI skeleton (lint + type-check on push).

### Phase 1 — Data Layer
- SQLAlchemy async models for every table in §5.3.
- Alembic migration history, including enabling the `vector` extension and creating vector indexes.
- Seed script for CUAD sample data + synthetic obligation calendar (§5.2), gated behind a `--demo` flag so it never runs against a real production DB by accident.

### Phase 2 — Auth & RBAC
- Register/login/refresh/logout endpoints, bcrypt hashing, JWT issuance, refresh-token rotation/denylist table.
- FastAPI dependencies: `get_current_user`, `require_role(...)`, `scoped_to_org(...)`.
- Full pytest coverage: unsuccessful login, expired token, wrong-role access to admin endpoint, cross-org data isolation (a user from org A must never see org B's contracts — write an explicit test for this).

### Phase 3 — Document Ingestion Pipeline
- Upload endpoint → file validation → storage → `contracts` row (`status=processing`) → enqueue `extraction_jobs` row.
- PyMuPDF/python-docx parsing into `contract_chunks` (paragraph-level, with section heading detection where possible).
- Deterministic pre-filter (regex/date/keyword) marking `passed_prefilter`.

### Phase 4 — Embeddings & Local Semantic Filter
- Load `BAAI/bge-base-en-v1.5` once at app/worker startup (not per-request) via `sentence-transformers`.
- Embed all `passed_prefilter=true` chunks, store in `contract_chunks.embedding`.
- Build the fixed reference-embedding set per obligation category (from CUAD examples), compare, keep top-similarity chunks.
- Dedup check against `clause_precedent_cache` (embedding cosine similarity) — short-circuit to cached extraction when matched.

### Phase 5 — LLM Extraction Layer
- `LLMProvider` abstraction with `GroqProvider` and `GeminiProvider` implementations behind one interface.
- Quota-aware provider selection reading/writing `llm_usage_log`.
- Batched, schema-constrained extraction call per contract using the Pydantic schema from §7; validation + one corrective retry; fallback to secondary provider on failure/429.
- Persist results into `obligations`, compute `computed_alert_date` in Python, write `clause_precedent_cache` entries for future dedup.
- Update `contracts.status` to `needs_review` or `active` based on confidence thresholds.
- Unit tests using mocked LLM responses (never call real APIs in CI) covering: valid response, malformed JSON needing retry, both providers exhausted (job goes to `failed`/pending-retry).

### Phase 6 — Obligation & Review APIs
- CRUD/list/filter endpoints for `obligations`, review/approve/edit/waive actions, audit-log writes on every mutation.
- Calendar aggregation endpoint (`/obligations/calendar`) and dashboard summary endpoint.

### Phase 7 — Scheduler & Alerting
- APScheduler daily job as described in §9, running in the `worker` process.
- Email templates (plain + HTML) via `aiosmtplib`; per-obligation try/except isolation; `alerts` table bookkeeping.
- Manual "trigger alert scan now" admin endpoint for testing without waiting a day.
- Tests: mock SMTP, verify correct obligations get flagged at correct lead times, verify no duplicate alerts sent same day.

### Phase 8 — Frontend Core
- Auth pages + protected routing + token refresh handling (axios/fetch interceptor).
- Dashboard, Contract list/upload, Contract detail w/ PDF viewer + obligation traceability, Review Queue, Compliance Calendar, Precedent Search, Admin settings, Audit log.
- Generated typed API client from FastAPI's OpenAPI schema.
- Loading/empty/error states for every data view (no blank screens).

### Phase 9 — Precedent Search Feature
- `/precedents/search` endpoint: embed the query with the same local model, `pgvector` cosine search over `clause_precedent_cache`/`contract_chunks`, return ranked results with source contract links.
- Frontend search UI with result cards.

### Phase 10 — Polish, Hardening, and QA Pass
- Rate limiting on auth routes, CORS lockdown, dependency vulnerability scan in CI.
- Full RBAC + multi-tenant isolation test sweep.
- Load-test the extraction pipeline against all 510 CUAD contracts in a staging run to sanity-check the token-minimization funnel (log tokens-used-per-contract before/after each filter stage, confirm the >80% reduction expected from the funnel design in §3).
- Accessibility pass on frontend (keyboard nav, contrast, ARIA labels on interactive elements).
- README with setup instructions, architecture diagram, and `.env.example` fully documented.

### Phase 11 — Demo Readiness
- Seed staging with the synthetic obligation calendar (§5.2) so the dashboard and "expiring in 30 days" view look populated and realistic without requiring live uploads during a demo.
- Write a short `DEMO_SCRIPT.md`: upload a sample contract → watch status go `processing → needs_review` → review/approve an obligation → see it appear on the compliance calendar → manually trigger the alert scan → see an email/alert fire.

---

## 13. Acceptance Criteria (definition of "done" for the MVP)

- [ ] A user can register, log in, and see only their own organization's data (verified by test, not just manual check).
- [ ] Uploading a real contract PDF results in extracted obligations appearing in the Review Queue within a reasonable time, each traceable to its exact source paragraph.
- [ ] The token-minimization funnel measurably reduces LLM input tokens by filtering non-obligation text before any LLM call (log and expose this ratio in the admin LLM-usage view).
- [ ] If Groq's free-tier quota is exhausted, the system automatically continues on Gemini without user-visible failure.
- [ ] The Compliance Calendar correctly surfaces "contracts/obligations expiring in the next 30 days" and this view is populated and demo-ready.
- [ ] The scheduler correctly computes alert dates from trigger date + notice period and sends alerts at configured lead times, without duplicate sends.
- [ ] All state-changing endpoints are authenticated, authorized by role, scoped by org, and write an audit-log entry.
- [ ] CI runs lint + type-check + backend tests + frontend tests on every push and must pass before merge.
