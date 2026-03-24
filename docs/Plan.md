# Title Intelligence Hub — Product & Engineering Specification

> **Classification**: Internal — Engineering Reference
> **Last Updated**: 2026-03-20
> **Status**: v1.0 — MVP Implementation Complete

---

## 1. Platform Overview

Title Intelligence Hub is a **multi-tenant SaaS platform** composed of pluggable **micro apps** (5–10 planned). Each micro app addresses a specific domain within the title and real estate ecosystem.

### Platform Rules

| Rule | Detail |
|------|--------|
| **Micro App Architecture** | Platform hosts 5–10 micro apps. MVP ships 2: Title Intelligence, Tax Search & Certification (stub) |
| **SaaS Model** | All micro apps hosted as multi-tenant SaaS |
| **Org-Based Purchasing** | Organizations purchase individual micro apps via subscriptions |
| **Enable/Disable** | Orgs can enable/disable purchased apps at any time |
| **Shared Database** | All micro apps share one PostgreSQL instance. Cross-app data access within same org only |
| **AI-Native** | Claude Haiku (`claude-haiku-4-5-20251001`) is the sole AI model |
| **Multi-Tenancy** | Every entity is scoped to an organization via `org_id` FK. No exceptions |

### Platform Entities

```
Organization (1) ──── (*) User (roles: owner, admin, member)
      |
      └──── (*) Subscription ──── (1) MicroApp
                  └── status: active | disabled
```

### User Roles & Permissions

| Role | Org Management | User Management | Subscriptions | Micro App Data |
|------|:-:|:-:|:-:|:-:|
| **Owner** | Full CRUD | Add/remove/promote | Purchase/enable/disable | Full access |
| **Admin** | Read | Add/remove members | Enable/disable | Full access |
| **Member** | Read | — | — | Full access |

---

## 2. Title Intelligence — Micro App

### Overview

AI-powered title document analysis platform that processes **200–500 page title commitment PDFs** and produces structured extractions, risk flags, readiness scores, and audience-specific reports.

**Target metric**: Reduce human review time from **12–15 hours to 1–2 hours** per title commitment.

### Core Value Proposition

| Without Title Intelligence | With Title Intelligence |
|---|---|
| Human reads 200–500 pages manually | AI reads all pages in 15–20 minutes |
| Human types data into 30–50 fields | AI extracts structured data with evidence |
| Human cross-references across sections | AI flags mismatches automatically |
| 12–15 hours per title commitment | 1–2 hours of human review |
| Errors caught at closing or post-close | Errors caught at ingestion |

### User Roles & Workflows

| Role | What They Do |
|---|---|
| **Processor** | Uploads title commitment, monitors processing, reviews extractions, uses chat |
| **Underwriter** | Reviews risk flags, makes approve/reject/escalate decisions via Review Assistant |
| **Attorney** | Receives attorney memo report with legal analysis |
| **Lender** | Receives lender summary with business-focused risk assessment |
| **Buyer** | Receives plain-language buyer overview |

---

## 3. End-to-End User Workflow

### Step 1: Upload
- Processor uploads title commitment PDF(s)
- Pack created with status `uploading`
- Files validated: PDF only, max 100 MB per file
- **Acceptance**: Pack appears in list with status badge, files listed with sizes

### Step 2: Process
- Processor clicks "Start Processing"
- 7-stage pipeline runs in background
- UI polls every 3 seconds, shows per-stage progress
- **Acceptance**: Pipeline progress bar updates in real time. Completion < 30 min for 300 pages

### Step 3: Review Extractions
Processor sees all extracted data organized by type:
- **Parties**: buyer, seller, lender, title company
- **Property info**: address, APN, county, state
- **Requirements**: Schedule C conditions
- **Exceptions**: Schedule B encumbrances
- **Endorsements**: ALTA coverage
- **Legal description**: metes and bounds / lot and block
- Each extraction includes evidence refs (page number + text snippet)
- **Acceptance**: All extractions displayed with evidence citations linking to source pages

