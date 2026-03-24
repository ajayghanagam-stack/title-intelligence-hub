# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

**This is a production system.** Every change must be tested, secure, tenant-isolated, and backward-compatible. No shortcuts — treat every commit as if it ships to paying customers.

---

## Prerequisites

- **Python 3.11+** — backend
- **Node 18+ / npm** — frontend (Next.js 14, React 18, TypeScript 5)
- **PostgreSQL 16** — production database (async via `asyncpg`)
- **Tesseract OCR** — system dependency for `pytesseract` (`brew install tesseract` on macOS)
- **Docker** — for `docker-compose` full-stack or Temporal orchestration

### Required Environment Variables

Copy `.env.example` and update (note: `.env.example` has stale Supabase references — ignore those):
```
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/title_intelligence_hub
JWT_SECRET=<any-strong-secret>
ANTHROPIC_API_KEY=sk-ant-...
NEXT_PUBLIC_API_URL=http://localhost:8000
```

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
./start-dev.sh                  # starts Postgres, Temporal, backend, frontend
docker-compose up               # full stack via Docker (db:5432, backend:8000, frontend:3000)
```

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
- **Pipeline throughput**: A 300-page title commitment should complete the full 7-stage pipeline in under 30 minutes.
- **AI calls**: Haiku calls should return within 10–30 seconds per page/chunk. All AI calls retry with exponential backoff.
- **Database**: Every tenant-scoped query uses the `org_id` index. JSONB columns have GIN indexes where queried. `ti_text_chunks` has a tsvector GIN index for full-text search.

---

## Business Rules

See [docs/Plan.md](docs/Plan.md) for the full product spec — database schema, API contract, user roles, subscription lifecycle, pipeline stages, micro app descriptions, and acceptance criteria.

---

## Determinism & Output Stability Contract

### Guaranteed Stable (same input → identical output, always)

| Output | Condition |
|--------|-----------|
| OCR text | Same image bytes + same Tesseract version |
| Text chunks | Same OCR text + same chunker version |
| Readiness score, status, categories, estimated_days | Same flags + same rules version (`flag_rules_v1`) |
| Extraction schemas | Same tool definition hash (`extraction_tool_hash`) |

### Practically Stable (temp=0, same model+prompt → near-identical)

| Output | Notes |
|--------|-------|
| Extracted facts (parties, property, requirements) | Stable for identical document text with temp=0 |
| Section boundaries | Stable for identical page text |
| Flag types after rule normalization | Floor/cap/dedup rules guarantee bounds even if raw LLM output varies |

### May Vary (non-deterministic by design)

| Output | Reason |
|--------|--------|
| Report narrative text | LLM creative generation |
| Chat responses | Conversational, context-dependent |
| AI explanations on flags | Explanatory text varies |
| Raw flag severity before rules | LLM judgment; clamped by `flag_rules.py` |

### Version Change Policy

Any change to prompts, models, tool schemas, or rule sets **must** create a new `PipelineRun` record with updated hashes. Tracked fields:
- `ai_platform`, `ai_model` — AI provider/model
- `ingestion_prompt_hash`, `risk_prompt_hash` — system prompt hashes
- `extraction_tool_hash`, `risk_tool_hash` — tool definition hashes
- `ocr_engine` — Tesseract version string
- `chunker_version`, `rules_version` — algorithm versions

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

Middleware executes in this order (Starlette LIFO — last added = outermost = runs first):
1. **RequestIdMiddleware** — generates/propagates `X-Request-Id`
2. **MetricsMiddleware** — request count + latency tracking
3. **CORS** — allows configured frontend origins
4. **TenantContextMiddleware** — resolves `org_id` from `X-Org-Id` header; sets `request.state.org_id`. Skips `/api/v1/admin/` routes.
5. **MicroAppAccessMiddleware** — for routes matching `/api/v1/apps/{slug}/*`, queries DB to verify the org has an active subscription; returns 403 if not

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

The first fully implemented micro app. Processes title commitment PDFs through a 7-stage pipeline (ingest → render → OCR → index → ingestion agent → risk agent → complete).

**Directory**: `backend/app/micro_apps/title_intelligence/`

**Models** (all prefixed `ti_`):
| Table | Purpose | Tenant-scoped |
|-------|---------|:---:|
| `ti_packs` | Upload container with pipeline status | Yes |
| `ti_pack_files` | Uploaded PDF metadata + storage path | Yes |
| `ti_pages` | Page images + OCR text per rendered page | Yes |
| `ti_sections` | Detected document sections (Schedule A/B/C, etc.) | Yes |
| `ti_extractions` | Structured data extracted by AI (parties, property, etc.) | Yes |
| `ti_flags` | AI-identified risk flags with severity | Yes |
| `ti_reviews` | Human decisions on flags (approve/reject/escalate) | Yes |
| `ti_text_chunks` | Chunked text for full-text search (tsvector + GIN) | Yes |
| `ti_chat_messages` | User/assistant conversation history | Yes |

**AI Agents** (all subclass `BaseAIService`):
| Agent | Method | I/O |
|-------|--------|-----|
| `OCRAgent` | `extract_text(image_bytes)` → `{text, confidence}` | Uses Tesseract (`pytesseract`, sync wrapped in `asyncio.to_thread`) |
| `IngestionAgent` | `analyze(pages_text)` → `{sections, extractions}` | Text → structured (supports iterative tool-calling) |
| `RiskAgent` | `analyze(extractions, sections)` → `[flags]` | Structured → structured |
| `ChatAgent` | `answer(question, chunks, extractions, history)` → `(text, citations)` | Text → text (supports SSE streaming) |
| `ReviewAssistant` | `recommend(flag, extractions)` → `{decision, reasoning, confidence}` | Structured → structured |
| `ReportAgent` | `generate(pack_name, audience, ...)` → text | Structured → text/PDF/JSON/Markdown |

**Pipeline** (`pipeline/orchestrator.py`):
- Dual backend: `PIPELINE_BACKEND` setting selects `background_tasks` (FastAPI BackgroundTasks) or `temporal` (durable Temporal workflows)
- Each stage retries up to 3–5 times with exponential backoff
- AI stages use delete-then-insert for idempotent retries
- Pack status transitions: `uploading → processing → completed | failed`
- Frontend polls `GET /packs/{id}/pipeline` every 3 seconds

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
- Mock retrieval for MVP (no real county portal integration)
- AI output caching at parse and chain stages (keyed by composite version hashes)
- Deterministic flag detection via `services/flag_rules.py` with severity floor/cap rules
- Pipeline pauses at retrieve if non-digital sources exist (`awaiting_abstractor`)
- `TAPipelineRun` records version metadata for every execution

**Key files**:
- `services/flag_rules.py` — deterministic rules engine (`RULES_VERSION`, severity clamping, dedup)
- `pipeline/version_tracker.py` — prompt/tool/rules hash computation, cache key helpers
- `tests/title_search/test_determinism.py` — golden-set regression tests
- `tests/title_search/test_flag_rules.py` — rules engine unit tests

### AI Integration

`BaseAIService` in `backend/app/ai/base_service.py` is the base class for all AI work. It takes `org_id` for tenant scoping and provides:
- `call_haiku()` — text generation with 3-attempt exponential backoff
- `call_haiku_structured()` — structured output via tool_use pattern
- `call_with_tools()` — iterative tool-calling loop for multi-step agent workflows
- `call_streaming()` — SSE streaming for real-time chat responses

**Multi-provider**: Uses `litellm` under the hood. Set `AI_PLATFORM` to `anthropic`, `bedrock`, `openai`, or `azure`. Default model: `claude-haiku-4-5-20251001`. Tool definitions use Anthropic format (auto-converted to OpenAI format by `_convert_tools` when needed).

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
- **Migrations**: Alembic with async engine. Target metadata comes from `app.models.Base`. All TI models are imported in `app/models/__init__.py` so Alembic detects them.
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

**Title Intelligence routes** mount at `/api/v1/apps/title-intelligence/packs/{packId}/` with sub-resources: `pipeline`, `pages`, `extractions`, `flags`, `readiness`, `chat` (+`/stream` for SSE), `reports`, `search`.

**Title Search routes** mount at `/api/v1/apps/title-search/` with: `orders` (CRUD + `/process` + `/pipeline`), `orders/{orderId}/sources` (list + upload), `orders/{orderId}/documents` (list + correct), `orders/{orderId}/chain`, `orders/{orderId}/flags` (list + review), `orders/{orderId}/package` (get + issue + PDF), `county-sources` (platform admin CRUD).

**Frontend** (Next.js App Router at `frontend/src/app/`):
- `(auth)/login` — unauthenticated layout
- `(platform)/` — authenticated layout with sidebar: `dashboard`, `admin/*`, `apps/*`
- TI pages: `apps/title-intelligence/packs/[packId]/` with sub-pages: `documents`, `results`, `readiness`, `export`
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
| `JWT_SECRET` | (required) | HS256 signing key |
| `JWT_EXPIRATION_MINUTES` | `1440` | Token lifetime (24h) |
| `AI_PLATFORM` | `anthropic` | AI provider: anthropic/bedrock/openai/azure |
| `STORAGE_PROVIDER` | `local` | Storage backend: local/s3 |
| `PIPELINE_BACKEND` | `background_tasks` | Pipeline executor: background_tasks/temporal |
| `TESSERACT_PATH` | (system default) | Custom Tesseract binary path |
| `FILE_UPLOAD_MAX_SIZE` | `104857600` (100MB) | Max upload size |
| `CORS_ORIGINS` | `["http://localhost:3000"]` | Allowed origins |

---

## Common Gotchas

- **Circular imports in micro apps**: Every micro app `__init__.py` must use the `__getattr__` lazy import pattern (see Micro App Plugin System above). Direct imports will cause circular import errors at startup.
- **SQLite vs PostgreSQL in tests**: Tests use SQLite. `app/models/compat.py` provides `UUID` → `String(36)` and `JSONB` → `JSON` TypeDecorators. If you add a new model with PostgreSQL-specific types, use these compat types or tests will fail.
- **fpdf2 multi_cell**: Must pass `new_x="LMARGIN", new_y="NEXT"` to avoid width issues in PDF report generation.
- **Storage type hints**: Always use `StorageProvider` (the abstract base), never `LocalStorage` directly — the implementation is selected at runtime by config.
- **Tenant scoping in tests**: Tests seed a fixed org (`TEST_ORG_ID`). Any new test data must use this org ID or tenant middleware will reject it.
- **AI tool definitions**: Written in Anthropic format. `BaseAIService._convert_tools()` auto-converts to OpenAI format when `AI_PLATFORM` is openai/azure. Don't write provider-specific tool schemas.
