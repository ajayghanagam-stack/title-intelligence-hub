---
name: audit-performance-optimization
description: Audit the application for performance bottlenecks across frontend, backend, database, APIs, caching, background jobs, and multi-tenant SaaS scalability, then produce an evidence-based optimization plan.
argument-hint: "[report|area NAME]"
allowed-tools: Read, Grep, Glob, Bash, Task
effort: max
---

# Performance Optimization Audit

You are auditing the Title Intelligence Hub for performance bottlenecks, waste, scalability risks, and inefficient patterns. This is a **read-only audit** — do not edit code unless explicitly asked.

## Mode Selection

Based on `$ARGUMENTS`:

- **No args / `report`**: Run the full audit across all areas and produce the complete report.
- **`area NAME`** (e.g., `area backend`, `area database`, `area frontend`): Audit and report only the specified area.

---

## Objective

Evaluate the application for performance bottlenecks across:
- Frontend / UI
- Backend / API
- Database and queries
- Caching and state
- Background jobs and async workflows
- Network and payloads
- Multi-tenant isolation and scaling impact
- Observability and profiling readiness
- Build and runtime configuration
- User-perceived performance

The goal is to identify:
1. What is currently slow or likely to become slow
2. Where the evidence is found (exact files, lines, configs)
3. What can be optimized now
4. What should be deferred
5. What gives the best value for effort

---

## Audit Rules

- **Be evidence-based.** Inspect actual code, configs, docs, tests, scripts, and architecture.
- **Do not assume** performance problems without code or runtime evidence.
- **Distinguish between**:
  - Confirmed bottlenecks (evidence of slow behavior in code/logs)
  - Likely bottlenecks (patterns known to cause issues at scale)
  - Speculative risks (could become problems under specific conditions)
- **Prefer low-risk, high-impact** optimizations first.
- **Do not recommend premature optimization.**
- **Treat multi-tenant scalability** and noisy-neighbor risks as first-class concerns.
- **Call out missing observability** if profiling is weak.
- **Do not edit code** as part of this audit unless explicitly asked.

---

## Areas to Inspect

### 1. Frontend and UI Performance

**Key files**: `frontend/src/`, `frontend/next.config.js`, `frontend/package.json`

Inspect for:
- Unnecessarily large bundles
- Unnecessary re-renders
- Expensive components
- Missing memoization where clearly useful
- Blocking rendering work
- Large initial page loads
- Poor lazy loading / code splitting
- Slow tables/lists/grids
- Chatty frontend-to-backend interaction (excessive API calls)
- Repeated fetching instead of caching
- Expensive derived state or repeated transforms
- Inefficient image/font/script loading
- Weak pagination, filtering, or virtualization patterns
- Slow user-perceived flows (pipeline polling, chat streaming)

### 2. Backend and API Performance

**Key files**: `backend/app/api/`, `backend/app/micro_apps/*/routes/`, `backend/app/core/`, `backend/app/services/`

Inspect for:
- Large controllers/handlers doing too much work
- Synchronous work that should be async
- Repeated calls to the same services
- Unnecessary serialization/deserialization
- Excessive object mapping
- High-latency request chains
- Duplicate validations or duplicate DB access
- Inefficient loops over data
- Slow endpoints
- CPU-heavy work on request path
- Blocking I/O
- Poor batching/coalescing
- Unbounded processing in request path

### 3. Database and Persistence Performance

**Key files**: `backend/app/models/`, `backend/app/micro_apps/*/models/`, `backend/alembic/versions/`, `backend/app/models/base.py`

Inspect for:
- N+1 queries
- Missing indexes
- Inefficient joins
- Full table scans
- Over-fetching columns
- Weak pagination strategy
- Poor filtering patterns
- Unnecessary transactions
- Chatty ORM behavior
- Repeated lookups that should be cached
- Tenant-scoping impact on query efficiency (`org_id` index usage)
- JSONB column query efficiency (GIN indexes)
- Full-text search index usage (`tsvector`)

### 4. Caching and State

**Key files**: `backend/app/services/storage.py`, `backend/app/micro_apps/*/pipeline/stages.py`, `backend/app/micro_apps/*/pipeline/version_tracker.py`

Inspect for:
- Missing caching opportunities
- Unsafe cache keys in multi-tenant scenarios
- Low-value or stale-prone caches
- Duplicated cache lookups
- Missing request-scoped memoization
- Cache invalidation risks
- Expensive recomputation
- Weak CDN/browser caching opportunities for UI assets
- AI output cache effectiveness (hit rates, key composition)