### Step 4: Review Risk Flags
Underwriter reviews each flag:
- Sees severity: critical / high / medium / low
- Sees AI explanation with evidence citations
- Clicks "Get AI Recommendation" → Review Assistant suggests a decision
- Makes decision: approve / reject / escalate
- Provides reason code and optional notes
- **Acceptance**: Flag status updates immediately. Review persisted with reviewer identity and timestamp

### Step 5: Check Readiness
Dashboard shows:
- Overall score (0–100)
- Category breakdowns: requirements, endorsements, liens, exceptions, consistency
- AI-generated plain-language summary
- **Acceptance**: Score reflects current flag statuses. Recalculates on demand

### Step 6: Chat (AI Q&A)
Users ask questions in plain English:
- "What endorsements are missing?"
- "Who is the seller?"
- "What does exception #3 mean for the buyer?"
- AI responds with citations to specific pages
- Full conversation history preserved per pack
- **Acceptance**: Responses include page citations. History loads on revisit

### Step 7: Generate Reports
- User selects audience (attorney / lender / buyer) and format (PDF / JSON)
- AI generates audience-appropriate report
- Download link provided
- **Acceptance**: Report reflects all extractions, flags, and readiness data

### Step 8: Audit Trail
All actions logged for compliance:
- Flag reviews with decision, reviewer, timestamp
- Reports generated
- AI assistant consultations

---

## 4. Processing Pipeline (7 Stages)

| # | Stage | What Happens | Output | Retry |
|---|-------|-------------|--------|-------|
| 1 | **Ingest** | Validate uploaded files, mark pack as processing | Pack status → `processing` | 3x |
| 2 | **Render** | PyMuPDF: PDF → JPEG pages + thumbnails (200px wide) | Page images in storage | 3x |
| 3 | **OCR** | Claude Vision: page image → text extraction | `ocr_text` per page, OCR JSON in storage | 5x |
| 4 | **Index** | Chunk OCR text into paragraphs, create search index | TextChunk records with tsvector | 3x |
| 5 | **Ingestion Agent** | AI detects sections, extracts structured data with evidence | Section + Extraction records | 5x |
| 6 | **Risk Agent** | AI analyzes extractions for ALTA compliance risks | Flag records with severity | 5x |
| 7 | **Complete** | Calculate readiness score, generate AI summary | Pack status → `completed` | 3x |

### Pipeline Characteristics

| Property | Specification |
|----------|---------------|
| **Execution** | FastAPI `BackgroundTasks` — no Celery/Redis for MVP |
| **Idempotency** | Every stage uses delete-then-insert pattern for safe retries |
| **Retry** | Exponential backoff: 2s base, doubles per attempt |
| **AI stage retries** | 5 attempts max for OCR, Ingestion Agent, Risk Agent |
| **Non-AI retries** | 3 attempts max for Ingest, Render, Index, Complete |
| **Failure** | On final retry failure: `pack.status = "failed"`, `pack.error_message` set |
| **Status polling** | Frontend polls `GET /packs/{id}/pipeline` every 3 seconds |
| **Status transitions** | `uploading → processing → completed \| failed` |

---

## 5. Database Schema

All TI tables prefixed with `ti_`. All tenant-scoped tables include `org_id` FK + index.

### `ti_packs`

| Column | Type | Constraints | Notes |
|--------|------|------------|-------|
| `id` | UUID | PK | |
| `org_id` | UUID | FK → organizations, NOT NULL, indexed | TenantMixin |
| `name` | VARCHAR(255) | NOT NULL | User-given name |
| `status` | VARCHAR(50) | NOT NULL, default "uploading" | uploading, processing, completed, failed |
| `current_stage` | VARCHAR(50) | nullable | Current pipeline stage |
| `readiness_score` | INTEGER | nullable | 0–100, set on completion |
| `readiness_summary` | TEXT | nullable | AI-generated summary |
| `error_message` | TEXT | nullable | Set on failure |
| `created_at` | TIMESTAMPTZ | NOT NULL | TimestampMixin |
| `updated_at` | TIMESTAMPTZ | NOT NULL | TimestampMixin |

