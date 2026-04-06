# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**This is a production system.** Every change must be tested, secure, tenant-isolated, and backward-compatible. No shortcuts — treat every commit as if it ships to paying customers.

---

## Prerequisites

- **Python 3.12** — backend (CI uses 3.12)
- **Node 20 / npm** — frontend (Next.js 14, React 18, TypeScript 5)
- **PostgreSQL 16** — production database (async via `asyncpg`)
- **Tesseract OCR** — system dependency for `pytesseract` (`brew install tesseract` on macOS)
- **Docker** — for `docker-compose` full-stack or Temporal orchestration

### Required Environment Variables

Copy `.env.example` and update (note: `.env.example` has stale Supabase references — ignore those):
```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/title_intelligence_hub
JWT_SECRET=<any-strong-secret>
GOOGLE_API_KEY=<your-google-api-key>        # required if AI_PROVIDER=gemini
ANTHROPIC_API_KEY=<your-anthropic-api-key>  # required if AI_PROVIDER=claude (default)
NEXT_PUBLIC_API_URL=http://localhost:8000
```

### Default Login Credentials (Dev/Seed)

- **Platform Admin**: `admin@logikality.com` / `admin123`
- **Customer Demo**: `admin@societytitle.com` / `admin123`

Created by `backend/scripts/seed.py`. The platform admin has `is_platform_admin=True`.

---

## Commands

### Backend
```bash
cd backend && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload   # dev server
cd backend && pytest                                                       # all tests
cd backend && pytest tests/test_health.py                                  # single file
cd backend && pytest tests/test_organizations.py::test_create_organization -v  # single test
cd backend && pytest tests/title_intelligence/ -v                          # TI tests only
cd backend && alembic revision --autogenerate -m "description"             # new migration
cd backend && alembic upgrade head                                         # apply migrations
cd backend && alembic downgrade -1                                         # rollback one
cd backend && python scripts/seed.py                                       # seed admin user + TI app
```

### Frontend
```bash
cd frontend && npm run dev      # dev server on :3000
cd frontend && npm run build    # production build (type-checks + compiles)
cd frontend && npm run lint     # ESLint
```

### Full Stack
```bash
./start-dev.sh                  # starts Postgres, Temporal, backend, unified worker, frontend
docker-compose up               # full stack via Docker (db:5436 on host, backend:8000, frontend:3001 on host)
python -m app.pipeline.unified_worker  # unified Temporal worker (polls both TI and TSA queues)
```

**Dev port mapping** (docker-compose): PostgreSQL is exposed on host port **5436** (not 5432), frontend on **3001** (not 3000). Use `psql -h localhost -p 5436` for local DB access. `start-dev.sh` runs frontend on `:3000` and Temporal UI on `http://localhost:8085`. Temporal uses a dedicated `temporal-db` container (postgres:16-alpine) for its state, separate from the app database.

### Production Deployment (AWS EC2)
```bash
git push origin main                              # triggers CI (tests + build) then CD (deploy to EC2 via SSH)
EC2_HOST=<ip> ./infra/prod/deploy.sh               # manual deploy: SSH into EC2, pull, build, restart
EC2_HOST=<ip> ./infra/prod/deploy.sh backend       # deploy backend only
EC2_HOST=<ip> ./infra/prod/deploy.sh frontend      # deploy frontend only
./infra/prod/setup.sh                              # one-time EC2 infrastructure creation
./infra/prod/teardown.sh                           # remove EC2 resources (destructive, prompts for confirm)
```

**Production URL**: `http://<EC2_ELASTIC_IP>` (EC2 t4g.xlarge, us-east-1)

**CI/CD Pipeline** (GitHub Actions):
- **CI** (`.github/workflows/ci.yml`): backend tests (Python 3.12) → frontend lint+build (Node 20) → Docker image build check. Runs on push to `main` and PRs.
- **CD** (`.github/workflows/deploy-aws.yml`): SSHes into EC2 → pulls code → builds Docker images on-instance → restarts containers → runs migrations → health check. Runs on push to `main` only.

**Production stack** (AWS EC2): EC2 t4g.xlarge (4 vCPU/16GB, ARM64) running Docker Compose (backend + frontend + Caddy reverse proxy + Temporal + temporal-db + unified worker), RDS PostgreSQL 16 (db.t4g.large, encrypted, private), S3 (file storage). Temporal uses a dedicated postgres:16-alpine container (not RDS) for its state. Secrets in SSM Parameter Store, fetched at deploy time into `.env.prod`.

**AWS Resources** (managed by `infra/prod/setup.sh`):
- EC2: `ti-hub-prod-server` (t4g.xlarge, 30GB gp3, Elastic IP)
- S3: `ti-hub-prod-storage-{account_id}` (public access blocked)
- RDS: `ti-hub-prod-db` (PostgreSQL 16, db.t4g.large, private)
- SSM: `/ti-hub-prod/database-url`, `/ti-hub-prod/jwt-secret`, `/ti-hub-prod/google-api-key`, `/ti-hub-prod/anthropic-api-key`
- IAM: `ti-hub-prod-ec2-role` (S3 + SSM access), `ti-hub-prod-ec2-profile`
- Security Groups: `ti-hub-prod-ec2-sg` (SSH/HTTP/HTTPS), `ti-hub-prod-rds-sg` (PostgreSQL from EC2)

