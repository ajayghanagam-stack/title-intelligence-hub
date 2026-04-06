# Micro-Apps Golden Template Readiness Report

> **Classification**: Internal — Engineering Reference
> **Generated**: 2026-03-23
> **Scope**: Title Intelligence Hub — Full Codebase Audit (Phases 0–2)

---

## Table of Contents

- [Phase 0 — Codebase Discovery](#phase-0--codebase-discovery)
- [Phase 1 — Reverse-Engineer Implemented Requirements](#phase-1--reverse-engineer-implemented-requirements)
- [Phase 2 — Current Architecture Assessment](#phase-2--current-architecture-assessment)
- [Phase 3 — Target Golden Template Mapping](#phase-3--target-golden-template-mapping)
- [Phase 4 — Claude Code Operating Artifacts](#phase-4--claude-code-operating-artifacts)
- [Phase 5 — Phased Refactor Roadmap](#phase-5--phased-refactor-roadmap)

---

# Phase 0 — Codebase Discovery

## 1. Tech Stack

| Layer | Technology | Version/Detail |
|-------|-----------|----------------|
| **Backend Framework** | FastAPI | Async, with Starlette middleware |
| **Python** | 3.12 | `python:3.12-slim` Docker image |
| **ORM** | SQLAlchemy 2.0 | Async sessions via `asyncpg` (prod) / `aiosqlite` (test) |
| **Database** | PostgreSQL 16 | RLS enabled, JSONB+GIN indexes |
| **Migrations** | Alembic | Async engine, append-only in prod |
| **Auth** | Local JWT (HS256) | `PyJWT` + `passlib[bcrypt]`, no Supabase |
| **AI** | LiteLLM | Multi-provider: Anthropic, Bedrock, OpenAI, Azure |
| **AI Model** | Claude Haiku 4.5 | `claude-haiku-4-5-20251001` default |
| **OCR** | Tesseract | Via `pytesseract`, sync wrapped in `asyncio.to_thread` |
| **PDF Rendering** | pdf2image (Poppler) | Page image extraction |
| **Report Gen** | fpdf2 | PDF + JSON + Markdown output |
| **Pipeline** | BackgroundTasks / Temporal | Toggle via `PIPELINE_BACKEND` setting |
| **Frontend** | Next.js 14 | App Router, `"use client"` components |
| **TypeScript** | Strict mode | No `any` without justification |
| **Styling** | Tailwind CSS 3 | OKLch color system, custom component classes |
| **State** | Zustand | `org-store.ts`, persisted to localStorage |
| **Fonts** | Geist / Geist Mono | Via `next/font/google` |
| **Storage** | Abstract `StorageProvider` | `LocalStorage` + `S3Storage` (aiobotocore) |
| **Containerization** | Docker Compose | 5 services: db, backend, frontend, temporal, temporal-worker |

## 2. Repository / Module Map

```
title_intelligence_hub/
├── backend/
│   ├── app/
│   │   ├── main.py                          # FastAPI app factory (create_app)
│   │   ├── config.py                        # Pydantic Settings
│   │   ├── database.py                      # Async engine + session factory
│   │   ├── dependencies.py                  # Auth deps (get_current_user, get_current_member, require_*)
│   │   ├── ai/
│   │   │   └── base_service.py              # BaseAIService (litellm, call_haiku, call_with_tools, call_streaming)
│   │   ├── middleware/
│   │   │   ├── tenant.py                    # TenantContextMiddleware (X-Org-Id → request.state.org_id)
│   │   │   └── micro_app_access.py          # MicroAppAccessMiddleware (subscription gate)
│   │   ├── models/
│   │   │   ├── base.py                      # Base, TenantMixin, TimestampMixin
│   │   │   ├── compat.py                    # Cross-DB UUID + JSONB TypeDecorators
│   │   │   ├── organization.py, user.py, micro_app.py, subscription.py
│   │   │   └── __init__.py                  # Imports all models for Alembic
│   │   ├── routes/
│   │   │   ├── auth.py                      # POST /login, GET /me
│   │   │   ├── organizations.py, micro_apps.py, subscriptions.py, admin.py
│   │   │   └── health.py
│   │   ├── services/
│   │   │   ├── auth_service.py              # bcrypt hash/verify, JWT create/decode
│   │   │   └── storage.py                   # StorageProvider ABC + LocalStorage + S3Storage
│   │   ├── micro_apps/
│   │   │   ├── registry.py                  # Auto-discovers micro apps at startup
│   │   │   └── title_intelligence/
│   │   │       ├── __init__.py              # __getattr__ lazy import (anti-circular)
│   │   │       ├── app.py                   # TitleIntelligenceApp(MicroAppBase)
│   │   │       ├── models/                  # ti_packs, ti_pack_files, ti_pages, ti_sections,
│   │   │       │                            # ti_extractions, ti_flags, ti_reviews, ti_text_chunks,
│   │   │       │                            # ti_chat_messages
│   │   │       ├── schemas/                 # Pydantic request/response schemas
│   │   │       ├── services/                # pack_service, page_service, extraction_service,
│   │   │       │                            # flag_service, readiness_service, chat_service,
│   │   │       │                            # report_service, search_service
│   │   │       ├── routes/                  # packs, pages, extractions, flags, readiness,
│   │   │       │                            # chat, reports, search
│   │   │       ├── ai/                      # ocr_agent, ingestion_agent, risk_agent,
│   │   │       │                            # chat_agent, review_assistant, report_agent
│   │   │       └── pipeline/
│   │   │           ├── orchestrator.py       # BackgroundTasks orchestrator
│   │   │           ├── stages.py             # 7 stages: ingest → render → ocr → index →
│   │   │           │                         #   ingestion_agent → risk_agent → complete
│   │   │           ├── temporal_orchestrator.py  # Temporal workflow definition
│   │   │           └── temporal_activities.py    # Temporal activity implementations
│   │   └── schemas/                         # Platform-level Pydantic schemas
│   ├── alembic/                             # Migration versions
│   ├── scripts/seed.py                      # Seeds admin user + test org
│   ├── tests/
│   │   ├── conftest.py                      # SQLite test DB, fixture overrides
│   │   ├── title_intelligence/conftest.py   # TI-specific fixtures
│   │   └── *.py                             # 59 passing tests
│   ├── requirements.txt
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx                   # Root layout (Geist font)
│   │   │   ├── globals.css                  # OKLch theme + component classes
│   │   │   ├── page.tsx                     # Login page
│   │   │   └── (platform)/
│   │   │       ├── layout.tsx               # Sidebar + main content wrapper
│   │   │       ├── dashboard/page.tsx
│   │   │       ├── admin/                   # users, subscriptions, accounts, apps
│   │   │       └── apps/title-intelligence/
│   │   │           ├── page.tsx             # Pack list
│   │   │           └── packs/
│   │   │               ├── new/page.tsx     # Upload flow
│   │   │               └── [packId]/
│   │   │                   ├── layout.tsx   # Breadcrumbs wrapper
│   │   │                   ├── page.tsx     # Pack overview + pipeline
│   │   │                   ├── results/page.tsx  # Tabs: Flags/Checklist/Extractions
│   │   │                   └── documents/page.tsx # Document viewer
│   │   ├── components/
│   │   │   ├── sidebar.tsx                  # White sidebar with amber accents
│   │   │   └── title-intelligence/
│   │   │       ├── flags-table.tsx          # Flag rows + quick actions + pagination
│   │   │       ├── flag-detail-dialog.tsx   # Full flag review modal
│   │   │       ├── extraction-table.tsx     # Grouped accordion + filter pills + pagination
│   │   │       ├── readiness-dashboard.tsx  # Donut + categories + AI summary
│   │   │       ├── closing-checklist.tsx    # Checklist items + inline actions + pagination
│   │   │       ├── pipeline-progress.tsx    # Circular pipeline with connecting lines
│   │   │       ├── pack-status-badge.tsx    # Status pills
│   │   │       ├── severity-badge.tsx       # critical/high/medium/low badges
│   │   │       ├── chat-slide-panel.tsx     # Sliding chat panel
│   │   │       ├── chat-panel.tsx           # Full chat page component
│   │   │       ├── chat-message.tsx         # Message bubble
│   │   │       ├── export-panel.tsx         # Report generation UI
│   │   │       ├── review-form.tsx          # Flag review form
│   │   │       ├── review-assistant-panel.tsx # AI recommendation panel
│   │   │       └── pagination.tsx           # Reusable pagination + usePagination hook
│   │   ├── hooks/
│   │   │   ├── use-auth.ts                 # Login/logout/token management
│   │   │   ├── use-org.ts                  # orgFetch wrapper with X-Org-Id
│   │   │   ├── use-packs.ts               # Pack list fetching
│   │   │   ├── use-pack.ts                # Single pack + polling
│   │   │   ├── use-chat.ts                # Chat message management
│   │   │   └── use-pipeline-status.ts     # Pipeline polling
│   │   ├── lib/
│   │   │   ├── api.ts                     # apiFetch, uploadFiles (auth headers)
│   │   │   ├── auth.ts                    # getToken/setToken/clearToken/login/signOut/fetchMe
│   │   │   ├── ti-types.ts               # TI TypeScript interfaces
│   │   │   ├── ti-constants.ts            # Category labels, severity maps
│   │   │   └── utils.ts                   # cn() utility (clsx + twMerge)
│   │   └── stores/
│   │       └── org-store.ts               # Zustand org state (persisted)
│   ├── tailwind.config.ts
│   ├── next.config.js
│   └── Dockerfile
├── docker-compose.yml                      # 5 services
├── docs/Plan.md                            # Full product spec
└── CLAUDE.md                               # Project operating guide
```

## 3. Main Entry Points

| Entry Point | File | Purpose |
|-------------|------|---------|
| **Backend app factory** | `backend/app/main.py` → `create_app()` | Creates FastAPI app, mounts middleware, discovers micro apps, includes routers |
| **Frontend root** | `frontend/src/app/layout.tsx` | Next.js root layout with Geist font |
| **Login page** | `frontend/src/app/page.tsx` | Auth entry, redirects to `/dashboard` |
| **Platform layout** | `frontend/src/app/(platform)/layout.tsx` | Sidebar + main content area |
| **Temporal worker** | `backend/app/micro_apps/title_intelligence/pipeline/temporal_activities.py` | Separate process for pipeline activities |
| **Seed script** | `backend/scripts/seed.py` | Creates admin user + test org + subscriptions |
| **Alembic** | `backend/alembic/env.py` | Migration runner |

## 4. Major Runtime Components

| Component | Responsibility |
|-----------|---------------|
| **FastAPI App** | HTTP server, route handling, dependency injection |
| **Middleware Stack** | CORS → TenantContext → MicroAppAccess (Starlette LIFO) |
| **Auth Dependencies** | JWT decode → user lookup → member validation → role check |
| **Micro App Registry** | Auto-discovers `micro_apps/*/` at startup, mounts routers |
| **Pipeline Orchestrator** | Runs 7 stages sequentially (BackgroundTasks or Temporal) |
| **AI Agent System** | `BaseAIService` → domain agents (OCR, Ingestion, Risk, Chat, Review, Report) |
| **Storage Provider** | Abstract file I/O (Local or S3), tenant-scoped paths |
| **Zustand Store** | Client-side org state with localStorage persistence |
| **Next.js App Router** | File-based routing with `(platform)` route group |

## 5. Request Flow

```
Browser → Next.js frontend → apiFetch() adds Auth+OrgId headers
  → FastAPI backend
    → CORS middleware (allow/deny origin)
    → TenantContextMiddleware (resolve org_id → request.state.org_id)
    → MicroAppAccessMiddleware (check subscription for /apps/{slug}/* routes)
    → FastAPI route handler
      → get_current_user() dep (decode JWT → AuthenticatedUser)
      → get_current_member() dep (verify user ∈ org → User model)
      → Service layer (business logic)
      → SQLAlchemy async session (tenant-scoped queries)
    → JSON response
```

## 6. Auth Flow

```
1. POST /api/v1/auth/login { email, password }
2. auth_service.authenticate_user() → bcrypt verify
3. auth_service.create_access_token() → HS256 JWT with { sub: user_id, org_id }
4. Frontend stores token in localStorage (key: "auth_token")
5. All subsequent requests: Authorization: Bearer <token> + X-Org-Id: <org_id>
6. Backend: get_current_user() decodes JWT → AuthenticatedUser
7. Backend: get_current_member() looks up User in org → validates membership + role
```

## 7. Tenant Flow

```
1. Request arrives with X-Org-Id header (or falls back to JWT app_metadata.org_id)
2. TenantContextMiddleware sets request.state.org_id
3. MicroAppAccessMiddleware checks org has active subscription for the micro app
4. get_current_member() validates user belongs to this org
5. All DB queries filter by org_id (TenantMixin adds FK+index)
6. Storage paths scoped: {org_id}/{pack_id}/files/...
7. PostgreSQL RLS enabled as defense-in-depth
```

## 8. Persistence Flow

```
Backend:
  app/database.py → create_async_engine(DATABASE_URL)
                   → async_sessionmaker → get_db() dependency

  Models: Base → TenantMixin(org_id FK+index) + TimestampMixin(created_at/updated_at)
  Compat: UUID → native PG UUID or String(36) SQLite
          JSONB → native PG JSONB or JSON SQLite

  Queries: Always session.execute(select(Model).where(Model.org_id == org_id))

  Migrations: Alembic with async engine, target_metadata = Base.metadata

Frontend:
  Zustand org-store → localStorage persistence (org_id, org_name)
  Auth token → localStorage (key: "auth_token")
```

## 9. Key Files to Inspect Next

| File | Why |
|------|-----|
| `docs/Plan.md` | Full product spec — the "requirements truth" |
| `backend/app/micro_apps/title_intelligence/routes/*.py` | All API endpoints — what's actually implemented |
| `backend/app/micro_apps/title_intelligence/schemas/*.py` | Request/response contracts |
| `backend/app/micro_apps/title_intelligence/pipeline/stages.py` | Pipeline stage logic |
| `backend/app/micro_apps/title_intelligence/ai/*.py` | All 6 AI agent implementations |
| `backend/app/micro_apps/title_intelligence/services/*.py` | Business logic for each domain |
| `backend/tests/title_intelligence/` | Test coverage map |
| `frontend/src/lib/ti-types.ts` | Frontend type definitions |

## 10. Risks, Blind Spots, and Unknowns

| # | Risk/Unknown | Severity | Detail |
|---|-------------|----------|--------|
| 1 | **No rate limiting** | Medium | No request rate limiting on any endpoint — AI endpoints are expensive |
| 2 | **BackgroundTasks reliability** | Medium | Default pipeline backend uses FastAPI BackgroundTasks — no persistence, no retry across server restarts |
| 3 | **Temporal optional but complex** | Low | Temporal adds 2 extra containers but provides durable execution; toggle adds code paths to maintain |
| 4 | **No WebSocket/SSE for pipeline** | Low | Frontend polls every 3 seconds — works but not real-time |
| 5 | **Test DB mismatch** | Medium | Tests use SQLite, prod uses PostgreSQL — some SQL behavior differences possible (JSONB, UUID, RLS) |
| 6 | **No CI/CD pipeline** | High | No GitHub Actions, no automated test/build/deploy pipeline visible |
| 7 | **Single-file storage abstraction** | Low | S3Storage exists but hasn't been verified in production |
| 8 | **No observability** | Medium | No structured logging, no metrics, no tracing beyond basic `console.error` |
| 9 | **PDF processing resource-bound** | Medium | Tesseract OCR + pdf2image are CPU-heavy; no queue depth limiting |
| 10 | **No API versioning strategy** | Low | All routes at `/api/v1/` but no plan for v2 migration documented |

---

# Phase 1 — Reverse-Engineer Implemented Requirements

## Requirement Traceability Matrix

### Legend

- **FULL** = Implemented end-to-end (backend + frontend + tests)
- **PARTIAL** = Implemented but incomplete or deviating from spec
- **BACKEND-ONLY** = Backend done, no frontend
- **MISSING** = Not implemented anywhere
- **EXTRA** = Implemented but not in the spec

---

## A. Platform Requirements

| # | Spec Requirement | Status | Evidence | Gaps |
|---|-----------------|--------|----------|------|
| P1 | Multi-tenant SaaS with org-based scoping | **FULL** | `TenantMixin`, `TenantContextMiddleware`, `X-Org-Id` header, org_id on all TI tables | — |
| P2 | Org CRUD (create, read, update) | **FULL** | `POST/GET/PATCH /organizations`, admin accounts endpoint | No DELETE org |
| P3 | User management (invite, update, roles) | **PARTIAL** | `POST .../users/invite`, `PATCH .../users/{id}` | No DELETE user, no deactivate |
| P4 | Subscription purchase + enable/disable | **FULL** | `POST/PATCH /subscriptions`, admin toggle | — |
| P5 | Micro app plugin system | **FULL** | `registry.py` auto-discovers `micro_apps/*/` | — |
| P6 | MicroAppAccessMiddleware (subscription gate) | **FULL** | Returns 403 if no active sub | Tested indirectly |
| P7 | Role-based access control (owner/admin/member) | **FULL** | `require_admin()`, `require_owner()`, `get_current_member()` | — |
| P8 | JWT authentication on all routes | **FULL** | Local HS256 JWT via `PyJWT` + `passlib[bcrypt]` | Spec says Supabase — migrated to local |
| P9 | Platform admin (Logikality admin) | **FULL** | `is_platform_admin`, `require_platform_admin()`, seed script | — |


## B. Title Intelligence — Upload & Processing

| # | Spec Requirement | Status | Evidence | Gaps |
|---|-----------------|--------|----------|------|
| T1 | Create pack with name | **FULL** | `POST /packs` → status=uploading, tested | — |
| T2 | Upload PDF files with validation | **FULL** | Extension + magic bytes check, size limit | Frontend lacks size validation |
| T3 | Start processing (7-stage pipeline) | **FULL** | `POST /packs/{id}/process`, BackgroundTasks + Temporal | — |
| T4 | Pipeline progress polling | **FULL** | `GET /packs/{id}/pipeline`, frontend polls 3s | — |
| T5 | Stage 1: Ingest (validate files) | **FULL** | Checks file count + storage existence | — |
| T6 | Stage 2: Render (PDF → JPEG) | **FULL** | PyMuPDF, 150 DPI + 72 DPI thumbs | — |
| T7 | Stage 3: OCR | **PARTIAL** | Tesseract (not Claude Vision per spec) | Spec says "Claude Vision" — migrated to Tesseract |
| T8 | Stage 4: Index (text chunking) | **FULL** | Hierarchical chunker, tsvector GIN index | — |
| T9 | Stage 5: Ingestion Agent | **FULL** | Tool-calling loop, sections + extractions | — |
| T10 | Stage 6: Risk Agent | **FULL** | Tool-calling loop, creates flags | Re-run deletes human reviews |
| T11 | Stage 7: Complete (readiness + summary) | **FULL** | Calculates score, AI summary | — |
| T12 | Pipeline < 30 min for 300 pages | **UNKNOWN** | Not benchmarked in tests | No perf tests |
| T13 | Retry with exponential backoff | **FULL** | 3x for non-AI, 5x for AI stages | — |
| T14 | Failure sets pack.status=failed | **FULL** | Tested in temporal_activities tests | — |
| T15 | Pack delete | **FULL** | `DELETE /packs/{id}`, require_admin | — |
| T16 | Concurrent packs (5 per org) | **MISSING** | No concurrency limit enforced | — |

## C. Title Intelligence — Data & Review

| # | Spec Requirement | Status | Evidence | Gaps |
|---|-----------------|--------|----------|------|
| D1 | Extractions grouped by 6 types | **FULL** | party, property_info, requirement, exception, endorsement, legal_description | — |
| D2 | Evidence refs (page + snippet) | **FULL** | JSONB array on extractions + flags | — |
| D3 | Flag types (5 categories) | **FULL** | missing_endorsement, unacceptable_exception, unresolved_lien, cross_section_mismatch, requirement_missing_proof | — |
| D4 | Flag severity levels | **FULL** | critical, high, medium, low | — |
| D5 | Flag review (approve/reject/escalate) | **FULL** | `POST .../review`, updates flag status, creates Review record | — |
| D6 | AI recommendation on flags | **FULL** | `GET .../recommend` (spec) / actual `POST` | Spec says GET, impl is POST |
| D7 | Review persisted with reviewer + timestamp | **FULL** | Review model with reviewer_id, created_at | — |
| D8 | Readiness score 0-100 | **FULL** | Weighted 5-category + penalty algorithm | — |
| D9 | Readiness categories (5) | **FULL** | requirements, endorsements, liens, exceptions, consistency | — |
| D10 | AI-generated plain-language summary | **FULL** | `generate_summary()` in stage_complete | — |
| D11 | Readiness recalculates on demand | **FULL** | Computed live every GET request | Not cached |
| D12 | Closing checklist | **FULL** | Built from extractions + flags in readiness_service | — |
| D13 | Estimated days to clear | **FULL** | Severity-weighted formula | — |

## D. Title Intelligence — Chat, Reports, Search

| # | Spec Requirement | Status | Evidence | Gaps |
|---|-----------------|--------|----------|------|
| C1 | Chat with page citations | **FULL** | `POST /chat`, `POST /chat/stream` (SSE) | Stream citations lack text_snippet |
| C2 | Chat history preserved per pack | **FULL** | `GET /chat`, ti_chat_messages table | — |
| C3 | Report generation (attorney/lender/buyer) | **FULL** | `POST /reports`, 4 audiences | Added "underwriter" beyond spec |
| C4 | Report formats (PDF/JSON) | **FULL** | PDF via fpdf2, JSON, Markdown, Text | Spec says PDF+JSON; impl adds Markdown+Text |
| C5 | Report download | **FULL** | `POST /reports/download`, `GET /reports?uri=` | — |
| C6 | Full-text search | **BACKEND-ONLY** | `GET /packs/{id}/search?q=` works | No frontend UI |
| C7 | Audit trail logging | **PARTIAL** | Reviews create `AuditEvent` rows (tested) | No frontend display, no listing endpoint |

## E. Frontend Requirements

| # | Spec Requirement | Status | Evidence | Gaps |
|---|-----------------|--------|----------|------|
| F1 | Pack list with status badges | **FULL** | Card-based layout, PackStatusBadge | — |
| F2 | Upload dropzone (PDF) | **FULL** | react-dropzone, extension filter | No size validation |
| F3 | Pipeline progress real-time | **FULL** | Circular track, 3s polling, auto-redirect on complete | — |
| F4 | Extraction table with evidence | **FULL** | Grouped accordion, filter pills, pagination | — |
| F5 | Flag cards with review | **FULL** | Expandable rows, quick actions, detail dialog, AI recommendation | — |
| F6 | Readiness dashboard | **FULL** | Donut, categories, AI summary, checklist | — |
| F7 | Chat panel with citations | **FULL** | Slide panel, SSE streaming, citation parsing | — |
| F8 | Report generation UI | **FULL** | Export panel in results page | Not a dedicated page |
| F9 | Search UI | **MISSING** | No search component or page | — |
| F10 | Audit trail UI | **MISSING** | No audit display component | — |
| F11 | ROI Calculator | **MISSING** | Not referenced anywhere | Spec §14 |
| F12 | Document viewer | **FULL** | Full page viewer with thumbnails, OCR overlay | — |

## F. Testing Requirements

| # | Spec Requirement | Status | Evidence | Gaps |
|---|-----------------|--------|----------|------|
| X1 | All tests pass | **FULL** | 59 tests pass | — |
| X2 | No test touches production DB | **FULL** | SQLite override in conftest | — |
| X3 | Every TI endpoint has ≥1 test | **PARTIAL** | 35 TI tests | Missing: POST /chat, POST /chat/stream, POST /reports, POST /reports/download, GET /reports |
| X4 | Cross-tenant isolation test | **MISSING** | No test attempts cross-org access | — |
| X5 | S3Storage tests | **MISSING** | Only LocalStorage tested | — |

## G. Extra Features (Not in Spec)

| # | Feature | Evidence |
|---|---------|----------|
| E1 | SSE streaming chat (`/chat/stream`) | Full implementation + frontend support |
| E2 | Temporal pipeline backend | Toggle via `PIPELINE_BACKEND=temporal` |
| E3 | S3 storage provider | `S3Storage` class with aiobotocore |
| E4 | Multi-AI provider (LiteLLM) | anthropic/bedrock/openai/azure |
| E5 | Hierarchical text chunker | Paragraph→sentence→character with overlap |
| E6 | Tool-calling AI agents | Iterative tool loop in all agents |
| E7 | Platform admin panel | Full CRUD UI for accounts, apps, subscriptions |
| E8 | Password reset (admin) | `PATCH .../users/{id}/password` |
| E9 | Pack file download | `GET /packs/{id}/files/{fileId}/download` |
| E10 | Underwriter audience for reports | 4th audience beyond the 3 in spec |

## Summary Counts

| Category | FULL | PARTIAL | BACKEND-ONLY | MISSING |
|----------|:----:|:-------:|:------------:|:-------:|
| Platform (P1-P10) | 8 | 2 | 0 | 0 |
| Upload & Pipeline (T1-T16) | 12 | 2 | 0 | 2 |
| Data & Review (D1-D13) | 13 | 0 | 0 | 0 |
| Chat/Reports/Search (C1-C7) | 5 | 1 | 1 | 0 |
| Frontend (F1-F12) | 8 | 0 | 0 | 3+1 partial |
| Testing (X1-X5) | 2 | 1 | 0 | 2 |

**Overall**: 48 of 63 requirements FULL, 6 PARTIAL, 1 BACKEND-ONLY, 7 MISSING, plus 10 EXTRA features beyond spec.

## Key Spec Deviations

1. **Auth**: Spec says Supabase JWT → Actually local bcrypt + self-issued HS256 JWT
2. **OCR**: Spec says Claude Vision → Actually Tesseract via pytesseract
3. **AI model**: Spec says Claude Haiku only → Actually multi-provider via LiteLLM
4. **Flag recommend**: Spec says `GET` → Actually `POST`
5. **Pipeline**: Spec says BackgroundTasks only → Also supports Temporal
6. **Storage**: Spec says local only → Also supports S3
7. **Frontend routes**: Spec shows dedicated pages for extractions/flags/chat/reports → Actually consolidated into results page tabs + slide panel

---

# Phase 2 — Current Architecture Assessment

## Overall Architecture Grade: B- (Solid foundation, meaningful gaps)

The codebase is well-structured for an MVP — clean plugin system, good separation of platform vs. micro app concerns, and thorough AI agent abstractions. However, there are genuine security vulnerabilities, consistency gaps, and technical debt that must be addressed before this becomes the "golden template."

---

## 1. Structural Strengths

| Strength | Evidence |
|----------|---------|
| **Clean plugin system** | `registry.py` auto-discovers micro apps; adding a new app requires only a new directory |
| **Tenant isolation at multiple layers** | Middleware + dependency + DB column + RLS (on TI tables) |
| **AI agent abstraction** | `BaseAIService` provides consistent retry, timeout, structured output, and tool-calling patterns |
| **Dual pipeline backends** | `PIPELINE_BACKEND` toggle between BackgroundTasks and Temporal without code changes |
| **Multi-provider AI** | LiteLLM abstraction supports Anthropic/Bedrock/OpenAI/Azure with zero agent changes |
| **Idempotent pipeline stages** | Delete-then-insert pattern enables safe retries |
| **Comprehensive type system** | Both backend (Pydantic) and frontend (TypeScript) have full domain types |
| **Good test infrastructure** | SQLite test DB, dependency overrides, seed data, 59 passing tests |

---

## 2. Security Vulnerabilities

| # | Finding | Severity | Location |
|---|---------|----------|----------|
| S1 | **Insecure default JWT secret** — `"change-me-in-production"` with no startup validation | CRITICAL | `config.py:10` |
| S2 | **No rate limiting on login** — unlimited brute-force attempts allowed | CRITICAL | `routes/auth.py` |
| S3 | **Path traversal in LocalStorage** — filenames not validated against base path; `../../` can escape storage root | MEDIUM | `services/storage.py:_resolve()` |
| S4 | **X-Org-Id not bound to JWT** — valid token + arbitrary org UUID reaches middleware without crypto verification; defense relies entirely on `get_current_member` | MEDIUM | `middleware/tenant.py` |
| S5 | **No token revocation** — no logout endpoint, no blacklist; stolen tokens valid for 24 hours | MEDIUM | `services/auth_service.py` |
| S6 | **Raw exception text in SSE stream** — internal errors (DB, AI provider) leak to client | LOW | `chat_service.py:125` |
| S7 | **`error_message` may leak internals** — raw Python exceptions stored in `pack.error_message` and served to frontend | MEDIUM | `orchestrator.py` |

---

## 3. Backend Architecture Issues

### 3a. Layering Violations

| # | Issue | Severity | Location |
|---|-------|----------|----------|
| L1 | **No service layer for Pages** — 3 raw DB queries directly in route handlers | Medium | `routes/pages.py:24,41,64` |
| L2 | **AI agent instantiated in route** — ReviewAssistant created directly in flags route | Medium | `routes/flags.py:106` |
| L3 | **Raw DB query in route** — extraction query bypasses `extraction_service` | Medium | `routes/flags.py:94` |
| L4 | **File validation in route** — PDF magic bytes + size check belongs in service layer | Low | `routes/packs.py:99-117` |

### 3b. Dependency Injection Anti-Patterns

| # | Issue | Severity | Location |
|---|-------|----------|----------|
| D1 | **`get_session_factory()` called imperatively** — bypasses DI, untestable via standard overrides | Medium | `routes/packs.py:144` |
| D2 | **`get_storage()` called imperatively in service** — service resolves own dependency | Medium | `chat_service.py:50,106` |
| D3 | **`get_settings()` called imperatively in route** — bypasses `Depends()` | Low | `routes/packs.py:99` |
| D4 | **Three independent engine initialization paths** — potential resource leak | Medium | `deps.py:16-41` |

### 3c. Missing Tenant Scoping (15 queries)

| # | File | Lines | Query Target |
|---|------|-------|-------------|
| Q1 | `pipeline/stages.py` | 30,52,57,123,186,217,249,259,260 | PackFile, Page, Pack, Extraction, Flag |
| Q2 | `pipeline/orchestrator.py` | 117,129,150,178,196 | Pack |
| Q3 | `pipeline/temporal_activities.py` | 65,138,171 | Pack |
| Q4 | `services/pack_service.py` | 72-76 | PackFile (function signature missing `org_id`) |

All 15 queries filter by `pack_id` (UUID) only, omitting `org_id`. While `pack_id` is a UUID (practically unique), this violates defense-in-depth. The `org_id` is available in scope at every call site.

### 3d. Transaction Ownership Ambiguity

Services (`pack_service`, `flag_service`) commit internally, but calling routes also commit — dual-commit pattern in 5+ places. No consistent rule for who owns the transaction boundary.

### 3e. Code Duplication

| # | What's Duplicated | Locations | Impact |
|---|-------------------|-----------|--------|
| CD1 | Tool conversion function (`_convert_tools`) | `base_service.py:269-292` + `chat_agent.py:267-282` | Diverging implementations |
| CD2 | Citation regex extraction | 3 separate implementations across `chat_agent.py` + `chat_service.py` | Bug fixes must be applied 3x |
| CD3 | `evidence_refs` JSON schema | 5 tool definitions across agents | Schema changes require 5 edits |
| CD4 | `pack_id`-only DB queries in stages | 9 instances across `stages.py` | No shared helper |

---

## 4. Frontend Architecture Issues

### 4a. Type Safety Gaps

| # | Issue | Severity | Location |
|---|-------|----------|----------|
| T1 | **`Pack` defined 3 times** — canonical in `ti-types.ts`, local copies in `use-pack.ts` and `use-packs.ts` with different fields | High | 3 files |
| T2 | **`ChatMessage` defined 4 times** — canonical + 3 local copies with `role: string` instead of union | High | 4 files |
| T3 | **`ChecklistItem` type incomplete** — 4 unsafe `as` casts to access `flag_id`, `ai_explanation`, `detail`, `evidence_page` | High | `closing-checklist.tsx:110-113` |
| T4 | **`StageStatus` loosely typed** — `status: string` instead of union in hook + component | Medium | `use-pipeline-status.ts`, `pipeline-progress.tsx` |

### 4b. Data Fetching Issues

| # | Issue | Severity | Location |
|---|-------|----------|----------|
| F1 | **`fetchMe()` called twice per page** — `useAuth` in both layout and sidebar, no shared cache | Medium | `use-auth.ts` |
| F2 | **`usePack()` called twice on pack detail** — layout + page both fetch independently | Medium | `layout.tsx` + `page.tsx` |
| F3 | **All fetch errors silently swallowed** — `catch { setData([]) }` with no error state | Medium | All hooks |
| F4 | **No `AbortController`** — polling hook can setState on unmounted component | Low | `use-pipeline-status.ts` |
| F5 | **Boilerplate fetch hook pattern** — identical `useState` + `useCallback` + `useEffect` repeated 6x | Low | All hooks |

### 4c. Component Architecture Issues

| # | Issue | Severity | Location |
|---|-------|----------|----------|
| C1 | **`ClosingChecklist` makes direct API calls** — bypasses parent's review coordination | High | `closing-checklist.tsx:58-77` |
| C2 | **`ReadinessGauge` is dead code** — orphaned component with conflicting thresholds (80/50 vs 90/60) | Medium | `readiness-gauge.tsx` |
| C3 | **`ResultsPage` is a god-page** — 7 state vars, 4 fetch callbacks, tab bar, review logic | Medium | `results/page.tsx` |
| C4 | **`AuthImage` trapped in page file** — reusable component defined inline in `DocumentsPage` | Low | `documents/page.tsx:19-55` |

### 4d. Styling Inconsistencies

| # | Issue | Severity | Location |
|---|-------|----------|----------|
| Y1 | **Score threshold logic in 5 places** — `readiness-gauge` uses 80/50, everything else uses 90/60 | Medium | 5 files |
| Y2 | **`border-l-3` is invalid Tailwind** — sidebar active indicator not rendered | Medium | `sidebar.tsx:120,142` |
| Y3 | **Hardcoded hex colors in `globals.css`** — `#d97706`, `#ea580c` instead of CSS custom properties | Low | `globals.css:77,149,158` |
| Y4 | **`btn-cta`/`btn-secondary` vs `Button` component** — no rule for when to use which | Low | Throughout |

---

## 5. Observability Gaps

| # | Gap | Severity |
|---|-----|----------|
| O1 | **No structured (JSON) logging** — plain text format, unusable by log aggregators | High |
| O2 | **No request correlation IDs** — concurrent requests interleave without tracing | High |
| O3 | **No metrics endpoint** — no Prometheus, StatsD, or OpenTelemetry | High |
| O4 | **Shallow health check** — returns `healthy` without checking DB/storage/AI connectivity | Medium |
| O5 | **No alerting on pipeline failure** — failures only discoverable by polling | Medium |

---

## 6. Data Integrity Concerns

| # | Issue | Severity | Location |
|---|-------|----------|----------|
| I1 | **GIN index dropped in migration** — full-text search runs as sequential scan | Medium | Migration `f40fd107f581` |
| I2 | **RLS disabled on platform tables** — `organizations`, `users`, `subscriptions` lack DB-level protection | Medium | Migration `001` |
| I3 | **Stale `processing` packs** — no watchdog to recover packs stuck in `processing` after crashes | Medium | `orchestrator.py` |
| I4 | **Re-running risk agent deletes human reviews** — `stage_risk_agent` deletes all flags before re-creating | Medium | `stages.py` |
| I5 | **No `ondelete` on platform FKs** — can't delete orgs without manual cleanup | Low | Migration `001` |

---

## 7. Configuration Issues

| # | Issue | Severity | Location |
|---|-------|----------|----------|
| K1 | **`STORAGE_PROVIDER` / `PIPELINE_BACKEND` not enum-constrained** — invalid values silently fall through | Medium | `config.py` |
| K2 | **`datetime.utcnow()` deprecated** — used in `report_service.py`, rest of codebase uses `datetime.now(timezone.utc)` | Low | `report_service.py:67,77,103` |
| K3 | **7 hardcoded tuning constants** — OCR batch size, AI timeout, chat history window, etc. should be in Settings | Low | Various |

---

## 8. Prioritized Issue Summary

### Must Fix (before golden template)

| Priority | Count | Issues |
|----------|:-----:|--------|
| **CRITICAL** | 2 | S1 (JWT secret), S2 (login rate limiting) |
| **HIGH** | 7 | Q1-Q4 (15 unscoped queries), T1-T3 (type safety), C1 (checklist API leak), O1-O3 (observability) |

### Should Fix (quality bar)

| Priority | Count | Issues |
|----------|:-----:|--------|
| **MEDIUM** | 20 | S3-S5,S7 (security), L1-L2, D1-D2,D4 (architecture), CD1-CD2 (duplication), F1-F3 (frontend fetch), Y1-Y2 (styling), I1-I4 (data), K1 |

### Nice to Fix (polish)

| Priority | Count | Issues |
|----------|:-----:|--------|
| **LOW** | 14 | Remaining items across all categories |

---

---

# Phase 3 — Target Golden Template Mapping

## Golden Template Definition

The "golden template" is the reference architecture that any new micro app can follow by copying patterns from Title Intelligence. It must satisfy:

1. **Zero platform edits** — Adding a new micro app requires NO changes to platform code (sidebar, middleware, models/__init__, etc.)
2. **Convention over configuration** — File structure, naming, and patterns are self-documenting
3. **Shared infrastructure** — Storage, AI, pipeline, audit, and auth are platform-provided
4. **Clean boundaries** — Micro app code never reaches into another micro app or into platform internals

---

## A. Backend Golden Template

### Target Directory Structure (per micro app)

```
backend/app/micro_apps/{app_name}/
├── __init__.py          # __getattr__ lazy import pattern
├── app.py               # class MyApp(MicroAppBase) — slug, name, get_router(), get_models()
├── models/
│   ├── __init__.py      # Exports all models for Alembic discovery
│   └── *.py             # SQLAlchemy models (table prefix: {abbrev}_)
├── schemas/
│   └── *.py             # Pydantic request/response schemas
├── services/
│   └── *.py             # Business logic (receives db, org_id, storage as params)
├── routes/
│   ├── __init__.py      # Assembles router from sub-routers
│   └── *.py             # FastAPI route handlers (thin — delegate to services)
├── ai/
│   └── *.py             # AI agents (subclass BaseAIService)
├── pipeline/            # Optional — only if app has background processing
│   ├── stages.py        # Stage functions
│   └── orchestrator.py  # Stage registry + execution
└── tests/               # Or in backend/tests/{app_name}/
    └── *.py
```

### Current State → Target State Map

| # | Aspect | Current State | Target State | Gap | Priority |
|---|--------|--------------|--------------|-----|----------|
| B1 | **MicroAppBase contract** | 3 methods: `slug`, `name`, `get_router()` | Add `get_models() → list[type]` for Alembic discovery; optional `on_startup()`, `on_shutdown()` | No model registration protocol; `app/models/__init__.py` has TI-specific imports | High |
| B2 | **Model discovery** | `app/models/__init__.py` calls `ensure_ti_models()` — hardcoded TI import | `main.py` calls `app.get_models()` during startup; each app registers its own models | Platform code must be edited to add a micro app | High |
| B3 | **StorageProvider location** | Lives in `title_intelligence/services/storage.py` | Move to `app/services/storage.py`; add `get_storage` to `app/core/deps.py` | Every new app must import from TI or duplicate | High |
| B4 | **Pipeline base** | No shared pipeline framework; orchestrator is TI-only | Extract `BasePipelineOrchestrator` to `app/services/pipeline.py` with stage registry pattern | New apps must copy+adapt 200 lines of orchestrator code | Medium |
| B5 | **Route → Service layering** | 4 layering violations (pages, flags, packs) | Routes are thin dispatchers; all DB queries in services; services receive dependencies as params | Routes contain raw DB queries and AI agent instantiation | Medium |
| B6 | **DI consistency** | 3 anti-patterns: imperative `get_settings()`, `get_session_factory()`, `get_storage()` | All dependencies via `Depends()` in route signatures | Some deps bypass DI, untestable | Medium |
| B7 | **Tenant scoping** | 15 queries missing `org_id` filter in pipeline/stages | All queries include `org_id` in WHERE clause; shared `get_pack(db, pack_id, org_id)` helper | Defense-in-depth violation | High |
| B8 | **Transaction ownership** | Dual-commit in 5+ places (service + route both commit) | Convention: services `flush()`, routes `commit()` — or services own the full transaction | Ambiguous ownership | Medium |
| B9 | **Error handling** | 3 silent exception swallows; raw exceptions in SSE/error_message | Sanitized user-facing messages; all exceptions logged with context | Internal details leak to client | Medium |
| B10 | **Audit event types** | Free-form strings (`"ti_pack"`, `"pack_created"`) | Enum or constant registry per app; `target_type` uses `{prefix}_{entity}` convention documented | No enforcement | Low |
| B11 | **Config validation** | Default JWT secret not validated; `STORAGE_PROVIDER`/`PIPELINE_BACKEND` accept any string | Startup validators reject insecure defaults; `Literal` types for enum settings | Silent misconfiguration | High |
| B12 | **Double-mount bug** | `discover_micro_apps()` called in both `create_app()` and `lifespan` | Call only in `lifespan` (or only in `create_app()`) — not both | Routes mounted twice | Low |
| B13 | **Temporal task queue** | Hardcoded `"title-intelligence"` in config | `TEMPORAL_TASK_QUEUE` constructed from app slug: `f"{app.slug}-pipeline"` | Prevents multi-app Temporal | Low |
| B14 | **Code duplication** | `_convert_tools` duplicated; citation regex 3x; `evidence_refs` schema 5x | Shared utilities: `extract_citations()` in `app/ai/utils.py`; `EVIDENCE_REFS_SCHEMA` constant | Bug fixes must be applied N times | Medium |

### Platform Infrastructure Additions Needed

| # | Component | What to Create | Location |
|---|-----------|---------------|----------|
| P1 | `get_models()` on `MicroAppBase` | Optional method returning `list[type]`; `main.py` iterates all apps and imports their models for Alembic | `app/micro_apps/base.py` |
| P2 | Storage at platform level | Move `StorageProvider`, `LocalStorage`, `S3Storage`, `get_storage()` | `app/services/storage.py` + `app/core/deps.py` |
| P3 | `BasePipelineOrchestrator` | Abstract: stage registry, retry logic, timeout, status tracking, audit events | `app/services/pipeline.py` |
| P4 | `sanitize_error()` utility | Strips internal details from exception messages for user-facing fields | `app/core/utils.py` |
| P5 | AI shared utilities | `extract_citations(text)`, `EVIDENCE_REFS_SCHEMA` constant | `app/ai/utils.py` |

---

## B. Frontend Golden Template

### Target Directory Structure (per micro app)

```
frontend/src/
├── app/(platform)/apps/{app-slug}/
│   ├── layout.tsx              # App-level layout (optional)
│   ├── page.tsx                # App index/list page
│   └── {entities}/
│       └── [entityId]/
│           ├── layout.tsx      # Entity detail layout (breadcrumbs)
│           ├── page.tsx        # Entity overview
│           ├── results/page.tsx # Domain-specific output
│           └── documents/page.tsx # If applicable
├── components/{app-slug}/
│   ├── *.tsx                   # Domain-specific components
│   └── (no generic primitives here)
├── hooks/
│   └── use-{app}-*.ts          # App-specific data hooks
└── lib/
    ├── {app}-types.ts          # Domain TypeScript interfaces
    └── {app}-constants.ts      # Domain labels, colors, enums
```

### Current State → Target State Map

| # | Aspect | Current State | Target State | Gap | Priority |
|---|--------|--------------|--------------|-----|----------|
| F1 | **Sidebar navigation** | Hardcoded `tiNavItems` array + `isInsideTI` path check | Dynamic nav registry: each app exports `{ slug, navItems[] }`; sidebar reads current app from URL and looks up items | Adding an app requires editing `sidebar.tsx` | High |
| F2 | **App card icon** | Hardcoded `if (slug === "title-intelligence")` → `FileSearch` | Icon passed as prop or resolved from a registry/API field | Adding an app requires editing `app-card.tsx` | Medium |
| F3 | **Onboarding auto-subscribe** | Hardcodes `slug === "title-intelligence"` | Remove auto-subscribe or make default app configurable | TI coupling in platform code | Low |
| F4 | **Breadcrumb labels** | Hardcoded segment labels for TI paths (`packs`, `results`, etc.) | Generic segment-to-label mapping from route metadata or per-app config | Adding an app requires editing breadcrumb map | Medium |
| F5 | **Pagination component** | Filed under `components/title-intelligence/` | Move to `components/ui/pagination.tsx` — it's a pure primitive | Misplaced generic component | Medium |
| F6 | **Pipeline progress** | 7 hardcoded TI stage names in `STAGES` constant | Accept `stages` and `stageLabels` as props; TI passes its constants | Component is TI-locked | Medium |
| F7 | **Type definitions** | `Pack` defined 3x, `ChatMessage` 4x, `StageStatus` 3x | Single canonical definition in `ti-types.ts`; all hooks/components import from there | Type drift across files | High |
| F8 | **`ChecklistItem` type** | Missing `flag_id`, `ai_explanation`, `detail`, `evidence_page` fields | Add missing fields to canonical `ChecklistItem` in `ti-types.ts` | 4 unsafe type assertions | High |
| F9 | **Data fetching pattern** | Identical boilerplate in 6 hooks (`useState` + `useCallback` + `useEffect`) | Generic `useOrgFetch<T>(path, initial)` hook; app hooks wrap it with typed paths | Copy-paste boilerplate | Medium |
| F10 | **Error handling** | All fetch errors silently swallowed (`catch { setData([]) }`) | Hooks return `{ data, loading, error }`; pages render error states | Users can't distinguish "empty" from "failed" | Medium |
| F11 | **Duplicate fetch calls** | `useAuth` called 2x per page; `usePack` called 2x on pack detail | Auth in React Context (single provider); pack data via context or prop drilling | Redundant API calls | Medium |
| F12 | **Dead code** | `readiness-gauge.tsx` orphaned with conflicting thresholds (80/50 vs 90/60) | Delete `readiness-gauge.tsx` | Confusion risk | Low |
| F13 | **`ClosingChecklist` API calls** | Component calls `orgFetch` directly, bypassing parent coordination | Accept `onAction(flagId, decision)` callback prop; parent handles mutations | Violates single responsibility | High |
| F14 | **`AuthImage` location** | Defined inline in `documents/page.tsx` | Extract to `components/ui/auth-image.tsx` | Not reusable | Low |
| F15 | **Score threshold logic** | Duplicated in 5 places with inconsistent values | Single `getReadinessStatus(score)` in `ti-constants.ts` | Bug if thresholds change | Medium |
| F16 | **Loading spinner** | Identical markup repeated 7 times | `components/ui/loading-spinner.tsx` | Duplication | Low |
| F17 | **Styling: `border-l-3`** | Invalid Tailwind class; sidebar active indicator doesn't render | Change to `border-l-2` or add custom width in tailwind config | Visual bug | Medium |
| F18 | **Styling: hardcoded hex** | `#d97706`, `#ea580c` in `globals.css` instead of CSS vars | Replace with `var(--brand-amber)` etc. | Theme inconsistency | Low |

### Platform Infrastructure Additions Needed

| # | Component | What to Create | Location |
|---|-----------|---------------|----------|
| PF1 | **App nav registry** | `appNavRegistry: Record<string, NavItem[]>` populated per-app; sidebar reads it dynamically | `lib/app-registry.ts` + sidebar refactor |
| PF2 | **`useOrgFetch<T>` generic hook** | Encapsulates `useState(initial) + useCallback(orgFetch) + useEffect(fetch)` with `{ data, loading, error }` return | `hooks/use-org-fetch.ts` |
| PF3 | **Auth Context** | `AuthProvider` wrapping `(platform)/layout.tsx`; single `fetchMe()` call shared via context | `components/auth-provider.tsx` |
| PF4 | **`LoadingSpinner` component** | Reusable spinner with size prop | `components/ui/loading-spinner.tsx` |
| PF5 | **Move `Pagination`** | Relocate from `title-intelligence/` to `ui/` | `components/ui/pagination.tsx` |

---

## C. Observability & Security Golden Template

| # | Aspect | Current State | Target State | Priority |
|---|--------|--------------|--------------|----------|
| O1 | **Structured logging** | Plain text `basicConfig` | JSON logging via `structlog` or `python-json-logger`; `org_id`, `pack_id`, `request_id` in every log line | High |
| O2 | **Request correlation** | None | `X-Request-Id` middleware; ID propagated through all log entries | High |
| O3 | **Metrics** | None | `/metrics` endpoint (Prometheus client); request latency, pipeline duration, AI call counts | High |
| O4 | **Health check depth** | Shallow ping | Check DB connectivity, storage accessibility, AI provider reachability | Medium |
| O5 | **JWT secret validation** | Insecure default accepted | Startup validator rejects `"change-me-in-production"` | Critical |
| O6 | **Login rate limiting** | None | Rate limit middleware on `/api/v1/auth/login` (e.g., `slowapi`) | Critical |
| O7 | **Path traversal fix** | Filenames not validated | `_resolve()` validates `resolved.is_relative_to(base_path)` | Medium |
| O8 | **Token revocation** | No logout | Add `/api/v1/auth/logout` + short-lived tokens (1h) + refresh token pattern; or token blacklist | Medium |

---

## D. Testing Golden Template

| # | Aspect | Current State | Target State | Priority |
|---|--------|--------------|--------------|----------|
| TE1 | **Cross-tenant test** | None | Test that User-A with Org-A token + Org-B header gets 403 | High |
| TE2 | **Chat/Report endpoint tests** | Not tested | At minimum: `POST /chat` returns 201, `POST /reports` returns 200 | Medium |
| TE3 | **S3Storage tests** | Not tested | Mock `aiobotocore` session; test put/get/exists/delete | Medium |
| TE4 | **Pipeline stage unit tests** | Only endpoint-level | Test individual stage functions with mocked AI/storage | Medium |
| TE5 | **Frontend test infrastructure** | None visible | Vitest + React Testing Library setup; smoke tests for key pages | Low |

---

## E. Golden Template Compliance Scorecard

### Scoring: How close is TI to the golden template today?

| Category | Weight | Current Score | Target | Gap |
|----------|:------:|:------------:|:------:|:---:|
| **Plugin architecture** (B1-B3, B12-B13) | 15% | 5/10 | 10/10 | Model registration, storage location, double-mount |
| **Backend layering** (B5-B10) | 15% | 6/10 | 10/10 | Route violations, DI anti-patterns, transaction ambiguity |
| **Tenant scoping** (B7) | 10% | 4/10 | 10/10 | 15 unscoped queries |
| **Security** (O5-O8) | 15% | 3/10 | 10/10 | JWT secret, no rate limit, path traversal, no logout |
| **Frontend extensibility** (F1-F6) | 10% | 3/10 | 10/10 | Hardcoded sidebar, icons, breadcrumbs |
| **Frontend code quality** (F7-F16) | 10% | 5/10 | 10/10 | Type drift, error swallowing, dead code |
| **Observability** (O1-O4) | 10% | 1/10 | 10/10 | No structured logs, metrics, or tracing |
| **Testing** (TE1-TE5) | 10% | 5/10 | 10/10 | Missing cross-tenant, chat, reports, S3 tests |
| **Config & data integrity** (B11, I1-I5) | 5% | 5/10 | 10/10 | Enum validation, GIN index, stale packs |

**Weighted Score: 4.1 / 10.0**

---

## F. Refactor Sequence (Recommended Order)

The following sequence minimizes risk and maximizes golden-template readiness per step:

| Phase | Items | Risk | Impact | Effort |
|:-----:|-------|:----:|:------:|:------:|
| **R1** | O5, O6 — JWT secret validation + login rate limiting | Low | Critical security | Small |
| **R2** | B7 — Add `org_id` to all 15 unscoped queries | Low | High (tenant safety) | Small |
| **R3** | B3 — Move StorageProvider to platform level | Low | High (unblocks future apps) | Medium |
| **R4** | F7, F8 — Consolidate TypeScript types; fix `ChecklistItem` | Low | High (type safety) | Small |
| **R5** | F1 — Dynamic sidebar nav registry | Low | High (unblocks future apps) | Medium |
| **R6** | B1, B2 — `get_models()` on MicroAppBase; remove TI imports from platform | Low | High (clean plugin boundary) | Medium |
| **R7** | O1, O2 — Structured JSON logging + request correlation IDs | Low | High (production readiness) | Medium |
| **R8** | B5, B6 — Fix layering violations + DI anti-patterns | Low | Medium (code quality) | Medium |
| **R9** | F9, F10, F11 — Generic `useOrgFetch`, error states, auth context | Low | Medium (frontend quality) | Medium |
| **R10** | B4, F6 — Extract BasePipelineOrchestrator; genericize pipeline-progress component | Medium | Medium (future app readiness) | Large |
| **R11** | F13, F12, F15 — Fix ClosingChecklist API leak; delete dead code; centralize thresholds | Low | Medium (correctness) | Small |
| **R12** | TE1-TE4 — Add cross-tenant, chat, report, S3 tests | Low | Medium (confidence) | Medium |
| **R13** | O3, O4 — Metrics endpoint + deep health check | Low | Medium (production ops) | Medium |
| **R14** | O7, O8 — Path traversal fix + token revocation | Low | Medium (security hardening) | Medium |
| **R15** | B8, B9, B10, B11, B14, F2-F5, F14, F16-F18 — Remaining polish | Low | Low | Medium |

---

---

# Phase 4 — Claude Code Operating Artifacts

## Overview

Phase 4 generates production-quality Claude Code configuration files tailored to this repository. These artifacts encode the architecture rules, tenant isolation requirements, and quality expectations from Phases 0–3 into machine-enforceable guidance.

## Artifact Inventory

| # | Artifact | File Path | Purpose |
|---|----------|-----------|---------|
| 1 | **CLAUDE.md** | `CLAUDE.md` (root) | Production operating guide — architecture rules, tenant isolation, auth boundaries, testing expectations, refactor discipline |
| 2 | **microapp-researcher** | `.claude/agents/microapp-researcher.md` | Read-only architecture exploration agent; traces request flows, maps dependencies, checks tenant scoping |
| 3 | **microapp-implementer** | `.claude/agents/microapp-implementer.md` | Minimal-change code writer; enforces layer discipline, DI, tenant safety, runs tests after changes |
| 4 | **microapp-tester** | `.claude/agents/microapp-tester.md` | Targeted test runner; identifies affected tests, runs them, reports concise pass/fail with coverage gaps |
| 5 | **microapp-reviewer** | `.claude/agents/microapp-reviewer.md` | Code reviewer; classifies findings as CRITICAL/WARNING/SUGGESTION; checks correctness, tenant safety, maintainability, performance |
| 6 | **tenant-safety-check** | `.claude/skills/tenant-safety-check/SKILL.md` | Full tenant isolation audit — middleware resolution, query scoping, cache safety, async propagation |
| 7 | **trace-request-flow** | `.claude/skills/trace-request-flow/SKILL.md` | End-to-end request trace from HTTP entry through auth, service, persistence, back to tests |
| 8 | **add-endpoint** | `.claude/skills/add-endpoint/SKILL.md` | Scaffolds new endpoints following exact project conventions (route → service → schema → test) |
| 9 | **review-pr** | `.claude/skills/review-pr/SKILL.md` | PR review enforcing correctness, tenant safety, test quality, and low blast radius |

---

## Artifact 1: CLAUDE.md

**Purpose**: Replace the existing CLAUDE.md with a production-quality operating guide that encodes all architecture rules, tenant isolation requirements, and quality expectations.

**Key Sections**:

- **What This Is**: Title Intelligence Hub overview — multi-tenant SaaS platform with pluggable micro apps, TI as the golden reference template
- **Commands**: Backend (uvicorn, pytest, alembic), Frontend (npm dev/build/lint), Docker (compose up, rebuild, cache clear)
- **Architecture Rules**: Micro app plugin system (MicroAppBase contract, registry auto-discovery, `__getattr__` lazy import, table prefix convention), backend layering (routes → services → models, strict separation), DI discipline (all deps via `Depends()`), transaction ownership (services `flush()`, routes `commit()`)
- **Tenant Isolation Rules**: Every query scoped by `org_id`, every INSERT sets `org_id`, pipeline stages use `org_id` parameter, storage paths scoped by `org_id`, `get_current_member()` required on all tenant routes
- **Auth & Boundary Rules**: Local bcrypt + HS256 JWT, dependency chain (get_current_user → get_current_member → require_admin), repository boundaries (no cross-micro-app imports, no platform→micro-app imports)
- **Testing Expectations**: Every endpoint has happy-path + error test, cross-tenant isolation tests required, fixed UUIDs in conftest
- **Output & Reporting Style**: Lead with file:line, classify severity, state rule violated, show minimal diff, verify compilation
- **Refactor Expectations**: Low-blast-radius principle (minimum files, one concern per commit, read before write, run tests before and after)

---

## Artifact 2: microapp-researcher Agent

**Purpose**: Read-first architecture exploration. Used before any code changes to understand how a feature works end-to-end.

**Configuration**:
- Tools: Read, Grep, Glob, Bash, WebFetch, WebSearch (read-only — no Write/Edit)
- Model: Sonnet (fast, thorough research)
- Max turns: 30
- Effort: High

**Behavior**:
1. Starts with the route contract, traces inward to services, then models
2. Checks tenant scoping on every query found
3. Maps import dependencies and flags cross-boundary violations
4. Checks test coverage for every endpoint investigated
5. Outputs structured findings: Request Flow → Dependencies → Test Coverage → Issues Found

---

## Artifact 3: microapp-implementer Agent

**Purpose**: Minimal-change code writer. Makes the smallest safe change possible while enforcing all architecture rules.

**Configuration**:
- Tools: Read, Grep, Glob, Bash, Edit, Write (full access)
- Model: Opus (highest quality for code generation)
- Max turns: 50
- Effort: High

**Behavior**:
1. Reads target files before modifying them
2. Enforces: tenant safety (org_id in every query), layer discipline (routes → services), DI via Depends()
3. Follows backend conventions: Pydantic schemas, service function signatures, model mixins
4. Follows frontend conventions: canonical types from ti-types.ts, Tailwind theme tokens
5. Runs tests after every change (`pytest` for backend, `npm run build` for frontend)

---

## Artifact 4: microapp-tester Agent

**Purpose**: Targeted test verification. Runs after code changes to confirm correctness and identify gaps.

**Configuration**:
- Tools: Read, Grep, Glob, Bash (read-only + execution)
- Model: Sonnet
- Max turns: 20
- Effort: Medium

**Behavior**:
1. Identifies affected tests from changed files
2. Runs targeted tests first (fast feedback), then full suite
3. Reports concise pass/fail with timing
4. Checks beyond pass/fail: tenant isolation in tests, error case coverage, edge cases, regression risk

---

## Artifact 5: microapp-reviewer Agent

**Purpose**: Code review with severity classification. Focuses on correctness, tenant safety, maintainability, and performance risk.

**Configuration**:
- Tools: Read, Grep, Glob, Bash (read-only)
- Model: Opus (highest quality for review judgment)
- Max turns: 30
- Effort: High

**Review Checklist**:
1. **Correctness**: Logic matches intent, edge cases handled, HTTP status codes correct
2. **Tenant Safety** (CRITICAL — blocks merge): org_id in every query, get_current_member on routes, no cross-app imports
3. **Maintainability**: Thin routes, DI discipline, canonical types, no duplication
4. **Performance Risk**: No N+1 queries, no unbounded results, no blocking in async, AI calls have timeouts

**Output Classification**: 🔴 CRITICAL (must fix) → 🟡 WARNING (should fix) → 🔵 SUGGESTION (nice to have) → ✅ GOOD

---

## Artifact 6: tenant-safety-check Skill

**Purpose**: `/tenant-safety-check` — Comprehensive tenant isolation audit across the entire codebase.

**Checks Performed**:
1. **Tenant Resolution**: Verify TenantContextMiddleware UUID validation, get_current_member org+user+active checks, all routes use proper auth dependencies
2. **Query Scoping**: Find all SQLAlchemy queries, verify org_id in every WHERE clause for tenant-scoped tables. High-risk targets: pipeline/stages.py, pipeline/orchestrator.py, pipeline/temporal_activities.py, all services
3. **Cache Safety**: Search for lru_cache, functools.cache, module-level state. Verify any caches are keyed by org_id
4. **Async/Event Propagation**: Verify BackgroundTasks receive org_id, Temporal activities use org_id, audit events always include org_id

**Output**: Passing checks, violations found with severity, total queries checked vs properly scoped, overall risk level

---

## Artifact 7: trace-request-flow Skill

**Purpose**: `/trace-request-flow POST /packs/{packId}/flags/{flagId}/review` — Traces a single request from HTTP entry through every layer.

**Steps**:
1. Find the route handler (method, path, dependencies, response model)
2. Check auth and tenant dependencies
3. Trace service function(s) — DB queries, org_id scoping, other service/agent calls
4. Check persistence — models touched, tenant scoping, cascading effects
5. Check test coverage — what's tested, what's missing

**Output**: Structured trace with ✅/❌ markers on every query's tenant scoping

---

## Artifact 8: add-endpoint Skill

**Purpose**: `/add-endpoint GET /packs/{packId}/audit-trail` — Scaffolds a new endpoint following exact project conventions.

**Steps**:
1. Study existing patterns (reads a similar route, service, schema, and test file)
2. Create schema with `ConfigDict(from_attributes=True)`
3. Create service function with `(db, org_id, ...)` signature and org_id in all queries
4. Create thin route with `Depends(get_db)`, `Depends(get_current_member)`, `Depends(get_org_id)`
5. Register route in `routes/__init__.py`
6. Create test with happy-path + error case
7. Run `pytest` to verify

---

## Artifact 9: review-pr Skill

**Purpose**: `/review-pr 123` or `/review-pr staged` — Reviews changes against all quality standards.

**Checks**:
- Correctness (logic, edge cases, status codes)
- Tenant Safety (org_id in queries, get_current_member on routes, no cross-app imports) — BLOCKS merge if violated
- Test Quality (new endpoints tested, happy + error paths, specific assertions, regression tests)
- Blast Radius (file count, scope creep, signature changes, migration safety)

**Output**: CRITICAL/WARNING/SUGGESTION findings, test coverage assessment, blast radius rating, final verdict (APPROVE / REQUEST CHANGES / BLOCK)

---

# Phase 5 — Phased Refactor Roadmap

This roadmap takes the codebase from **4.1/10** (current golden template score) to **8.2/10** across 5 refactor waves. Each wave is self-contained — it can be merged independently and leaves the codebase in a working state.

## Dependency Graph

```
Wave 1 (Security) ─────────────────────────────────────┐
Wave 2 (Tenant Safety) ────────────────────────────────┤
Wave 3 (Plugin Boundaries) ───── Wave 4 (Code Quality) ┤
                                                        ├── Wave 5 (Observability + Polish)
```

Waves 1–3 can run in parallel. Wave 4 depends on Wave 3 (storage move). Wave 5 depends on all prior waves.

---

## Wave 1: Security Hardening (CRITICAL)

**Goal**: Eliminate the two CRITICAL vulnerabilities and the MEDIUM path traversal.
**Effort**: Small (1–2 hours) | **Risk**: Low | **Score Impact**: Security 3→5

### W1.1 — JWT Secret Startup Validation

| Attribute | Detail |
|-----------|--------|
| **Files** | `backend/app/config.py` |
| **Change** | Add `@model_validator(mode="after")` that raises `ValueError` if `JWT_SECRET == "change-me-in-production"` and `DEBUG` is not set. Constrain `STORAGE_PROVIDER: Literal["local", "s3"]` and `PIPELINE_BACKEND: Literal["background_tasks", "temporal"]`. |
| **Test** | Remove `JWT_SECRET` from `.env`, run `uvicorn` — should crash at startup with clear message. |
| **Acceptance** | App refuses to boot with default secret in non-debug mode. |

### W1.2 — Login Rate Limiting

| Attribute | Detail |
|-----------|--------|
| **Files** | `backend/requirements.txt`, `backend/app/routes/auth.py`, `backend/app/main.py` |
| **Change** | Add `slowapi` to requirements. Apply `@limiter.limit("5/minute")` to `POST /api/v1/auth/login`. Configure `slowapi` in `main.py`. |
| **Test** | Add test: 6 rapid login attempts → 6th returns 429. |
| **Acceptance** | 5 failed logins within 1 minute triggers 429 Too Many Requests. |

### W1.3 — Path Traversal Fix in LocalStorage

| Attribute | Detail |
|-----------|--------|
| **Files** | `backend/app/services/storage.py` (or current TI location) |
| **Change** | In `_resolve()`, add: `resolved = full_path.resolve()` then `if not resolved.is_relative_to(self.base_path.resolve()): raise ValueError("Path traversal detected")`. |
| **Test** | Add test: `storage.put("../../etc/passwd", b"data")` → raises `ValueError`. |
| **Acceptance** | Any `../` path that escapes `base_path` raises an error. |

---

## Wave 2: Tenant Safety (HIGH)

**Goal**: Add `org_id` to all 15 unscoped queries. Zero tenant isolation violations.
**Effort**: Small (1–2 hours) | **Risk**: Low | **Score Impact**: Tenant Scoping 4→10

### W2.1 — Pipeline Stages Tenant Scoping

| Attribute | Detail |
|-----------|--------|
| **Files** | `backend/app/micro_apps/title_intelligence/pipeline/stages.py` |
| **Change** | Add `org_id` to every query's WHERE clause (9 instances at lines 30, 52, 57, 123, 186, 217, 249, 259, 260). All stage functions already receive `org_id` as a parameter. |
| **Acceptance** | Every query in `stages.py` includes `org_id` filter. |

### W2.2 — Orchestrator Tenant Scoping

| Attribute | Detail |
|-----------|--------|
| **Files** | `backend/app/micro_apps/title_intelligence/pipeline/orchestrator.py` |
| **Change** | Add `Pack.org_id == org_id` to all 5 Pack queries (lines 117, 129, 150, 178, 196). |
| **Acceptance** | All Pack queries include `org_id` filter. |

### W2.3 — Temporal Activities Tenant Scoping

| Attribute | Detail |
|-----------|--------|
| **Files** | `backend/app/micro_apps/title_intelligence/pipeline/temporal_activities.py` |
| **Change** | Add `Pack.org_id == org_uuid` to all 3 Pack queries (lines 65, 138, 171). |
| **Acceptance** | All Pack queries include `org_id` filter. |

### W2.4 — pack_service.get_pack_files Tenant Scoping

| Attribute | Detail |
|-----------|--------|
| **Files** | `backend/app/micro_apps/title_intelligence/services/pack_service.py` |
| **Change** | Add `org_id: uuid.UUID` parameter to `get_pack_files()`. Add `PackFile.org_id == org_id` to query. Update all callers. |
| **Acceptance** | Function signature requires `org_id`. |

---

## Wave 3: Plugin Boundary Cleanup (HIGH)

**Goal**: Make the micro app plugin system truly zero-platform-edit for new apps.
**Effort**: Medium (3–4 hours) | **Risk**: Medium | **Score Impact**: Plugin 5→9, Frontend Ext 3→7

### W3.1 — Move StorageProvider to Platform Level

| Attribute | Detail |
|-----------|--------|
| **Files** | Create `backend/app/services/storage.py` (new). Update `backend/app/core/deps.py`. Update all importers. |
| **Change** | Move `StorageProvider`, `LocalStorage`, `S3Storage`, `get_storage()` from TI to `app/services/storage.py`. Add `get_storage` to `app/core/deps.py`. Leave TI-specific path builders in a thin TI wrapper. |
| **Test** | `pytest tests/test_storage.py -v` — all 9 tests pass. Full suite passes. |
| **Acceptance** | Zero imports of storage from `app.micro_apps.title_intelligence` outside TI. |

### W3.2 — Add `get_models()` to MicroAppBase

| Attribute | Detail |
|-----------|--------|
| **Files** | `backend/app/micro_apps/base.py`, `title_intelligence/app.py`, `app/models/__init__.py`, `app/main.py` |
| **Change** | Add optional `get_models() → list[type]` to `MicroAppBase`. TI overrides to return all 9 model classes. In `main.py` lifespan, call `app.get_models()` for each discovered app. Remove `ensure_ti_models()` from `app/models/__init__.py`. |
| **Acceptance** | `app/models/__init__.py` has zero micro-app-specific imports. |

### W3.3 — Dynamic Sidebar Navigation

| Attribute | Detail |
|-----------|--------|
| **Files** | `frontend/src/lib/app-registry.ts` (new), `frontend/src/components/sidebar.tsx` |
| **Change** | Create `app-registry.ts` with `appNavConfig` registry. Refactor `sidebar.tsx` to extract app slug from pathname, look up nav items dynamically. Remove all `isInsideTI` conditionals. |
| **Acceptance** | `sidebar.tsx` contains zero occurrences of `"title-intelligence"` as a string literal. |

### W3.4 — Fix Double-Mount Bug

| Attribute | Detail |
|-----------|--------|
| **Files** | `backend/app/main.py` |
| **Change** | Remove `discover_micro_apps()` from `create_app()`. Keep only in `lifespan`. |
| **Acceptance** | `discover_micro_apps()` called exactly once during startup. |

---

## Wave 4: Code Quality (MEDIUM)

**Goal**: Fix layering violations, type safety gaps, DI anti-patterns, and frontend architecture issues.
**Effort**: Medium-Large (4–6 hours) | **Risk**: Low | **Score Impact**: Backend 6→9, Frontend 5→8

### W4.1 — Consolidate Frontend Types

| Attribute | Detail |
|-----------|--------|
| **Files** | `ti-types.ts`, `use-pack.ts`, `use-packs.ts`, `use-chat.ts`, `use-pipeline-status.ts`, `chat-panel.tsx`, `chat-message.tsx`, `pipeline-progress.tsx`, `closing-checklist.tsx` |
| **Change** | Add missing fields to canonical types in `ti-types.ts`. Delete all local type redefinitions. Replace with imports from `ti-types.ts`. Tighten `status: string` → union types, `role: string` → `"user" \| "assistant"`. |
| **Acceptance** | `grep -r "interface Pack " frontend/src/` returns exactly 1 result. |

### W4.2 — Fix ClosingChecklist API Leak

| Attribute | Detail |
|-----------|--------|
| **Files** | `closing-checklist.tsx`, `results/page.tsx` |
| **Change** | Remove `orgFetch` from `ClosingChecklist`. Add `onAction` callback prop. Parent handles mutations. |
| **Acceptance** | `closing-checklist.tsx` has zero `orgFetch` calls. |

### W4.3 — Create Page Service Layer

| Attribute | Detail |
|-----------|--------|
| **Files** | `services/page_service.py` (new), `routes/pages.py` |
| **Change** | Create service functions for page queries. Routes become thin dispatchers. |
| **Acceptance** | `routes/pages.py` contains zero `db.execute()` calls. |

### W4.4 — Fix DI Anti-Patterns in Packs Route

| Attribute | Detail |
|-----------|--------|
| **Files** | `routes/packs.py` |
| **Change** | Replace imperative `get_settings()`, `get_session_factory()`, `get_storage()` with `Depends()`. Move PDF validation to service. |
| **Acceptance** | Zero imperative dependency resolution in routes. |

### W4.5 — Fix Flags Route Layering

| Attribute | Detail |
|-----------|--------|
| **Files** | `routes/flags.py`, `services/flag_service.py` |
| **Change** | Move raw extraction query to service. Move ReviewAssistant instantiation to service. |
| **Acceptance** | `routes/flags.py` has zero `db.execute()` calls and zero AI agent imports. |

### W4.6 — Delete Dead Code + Centralize Thresholds

| Attribute | Detail |
|-----------|--------|
| **Files** | Delete `readiness-gauge.tsx`. Add `getReadinessStatus()` to `ti-constants.ts`. Update 5 locations. |
| **Acceptance** | `readiness-gauge.tsx` deleted. Zero inline threshold logic. |

### W4.7 — Move Pagination to UI Layer

| Attribute | Detail |
|-----------|--------|
| **Files** | Move `components/title-intelligence/pagination.tsx` → `components/ui/pagination.tsx`. Update imports. |
| **Acceptance** | `components/title-intelligence/pagination.tsx` no longer exists. |

---

## Wave 5: Observability + Polish (MEDIUM)

**Goal**: Production-ready logging, health checks, and remaining cleanup.
**Effort**: Medium (3–4 hours) | **Risk**: Low | **Score Impact**: Observability 1→7, Config 5→8

### W5.1 — Structured JSON Logging

| Attribute | Detail |
|-----------|--------|
| **Files** | `requirements.txt`, `app/main.py`, `app/core/logging.py` (new) |
| **Change** | Add `structlog`. Configure JSON renderer with `org_id` and `request_id` context. Replace `basicConfig()`. |
| **Acceptance** | Every log line is valid JSON. |

### W5.2 — Request Correlation ID Middleware

| Attribute | Detail |
|-----------|--------|
| **Files** | `app/core/middleware.py`, `app/main.py` |
| **Change** | Add `RequestIdMiddleware` — reads/generates `X-Request-Id`, sets on request state, adds to structlog context. |
| **Acceptance** | Every log line includes `request_id`. |

### W5.3 — Deep Health Check

| Attribute | Detail |
|-----------|--------|
| **Files** | `app/routes/health.py` |
| **Change** | Expand `GET /health` to check DB (`SELECT 1`) and storage (`exists()`). Return component status. 503 on failure. |
| **Acceptance** | Health endpoint returns DB and storage status. |

### W5.4 — Sanitize Error Messages

| Attribute | Detail |
|-----------|--------|
| **Files** | `pipeline/orchestrator.py`, `services/chat_service.py` |
| **Change** | Replace raw exception text in `pack.error_message` with sanitized messages. Replace `str(e)` in SSE errors with generic message. Log full errors separately. |
| **Acceptance** | `error_message` fields contain no file paths or stack traces. |

### W5.5 — Fix Sidebar border-l-3

| Attribute | Detail |
|-----------|--------|
| **Files** | `frontend/src/components/sidebar.tsx` |
| **Change** | Replace invalid `border-l-3` with `border-l-[3px]` or `border-l-2`. |
| **Acceptance** | Active sidebar item has visible left border. |

### W5.6 — Fix datetime.utcnow() Deprecation

| Attribute | Detail |
|-----------|--------|
| **Files** | `backend/app/micro_apps/title_intelligence/services/report_service.py` |
| **Change** | Replace `datetime.utcnow()` with `datetime.now(timezone.utc)` at 3 locations. |
| **Acceptance** | `grep -rn "utcnow" backend/app/` returns zero results. |

---

## Roadmap Summary

| Wave | Focus | Tasks | Effort | Score Impact |
|:----:|-------|:-----:|:------:|:------------:|
| **1** | Security | 3 | Small | Security 3→5 |
| **2** | Tenant Safety | 4 | Small | Tenant 4→10 |
| **3** | Plugin Boundaries | 4 | Medium | Plugin 5→9, Frontend Ext 3→7 |
| **4** | Code Quality | 7 | Medium-Large | Backend 6→9, Frontend 5→8 |
| **5** | Observability + Polish | 6 | Medium | Observability 1→7, Config 5→8 |

## Projected Scores After All Waves

| Category | Before | After |
|----------|:------:|:-----:|
| Plugin architecture | 5/10 | 9/10 |
| Backend layering | 6/10 | 9/10 |
| Tenant scoping | 4/10 | 10/10 |
| Security | 3/10 | 7/10 |
| Frontend extensibility | 3/10 | 8/10 |
| Frontend code quality | 5/10 | 8/10 |
| Observability | 1/10 | 7/10 |
| Testing | 5/10 | 6/10 |
| Config & data integrity | 5/10 | 8/10 |
| **Weighted Total** | **4.1/10** | **8.2/10** |

## Remaining Items for 10/10 (Future Waves)

| Item | Why Deferred |
|------|-------------|
| Metrics endpoint (Prometheus) | Requires choosing a metrics stack |
| Token revocation / refresh tokens | Architectural decision on session model |
| Cross-tenant integration tests | Requires test infrastructure expansion |
| S3Storage tests | Requires mocking infrastructure |
| Frontend test infrastructure (Vitest) | Separate initiative |
| Pipeline failure alerting | Requires choosing a notification channel |
| Circuit breaker for AI calls | Requires evaluating `pybreaker` or custom |
| Generic `useOrgFetch` hook | Can be done incrementally as hooks are touched |
| Auth Context provider | Can be done when frontend perf is prioritized |

---

*End of Phases 0–5 Report*