### `ti_pack_files`

| Column | Type | Constraints | Notes |
|--------|------|------------|-------|
| `id` | UUID | PK | |
| `pack_id` | UUID | FK → ti_packs, NOT NULL | |
| `org_id` | UUID | FK → organizations, NOT NULL, indexed | |
| `filename` | VARCHAR(255) | NOT NULL | Original filename |
| `storage_path` | TEXT | NOT NULL | Path in storage |
| `file_size` | BIGINT | NOT NULL | Bytes |
| `page_count` | INTEGER | nullable | Set after render |
| `created_at` | TIMESTAMPTZ | NOT NULL | |

### `ti_pages`

| Column | Type | Constraints | Notes |
|--------|------|------------|-------|
| `id` | UUID | PK | |
| `pack_id` | UUID | FK → ti_packs, NOT NULL | |
| `file_id` | UUID | FK → ti_pack_files, NOT NULL | |
| `org_id` | UUID | FK → organizations, NOT NULL, indexed | |
| `page_number` | INTEGER | NOT NULL | 1-indexed |
| `image_uri` | TEXT | NOT NULL | Path to JPEG |
| `thumb_uri` | TEXT | NOT NULL | Path to thumbnail |
| `ocr_uri` | TEXT | nullable | Path to OCR JSON |
| `ocr_text` | TEXT | nullable | Plain text |
| `created_at` | TIMESTAMPTZ | NOT NULL | |

### `ti_sections`

| Column | Type | Constraints | Notes |
|--------|------|------------|-------|
| `id` | UUID | PK | |
| `pack_id` | UUID | FK → ti_packs, NOT NULL | |
| `org_id` | UUID | FK → organizations, NOT NULL, indexed | |
| `section_type` | VARCHAR(50) | NOT NULL | schedule_a, schedule_b, schedule_c, endorsements, legal_description |
| `start_page` | INTEGER | NOT NULL | |
| `end_page` | INTEGER | NOT NULL | |
| `confidence` | FLOAT | NOT NULL | 0.0–1.0 |
| `created_at` | TIMESTAMPTZ | NOT NULL | |

### `ti_extractions`

| Column | Type | Constraints | Notes |
|--------|------|------------|-------|
| `id` | UUID | PK | |
| `pack_id` | UUID | FK → ti_packs, NOT NULL | |
| `org_id` | UUID | FK → organizations, NOT NULL, indexed | |
| `extraction_type` | VARCHAR(50) | NOT NULL | party, property_info, requirement, exception, endorsement, legal_description |
| `label` | VARCHAR(255) | NOT NULL | e.g., "Buyer", "APN" |
| `value` | JSONB | NOT NULL | Flexible extracted data |
| `evidence_refs` | JSONB | NOT NULL | Array of `{page_number, text_snippet}` |
| `section_id` | UUID | FK → ti_sections, nullable | |
| `confidence` | FLOAT | NOT NULL | 0.0–1.0 |
| `created_at` | TIMESTAMPTZ | NOT NULL | |

### `ti_flags`

| Column | Type | Constraints | Notes |
|--------|------|------------|-------|
| `id` | UUID | PK | |
| `pack_id` | UUID | FK → ti_packs, NOT NULL | |
| `org_id` | UUID | FK → organizations, NOT NULL, indexed | |
| `flag_type` | VARCHAR(50) | NOT NULL | missing_endorsement, unacceptable_exception, unresolved_lien, cross_section_mismatch, requirement_missing_proof |
| `severity` | VARCHAR(20) | NOT NULL | critical, high, medium, low |
| `title` | VARCHAR(255) | NOT NULL | Short description |
| `description` | TEXT | NOT NULL | Detailed description |
| `ai_explanation` | TEXT | NOT NULL | AI reasoning |
| `evidence_refs` | JSONB | NOT NULL | Array of `{page_number, text_snippet}` |
| `status` | VARCHAR(50) | NOT NULL, default "open" | open, approved, rejected, escalated |
| `created_at` | TIMESTAMPTZ | NOT NULL | |

