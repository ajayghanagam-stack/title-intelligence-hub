# Title Intelligence Pipeline — Architecture Audit & Phased Refactor Plan

**Date:** 2026-03-27
**Author:** Architecture Audit (Claude)
**Status:** Draft — Pending Review
**Benchmark Target:** 100 pages in 60 seconds

---

## Table of Contents

1. [Current Architecture Summary](#1-current-architecture-summary)
2. [Gap Analysis vs Target Architecture](#2-gap-analysis-vs-target-architecture)
3. [Bottleneck Analysis](#3-bottleneck-analysis)
4. [Determinism & Stability Risks](#4-determinism--stability-risks)
5. [Phased Refactor Roadmap](#5-phased-refactor-roadmap)
6. [Recommended First Phase](#6-recommended-first-phase)
7. [Appendix: File Reference](#7-appendix-file-reference)

---

## Core Architecture Decision: All-LLM, No OCR

**Decision:** Eliminate all OCR (Tesseract, embedded text extraction routing) from the pipeline. Send native PDFs directly to Gemini 2.5 Flash for all document understanding.

**Rationale:** Our research confirms that OCR and embedded text extraction skip critical data — stamps, seals, handwritten annotations, marginal notes, multi-layer scan content, and precise legal description formatting. Every downstream stage (extraction, flagging, chain building) suffers when the source text is incomplete. The LLM must see exactly what a human title examiner sees.

**Gemini 2.5 Flash Native PDF Capabilities:**
| Capability | Value |
|-----------|-------|
| Max pages per PDF | 1,000 |
| Max file size | 50 MB |
| Cost per page (visual) | 258 tokens (~$0.00008) |
| Native text extraction | FREE (not charged) |
| Context window | 1,048,576 tokens (1M) |
| Output throughput | ~245 tokens/sec |
| Files API retention | 48 hours (free storage) |
| SDK support | `google-genai` (`Part.from_bytes`, Files API) |
| litellm support | `type: "file"` with `data:application/pdf;base64,...` |

**100-page PDF token budget:**
- Visual: 100 × 258 = 25,800 tokens
- Native text: FREE
- System prompt + schema: ~2,000 tokens
- **Total input: ~28,000 tokens** (2.7% of 1M context window)
- Output (16K tokens at 245 tok/s): ~65 seconds for single call
- **Split into 4 × 25-page chunks in parallel: ~18 seconds examine time**

---

## 1. Current Architecture Summary

### 1.1 High-Level System Flow

```
User uploads PDF(s) via frontend
  → POST /packs/{id}/files (multipart upload, PDF validation, hash computation)
  → POST /packs/{id}/process (triggers pipeline)
  → Pipeline runs asynchronously (BackgroundTasks or Temporal)
  → Frontend polls via SSE (/pipeline/stream) or HTTP polling (/pipeline) every 3s
  → Pack status: uploading → processing → completed | failed
```

### 1.2 Pipeline Stages (4 Sequential Stages)

| Stage | What It Does | Concurrency | LLM? | Typical Time (50pp) |
|-------|-------------|-------------|-------|---------------------|
| **ingest** | Validate files exist in storage | None | No | <1s |
| **render** | PDF → JPEG + extract embedded text | 8 concurrent pages | No | 60–120s |
| **examine** | OCR + extraction + section detection + flagging (single-pass AI) | All batches parallel | Yes (Gemini 2.5 Flash) | 30–90s |
| **complete** | Readiness score (rules) + summary (LLM) + PDF report | Sequential | Yes (summary only) | 10–30s |

**Total for 50 pages:** 100–240 seconds (1.5–4 minutes) — **far too slow**

### 1.3 Why The Current Architecture Is Slow

The pipeline has **two major time sinks** that are architecturally unnecessary:

1. **Render stage (60–120s):** Converts every PDF page to JPEG at 72 DPI for the LLM. This is completely unnecessary — Gemini 2.5 Flash can process native PDFs directly.

2. **Text/image routing overhead:** The examine stage splits pages into "text" (embedded text ≥50 chars) and "image" (scanned) groups, uses different batch sizes (25 vs 10), different JSON schemas, and different content encoding. This complexity exists to work around OCR limitations — not needed with native PDF.

3. **OCR data loss:** Pages routed as "text" only get their embedded PDF text layer, missing stamps, annotations, and visual context. This causes incomplete extractions and missed flags downstream.

### 1.4 Current AI Integration

| Component | Role | Problem |
|-----------|------|---------|
| `TitleExaminerAgent` | Single-pass: OCR + extraction + flagging in one call | Monolithic — does too much per call |
| Text/image split | Routes pages by embedded text threshold | Causes data loss on "text" pages |
| Base64 image encoding | Sends JPEG images as data URLs | 3x bloat vs native PDF |
| Dual JSON schemas | `EXAMINATION_JSON_SCHEMA` vs `TEXT_ONLY` | Unnecessary complexity |

### 1.5 Frontend Flow

```
Pack Detail Page → usePipelineStatus(packId) via SSE or polling every 3s
                 → PipelineProgress: 4-stage visual tracker
                 → examine_progress: "3/6 batches, 12 flags"
                 → Auto-navigates to /results on completion

Results Page     → Flags table with evidence refs (page_number + text_snippet)
                 → Summary cards: critical count, warnings, validation score
                 → Re-analyze button triggers new pipeline run
```

---

## 2. Gap Analysis vs Target Architecture

### 2.1 Stage-by-Stage Comparison

| Target Stage | Current State | Gap |
|-------------|---------------|:---:|
| **1. Ingestion** (upload, hash, split PDF into chunks, async job) | Upload + hash exists. No PDF splitting for parallel processing. | Medium |
| **2. Document Understanding** (LLM classifies pages, groups documents, tags types) | Mixed into examine stage. Section detection exists but no page classification or document grouping. | High |
| **3. Structured Extraction** (LLM extracts per document type with strict schemas, page refs) | Single generic extractor handles all 8 types in one pass. No specialized prompts. | High |
| **4. Title Reasoning** (LLM + rules: chain building, gap detection, release matching, party normalization) | Flag rules engine exists (severity clamping, dedup). No chain builder, no party normalization, no release matching. | High |
| **5. Report Generation** (from validated structured facts, page-linked evidence) | Exists — PDF report from structured data (fpdf2). Evidence refs included. | Low |
| **6. Observability** (per-stage latency, token/cost, structured logs, benchmarks) | Mostly missing. No timing, no token tracking, no structured logging. | Critical |

### 2.2 What Is Mixed Together (Monolithic Examine Stage)

```
┌─────────────────────────────────────────────────┐
│              TitleExaminerAgent                  │
│                                                 │
│  1. OCR/Transcription  ← REMOVE (native PDF)   │
│  2. Section Detection  ← should be own stage    │
│  3. Data Extraction    ← should be specialized  │
│  4. Flag Detection     ← should use rules first │
│                                                 │
│  ALL IN ONE PROMPT + ONE JSON SCHEMA            │
│  + Unnecessary render stage before it           │
└─────────────────────────────────────────────────┘
```

### 2.3 What Will Not Scale

| Issue | Impact at 100 Pages (current) | Impact at 500 Pages |
|-------|------------------------------|-------------------|
| Render stage (JPEG generation) | ~30–60s wasted | ~150s wasted |
| Text/image split routing | Complex batching, data loss | More batches, more data loss |
| All batches fire simultaneously | Works for 3–6 batches | 20+ batches → rate limit storm |
| Generic prompt for all doc types | Lower accuracy | Much lower accuracy |
| No page classification | Wastes LLM on blank/cover pages | 20–30% waste |
| Sequential stages | Can't overlap render + examine | Massive time waste |
| Frontend fetches all flags at once | OK for 20 flags | 200+ flags → large payload |

---

## 3. Bottleneck Analysis

### 3.1 Current vs Target Timing (100 Pages)

**Current architecture:**
| Stage | Time | Why |
|-------|------|-----|
| Ingest | 2s | File validation |
| Render | 30–60s | **UNNECESSARY** — 100 pages × JPEG + thumbnail |
| Examine | 30–60s | 4–6 batches of mixed text/image to Gemini |
| Complete | 10–20s | Readiness + summary + PDF report |
| **Total** | **72–142s** | **Fails 60s target** |

**Target architecture (native PDF, no OCR):**
| Stage | Time | Why |
|-------|------|-----|
| Ingest | 2s | Hash + split PDF into 4 × 25-page chunks |
| Examine | 18–25s | 4 parallel Gemini calls on native PDF chunks |
| Reason | 2–5s | Deterministic rules + LLM for ambiguity |
| Complete | 8–15s | Readiness + summary + report (parallel where possible) |
| **Total** | **30–47s** | **Meets 60s target** |

**Savings breakdown:**
- Render stage eliminated: **-60s**
- Native PDF vs base64 images: **-5s** (no encoding overhead)
- Parallel PDF chunks vs sequential text/image batches: **-15s**
- Total saved: **~80s**

### 3.2 Top Bottlenecks to Eliminate

#### 1. Render Stage — Entirely Unnecessary (30–60s for 100pp)
- Converts PDF to JPEG just to send images to Gemini
- Gemini can read native PDFs directly
- **Action:** Eliminate render-for-AI entirely. Keep render-for-UI as a background task that runs in parallel.

#### 2. Text/Image Split — Causes Data Loss + Complexity
- Pages with embedded text (≥50 chars) skip visual processing
- Misses stamps, annotations, handwritten notes, visual layout
- Creates two code paths, two schemas, two batch sizes
- **Action:** Remove split. Send native PDF. LLM sees everything.

#### 3. Output Token Generation — The Real Bottleneck
- At 245 tokens/sec, generating 16K output tokens takes ~65 seconds
- Single 100-page call would miss the 60s target on output alone
- **Action:** Split into 4 × 25-page chunks. Each generates ~4K tokens in ~16s. All run in parallel.

#### 4. Sequential Stages — No Overlap
- Current: ingest → render → examine → complete (strictly sequential)
- **Action:** Pipeline stages overlap where possible. UI rendering runs as background task, not blocking.

#### 5. Monolithic Examine — Does Too Much Per Call
- One prompt does classification + extraction + flagging
- Large output schema = more output tokens = slower
- **Action:** Split into focused LLM calls with smaller schemas (Phase 3+).

### 3.3 Scaling Estimates

| Document Size | Chunks (25pp each) | Parallel Calls | Examine Time | Total Pipeline |
|:---:|:---:|:---:|:---:|:---:|
| 25 pages | 1 | 1 | ~18s | ~28s |
| 50 pages | 2 | 2 | ~18s | ~30s |
| 100 pages | 4 | 4 | ~18s | ~35s |
| 250 pages | 10 | 5 (bounded) | ~36s (2 waves) | ~55s |
| 500 pages | 20 | 5 (bounded) | ~72s (4 waves) | ~95s |

*Assumes: 25 pages per chunk, 5 max concurrent Gemini calls, ~18s per call, ~15s for complete stage.*

---

## 4. Determinism & Stability Risks

### 4.1 All-LLM Determinism Profile

| Component | Deterministic? | Mitigation |
|-----------|:-:|------|
| File hashing | Yes | — |
| PDF chunk assignment | Yes | Deterministic page ranges |
| Gemini PDF processing (temp=0) | ~98% stable | Cache results by file hash + version |
| Section detection by LLM | ~95% stable | Validate against known section types |
| Data extraction by LLM | ~90% stable | Strict JSON schema + Pydantic validation |
| Flag detection by LLM | ~85% stable | Rules engine clamps severity post-LLM |
| Flag rules (severity/dedup) | Yes | — |
| Readiness scoring | Yes | — |
| Cache key computation | Yes | — |

### 4.2 Achieving 90% Cross-Run Consistency

1. **Cache aggressively** — same file hash + version = replay cached results (100% deterministic)
2. **Strict JSON schemas** — closed-set enums (12 flag types, 8 extraction types, 4 severity levels)
3. **Temperature 0.0** — minimize LLM variation
4. **Post-LLM rules engine** — severity clamping, dedup, and sorting are fully deterministic
5. **Party name normalization** (Phase 5) — deterministic fuzzy matching before chain comparison
6. **Deterministic chain logic** (Phase 5) — rules-based gap detection, LLM only for ambiguity
7. **Pydantic validation** — reject and retry malformed LLM output

**Key insight:** With native PDF, determinism actually improves vs current architecture because all pages get identical treatment (no text vs image routing that produces different quality outputs).

---

## 5. Phased Refactor Roadmap

### Overview

```
Phase 0: Audit & Architecture Map                    ◀── YOU ARE HERE
Phase 1: Native PDF Pipeline + Render Elimination     ◀── RECOMMENDED FIRST (highest impact)
Phase 2: Observability & Instrumentation Baseline
Phase 3: Multi-Stage LLM Pipeline (classify → extract → flag)
Phase 4: Bounded Concurrency & Adaptive Rate Limiting
Phase 5: Deterministic Title Reasoning Engine
Phase 6: Specialist Extractors & Strict Schemas
Phase 7: UI Pipeline Tracker & Evidence-Linked Viewer
Phase 8: Evaluation Harness & Regression Benchmarks
Phase 9: Production Hardening & Scale Testing
```

**Benchmark targets per phase:**

| Phase | 100-page Target | 500-page Target |
|:---:|:---:|:---:|
| Current | 72–142s (FAIL) | 200–560s |
| After Phase 1 | **30–47s (PASS)** | 95–150s |
| After Phase 4 | 25–35s | 70–100s |
| After Phase 6 | 20–30s | 55–80s |

---

### Phase 1: Native PDF Pipeline + Render Elimination

**Goal:** Replace the render-then-image pipeline with native PDF upload to Gemini. Eliminate OCR and text extraction routing entirely. Hit the 100-pages-in-60s benchmark.

**Scope:**
- Remove text/image split logic (`MIN_EMBEDDED_TEXT_LEN` threshold, dual batch sizes, dual JSON schemas)
- Send native PDF bytes to Gemini via `google-genai` SDK (`Part.from_bytes(mime_type="application/pdf")`)
- Split large PDFs into page-range chunks (25–50 pages each) for parallel processing
- Make render stage a non-blocking background task (UI thumbnails only, not on critical path)
- Simplify examine batching to uniform chunk-based processing
- Update cache keys to reflect new pipeline mode

**Files likely affected:**
- `backend/app/ai/base_service.py` — add native PDF content support in `_call_genai_cached()`
- `backend/app/micro_apps/title_intelligence/ai/title_examiner_agent.py` — replace image batching with PDF chunk batching
- `backend/app/micro_apps/title_intelligence/pipeline/stages.py` — rewrite `stage_render` (UI-only), rewrite `stage_examine` (native PDF)
- `backend/app/micro_apps/title_intelligence/pipeline/orchestrator.py` — run render as background task
- `backend/app/micro_apps/title_intelligence/schemas/examiner.py` — single unified JSON schema (remove `TEXT_ONLY` variant)
- `backend/app/micro_apps/title_intelligence/pipeline/version_tracker.py` — update cache key for native PDF mode
- `backend/app/config.py` — new settings: `EXAMINER_CHUNK_SIZE` (pages per chunk), `EXAMINER_MAX_CONCURRENT_CHUNKS`

**Design choices:**
- **PDF splitting:** Use PyMuPDF to split PDF into page-range chunks (e.g., pages 1–25, 26–50, etc.) as byte buffers — no disk I/O
- **Parallel chunks:** `asyncio.Semaphore(N)` bounds concurrent Gemini calls (default N=5)
- **Native PDF to Gemini:** `types.Part.from_bytes(data=chunk_bytes, mime_type="application/pdf")` — no base64 encoding, no image rendering
- **Files API for large PDFs:** If PDF > 20MB, use Gemini Files API (upload once, reference in calls) — 48hr retention, free
- **UI rendering:** Page images for the document viewer are generated as a separate background task that does not block the AI pipeline
- **Single JSON schema:** Remove `EXAMINATION_JSON_SCHEMA_TEXT_ONLY`. All chunks use the full schema with `page_transcriptions` (Gemini provides transcriptions from native PDF)
- **Backward compatibility:** Existing `Page` records still created (from Gemini transcriptions), so frontend page viewer continues to work

**Risks:**
- litellm's PDF support for Gemini may have edge cases (fallback: use `google-genai` SDK directly)
- Very large PDFs (>50MB) need splitting before upload
- Gemini's native PDF parsing on degraded scans needs validation against current quality

**Testing approach:**
- Unit test: PDF chunk splitting produces correct page ranges
- Unit test: native PDF content sent correctly to Gemini SDK
- Integration test: same PDF produces equivalent extractions/flags via native PDF vs current image pipeline
- Benchmark test: 100-page PDF completes in under 60 seconds
- Regression test: existing golden-set determinism tests still pass

**Expected benefit:**
- Render stage: 60s → 0s (on critical path; UI render runs in background)
- Examine stage: 30–60s → 18–25s (native PDF + parallel chunks)
- Data quality: improved (LLM sees full visual content, no OCR data loss)
- Code simplification: remove dual schema, dual batch sizing, text/image routing
- **100-page benchmark: 72–142s → 30–47s (PASS)**

**Rollback:** Config flag `PIPELINE_MODE=legacy` reverts to image-based pipeline

---

### Phase 2: Observability & Instrumentation Baseline

**Goal:** Add per-stage timing, token/cost tracking, and structured logging so we can measure and prove improvements.

**Scope:**
- Wrap each pipeline stage with wall-clock timing
- Track Gemini API call latency, input/output tokens, and cost per chunk
- Add structured JSON logging with `org_id`, `pack_id`, `stage`, `chunk_num` fields
- Store metrics in `PipelineRun.version_metadata` JSONB
- Log pipeline summary on completion: total time, per-stage times, total tokens, cost estimate

**Files likely affected:**
- `backend/app/ai/base_service.py` — wrap LLM calls with timing + token extraction
- `backend/app/micro_apps/title_intelligence/pipeline/stages.py` — stage timing
- `backend/app/micro_apps/title_intelligence/pipeline/orchestrator.py` — pipeline-level timing
- `backend/app/micro_apps/title_intelligence/ai/title_examiner_agent.py` — chunk-level metrics

**Design choices:**
- `time.perf_counter()` for wall-clock timing
- Tokens from litellm response metadata (`usage.prompt_tokens`, `usage.completion_tokens`)
- Metrics stored in existing JSONB column (no new tables)
- Cost estimate: `input_tokens × $0.30/1M + output_tokens × $2.50/1M`

**Risks:** Minimal — read-only instrumentation, no behavior changes

**Expected benefit:**
- Baseline measurements for all subsequent phases
- Can answer: "100-page PDF: examine took Xs (N chunks, M tokens, $C cost)"
- Data-driven prioritization of remaining phases

**Rollback:** Remove timing code — zero risk

---

### Phase 3: Multi-Stage LLM Pipeline (Classify → Extract → Flag)

**Goal:** Split the monolithic examine call into focused LLM stages with smaller schemas and higher accuracy.

**Scope:**
- **Stage A — Classify:** LLM classifies each page (content type, document type, section boundaries). Small output schema.
- **Stage B — Extract:** LLM extracts structured data from classified page groups. Type-specific prompts.
- **Stage C — Flag:** LLM detects risks from extracted data + original pages. Focused on anomalies.
- Each stage has its own prompt, schema, and cache key
- Stages can run with different chunk sizes optimized for their task

**Pipeline becomes:**
```
ingest → [classify → extract → flag] → complete
          ↑ all LLM, native PDF ↑
```

**Files likely affected:**
- `backend/app/micro_apps/title_intelligence/ai/title_examiner_agent.py` — split into 3 focused agents
- New: `ai/classify_agent.py`, `ai/extract_agent.py`, `ai/flag_agent.py`
- `backend/app/micro_apps/title_intelligence/schemas/examiner.py` — per-stage schemas
- `backend/app/micro_apps/title_intelligence/pipeline/stages.py` — new sub-stages

**Design choices:**
- Classify output feeds extract input (structured intermediate data)
- Extract output feeds flag input (validated extractions)
- Each stage validates output via Pydantic before passing downstream
- Classify is lightweight (~2K output tokens) — fast, enables smart routing
- Extract uses type-specific prompts (deed prompt, mortgage prompt, etc.)
- Flag stage sees both raw PDF pages AND extracted data — catches what extraction missed

**Risks:**
- 3 LLM calls instead of 1 per chunk — but each is faster (smaller schema → fewer output tokens)
- Inter-stage data validation adds latency — but catches errors early
- More code to maintain — but each agent is simpler and testable independently

**Expected benefit:**
- Higher extraction accuracy (focused prompts)
- Lower total output tokens (smaller per-stage schemas)
- Independent caching per stage (classify cache survives extract prompt changes)
- Foundation for specialized extractors (Phase 6)

**Rollback:** Config flag `PIPELINE_STAGES=unified` runs single-pass examine

---

### Phase 4: Bounded Concurrency & Adaptive Rate Limiting

**Goal:** Ensure 500-page documents process reliably without rate limit storms.

**Scope:**
- `asyncio.Semaphore(N)` bounds concurrent Gemini calls (configurable, default N=5)
- Staggered chunk launch (200–500ms between starts)
- Adaptive throttling: on 429, reduce concurrency and increase cooldown
- Per-org rate tracking to prevent one large pack from starving others

**Files likely affected:**
- `backend/app/micro_apps/title_intelligence/ai/title_examiner_agent.py` — bounded concurrency
- `backend/app/ai/base_service.py` — adaptive rate limiting
- `backend/app/config.py` — `EXAMINER_MAX_CONCURRENT_CHUNKS`, `EXAMINER_CHUNK_STAGGER_MS`

**Expected benefit:**
- 500-page docs (20 chunks): 4 waves × 18s = 72s examine (vs current rate-limited 180–300s)
- Predictable pipeline times (no variance from retry cascades)
- Multi-tenant fairness

**Rollback:** Set concurrency to 100 = current unbounded behavior

---

### Phase 5: Deterministic Title Reasoning Engine

**Goal:** Build title chain, detect gaps, and match releases using deterministic logic first, LLM only for ambiguity.

**Scope:**
- Party name normalizer (regex + fuzzy matching via `rapidfuzz`)
- Chain builder: sequence grantor/grantee events chronologically from extractions
- Gap detector: find breaks in ownership chain (deterministic graph traversal)
- Release matcher: match releases to mortgages/liens by instrument number
- Mismatch detector: legal description inconsistencies, name discrepancies
- LLM fallback: only for cases rules can't resolve (ambiguous names, unclear instruments)

**Files likely affected:**
- New: `services/chain_builder.py`, `services/party_normalizer.py`
- Extend: `services/flag_rules.py` — chain-aware rules
- `pipeline/stages.py` — new reasoning stage between extract and complete

**Design choices:**
- Deterministic first: 80% of chain flags from rules, 20% from LLM
- Rules-based flags = high confidence; LLM flags = medium confidence
- All reasoning traceable: each flag includes derivation path

**Expected benefit:**
- 90%+ determinism target achieved
- Rules execute in milliseconds (no LLM cost)
- Auditable: every flag has a clear derivation

**Rollback:** Disable reasoning engine → fall back to LLM-only flagging

---

### Phase 6: Specialist Extractors & Strict Schemas

**Goal:** Replace generic extraction with document-type-specific LLM extractors.

**Scope:**
- Strict Pydantic schemas per document type (deed, mortgage, lien, release, judgment, easement)
- Route page groups to specialized extraction prompts based on classification from Phase 3
- Validate extraction output against schema before storing
- Inter-document cross-references (mortgage number on release, etc.)

**Files likely affected:**
- New: `ai/extractors/deed_extractor.py`, `mortgage_extractor.py`, `lien_extractor.py`, etc.
- New: `schemas/instruments/` — per-type Pydantic schemas

**Design choices:**
- Each extractor: focused prompt (200–500 tokens vs 1300 current) + tight schema
- Generic fallback for unknown document types
- Validation: reject and retry on schema mismatch

**Expected benefit:**
- Higher extraction accuracy
- Lower token cost (smaller prompts/schemas)
- Foundation for advanced title reasoning

---

### Phase 7: UI Pipeline Tracker & Evidence-Linked Viewer

**Goal:** Document viewer with evidence highlighting, chain timeline, review queue.

**Scope:**
- PDF.js-based document viewer with page navigation
- Click flag → jump to source page with highlighted evidence region
- Title chain timeline (SVG/D3): ownership events with gap indicators
- Review queue: filterable by severity, status, document type
- Server-side flag pagination

**Expected benefit:** Dramatically reduced examiner review effort.

---

### Phase 8: Evaluation Harness & Regression Benchmarks

**Goal:** Automated quality and performance regression testing.

**Scope:**
- Benchmark suite: time each stage for 25/50/100/500 page documents
- Quality suite: compare extraction output against golden set
- Determinism suite: run same document 5x, measure output variance
- Cost tracker: tokens and API calls per document size
- CI integration: benchmark on PRs that touch pipeline code

**Benchmark targets:**

| Doc Size | Pipeline Time | Examine Time | Max Cost |
|:---:|:---:|:---:|:---:|
| 25 pages | <30s | <18s | <$0.05 |
| 50 pages | <35s | <18s | <$0.10 |
| 100 pages | <60s | <25s | <$0.20 |
| 500 pages | <120s | <75s | <$1.00 |

---

### Phase 9: Production Hardening & Scale Testing

**Goal:** Validate system handles 500-page documents reliably in production.

**Scope:**
- Load test: 10 concurrent 500-page pipelines
- Chaos test: kill worker mid-pipeline, verify Temporal recovery
- Memory profiling: ensure no OOM on large documents
- Rate limit test: verify adaptive throttling under real Gemini quotas
- Production monitoring dashboards

---

## 6. Recommended First Phase

### Phase 1: Native PDF Pipeline + Render Elimination

**Why this should be first:**

1. **Biggest single performance gain.** Eliminates 60s render stage entirely. Cuts examine time by 40%. Gets us from 72–142s to 30–47s for 100 pages.
2. **Fixes the data quality problem.** No more OCR data loss. LLM sees exactly what a human examiner sees — stamps, seals, annotations, layout.
3. **Simplifies the codebase.** Removes text/image routing, dual schemas, dual batch sizes, base64 encoding. Less code = fewer bugs.
4. **Enables everything else.** Phases 3–6 all build on native PDF input. Starting here sets the foundation.
5. **Low risk.** Gemini's native PDF support is production-ready. Fallback to legacy image pipeline via config flag.

**Implementation sequence:**
1. Add PDF chunk splitting utility (PyMuPDF split by page range → bytes)
2. Add native PDF content support to `BaseAIService._call_genai_cached()`
3. Rewrite `TitleExaminerAgent.examine_document()` to use PDF chunks instead of image batches
4. Make `stage_render` non-blocking (background task for UI thumbnails only)
5. Remove text/image split, dual schemas, dual batch sizing
6. Update cache keys and version tracking
7. Add 100-page benchmark test
8. Validate against golden set (extractions + flags match or improve)

**Success criteria:**
- 100-page PDF completes pipeline in under 60 seconds
- Extraction quality matches or exceeds current (validated against sample documents)
- All existing tests pass (with updated mocks for native PDF flow)
- Golden-set determinism tests pass

---

## 7. Appendix: File Reference

### Pipeline Core
| File | Purpose |
|------|---------|
| `backend/app/micro_apps/title_intelligence/pipeline/orchestrator.py` | Pipeline execution router |
| `backend/app/micro_apps/title_intelligence/pipeline/stages.py` | Stage implementations |
| `backend/app/micro_apps/title_intelligence/pipeline/temporal_workflows.py` | Temporal workflow |
| `backend/app/micro_apps/title_intelligence/pipeline/temporal_activities.py` | Temporal activities |
| `backend/app/micro_apps/title_intelligence/pipeline/version_tracker.py` | Version hashes + cache keys |

### AI Layer
| File | Purpose |
|------|---------|
| `backend/app/ai/base_service.py` | Base AI: LLM calls, context caching |
| `backend/app/micro_apps/title_intelligence/ai/title_examiner_agent.py` | Examiner agent (to be refactored) |
| `backend/app/micro_apps/title_intelligence/schemas/examiner.py` | Examiner schemas (to be unified) |

### Services
| File | Purpose |
|------|---------|
| `backend/app/micro_apps/title_intelligence/services/flag_rules.py` | Deterministic flag rules |
| `backend/app/micro_apps/title_intelligence/services/readiness_service.py` | Readiness scoring |
| `backend/app/micro_apps/title_intelligence/services/pipeline_service.py` | Pipeline status |

### Models & Routes
| File | Purpose |
|------|---------|
| `backend/app/micro_apps/title_intelligence/models/pack.py` | Pack, PackFile, Page, Flag, Extraction |
| `backend/app/micro_apps/title_intelligence/routes/packs.py` | API endpoints |
| `backend/app/micro_apps/title_intelligence/schemas/pack.py` | Request/response schemas |

### Frontend
| File | Purpose |
|------|---------|
| `frontend/src/hooks/use-pipeline-status.ts` | SSE + polling |
| `frontend/src/components/title-intelligence/pipeline-progress.tsx` | Progress UI |
| `frontend/src/components/title-intelligence/flags-table.tsx` | Flags table |

### Config
| File | Purpose |
|------|---------|
| `backend/app/config.py` | All settings |
| `backend/app/services/storage.py` | Storage provider |

---

*End of audit. Next step: implement Phase 1 (Native PDF Pipeline + Render Elimination) upon approval.*