### 5. Background Jobs, Queues, and Workflows

**Key files**: `backend/app/micro_apps/*/pipeline/orchestrator.py`, `backend/app/micro_apps/*/pipeline/stages.py`, `backend/app/micro_apps/*/ai/*.py`

Inspect for:
- Work on synchronous request path that should be queued
- Slow fan-out/fan-in patterns
- Excessive retries and backoff configuration
- Duplicate job execution risk
- Poor chunking or batching
- Lack of idempotency affecting safe optimization
- Workflow bottlenecks (sequential vs parallel stages)
- Poor concurrency control (batch sizes, semaphores)
- CPU-bound work blocking the event loop
- AI API call patterns (sequential vs concurrent, timeout settings)
- Pipeline stage ordering and dependencies

### 6. Network and Payload Efficiency

**Key files**: `backend/app/api/`, `frontend/src/lib/api.ts`, `backend/app/micro_apps/*/schemas/`

Inspect for:
- Oversized API responses
- Unnecessary fields in payloads
- Repeated round trips
- Weak batching
- Poor compression opportunities
- Asset over-delivery
- Frontend waterfall loading patterns
- SSE streaming efficiency
- File upload/download patterns

### 7. Multi-Tenant SaaS Performance Risks

**Key files**: `backend/app/models/base.py` (TenantMixin), `backend/app/core/middleware.py`, `backend/app/services/storage.py`