### `ti_reviews`

| Column | Type | Constraints | Notes |
|--------|------|------------|-------|
| `id` | UUID | PK | |
| `flag_id` | UUID | FK → ti_flags, NOT NULL | |
| `org_id` | UUID | FK → organizations, NOT NULL, indexed | |
| `reviewer_id` | UUID | FK → users, NOT NULL | |
| `decision` | VARCHAR(50) | NOT NULL | approve, reject, escalate |
| `reason_code` | VARCHAR(100) | NOT NULL | |
| `notes` | TEXT | nullable | |
| `created_at` | TIMESTAMPTZ | NOT NULL | |

### `ti_text_chunks`

| Column | Type | Constraints | Notes |
|--------|------|------------|-------|
| `id` | UUID | PK | |
| `pack_id` | UUID | FK → ti_packs, NOT NULL | |
| `org_id` | UUID | FK → organizations, NOT NULL, indexed | |
| `page_number` | INTEGER | NOT NULL | |
| `section_type` | VARCHAR(50) | nullable | |
| `content` | TEXT | NOT NULL | Chunk text |
| `ts_content` | TSVECTOR | nullable | PostgreSQL only, GIN-indexed |
| `created_at` | TIMESTAMPTZ | NOT NULL | |

### `ti_chat_messages`

| Column | Type | Constraints | Notes |
|--------|------|------------|-------|
| `id` | UUID | PK | |
| `pack_id` | UUID | FK → ti_packs, NOT NULL | |
| `org_id` | UUID | FK → organizations, NOT NULL, indexed | |
| `role` | VARCHAR(20) | NOT NULL | user, assistant |
| `content` | TEXT | NOT NULL | Message text |
| `citations` | JSONB | nullable | Array of `{page_number, text_snippet}` |
| `user_id` | UUID | FK → users, nullable | null for assistant messages |
| `created_at` | TIMESTAMPTZ | NOT NULL | |

### Data Model Relationships

```
Pack (1) ──── (*) PackFile (1) ──── (*) Page
  |                                       └── image_uri, thumb_uri, ocr_text
  |
  ├──── (*) Section (schedule_a, schedule_b, schedule_c, endorsements, legal_description)
  |           └── start_page, end_page, confidence
  |
  ├──── (*) Extraction (party, property_info, requirement, exception, endorsement, legal_description)
  |           └── label, value (JSONB), evidence_refs[]
  |
  ├──── (*) Flag
  |           ├── severity, title, description, ai_explanation, status
  |           ├── evidence_refs[]
  |           └──── (*) Review (approve/reject/escalate + reason_code + notes + reviewer)
  |
  ├──── (*) TextChunk (full-text search via tsvector + GIN)
  |
  └──── (*) ChatMessage (user/assistant + citations)
```

---

## 6. API Contract

All endpoints mounted at `/api/v1/apps/title-intelligence/`. Subscription gating handled by `MicroAppAccessMiddleware`.

### Pack Management

| Method | Path | Request | Response | Status Codes |
|--------|------|---------|----------|:---:|
| `POST` | `/packs` | `{name: string}` | `PackOut` | 201, 400, 403 |
| `GET` | `/packs` | — | `PackOut[]` | 200, 403 |
| `GET` | `/packs/{packId}` | — | `PackOut` (with files) | 200, 404 |
| `DELETE` | `/packs/{packId}` | — | `{detail: "deleted"}` | 200, 404 |

### File Upload & Processing