**GitHub repo secrets needed**: `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `EC2_HOST`, `EC2_SSH_KEY`.

---

## Production Standards

### Code Quality Rules

1. **Every feature must have tests.** No merging code without test coverage for the happy path and at least one error case.
2. **Every query must be tenant-scoped.** Always filter by `org_id`. Never return data from another org. If you write a query without `org_id` in the WHERE clause, justify why in a comment.
3. **Never trust client input.** Validate with Pydantic schemas on every endpoint. Sanitize file uploads. Enforce size limits.
4. **Handle errors explicitly.** Use `HTTPException` with appropriate status codes. Never swallow exceptions silently. Log errors with context (org_id, pack_id, stage name).
5. **Migrations are append-only in production.** Never edit a migration that has been applied. Always create new migrations. Test both `upgrade` and `downgrade` paths.
6. **No secrets in code.** All credentials go through `Settings` / env vars. Never hardcode API keys, DB URLs, or tokens.
7. **Type everything.** Backend uses Python type hints on all function signatures. Frontend uses TypeScript strict mode. No `any` types without justification.

### Security Requirements

- **Authentication**: All API routes except `/api/v1/health` require a valid JWT. Tokens are self-issued HS256 JWTs via `app/services/auth_service.py` (no Supabase).
- **Authorization**: Role-based access control via `get_current_member()`, `require_admin()`, `require_owner()`. Platform-wide admin routes use `require_platform_admin()`.
- **Tenant isolation**: `TenantMixin` adds `org_id` FK+index to all tenant-scoped tables. `MicroAppAccessMiddleware` gates all `/api/v1/apps/{slug}/*` routes.
- **File uploads**: PDF-only validation, configurable size limit (`FILE_UPLOAD_MAX_SIZE`), stored outside webroot.
- **SQL injection**: Prevented by SQLAlchemy ORM — never use raw string interpolation in queries.
- **CORS**: Explicit origin allowlist in `CORS_ORIGINS`.
- **Row-Level Security**: All tables have RLS enabled in PostgreSQL.

### Performance Expectations

- **API response time**: < 200ms for CRUD operations, < 500ms for list queries.
- **Pipeline throughput**: A 50-page title commitment should complete the full 4-stage pipeline (ingest → render → examine → complete) in under 2 minutes. The examine stage uses parallel batched AI calls with progressive streaming.
- **AI calls**: Gemini calls should return within 10–30 seconds per batch. All AI calls retry with exponential backoff.
- **Database**: Every tenant-scoped query uses the `org_id` index. JSONB columns have GIN indexes where queried. `ti_text_chunks` has a tsvector GIN index for full-text search.

---

## Business Rules

See [docs/Plan.md](docs/Plan.md) for the full product spec — database schema, API contract, user roles, subscription lifecycle, pipeline stages, micro app descriptions, and acceptance criteria.

See [docs/PRD_Platform_admin.md](docs/PRD_Platform_admin.md) for Platform Admin requirements — account onboarding, user management, subscription management, micro app CRUD, and admin frontend pages.

See [docs/PRD_Title_Search_and_Abstracting.md](docs/PRD_Title_Search_and_Abstracting.md) for Title Search & Abstracting micro app spec.

See [perf_optimizations.md](perf_optimizations.md) for the pipeline performance optimization roadmap (target: 250 pages in under 2 minutes).

---

## Determinism & Output Stability Contract

### Guaranteed Stable (same input → identical output, always)

| Output | Condition |
|--------|-----------|
| Text chunks | Same page text + same chunker version |
| AI cache key | Same `(page hashes + model + prompt hash + schema hash)` → identical cache key |

### Practically Stable (temp=0, same model+prompt → near-identical)

| Output | Notes |
|--------|-------|
| Page transcriptions (OCR via Gemini Vision) | Stable for identical page images with temp=0 |
| Extracted facts (parties, property, requirements) | Stable for identical document text with temp=0 |
| Section boundaries | Stable for identical page text |
| Flag types after rule normalization | Floor/cap/dedup rules guarantee bounds even if raw LLM output varies |

### May Vary (non-deterministic by design)

| Output | Reason |
|--------|--------|
| Chat responses | Conversational, context-dependent |
| AI explanations on flags | Explanatory text varies |
| Raw flag severity before rules | LLM judgment; clamped by `flag_rules.py` |

### Version Change Policy

Any change to prompts, models, tool schemas, or rule sets **must** create a new `PipelineRun` record with updated hashes. Tracked fields:
- `ai_platform`, `ai_model` — AI provider/model
- `ingestion_prompt_hash`, `risk_prompt_hash` — system prompt hashes
- `extraction_tool_hash`, `risk_tool_hash` — tool definition hashes
- `ocr_engine` — OCR engine identifier (e.g., `gemini_vision`)
- `chunker_version`, `rules_version` — algorithm versions
- `version_metadata` — JSONB with `pipeline_mode: "examiner"` and full version snapshot

### Examiner Caching Contract

AI output is cached per-pack, keyed by composite version hashes (computed by `pipeline/version_tracker.py`):
- `compute_examiner_cache_key(page_hashes, version_info)` → deterministic cache key
- Any change to model, prompts, schemas, or page content produces a different hash → automatic cache miss
- Cached data is replayed via idempotent delete-then-insert (same as fresh run)

### Testing Requirement

Run `pytest tests/title_intelligence/test_determinism.py -v` before any version bump. All golden-set snapshot tests must pass.

---

## Title Search & Abstracting — Determinism & Output Stability Contract

### Guaranteed Stable (same input → identical output, always)

| Output | Condition |
|--------|-----------|
| Flag types, severity, count | Same documents + same `RULES_VERSION` (`ta_flag_rules_v1` in `services/flag_rules.py`) |
| Severity clamping | Floor/cap rules in `SEVERITY_FLOOR` / `SEVERITY_CAP` dictionaries |
| Flag deduplication | Same `(flag_type, document_id)` pair always merges identically |
| Flag sort order | Deterministic: `(severity_order, flag_type, description)` |
| Evidence refs on flags | Same document fields → identical `evidence_refs` list |
| Chain link ordering | Same parsed documents → identical chain positions |
| Package auto-issue decision | Same `chain_complete` + same open flags → identical `status` |
| Cache keys | Same `(input_hash + model + prompt_hash + tool_hash)` → identical cache key |

### Practically Stable (temp=0, same model+prompt → near-identical)

| Output | Notes |
|--------|-------|
| Parsed document fields (doc_type, grantor, grantee, consideration) | Stable for identical raw content with temp=0 |
| AI-generated chain links | Stable for identical parsed documents with temp=0 |
| AI-detected anomalies | Stable for identical chain + documents with temp=0; clamped by `flag_rules.py` |

### May Vary (non-deterministic by design)

| Output | Reason |
|--------|--------|
| Package narrative text | LLM creative generation (PackageAgent) |
| AI explanations on flags | Explanatory text varies per run |
| Raw flag severity before rules | LLM judgment; clamped by floor/cap rules |

### Version Change Policy

Any change to prompts, models, tool schemas, or rule sets **must** create a new `TAPipelineRun` record with updated hashes. Tracked fields:
- `ai_platform`, `ai_model` — AI provider/model
- `parser_prompt_hash`, `chain_prompt_hash`, `anomaly_prompt_hash` — system prompt hashes
- `parser_tool_hash`, `chain_tool_hash`, `anomaly_tool_hash` — tool definition hashes
- `rules_version` — flag rules version from `services/flag_rules.py`
- `pipeline_backend` — execution backend (background_tasks/temporal)
- `version_metadata` — JSONB with full version snapshot

### Caching Contract

AI output is cached at two levels, keyed by composite version hashes:
- **Parse cache**: `(raw_document_content_hash + ai_model + parser_prompt_hash + parser_tool_hash)`
- **Chain cache**: `(parse_output_hash + ai_model + chain_prompt_hash + chain_tool_hash + anomaly_prompt_hash + anomaly_tool_hash + rules_version)`

Any config/model/prompt/tool/rules change produces a different hash → automatic cache miss. No explicit invalidation needed. Cached data is replayed via idempotent delete-then-insert.

### Closed-Set Classifications

All business-critical labels use bounded `Literal` types in Pydantic schemas:
- `FlagType`: 8 values (`chain_gap`, `name_mismatch`, `unreleased_mortgage`, ...)
- `FlagSeverity`: 4 values (`critical`, `high`, `medium`, `low`)
- `DocType`: 10 values (`deed`, `mortgage`, `lien`, `satisfaction`, ...)
- `LinkType`: 4 values (`conveyance`, `encumbrance`, `release`, `gap`)
- `OrderStatus`: 6 values (`pending`, `processing`, `completed`, ...)
- `ReviewDecision`: 3 values (`approve`, `reject`, `correct`)

### Testing Requirement

Run `pytest tests/title_search/test_determinism.py -v` before any version bump. All golden-set snapshot tests must pass. Run `pytest tests/title_search/test_flag_rules.py -v` after any change to `flag_rules.py`.

---

## Architecture

### Multi-Tenant Micro App Platform

This is a SaaS platform where **organizations** subscribe to **micro apps**. Each micro app is a self-contained feature module with its own models, routes, services, and AI agents.

**Key entities**: Organization → Users (with roles) → Subscriptions → MicroApps

### Authentication & Authorization

- **Auth is fully local** — no Supabase. Passwords hashed with bcrypt (`passlib`), JWTs signed with HS256 (`PyJWT`).
- **Auth routes**: `POST /api/v1/auth/login` (rate-limited 5/min), `GET /api/v1/auth/me`.
- **No public signup** — only platform admins create accounts via `POST /api/v1/admin/accounts`.
- **Platform admin**: `is_platform_admin` flag on User model. Seeded user: `admin@logikality.com` / `admin123`.
- **Frontend auth**: `src/lib/auth.ts` manages token in localStorage (key: `auth_token`). `apiFetch()` injects `Authorization: Bearer` + `X-Org-Id` headers.
- **User model**: `auth_user_id` = `id` for locally-created users (self-referential). `password_hash` column (nullable).

### Request Flow (Backend)

Middleware runs in this order on each request (Starlette LIFO — last added = outermost = runs first):
1. **RequestIdMiddleware** — generates/propagates `X-Request-Id` (outermost)
2. **MetricsMiddleware** — request count + latency tracking
3. **CORS** — allows configured frontend origins
4. **TenantContextMiddleware** — resolves `org_id` from `X-Org-Id` header; sets `request.state.org_id`. Skips `/api/v1/admin/` routes.
5. **MicroAppAccessMiddleware** — for routes matching `/api/v1/apps/{slug}/*`, queries DB to verify the org has an active subscription; returns 403 if not (innermost)

FastAPI dependencies then handle auth/authz:
- `get_current_user()` — decodes JWT → `AuthenticatedUser`
- `get_current_member()` — validates user belongs to the org (from `request.state.org_id`) → returns `User` model
- `require_admin()` / `require_owner()` / `require_platform_admin()` — role guards

### Micro App Plugin System

Adding a new micro app requires **only** adding a new directory under `backend/app/micro_apps/`:
```
micro_apps/
  my_new_app/
    __init__.py   # lazy export: micro_app (use __getattr__ pattern to avoid circular imports)
    app.py        # class MyNewApp(MicroAppBase) with slug, name, get_router()
    models/       # SQLAlchemy models (prefix tables with app abbreviation, e.g., ti_)
    schemas/      # Pydantic request/response schemas
    services/     # Business logic layer
    routes/       # FastAPI route modules
    ai/           # AI agent classes (subclass BaseAIService)
    pipeline/     # Background processing stages (if applicable)
```
`registry.py` auto-discovers all subdirectories at startup. `create_app()` mounts each app's router at `/api/v1/apps/{slug}/`.

**Important**: All micro app `__init__.py` files must use this `__getattr__` lazy import pattern to prevent circular imports:
```python
def __getattr__(name):
    if name == "micro_app":
        from app.micro_apps.my_app.app import micro_app
        return micro_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
```

### Title Intelligence Micro App

The first fully implemented micro app. Processes title commitment PDFs through a **4-stage pipeline**: `ingest → render → examine → complete`.

**Directory**: `backend/app/micro_apps/title_intelligence/`

**Models** (all prefixed `ti_`):
| Table | Purpose | Tenant-scoped |
|-------|---------|:---:|
| `ti_packs` | Upload container with pipeline status + `examine_progress` | Yes |
| `ti_pack_files` | Uploaded PDF metadata + storage path | Yes |
| `ti_pages` | Page images + OCR text per rendered page | Yes |
| `ti_sections` | Detected document sections (schedule_a, schedule_b1, schedule_b2, schedule_c, legal_description, endorsements) | Yes |
| `ti_extractions` | Structured data extracted by AI (parties, property, etc.) | Yes |
| `ti_flags` | AI-identified risk flags with severity | Yes |
| `ti_reviews` | Human decisions on flags (approve/reject/escalate) | Yes |
| `ti_text_chunks` | Chunked text for full-text search (tsvector + GIN) | Yes |
| `ti_chat_messages` | User/assistant conversation history | Yes |

**AI Agents** (all subclass `BaseAIService`):
| Agent | Method | I/O |
|-------|--------|-----|
| `TriageAgent` | `classify_pages_parallel(pdf_bytes, total_pages, chunk_size, concurrency)` → `TriageResult` | Lightweight page classifier: content/blank/cover/signature/transmittal/boilerplate + document type hints. Parallel chunking for large PDFs |
| `TitleExaminerAgent` | `examine_document(pages, storage, on_batch_complete)` → `ExaminerConsolidatedResult` | Unified agent: OCR + extraction + flagging in one pass. Hybrid text+vision batching, Gemini context caching, progressive streaming |
| `ChatAgent` | `answer(question, chunks, extractions, history)` → `(text, citations)` | Text → text (supports SSE streaming) |
| `ReviewAssistant` | `recommend(flag, extractions)` → `{decision, reasoning, confidence}` | Structured → structured |
| `ReportAgent` | `generate_executive_summary(...)` → bullet points | Structured → text (used in dashboard summary) |

**TriageAgent architecture** (`ai/triage_agent.py`):
- **Heuristic pre-triage**: Render stage extracts PyMuPDF text per page (<1ms/page). Pages with <20 chars (`HEURISTIC_BLANK_THRESHOLD`) marked as `page_type="blank"` and excluded from LLM triage
- **Parallel chunking**: `classify_pages_parallel()` splits PDFs >50pp (`TRIAGE_CHUNK_SIZE`) into N chunks, dispatches parallel calls via `asyncio.Semaphore(TRIAGE_CONCURRENCY=4)`
- **Safe fallback**: Failed chunks default all pages to `"content"` (conservative — more examined, never fewer)
- **Page number remapping**: `_merge_chunk_results()` remaps chunk-local page numbers to global, sums tokens, uses max elapsed (parallel wall time)
- **Context caching**: Pre-warms cache before parallel dispatch; all chunks reuse the same `TriageAgent` cache

**TitleExaminerAgent architecture** (`ai/title_examiner_agent.py`):
- **Hybrid text+vision**: Pages with embedded text (≥50 chars) sent as text; scanned pages sent as JPEG images
- **Smart batch sizing**: Text pages batch at 25 (`EXAMINER_BATCH_SIZE_TEXT`), image pages at 10 (`EXAMINER_BATCH_SIZE`). Reduces API calls for text-heavy PDFs
- **Dual JSON schema**: `EXAMINATION_JSON_SCHEMA` (with `page_transcriptions`) for image batches, `EXAMINATION_JSON_SCHEMA_TEXT_ONLY` (without) for text-only batches — saves output tokens
- **Progressive streaming**: Uses `asyncio.as_completed` + `on_batch_complete` callback to write results to DB as each batch finishes. `Pack.examine_progress` tracks "3/6 batches, 12 flags" for frontend SSE updates
- **Gemini context caching**: Uses `google-genai` SDK to cache system prompt + schema (TTL 10 min). All batch calls reference the cache, saving ~14K input tokens per run. Falls back to uncached `litellm` if caching fails. `_cache_lock` (asyncio.Lock) prevents double creation during concurrent pre-warm
- **Cache pre-warming**: Context cache creation runs concurrently with triage via `asyncio.create_task`, saving 1-2s
- **Pydantic schemas**: `schemas/examiner.py` defines `ExaminerConsolidatedResult`, `ExaminerBatchResult`, `ExaminerExtraction`, `ExaminerFlag`, `ExaminerSection`, `PageTranscription`

**Reports**: Report generation is **data-driven, no LLM needed**. `report_service.py` fetches pack data (extractions, flags) and passes structured inputs to `pdf_service.py` (`generate_pack_report_pdf()`) which renders via fpdf2. PDF is cached in storage for instant subsequent downloads. `generate_data_driven_summary()` produces a bullet-point executive summary from flag data (no LLM, no readiness score).

**Pipeline** (`pipeline/orchestrator.py`):
- Dual backend: `PIPELINE_BACKEND` setting selects `background_tasks` (FastAPI BackgroundTasks) or `temporal` (durable Temporal workflows)
- Each stage retries up to 3–5 times with exponential backoff
- Examine stage uses delete-then-insert for idempotent retries
- Complete stage pre-generates a cached PDF report for instant download
- Pack status transitions: `uploading → processing → completed | failed`
- Frontend polls `GET /packs/{id}/pipeline` every 3 seconds
- **Examine stage timeline** (native_pdf mode, 51pp PDF):
  1. Heuristic pre-triage in render (~0s, PyMuPDF text extraction)
  2. Triage + examiner cache pre-warm (parallel, ~5-8s)
  3. Build content-only PDF + document grouping (~0.2s)
  4. Examine batches (parallel, concurrency=8, ~10-15s)
  5. Consolidation + deterministic flags + DB writes (~2s)

### Title Search & Abstracting Micro App

The second micro app. Automates county record searches, document parsing, chain-of-title construction, anomaly detection, and abstract package generation.

**Directory**: `backend/app/micro_apps/title_search/`

**Models** (all prefixed `ta_`):
| Table | Purpose | Tenant-scoped |
|-------|---------|:---:|
| `ta_orders` | Search order with property details + pipeline status | Yes |
| `ta_source_assignments` | County source assignments per order | Yes |
| `ta_raw_documents` | Raw document content from county sources | Yes |
| `ta_documents` | AI-parsed structured document data | Yes |
| `ta_chain_links` | Chain-of-title links with gap detection | Yes |
| `ta_flags` | Risk flags with severity, evidence_refs, rules-based detection | Yes |
| `ta_reviews` | Human review decisions on flags | Yes |
| `ta_packages` | Abstract package metadata + PDF generation | Yes |
| `ta_pipeline_runs` | Version tracking per pipeline execution | Yes |
| `ta_county_sources` | County portal configs (platform-wide, NOT tenant-scoped) | No |

**AI Agents** (all subclass `BaseAIService`, all pinned `temperature=0`):
| Agent | Method | I/O |
|-------|--------|-----|
| `DocumentParserAgent` | `parse(raw_content)` → `{doc_type, grantor, grantee, ...}` | Text → structured |
| `ChainBuilderAgent` | `build(documents)` → `{chain_links, chain_complete}` | Structured → structured |
| `AnomalyDetectorAgent` | `detect(chain, docs)` → `[flags]` | Structured → structured (post-processed by `flag_rules.py`) |
| `PackageAgent` | `generate_narrative(...)` → text | Structured → text |

**Pipeline** (`pipeline/orchestrator.py`):
- 6-stage pipeline: `order → retrieve → parse → chain → package → complete`
- Dual backend: `PIPELINE_BACKEND` selects `background_tasks` (FastAPI) or `temporal` (durable workflows on `TSA_TEMPORAL_TASK_QUEUE`)
- Mock retrieval for MVP (no real county portal integration)
- AI output caching at parse and chain stages (keyed by composite version hashes)
- Deterministic flag detection via `services/flag_rules.py` with severity floor/cap rules
- Pipeline pauses at retrieve if non-digital sources exist (`awaiting_abstractor`)
- `TAPipelineRun` records version metadata for every execution

**Key files**:
- `services/flag_rules.py` — deterministic rules engine (`RULES_VERSION`, severity clamping, dedup)
- `pipeline/version_tracker.py` — prompt/tool/rules hash computation, cache key helpers
- `pipeline/temporal_workflows.py` — `ProcessOrderWorkflow` (Temporal durable workflow)
- `pipeline/temporal_activities.py` — per-stage Temporal activity wrappers
- `tests/title_search/test_determinism.py` — golden-set regression tests
- `tests/title_search/test_flag_rules.py` — rules engine unit tests

### AI Integration

`BaseAIService` in `backend/app/ai/base_service.py` is the base class for all AI work. It takes `org_id` for tenant scoping and provides:
- `call_haiku()` — text generation with 3-attempt exponential backoff
- `call_haiku_structured()` — structured output via tool_use pattern
- `call_json_structured()` — structured output via Gemini native JSON schema response format (faster than tool-use)
- `call_json_structured_cached()` — same as above but uses a Gemini context cache (avoids resending system prompt)
- `create_context_cache()` — creates a Gemini cached content object via `google-genai` SDK (TTL-based, stored in module-level `_context_cache_map`)
- `call_with_tools()` — iterative tool-calling loop for multi-step agent workflows
- `call_streaming()` — SSE streaming for real-time chat responses

**Tri-provider**: `AI_PROVIDER` setting selects `claude` (default), `gemini`, or `hybrid`. Uses `litellm` under the hood.
- **Claude** (default): `claude-sonnet-4-20250514` via Anthropic API. Forces `PIPELINE_MODE=legacy` (image-based). Uses `cache_control` prompt caching. Set `ANTHROPIC_API_KEY`.
- **Gemini**: `gemini/gemini-2.5-flash` via Google AI. Supports `native_pdf` mode (sends PDF chunks directly). Uses `google-genai` SDK for context caching (TTL 10 min). Set `GOOGLE_API_KEY`.
- **Hybrid** (Gemini vision + Claude extraction): Two-pass pipeline — Gemini reads PDF/images into transcriptions (no content filtering issues), then Claude analyzes text for sections/extractions/flags (excels at schema-following). Falls back to Gemini-only if Claude hits content policy errors. Requires both `GOOGLE_API_KEY` and `ANTHROPIC_API_KEY`. Forces `PIPELINE_MODE=native_pdf`. Uses `TRANSCRIPTION_ONLY_JSON_SCHEMA` + `TRANSCRIPTION_SYSTEM_PROMPT` for minimal Gemini pass, then `call_json_structured_claude()` for extraction.

**Per-agent overrides**: `TI_CHAT_PROVIDER` and `TA_AI_PROVIDER` (empty string = use global `AI_PROVIDER`) allow overriding the provider for specific agents without changing the whole app.

Tool definitions use Anthropic format (auto-converted to OpenAI format by `_convert_tools`). Provider modules: `ai/gemini_provider.py`, `ai/claude_provider.py`. `base_service.py` dispatches to the correct provider.

### Frontend ↔ Backend Connection

- `apiFetch()` (`frontend/src/lib/api.ts`) retrieves the JWT from localStorage and injects `Authorization: Bearer` + `X-Org-Id` headers
- `uploadFiles()` (`frontend/src/lib/api.ts`) handles multipart file uploads with the same auth headers
- `useOrg()` hook wraps `apiFetch` with the current org from Zustand store (`org-store.ts`, persisted to localStorage)
- Chat has both `/chat` (request-response) and `/chat/stream` (SSE via `ReadableStream`) endpoints

### Database

- **Production**: PostgreSQL 16 (async via `asyncpg`). All tables have RLS enabled.
- **Tests**: SQLite via `aiosqlite` with table create/drop per test.
- **ORM**: SQLAlchemy 2.0 async. `TenantMixin` adds `org_id` FK+index; `TimestampMixin` adds `created_at`/`updated_at`.
- **Cross-DB Compatibility**: `app/models/compat.py` provides `UUID` and `JSONB` TypeDecorators that render as native PostgreSQL types in prod and `String(36)` / `JSON` in SQLite tests.
- **Migrations**: Alembic with async engine. Target metadata comes from `app.models.Base`. All micro app models must be imported in `app/models/__init__.py` (via `ensure_micro_app_models()`) or Alembic won't detect them.
- **Table naming**: Platform tables use plain names (`organizations`, `users`, etc.). Micro app tables are prefixed with an abbreviation (`ti_packs`, `ti_flags`, etc.) to prevent collisions.

### Test Setup

Tests override FastAPI dependencies in `backend/tests/conftest.py`:
- `get_db` → test SQLite session
- `get_current_user` → fixed `AuthenticatedUser` (no JWT needed)
- `get_current_member` → fixed owner-role `User`
- `get_settings` → test settings with SQLite URL and test storage path
- `session_factory_override` → passed to `create_app()` so `MicroAppAccessMiddleware` uses the test DB

Seed data includes: Test Org, Test User (owner), Title Intelligence MicroApp, active Subscription.

Fixed test UUIDs: `TEST_ORG_ID`, `TEST_USER_ID`, `TEST_APP_ID`, `TEST_AUTH_USER_ID` in conftest.
TI-specific: `TEST_PACK_ID`, `TEST_FILE_ID`, `TEST_FLAG_ID` in `tests/title_intelligence/conftest.py`.
TSA-specific: `TEST_ORDER_ID`, `TEST_SOURCE_ASSIGNMENT_ID`, `TEST_RAW_DOC_ID`, `TEST_DOCUMENT_ID`, `TEST_CHAIN_LINK_ID`, `TEST_FLAG_ID`, `TEST_COUNTY_SOURCE_ID` in `tests/title_search/conftest.py`.

### Route Conventions

**Backend API** (see `backend/app/api/v1/` and each micro app's `routes/`):
- `/api/v1/health` — public; all other routes require JWT
- `/api/v1/auth/*` — login, current user
- `/api/v1/admin/*` — platform admin only (skips tenant context middleware)
- `/api/v1/organizations`, `/api/v1/subscriptions`, `/api/v1/micro-apps` — platform CRUD
- `/api/v1/apps/{slug}/*` — micro app routes, gated by subscription middleware

**Title Intelligence routes** mount at `/api/v1/apps/title-intelligence/packs/{packId}/` with sub-resources: `pipeline`, `pages`, `extractions`, `flags`, `chat` (+`/stream` for SSE), `reports` (`/download` for PDF, GET by URI), `search`.

**Title Search routes** mount at `/api/v1/apps/title-search/` with: `orders` (CRUD + `/process` + `/pipeline`), `orders/{orderId}/sources` (list + upload), `orders/{orderId}/documents` (list + correct), `orders/{orderId}/chain`, `orders/{orderId}/flags` (list + review), `orders/{orderId}/package` (get + issue + PDF), `county-sources` (platform admin CRUD).

**Frontend** (Next.js App Router at `frontend/src/app/`):
- `(auth)/login` — unauthenticated layout
- `(platform)/` — authenticated layout with sidebar: `dashboard`, `admin/*`, `apps/*`
- TI pages: `apps/title-intelligence/packs/[packId]/` with sub-pages: `documents`, `results`, `export`
- TSA pages: `apps/title-search/` (order list), `orders/new` (create), `orders/[orderId]/` with sub-pages: `documents`, `chain`, `flags`, `package`

### Storage

Abstract `StorageProvider` (`backend/app/services/storage.py`) with two implementations:
- `LocalStorage` — filesystem-based, configurable via `STORAGE_PATH`
- `S3Storage` — S3-compatible via `aiobotocore`, configurable via `S3_BUCKET`, `S3_REGION`, etc.

Set `STORAGE_PROVIDER` to `local` or `s3`. Path convention:
```
{org_id}/{pack_id}/files/{filename}     # uploaded PDFs
{org_id}/{pack_id}/pages/page_0001.jpg  # rendered page images
{org_id}/{pack_id}/thumbs/page_0001.jpg # thumbnails
{org_id}/{pack_id}/ocr/page_0001.json   # OCR output
```

All storage paths are tenant-scoped by org_id at the top level.

### Key Configuration (`backend/app/config.py`)

| Setting | Default | Purpose |
|---------|---------|---------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Database connection |
| `JWT_SECRET` | `change-me-in-production` | HS256 signing key (fails startup if default + `DEBUG=false`) |
| `JWT_EXPIRATION_MINUTES` | `1440` | Token lifetime (24h) |
| `AI_PROVIDER` | `claude` | AI provider: `claude`, `gemini`, or `hybrid`. Claude/hybrid auto-coerces pipeline mode |
| `GOOGLE_API_KEY` | `""` | Google AI API key (required if `AI_PROVIDER=gemini`) |
| `ANTHROPIC_API_KEY` | `""` | Anthropic API key (required if `AI_PROVIDER=claude` or `hybrid`) |
| `TI_CHAT_PROVIDER` | `""` | Override AI provider for TI chat agent (empty = use `AI_PROVIDER`) |
| `TA_AI_PROVIDER` | `""` | Override AI provider for TSA agents (empty = use `AI_PROVIDER`) |
| `STORAGE_PROVIDER` | `local` | Storage backend: local/s3 |
| `STORAGE_PATH` | `./storage` | Local storage base path |
| `PIPELINE_BACKEND` | `temporal` | Pipeline executor: background_tasks/temporal (both TI and TSA) |
| `PIPELINE_MODE` | `native_pdf` | `native_pdf` (Gemini only, sends PDF directly) or `legacy` (renders to JPEG) |
| `TEMPORAL_ADDRESS` | `localhost:7233` | Temporal server address |
| `TEMPORAL_TASK_QUEUE` | `title-intelligence` | Temporal task queue name (TI) |
| `TSA_TEMPORAL_TASK_QUEUE` | `title-search` | Temporal task queue name (TSA) |
| `TESSERACT_PATH` | (system default) | Custom Tesseract binary path |
| `FILE_UPLOAD_MAX_SIZE` | `104857600` (100MB) | Max upload size |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | Allowed origins |
| `DEBUG` | `false` | Allows insecure JWT_SECRET default for development |
| `NATIVE_PDF_BATCH_SIZE` | `20` | Pages per PDF chunk sent to Gemini (native_pdf mode) |
| `NATIVE_PDF_CONCURRENCY` | `12` | Max parallel Gemini calls in native_pdf mode |
| `TRIAGE_ENABLED` | `true` | Set false to skip triage (all pages → examine) |
| `TRIAGE_SKIP_BELOW` | `200` | Skip LLM triage for docs under this page count |
| `TRIAGE_CHUNK_SIZE` | `50` | Pages per triage chunk for parallel splitting |
| `TRIAGE_CONCURRENCY` | `4` | Max parallel triage LLM calls |
| `GROUPING_ENABLED` | `true` | Document-aligned chunking before extraction |
| `ADAPTIVE_CHUNK_SIZING` | `true` | Adjust batch size by text complexity |
| `SPECIALIZED_EXTRACTION_ENABLED` | `true` | Type-specific extractors per document group |
| `SUMMARY_MODE` | `data_driven` | `data_driven` (fast, deterministic) or `llm` (narrative, 10-15s) |
| `TSA_RESEARCH_MODE` | `grounded` | `grounded` (Claude web search) or `scraper` (legacy portal scraping) |
| `EXAMINER_BATCH_SIZE` | `10` | Max pages per image batch (legacy mode) |
| `EXAMINER_BATCH_SIZE_TEXT` | `25` | Max pages per text-only batch (legacy mode) |
| `EXAMINER_BATCH_OVERLAP` | `1` | Page overlap between adjacent batches for context continuity |
| `EXAMINER_BATCH_COOLDOWN` | `0.0` | Seconds between batch launches (rate limit protection) |
| `EXAMINER_RENDER_DPI` | `72` | DPI for page image rendering (auto-set to 100 for Claude) |
| `EXAMINER_MAX_OUTPUT_TOKENS` | `16384` | Max output tokens per examiner batch call |
| `CLAUDE_EXAMINER_BATCH_SIZE` | `8` | Image pages per batch when using Claude |
| `CLAUDE_EXAMINER_CONCURRENCY` | `8` | Parallel batch calls when using Claude |
| `CLAUDE_EXAMINER_RPM` | `50` | Proactive requests/minute limit for Claude (0 = disabled) |

---

## Common Gotchas

- **Circular imports in micro apps**: Every micro app `__init__.py` must use the `__getattr__` lazy import pattern (see Micro App Plugin System above). Direct imports will cause circular import errors at startup.
- **SQLite vs PostgreSQL in tests**: Tests use SQLite. `app/models/compat.py` provides `UUID` → `String(36)` and `JSONB` → `JSON` TypeDecorators. If you add a new model with PostgreSQL-specific types, use these compat types or tests will fail.
- **fpdf2 multi_cell**: Must pass `new_x="LMARGIN", new_y="NEXT"` to avoid width issues in PDF report generation.
- **Storage type hints**: Always use `StorageProvider` (the abstract base), never `LocalStorage` directly — the implementation is selected at runtime by config.
- **Tenant scoping in tests**: Tests seed a fixed org (`TEST_ORG_ID`). Any new test data must use this org ID or tenant middleware will reject it.
- **AI tool definitions**: Written in Anthropic format. `BaseAIService._convert_tools()` auto-converts to OpenAI format (used by Gemini via litellm). Don't write provider-specific tool schemas.
- **Commit completeness before pushing**: When refactoring (e.g., renaming functions), ensure both the implementation files AND their test files are committed together. CI runs tests from the pushed code — a renamed function with an old test file will break the pipeline.
- **`backend/storage/` is tracked by git**: Local dev data (uploaded PDFs, OCR output, AI cache, thumbnails) lives here and shows up in `git status`. Stage only `backend/app/` and `frontend/src/` code changes, not storage artifacts.
- **`gh` CLI token**: The GitHub CLI token may expire. Re-authenticate with `gh auth login -h github.com` if `gh run list` fails.
- **JWT_SECRET in dev**: With `DEBUG=false` (default), the app refuses to start if `JWT_SECRET` is the insecure default `change-me-in-production`. Set `DEBUG=true` in `.env` for local development, or set a real secret.
- **Alembic model detection**: New models must be imported in `app/models/__init__.py` (add to `ensure_micro_app_models()`) or `alembic revision --autogenerate` won't generate migrations for them.
- **Docker dev ports differ from local dev**: `docker-compose.yml` maps PostgreSQL to host port 5436 and frontend to 3001. `start-dev.sh` / local dev use the standard ports (5432, 3000).
- **Alembic migrations must be applied**: After adding new columns/tables, run `cd backend && PYTHONPATH=. alembic upgrade head` to apply to the running database. Code changes without migration will cause `UndefinedColumnError` at runtime.
- **google-genai SDK**: Used alongside litellm for Gemini context caching only. The `_context_cache_map` in `base_service.py` is module-level (in-memory, not persistent). Cache handles expire per TTL (default 10 min).