Inspect for:
- Tenant hot spots
- Noisy-neighbor risk (one tenant's heavy pipeline blocking others)
- Shared resource contention
- Tenant filters harming index usage
- Cache pollution across tenants
- High-cardinality metrics/logs causing cost or latency
- Poor isolation of heavy tenant workloads
- Storage namespace isolation effectiveness
- Pipeline concurrency across tenants

### 8. Observability and Profiling Readiness

**Key files**: `backend/app/core/logging.py`, `backend/app/core/middleware.py`, `backend/app/config.py`

Inspect for:
- Missing endpoint timing
- Missing DB query timing
- Missing frontend performance markers
- Weak tracing
- Lack of p95/p99 visibility
- Missing slow query logging
- Inability to attribute latency by component
- Inability to attribute issues by tenant, endpoint, or workflow
- Pipeline stage timing instrumentation
- AI API call duration tracking

### 9. Build and Runtime Efficiency

**Key files**: `backend/Dockerfile*`, `frontend/Dockerfile*`, `docker-compose*.yml`, `package.json`, `pyproject.toml`

Inspect for:
- Slow builds hurting throughput
- Unnecessary dependencies
- Bloated client bundles
- Heavy startup time
- Inefficient container/runtime config
- Poor worker/thread/process settings
- Missing production optimizations (uvicorn workers, gunicorn, etc.)

---

## Classification Rules

For each issue or opportunity, classify it as exactly one:

| Classification | Definition |
|---------------|------------|
| **Confirmed bottleneck** | Evidence of slow behavior in code patterns, logs, or measured performance |
| **Likely bottleneck** | Patterns known to cause issues at scale, even if not yet measured |
| **Optimization opportunity** | Room for improvement that isn't blocking but would help |
| **Future scaling risk** | Will become a problem as data/users/tenants grow |
| **Not an issue** | Investigated and found to be acceptable |

For each recommendation, provide:

| Attribute | Values |
|-----------|--------|
| **Impact** | High / Medium / Low |
| **Effort** | High / Medium / Low |
| **Risk** | High / Medium / Low |
| **When** | Now / Soon / Later |

---

## Optimization Principles

**Prefer these kinds of optimizations:**
- Remove duplicate work
- Reduce request-path latency
- Reduce query count and query cost
- Reduce payload size
- Batch where useful
- Cache safely (tenant-scoped)
- Move heavy work off the synchronous path
- Improve pagination and filtering
- Improve rendering efficiency
- Add parallelism to CPU-bound or I/O-bound work
- Improve profiling and observability before deep tuning
- Preserve correctness and tenant isolation

**Avoid these kinds of weak recommendations:**
- Vague "use caching"
- Vague "optimize queries"
- Premature micro-optimizations
- Broad rewrites without evidence
- Changes that risk tenant data leakage
- Tuning without measurement

---

## Audit Procedure

1. **Read `CLAUDE.md`** for architecture context, performance expectations, and business rules.
2. **Read `backend/app/config.py`** for runtime settings.
3. **For each area**, use Glob/Grep/Read to inspect the relevant files.
4. **For pipeline performance**, trace the full stage execution path:
   - `orchestrator.py` → each stage in `stages.py` → AI agents → storage
5. **For frontend**, check bundle size (`npm run build`), component patterns, API call frequency.
6. **For database**, check models for indexes, query patterns in services/routes, tenant scoping.
7. **Compile the report** in the format below.

---

## Required Output Format

```markdown
# Performance Optimization Audit Report

**Date**: {date}
**Auditor**: Claude Code
**Scope**: {full / area name}

---

## 1. Overall Performance Verdict

{Choose exactly one}:
- Healthy with minor optimization opportunities
- Acceptable but needs targeted optimization
- At risk and needs near-term optimization
- Performance bottlenecks are significant

---

## 2. Executive Summary

**Top performance strengths:**
- ...

**Top bottlenecks:**
- ...

**Biggest risks for scale:**
- ...

**What matters most right now:**
- ...

---

## 3. Findings by Area

### Frontend / UI
- **Status**: {Healthy / Needs Work / At Risk}
- **Evidence**: ...
- **Bottlenecks**: ...
- **Recommendations**: ...

### Backend / API
- **Status**: ...
- **Evidence**: ...
- **Bottlenecks**: ...
- **Recommendations**: ...

### Database / Persistence
- **Status**: ...
- **Evidence**: ...
- **Bottlenecks**: ...
- **Recommendations**: ...

### Caching / State
- **Status**: ...
- **Evidence**: ...
- **Bottlenecks**: ...
- **Recommendations**: ...

### Background Jobs / Workflows
- **Status**: ...
- **Evidence**: ...
- **Bottlenecks**: ...
- **Recommendations**: ...

### Network / Payloads
- **Status**: ...
- **Evidence**: ...
- **Bottlenecks**: ...
- **Recommendations**: ...

### Multi-Tenant Scalability
- **Status**: ...
- **Evidence**: ...
- **Bottlenecks**: ...
- **Recommendations**: ...

### Observability / Profiling
- **Status**: ...
- **Evidence**: ...
- **Bottlenecks**: ...
- **Recommendations**: ...

### Build / Runtime
- **Status**: ...
- **Evidence**: ...
- **Bottlenecks**: ...
- **Recommendations**: ...

---

## 4. Top Optimization Opportunities

| # | Title | Category | Classification | Impact | Effort | Risk | When | Files Involved |
|---|-------|----------|----------------|--------|--------|------|------|----------------|
| 1 | ... | ... | ... | ... | ... | ... | ... | ... |
| 2 | ... | ... | ... | ... | ... | ... | ... | ... |
...

**Details for each:**

### Optimization 1: {title}
- **Category**: ...
- **Classification**: Confirmed bottleneck / Likely bottleneck / etc.
- **Evidence**: {exact file, line, pattern}
- **Impact**: High / Medium / Low
- **Effort**: High / Medium / Low
- **Risk**: High / Medium / Low
- **When**: Now / Soon / Later
- **Files involved**: ...
- **Recommendation**: ...

---

## 5. Quick Wins

Low effort + low risk + high or medium impact:

| # | Title | Impact | Effort | Files |
|---|-------|--------|--------|-------|
| 1 | ... | ... | ... | ... |
...

---

## 6. Deep Optimizations to Defer

High effort or architectural changes not yet justified:

| # | Title | Why Defer | Revisit When |
|---|-------|-----------|--------------|
| 1 | ... | ... | ... |
...

---

## 7. Multi-Tenant Performance Risk Summary

- **Noisy-neighbor risks**: {Yes/No — details}
- **Tenant-scoped query scalability**: {Assessment}
- **Cache tenant safety**: {Assessment}
- **Tenant hotspot risk**: {Assessment}

---

## 8. Measurement and Observability Gaps

| Gap | Impact | Recommendation |
|-----|--------|----------------|
| ... | ... | ... |

---

## 9. Prioritized Action Plan

| Priority | Action | Impact | Effort | Category |
|----------|--------|--------|--------|----------|
| 1 | ... | ... | ... | ... |
| 2 | ... | ... | ... | ... |
...

**Mandatory before scaling / broader rollout:**
1. ...
2. ...
```