| Method | Path | Request | Response | Status Codes |
|--------|------|---------|----------|:---:|
| `POST` | `/packs/{packId}/files` | multipart/form-data (PDF) | `PackFileOut[]` | 201, 400, 404, 413 |
| `POST` | `/packs/{packId}/process` | — | `{detail: "started"}` | 200, 400, 404 |
| `GET` | `/packs/{packId}/pipeline` | — | `PipelineStatus` | 200, 404 |

### Pages

| Method | Path | Request | Response | Status Codes |
|--------|------|---------|----------|:---:|
| `GET` | `/packs/{packId}/pages` | — | `PageOut[]` | 200, 404 |

### Extractions

| Method | Path | Request | Response | Status Codes |
|--------|------|---------|----------|:---:|
| `GET` | `/packs/{packId}/extractions` | — | `ExtractionOut[]` | 200, 404 |

### Risk Flags

| Method | Path | Request | Response | Status Codes |
|--------|------|---------|----------|:---:|
| `GET` | `/packs/{packId}/flags` | — | `{flags, counts_by_severity}` | 200, 404 |
| `GET` | `/packs/{packId}/flags/{flagId}` | — | `FlagDetailOut` (with reviews) | 200, 404 |
| `POST` | `/packs/{packId}/flags/{flagId}/review` | `{decision, reason_code, notes?}` | `ReviewOut` | 201, 400, 404 |
| `GET` | `/packs/{packId}/flags/{flagId}/recommend` | — | `{decision, reasoning, confidence}` | 200, 404 |

### Readiness

| Method | Path | Request | Response | Status Codes |
|--------|------|---------|----------|:---:|
| `GET` | `/packs/{packId}/readiness` | — | `ReadinessOut` (score + categories) | 200, 404 |

### Chat

| Method | Path | Request | Response | Status Codes |
|--------|------|---------|----------|:---:|
| `POST` | `/packs/{packId}/chat` | `{message: string}` | `ChatMessageOut` | 201, 400, 404 |
| `GET` | `/packs/{packId}/chat` | — | `ChatMessageOut[]` | 200, 404 |

### Reports

| Method | Path | Request | Response | Status Codes |
|--------|------|---------|----------|:---:|
| `POST` | `/packs/{packId}/reports` | `{audience, format}` | `{content: string}` | 200, 400, 404 |

### Search

| Method | Path | Request | Response | Status Codes |
|--------|------|---------|----------|:---:|
| `GET` | `/packs/{packId}/search?q=...` | query param `q` | `SearchResultOut[]` | 200, 404 |

### Error Response Format

All errors return:
```json
{
  "detail": "Human-readable error message"
}
```

### Common Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 201 | Created |
| 400 | Bad request (invalid input, wrong state) |
| 403 | Not authorized or no active subscription |
| 404 | Resource not found |
| 413 | File too large (> 100 MB) |
| 500 | Server error |

---

## 7. AI Agents

All agents subclass `BaseAIService` which provides:
- `call_haiku()` — text generation with 3-attempt exponential backoff
- `call_haiku_structured()` — structured output via tool_use pattern
- Tenant-scoped via `org_id`

| Agent | Purpose | Input | Output | Method |
|-------|---------|-------|--------|--------|
| **OCRAgent** | Extract text from page image | Page image (base64) | `{text, confidence}` | `call_haiku_structured` |
| **IngestionAgent** | Detect sections + extract structured data | OCR text for all pages | Sections + Extractions | `call_haiku_structured` |
| **RiskAgent** | Identify ALTA compliance risks | All extractions + sections | Flags with severity + evidence | `call_haiku_structured` |
| **ChatAgent** | Answer questions with citations | Question + search results + extractions + history | Answer with page citations | `call_haiku` |
| **ReviewAssistant** | Recommend decision for a flag | Flag + extractions + evidence | `{decision, reasoning, confidence}` | `call_haiku_structured` |
| **ReportAgent** | Generate audience-specific report | Extractions + flags + readiness | Report text | `call_haiku` |

---

## 8. Security Requirements

| Area | Requirement |
|------|-------------|
| **Authentication** | All API routes except `/api/v1/health` require valid Supabase JWT |
| **Authorization** | Role-based via `get_current_member()`, `require_admin()`, `require_owner()` |
| **Tenant isolation** | `TenantMixin` on all tables. `MicroAppAccessMiddleware` gates app routes. Every query filters by `org_id` |
| **File validation** | PDF-only (content-type check), max 100 MB (`FILE_UPLOAD_MAX_SIZE`), stored outside webroot |
| **SQL injection** | SQLAlchemy ORM only — no raw string interpolation |
| **CORS** | Explicit origin allowlist via `CORS_ORIGINS` |
| **Secrets** | All credentials via env vars / `Settings`. No hardcoded keys |
| **Row-Level Security** | RLS enabled on all PostgreSQL tables |

---

## 9. Performance Targets

| Metric | Target |
|--------|--------|
| **API CRUD response** | < 200ms |
| **API list queries** | < 500ms |
| **Pipeline (300 pages)** | < 30 minutes end-to-end |
| **OCR per page** | 10–30 seconds |
| **AI agent calls** | Return within 30 seconds per invocation |
| **File upload** | Support up to 100 MB per file |
| **Concurrent packs** | Support 5 concurrent pipeline runs per org |

---

## 10. Testing Strategy

| Layer | Tool | Coverage Target |
|-------|------|:---:|
| **Unit tests** | pytest + SQLite | Every endpoint happy path + primary error cases |
| **DB compat** | `app/models/compat.py` | JSONB → JSON, UUID → CHAR(36) on SQLite |
| **Test isolation** | Per-test table create/drop | No test pollution |
| **Auth bypass** | Dependency overrides | Fixed `AuthenticatedUser` + owner-role `User` |
| **Middleware** | `session_factory_override` | Test DB used by `MicroAppAccessMiddleware` |
| **Seed data** | conftest fixtures | Org, User, MicroApp, Subscription pre-seeded |

### Running Tests

```bash
cd backend && pytest                              # all tests
cd backend && pytest tests/title_intelligence/ -v  # TI tests only
cd backend && pytest tests/test_health.py          # single file
```

---

## 11. Storage Architecture

Local filesystem with abstract interface (`services/storage.py`). Configurable via `STORAGE_PATH` env var.

### Path Convention

```
{STORAGE_PATH}/
  {org_id}/
    {pack_id}/
      files/{filename}          # uploaded PDFs
      pages/page_0001.jpg       # rendered page images
      thumbs/page_0001.jpg      # thumbnails (200px wide)
      ocr/page_0001.json        # OCR output JSON
```

- All paths tenant-scoped by `org_id` at top level
- Abstraction designed to swap for S3/GCS without changing calling code
- Docker: `storage_data` named volume mounted to backend service

---

## 12. Frontend Architecture

### Tech Stack

- **Framework**: Next.js 14 (App Router)
- **UI**: shadcn/ui + Tailwind CSS
- **State**: Zustand (org store, persisted to localStorage)
- **Auth**: Supabase Auth (SSR via `@supabase/ssr`)
- **API**: `apiFetch()` + `uploadFiles()` with auto-injected JWT + `X-Org-Id`
- **File upload**: `react-dropzone`

### Route Structure

| Route | Component | Description |
|-------|-----------|-------------|
| `/apps/title-intelligence` | Pack list | All packs for current org |
| `/apps/title-intelligence/packs/new` | Upload flow | Dropzone + pack creation |
| `/apps/title-intelligence/packs/[packId]` | Pack overview | Pipeline progress + files |
| `.../[packId]/extractions` | Extraction table | Grouped by type with evidence |
| `.../[packId]/flags` | Flag cards | Severity-colored cards with review modal |
| `.../[packId]/readiness` | Readiness gauge | Score + category breakdown |
| `.../[packId]/chat` | Chat panel | Message list + input |
| `.../[packId]/reports` | Report generator | Audience/format selector + download |

---

## 13. Deployment

### Docker Compose (Development)

```yaml
Services:
  db:        PostgreSQL 16 on :5432
  backend:   FastAPI on :8000 (auto-reload, storage volume)
  frontend:  Next.js on :3000
```

### Environment Variables

| Variable | Required | Default | Description |
|----------|:---:|---------|-------------|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `ANTHROPIC_API_KEY` | Yes | — | Claude API key |
| `NEXT_PUBLIC_SUPABASE_URL` | Yes | — | Supabase project URL |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | Yes | — | Supabase anon key |
| `SUPABASE_JWT_SECRET` | Yes | — | JWT verification secret |
| `STORAGE_PATH` | No | `./storage` | File storage root |
| `FILE_UPLOAD_MAX_SIZE` | No | `104857600` | Max upload size in bytes (100 MB) |
| `CORS_ORIGINS` | No | `["http://localhost:3000"]` | Allowed CORS origins |

---

## 14. ROI Calculator — Sub-App

### Overview

Static page within Title Intelligence that helps lenders, title companies, and operations teams estimate business value of AI-powered title review.

### What It Measures

- Reduction in manual effort
- Faster turnaround time
- Lower error rates
- Improved staff productivity
- Cost savings per file

### How It Works

Users input operational volumes, processing times, staffing costs, and exception rates. Calculator projects:
- Potential annual savings
- Efficiency gains
- Payback period

---

## 15. Tax Search & Certification — Micro App

*Stub implemented. Full specification to be defined.*

---

## 16. Verification Checklist

### Platform

- [ ] `POST /api/v1/organizations` creates an org
- [ ] `POST /api/v1/subscriptions` purchases a micro app for an org
- [ ] Unauthenticated requests to any non-health endpoint return 401
- [ ] Requests to `/api/v1/apps/title-intelligence/*` without active subscription return 403
- [ ] User from Org A cannot access Org B's data

### Title Intelligence — Upload & Processing

- [ ] `POST /packs` creates a pack with status `uploading`
- [ ] `POST /packs/{id}/files` accepts PDF upload, rejects non-PDF
- [ ] `POST /packs/{id}/process` triggers pipeline, returns immediately
- [ ] `GET /packs/{id}/pipeline` shows per-stage progress
- [ ] Full pipeline completes for a 300-page PDF in < 30 minutes
- [ ] Pipeline failure sets `pack.status = "failed"` with error message

### Title Intelligence — Extractions & Flags

- [ ] `GET /packs/{id}/extractions` returns structured data with evidence refs
- [ ] `GET /packs/{id}/flags` returns risk flags grouped by severity
- [ ] `POST /packs/{id}/flags/{flagId}/review` creates review, updates flag status
- [ ] `GET /packs/{id}/flags/{flagId}/recommend` returns AI recommendation

### Title Intelligence — Readiness, Chat, Reports

- [ ] `GET /packs/{id}/readiness` returns score 0–100 with category breakdown
- [ ] `POST /packs/{id}/chat` returns AI answer with page citations
- [ ] `GET /packs/{id}/chat` returns full conversation history
- [ ] `POST /packs/{id}/reports` generates audience-specific report
- [ ] `GET /packs/{id}/search?q=term` returns matching text chunks

### Frontend

- [ ] Pack list page loads and shows all packs
- [ ] Upload dropzone accepts PDFs, creates pack, uploads files
- [ ] Pipeline progress updates in real time during processing
- [ ] Extraction table displays all types with evidence citations
- [ ] Flag cards show severity colors, review modal works
- [ ] Readiness gauge displays score and categories
- [ ] Chat panel sends messages and displays AI responses with citations
- [ ] Report page generates and downloads reports

### Tests

- [ ] `cd backend && pytest` — all tests pass (platform + TI)
- [ ] No test touches the production database
- [ ] Every TI endpoint has at least one test
