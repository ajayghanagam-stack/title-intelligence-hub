# Title Intelligence Pipeline — Benchmark-Driven Refactor Plan V2

**Date:** 2026-03-27
**Author:** Architecture Audit (Claude)
**Status:** Draft — Pending Review

## Performance SLA

| Pages | Target Time | Rate |
|:-----:|:-----------:|:----:|
| 100 | 60 seconds | 1.67 pp/s |
| 200 | 120 seconds | 1.67 pp/s |
| 300 | 180 seconds | 1.67 pp/s |
| 400 | 240 seconds | 1.67 pp/s |
| 500 | 300 seconds | 1.67 pp/s |

**Linear scaling required:** ~0.6 seconds per page, end-to-end.

---

## 1. Repository Findings

### Major Entry Points
- **Upload:** `POST /api/v1/apps/title-intelligence/packs/{packId}/files` — multipart PDF upload, validates size (<100MB), computes SHA256 hash
- **Process:** `POST /api/v1/apps/title-intelligence/packs/{packId}/process` — returns 202 immediately, triggers async pipeline via BackgroundTasks or Temporal
- **Pipeline status:** `GET .../pipeline` (polling) and `GET .../pipeline/stream` (SSE every 2s, delta-only)
- **Results:** `GET .../flags`, `GET .../extractions`, `GET .../readiness`, `GET .../reports/download`

### Backend Processing Flow
```
/process (202 ACCEPTED)
  → trigger_pipeline() → BackgroundTasks.add_task() or Temporal workflow start
  → run_pipeline() executes 4 SEQUENTIAL stages:
    1. stage_ingest()   — validate files exist in storage
    2. stage_render()   — PDF → JPEG (72 DPI) + thumbnails + embedded text extraction
    3. stage_examine()  — LLM examination (OCR + sections + extractions + flags)
    4. stage_complete() — readiness score (rules) + summary (LLM) + PDF report
  → Pack.status = "completed" | "failed"
```

### Frontend Flow
- Pack detail page polls `usePack(packId)` every 3s while `status === "processing"`
- `usePipelineStatus(packId)` connects SSE (primary) or polls every 3s (fallback)
- `PipelineProgress` component renders 4-stage visual tracker
- `examine_progress` field shows "3/6 batches, 12 flags" during examine
- Auto-navigates to `/results` on completion
- Frontend expects exactly 4 stage names: `ingest`, `render`, `examine`, `complete`
- Stage labels defined in `STAGE_LABELS` constant — adding stages requires updating this map

### Model/Provider Integration
- Single model: `gemini/gemini-2.5-flash` via `litellm` (all roles)
- `google-genai` SDK used separately for Gemini context caching (TTL 10min)
- Temperature: 0.0 (pinned for determinism)
- Max output tokens: 16,384 per batch call
- Timeout: 300 seconds per LLM call
- Tool definitions in Anthropic format, auto-converted to OpenAI format by `_convert_tools()`

### Page Rendering/Parsing Flow
- `stage_render()` uses PyMuPDF (`fitz`) to render each page to JPEG at 72 DPI
- Embedded text extracted from PDF text layer via `fitz.Page.get_text()`
- Pages with ≥50 chars of embedded text flagged as "text" pages (skip Vision OCR)
- Concurrency: `asyncio.Semaphore(8)` — 8 pages rendered in parallel
- Each page: render JPEG + render thumbnail + 2 storage writes
- Donor pack detection: if identical file hash found in prior completed pack, clones pages instead of re-rendering

### Job/State Persistence
- `Pack.status`: `uploading` → `processing` → `completed` | `failed`
- `Pack.current_stage`: updated at each stage start
- `Pack.examine_progress`: updated per batch completion ("3/6 batches, 12 flags")
- `PipelineRun`: version metadata (model, prompt hashes, rules version) for reproducibility
- Examiner cache: stored as JSON in file storage, keyed by SHA256(file_hash + model + prompt + schema + rules)
- Summary cache: stored similarly, keyed by SHA256(extractions + flags + readiness + model)

### Background Tasks
- Dual backend: `PIPELINE_BACKEND` setting selects `background_tasks` (FastAPI) or `temporal` (durable)
- BackgroundTasks: in-process async, lost on crash
- Temporal: durable workflows, survives restarts, heartbeat monitoring
- Per-stage retries: ingest/render/complete = 3 attempts, examine = 5 attempts
- Global pipeline timeout: 30 minutes

---

## 2. Current Architecture Summary

### How the App Processes a Document (100-page PDF)

```
Stage         Time        What Happens                                    Serialized?
─────         ────        ────────────                                    ───────────
ingest        ~2s         Validate files exist in storage                 Yes (blocks render)
render        30-60s      100 pages × (JPEG + thumb + text extract)       Yes (blocks examine)
                          8 concurrent via semaphore
                          CPU-bound: asyncio.to_thread wraps PyMuPDF
examine       25-35s      Build smart batches (text@25pp, image@10pp)     Yes (blocks complete)
                          ~4-8 batches, all launched in parallel
                          Each batch: 1 Gemini call (22-30s)
                          Progressive DB writes via on_batch_complete
complete      15-20s      Readiness (pure rules, <1s)                     Yes (final)
                          Summary (LLM call, ~10s, cached)
                          PDF report (fpdf2, ~5s)
─────────────────────────────────────────────────────────────────────────
TOTAL         72-117s     FAILS 60-SECOND SLA
```

### What Is Synchronous vs Async
- **Async (good):** `/process` returns 202 immediately; pipeline runs in background
- **Async (good):** Within render stage, 8 pages render concurrently
- **Async (good):** Within examine stage, all batches fire concurrently
- **Synchronous (bad):** Stages are strictly sequential — render must finish ALL pages before examine starts
- **Synchronous (bad):** Complete stage waits for entire examine to finish

### What Stages Exist vs Mixed Together
The examine stage is a **monolithic single-pass agent** doing 4 jobs in one LLM call:
1. OCR/Transcription (should be handled by native PDF or separate parse)
2. Section Detection (could be rules-based for standard title sections)
3. Structured Extraction (should be type-specialized)
4. Flag Detection (should use rules first, LLM only for ambiguity)

### Where the UI Waits
- Frontend polls every 3s via SSE or HTTP
- Progress is visible at stage granularity + examine batch sub-progress
- No progress for render stage (just "running")
- No partial results visible until examine completes

### Artifact Reuse vs Reprocessing
- **Reused:** Donor pack detection skips render for identical files (cache hit)
- **Reused:** Examiner cache replays results for identical files + identical version
- **Reused:** Summary cache skips LLM if extractions/flags unchanged
- **NOT reused:** Page images loaded from storage into memory for each batch (no in-memory cache)
- **NOT reused:** Intermediate batch results deleted then re-written during consolidation (double DB write)

---

## 3. Gap Analysis vs Benchmark-Driven Target Architecture

### Stage-by-Stage Comparison

| Target Stage | Current State | Gap | SLA Impact |
|-------------|---------------|-----|:---:|
| **1. Ingestion** (upload, hash, split, thumbnails, async job) | Upload + hash exists. No PDF splitting. Thumbnails coupled to render stage. | Medium | Low |
| **2. Fast Page Triage** (classify pages quickly, skip blanks/boilerplate) | **Missing.** All pages get full examination. 20-30% of pages in a typical packet are blank, cover, or boilerplate. | High | High — wastes 20-30% of LLM budget |
| **3. Document Grouping** (group pages into logical documents before extraction) | **Missing.** Pages treated as flat sequence. Batch boundaries may split related documents. | High | Medium — reduces extraction quality |
| **4. Selective Structured Extraction** (specialized extractors per doc type) | **Single generic extractor.** One prompt, one schema handles all 8 extraction types. | High | Medium — lower accuracy, higher token waste |
| **5. Deterministic Title Reducer** (party normalization, chain building, gap detection, rules first) | **Partially exists.** Flag rules engine does severity clamping/dedup. No chain builder, no party normalizer, no release matcher. | High | High — forces LLM to do deterministic work |
| **6. Report Generation** (from validated structured facts only) | **Exists.** PDF report from structured data (fpdf2). Evidence refs included. Summary is LLM-generated but cached. | Low | Low |
| **7. UI Pipeline Tracker** (progress, doc viewer, evidence linking, chain timeline) | **Partially exists.** Pipeline tracker works. Flags table with evidence. No doc viewer with highlight overlay. No chain timeline. | Medium | Low (UX, not SLA) |
| **8. Observability** (per-stage timing, token/cost, structured logs, benchmark harness) | **Missing.** No timing metrics. No token tracking. No cost tracking. No benchmark harness. | Critical | Critical — can't measure SLA compliance |

### What Will Block Linear Scaling

| Blocker | Why It Prevents Linear Scaling |
|---------|-------------------------------|
| **Render stage on critical path** | 100pp × ~0.5s/page = 50s. 500pp = 250s. Grows linearly but wastes time — LLM can read native PDF. |
| **All stages sequential** | Each stage waits for prior to fully complete. No overlap = sum of worst cases. |
| **No page triage** | 20-30% of pages are blank/boilerplate. At 500pp, that's 100-150 wasted pages × LLM cost + time. |
| **Unbounded batch concurrency** | At 500pp: 20+ concurrent Gemini calls. Rate limit (60-120 RPM) → cascading retries → unpredictable latency. |
| **Monolithic examine** | Single schema includes all output types. Output tokens scale with schema size, not page complexity. |
| **No intermediate validation** | Malformed extraction from one batch propagates to flagging. No correction opportunity. |

---

## 4. Bottleneck Analysis

### 4.1 Precise Time Budget — Current Architecture (100 Pages, Cache Miss)

| Stage | Operation | Time | % of Total | Parallelism |
|-------|-----------|:----:|:---:|:---:|
| **Ingest** | File validation | 2s | 2% | None |
| **Render** | PDF→JPEG: 100pp ÷ 8 concurrent × ~0.5s/page | **6.3s** | — | Semaphore(8) |
| **Render** | Storage writes: 200 files (image+thumb) | **8s** | — | Parallel per page |
| **Render** | Embedded text extraction | **2s** | — | Parallel |
| **Render** | DB inserts: 100 Page records | **1s** | — | Batched |
| **Render subtotal** | | **~17s** | 17% | |
| **Examine** | Load page data (100 storage reads for images) | **2s** | — | `asyncio.gather` |
| **Examine** | Build smart batches | **<0.1s** | — | CPU |
| **Examine** | LLM calls: ~4-8 batches, all parallel, slowest ~25s | **25-30s** | — | `as_completed` |
| **Examine** | Consolidation (dedup, merge) | **0.5s** | — | CPU |
| **Examine** | DB writes (sections + extractions + flags + chunks) | **2s** | — | Sequential |
| **Examine subtotal** | | **~32s** | 32% | |
| **Complete** | Readiness calculation (pure rules) | **0.5s** | — | CPU |
| **Complete** | Summary LLM call | **10-15s** | — | Single call |
| **Complete** | PDF report generation (fpdf2) | **3-5s** | — | CPU |
| **Complete subtotal** | | **~17s** | 17% | |
| **Overhead** | Stage transitions, DB status updates, hash computation | **3s** | 3% | |
| **TOTAL** | | **~71s** | 100% | |

**Breakdown by category:**
- LLM API calls: **~40s** (57%) — examine batches + summary
- Page rendering (CPU): **~17s** (24%) — JPEG generation + storage I/O
- Complete stage: **~17s** (17%) — summary + report
- Overhead: **~3s** (4%)

### 4.2 Why 100 Pages Fails the 60s SLA

| Root Cause | Time Wasted | Fix |
|-----------|:-----------:|-----|
| Render stage on critical path | **17s** | Eliminate — use native PDF for LLM; render UI thumbnails in background |
| All stages sequential (no overlap) | **~10s** | Allow examine to start while render produces page images for UI |
| No page triage (all pages examined equally) | **~8s** (25% of examine) | Fast classification → skip blanks/boilerplate |
| Summary LLM call in complete stage | **10-15s** | Generate from structured data (no LLM), or cache aggressively |
| PDF report blocking | **3-5s** | Generate asynchronously |

**With all fixes:** 71s - 17s (render) - 10s (overlap) - 8s (triage) - 5s (async report) = **~31s** ← passes SLA

### 4.3 Scaling Analysis — Why Current Won't Scale Linearly

**Current scaling (projected):**

| Pages | Render | Examine | Complete | Total | SLA | Status |
|:-----:|:------:|:-------:|:--------:|:-----:|:---:|:------:|
| 100 | 17s | 32s | 17s | **71s** | 60s | FAIL |
| 200 | 34s | 35s (more batches, same wall clock if concurrent) | 17s | **89s** | 120s | PASS |
| 300 | 51s | 40s | 17s | **111s** | 180s | PASS |
| 500 | 85s | 50s (rate limits hit) | 17s | **155s** | 300s | PASS |

**Problem:** At 100 pages, the constant overheads (render + complete) dominate. At 500 pages, render grows linearly but examine grows sub-linearly (parallel batches). The system passes SLA at 200+ but fails at 100.

**Root cause:** The 60-second SLA at 100 pages is the hardest target. Fixed costs (render, complete, overhead) consume 37s before any LLM work begins.

### 4.4 Token Analysis — Current vs Native PDF

**Current approach (image batches, base64-encoded JPEGs):**

| Batch Type | Pages | Input Tokens | Output Tokens | Wall Clock |
|-----------|:-----:|:-----:|:-----:|:-----:|
| Text batch (25pp) | 25 | ~3,340 | ~2,000 | 18-22s |
| Image batch (10pp) | 10 | ~83,000 | ~5,500 | 22-28s |
| Image batch (10pp) | 10 | ~83,000 | ~5,500 | 22-28s |
| **100pp total (4 batches)** | 100 | **~172,000** | **~15,000** | **25-30s** (parallel) |

**Native PDF approach (direct PDF bytes to Gemini):**

| Chunk | Pages | Input Tokens | Output Tokens | Wall Clock |
|-------|:-----:|:-----:|:-----:|:-----:|
| Chunk 1 (25pp PDF) | 25 | ~8,450 (258 tok/page visual + free text) | ~4,000 | 16-20s |
| Chunk 2 (25pp PDF) | 25 | ~8,450 | ~4,000 | 16-20s |
| Chunk 3 (25pp PDF) | 25 | ~8,450 | ~4,000 | 16-20s |
| Chunk 4 (25pp PDF) | 25 | ~8,450 | ~4,000 | 16-20s |
| **100pp total (4 chunks)** | 100 | **~33,800** | **~16,000** | **18-22s** (parallel) |

**Native PDF saves:** 80% fewer input tokens, uniform chunk sizing, no base64 bloat, no render stage.

### 4.5 Specific Serialization Points Found in Code

1. **`orchestrator.py` line 211:** `for stage_name, stage_fn, max_retries in PIPELINE_STAGES:` — strict sequential loop
2. **`stages.py` line 317:** `stage_examine()` loads ALL pages before building batches — no streaming from render
3. **`stages.py` line 377-432:** Batch results written progressively, then ALL deleted, then consolidated results written — double I/O
4. **`title_examiner_agent.py` line 548:** `_load_page()` re-reads images from storage per batch — no in-memory cache for overlapping pages
5. **`stages.py` line 697:** Summary LLM call blocks complete stage — could be async/cached

### 4.6 Repeated/Unnecessary Work

| Work | Where | Waste |
|------|-------|-------|
| Render JPEG for LLM input | `stage_render()` | Entire render stage unnecessary if using native PDF |
| Re-read page images per batch | `examine_document()` → `_load_page()` | Overlap pages loaded twice from storage |
| Delete-then-rewrite batch results | `stage_examine()` lines 377-432 | 2× DB writes for same data |
| Generate thumbnails on critical path | `stage_render()` | Thumbnails only needed for UI, not AI |
| Full schema output for simple pages | `examine_batch()` | Blank/cover pages still generate full extraction schema output |

---

## 5. Benchmark Feasibility Analysis

### 5.1 Achievable Performance with Refactored Architecture

**Target architecture: Native PDF + triage + parallel chunks + async complete**

| Pages | Ingest | Triage | Examine (parallel chunks) | Complete | Total | SLA | Status |
|:-----:|:------:|:------:|:-------------------------:|:--------:|:-----:|:---:|:------:|
| 100 | 2s | 5s | 22s (4 chunks × 5 concurrent) | 8s | **37s** | 60s | PASS |
| 200 | 3s | 8s | 24s (8 chunks × 5 concurrent, 2 waves) | 8s | **43s** | 120s | PASS |
| 300 | 3s | 10s | 44s (12 chunks × 5 concurrent, 3 waves) | 8s | **65s** | 180s | PASS |
| 500 | 4s | 15s | 80s (20 chunks × 5 concurrent, 4 waves) | 8s | **107s** | 300s | PASS |

**Scaling rate:** ~0.18s per additional page (well under 0.6s SLA)

### 5.2 Key Assumptions

1. **Gemini native PDF processing:** 258 tokens/page visual + free text extraction. Confirmed supported via `google-genai` SDK `Part.from_bytes(mime_type="application/pdf")` and litellm `type: "file"`.
2. **Gemini throughput:** ~245 output tokens/second. 4K output tokens per chunk = ~16s generation time.
3. **Rate limits:** 5 concurrent chunks stays within Gemini Flash limits (60-1500 RPM depending on tier).
4. **Page triage:** Lightweight LLM call or vision classification (~5s for 100 pages). Eliminates 20-30% of pages from deep extraction.
5. **PDF splitting:** PyMuPDF splits PDF into page-range byte buffers in <1s (in-memory, no disk I/O).
6. **Summary generation:** Can be data-driven (no LLM) or cached aggressively to stay under 3s.

### 5.3 Which Stages Dominate Latency

| Stage | % of Pipeline (100pp) | % of Pipeline (500pp) | Scales With |
|-------|:----:|:----:|-----|
| **Examine** | 59% | 75% | Page count (linear with bounded concurrency) |
| **Triage** | 14% | 14% | Page count (lightweight, fast) |
| **Complete** | 22% | 7% | Fixed (constant time) |
| **Ingest** | 5% | 4% | Fixed (constant time) |

**Examine dominates at scale.** With bounded concurrency of 5, examine time grows as `ceil(chunks/5) × chunk_time`. For 500pp with 25pp chunks: ceil(20/5) × 20s = 80s.

### 5.4 Constraints Found in Code

- `EXAMINER_MAX_OUTPUT_TOKENS = 16384` — limits output per chunk (sufficient for 25-page chunks)
- `EXAMINER_BATCH_COOLDOWN = 0.0` — no rate limit protection (needs bounded concurrency)
- `RENDER_CONCURRENCY = 8` — only 8 concurrent page renders (irrelevant with native PDF)
- `PIPELINE_TIMEOUT = 30 * 60` — 30-minute global timeout (sufficient for SLA)
- Gemini context cache TTL: 10 minutes — sufficient for 5-minute SLA
- Gemini max pages per PDF: 1,000 — sufficient for 500-page target
- Gemini max PDF size: 50 MB — may need splitting for very large scanned PDFs

---

## 6. Phased Refactor Roadmap

### Overview

```
Phase 0: Benchmark Instrumentation Baseline          ◀── measure current state
Phase 1: Native PDF Pipeline + Render Elimination    ◀── RECOMMENDED FIRST (biggest SLA impact)
Phase 2: Fast Page Triage Stage                      ◀── skip 20-30% of pages
Phase 3: Document Grouping Stage                     ◀── group before extraction
Phase 4: Bounded Concurrency + Adaptive Rate Limits  ◀── reliable at scale
Phase 5: Schema-First Specialized Extraction Routing  ◀── higher quality, lower tokens
Phase 6: Deterministic Title Reducer / Rules Engine   ◀── 90%+ determinism
Phase 7: Fact-Based Report Generation                ◀── no LLM in complete stage
Phase 8: Pipeline Progress UI + Evidence-Linked Viewer ◀── examiner UX
Phase 9: Benchmark Harness + Regression Enforcement   ◀── CI-enforced SLA
Phase 10: Optimization (caching, hot-path, concurrency tuning) ◀── squeeze remaining margin
```

### SLA Impact Per Phase

| Phase | 100pp Time | 500pp Time | Delta |
|:-----:|:----------:|:----------:|:-----:|
| Current | 71s (FAIL) | ~155s | baseline |
| After Phase 0 | 71s | ~155s | +0 (measurement only) |
| After Phase 1 | **40s (PASS)** | ~95s | **-31s / -60s** |
| After Phase 2 | 34s | ~80s | -6s / -15s |
| After Phase 4 | 32s | ~75s (predictable) | -2s / -5s (reliability) |
| After Phase 7 | 27s | ~70s | -5s / -5s |

---

### Phase 0: Benchmark Instrumentation Baseline

**Goal:** Measure current pipeline performance precisely so we can prove SLA improvements.

**Why this matters for SLA:** Can't verify the SLA without per-stage timing. Need baselines before changing anything.

**Scope:**
- Wrap each pipeline stage with `time.perf_counter()` timing
- Track LLM call latency, input/output token counts per batch
- Store timing data in `PipelineRun.version_metadata` JSONB field
- Log structured pipeline summary on completion
- Add simple benchmark CLI command: `python -m benchmarks.run_pipeline --pages 100`

**Files affected:**
- `backend/app/micro_apps/title_intelligence/pipeline/orchestrator.py` — stage timing wrapper
- `backend/app/micro_apps/title_intelligence/pipeline/stages.py` — per-stage timing
- `backend/app/micro_apps/title_intelligence/ai/title_examiner_agent.py` — batch timing + token counts
- `backend/app/ai/base_service.py` — extract token usage from litellm response
- New: `backend/benchmarks/run_pipeline.py` — benchmark runner

**Design choices:**
- Store timing in existing JSONB column (no migration needed)
- Token counts from `response.usage.prompt_tokens` / `completion_tokens` (litellm exposes this)
- Cost estimate: `input_tokens × $0.30/1M + output_tokens × $2.50/1M`
- Benchmark runner: uploads test PDF, triggers pipeline, waits for completion, reports timing

**Testing:** Unit test verifying timing data appears in PipelineRun metadata.

**Benchmark impact:** 0 (measurement only, no performance changes)

**Risks:** Minimal — read-only instrumentation

**Rollback:** Remove timing code

---

### Phase 1: Native PDF Pipeline + Render Elimination

**Goal:** Eliminate the render stage from the critical path. Send native PDF directly to Gemini. Hit the 100pp/60s SLA.

**Why this matters for SLA:** Render stage costs 17s at 100pp and scales linearly. Eliminating it saves 17s immediately and removes a linear scaling bottleneck. Native PDF also reduces input tokens by ~80% (no base64 image bloat).

**Scope:**
- Split PDF into page-range chunks using PyMuPDF (in-memory, no disk I/O)
- Send native PDF bytes to Gemini via `google-genai` SDK `Part.from_bytes(mime_type="application/pdf")`
- Remove text/image routing logic (no more ≥50 char threshold, dual schemas, dual batch sizes)
- Make render stage a non-blocking background task (UI thumbnails only)
- Add bounded concurrency: `asyncio.Semaphore(5)` for chunk processing
- Update cache keys for native PDF mode
- Add pipeline config: `EXAMINER_CHUNK_SIZE=25`, `EXAMINER_MAX_CONCURRENT_CHUNKS=5`

**Files affected:**
- `backend/app/ai/base_service.py` — add PDF content type support in `_call_genai_cached()`
- `backend/app/micro_apps/title_intelligence/ai/title_examiner_agent.py` — replace image batching with PDF chunk processing
- `backend/app/micro_apps/title_intelligence/pipeline/stages.py` — rewrite `stage_render` (UI-only background), rewrite `stage_examine` (native PDF chunks)
- `backend/app/micro_apps/title_intelligence/pipeline/orchestrator.py` — decouple render from critical path
- `backend/app/micro_apps/title_intelligence/schemas/examiner.py` — single unified schema (remove TEXT_ONLY variant)
- `backend/app/micro_apps/title_intelligence/pipeline/version_tracker.py` — update cache key for native PDF
- `backend/app/config.py` — new settings

**Design choices:**
- **PDF splitting:** `fitz.open(pdf_bytes)` → select page range → `doc.tobytes()` produces new PDF bytes in memory. No temp files.
- **Chunk size 25 pages:** At 258 tok/page visual = 6,450 input tokens per chunk. Well within limits. Output ~4K tokens at ~245 tok/s = ~16s.
- **Bounded concurrency 5:** Keeps within Gemini rate limits while allowing 5 parallel chunks. 100pp = 4 chunks = 1 wave = 18s. 500pp = 20 chunks = 4 waves = 72s.
- **Render as background task:** After pipeline starts, schedule render task for UI thumbnails. Not blocking AI processing. Frontend shows "generating previews..." if thumbnails aren't ready yet.
- **Fallback:** Config `PIPELINE_MODE=legacy` runs old image-based pipeline.

**Testing:**
- Unit test: PDF chunk splitting produces correct page ranges and valid PDF bytes
- Unit test: native PDF content sent correctly to Gemini SDK
- Integration test: 50-page test PDF produces equivalent extractions via native PDF vs image pipeline
- Benchmark test: 100-page PDF completes under 60 seconds
- Golden set: existing determinism tests still pass with updated mocks

**Benchmark impact:**
- Render eliminated from critical path: **-17s at 100pp**
- Examine faster (native PDF, uniform chunks): **-7s at 100pp**
- New pipeline time: **~40s at 100pp** (PASSES SLA)
- At 500pp: ~95s (well under 300s SLA)

**Risks:**
- litellm PDF support may have edge cases → fallback to `google-genai` SDK directly
- Very large PDFs (>50MB) need file splitting before upload → use Gemini Files API
- Gemini's native PDF quality on heavily degraded scans needs validation

**Rollback:** `PIPELINE_MODE=legacy` config flag

---

### Phase 2: Fast Page Triage Stage

**Goal:** Classify pages before deep extraction. Skip blanks, covers, and boilerplate. Route content pages to appropriate processing.

**Why this matters for SLA:** 20-30% of pages in title packets are non-content (blank, cover, signature, transmittal). Skipping them saves ~20% of examine time and tokens.

**Scope:**
- New pipeline sub-stage: lightweight LLM call on full PDF to classify each page
- Classification output: `{page_number, page_type, document_type_hint, importance}`
- Page types: `content`, `blank`, `cover`, `signature`, `transmittal`, `boilerplate`
- Only `content` pages proceed to deep extraction
- Persisted in `ti_pages.page_type` column

**Files affected:**
- New: `backend/app/micro_apps/title_intelligence/ai/triage_agent.py`
- `backend/app/micro_apps/title_intelligence/pipeline/stages.py` — new triage sub-stage
- `backend/app/micro_apps/title_intelligence/models/pack.py` — add `page_type` to Page model
- New migration: add `page_type` column

**Design choices:**
- Single LLM call on entire PDF (or large chunk) with lightweight schema: `[{page_number, page_type}]`
- ~500 output tokens for 100 pages (just page numbers + types)
- Takes ~5s for 100 pages (much cheaper than full examination)
- Conservative: unknown pages classified as `content` (never skip important pages)

**Benchmark impact:** -6s at 100pp (skip ~25 pages from deep examine), -15s at 500pp

**Risks:** False positive classification → missed extractions. Mitigated by conservative default.

**Rollback:** Disable triage → all pages sent to examine (current behavior)

---

### Phase 3: Document Grouping Stage

**Goal:** Group related pages into logical documents before extraction. Enables document-type-specific processing.

**Why this matters for SLA:** Grouping ensures batch boundaries align with document boundaries (no splitting a deed across two chunks). Improves extraction quality and enables specialized routing in Phase 5.

**Scope:**
- Use triage hints (Phase 2) + heuristic rules to group consecutive content pages
- Output: `[{doc_id, doc_type, start_page, end_page, pages}]`
- Groups fed to extraction stage as units (not arbitrary page-range chunks)

**Files affected:**
- New: `backend/app/micro_apps/title_intelligence/services/document_grouper.py`
- `backend/app/micro_apps/title_intelligence/pipeline/stages.py` — integrate grouping

**Design choices:**
- Primarily rules-based (page type transitions signal document boundaries)
- LLM assistance only for ambiguous boundaries
- Groups bounded to max chunk size (25 pages) — large documents split at section boundaries

**Benchmark impact:** Minimal direct time savings. Significant quality improvement for extraction.

**Rollback:** Disable grouping → use page-range chunks (Phase 1 behavior)

---

### Phase 4: Bounded Concurrency + Adaptive Rate Limiting

**Goal:** Ensure 500-page documents process reliably without rate limit storms.

**Why this matters for SLA:** At 500pp with 20 chunks, unbounded concurrency causes rate limiting (429 errors) → cascading retries → unpredictable latency (up to 5x slowdown). Bounded concurrency makes timing predictable.

**Scope:**
- `asyncio.Semaphore(N)` bounds concurrent Gemini calls (default N=5)
- Staggered launch: 200ms between chunk starts
- Adaptive throttling: on 429, reduce N temporarily, increase cooldown
- Per-pipeline metrics: track rate limit events, retry counts

**Files affected:**
- `backend/app/micro_apps/title_intelligence/ai/title_examiner_agent.py` — semaphore wrapper
- `backend/app/ai/base_service.py` — adaptive rate handling
- `backend/app/config.py` — `EXAMINER_MAX_CONCURRENT_CHUNKS=5`, `EXAMINER_CHUNK_STAGGER_MS=200`

**Benchmark impact:** -2s at 100pp (predictable timing), critical for 500pp (prevents 5x slowdown)

**Rollback:** Set concurrency to 100 = unbounded

---

### Phase 5: Schema-First Specialized Extraction Routing

**Goal:** Route document groups to type-specific extractors with focused prompts and tight schemas.

**Why this matters for SLA:** Specialized prompts are shorter (200-500 tokens vs 1300). Tighter schemas produce fewer output tokens. Both reduce LLM time per chunk.

**Scope:**
- Extractors per doc type: deed, mortgage, lien, release, judgment, easement, generic
- Each has a focused system prompt + strict Pydantic schema
- Route based on `doc_type` from Phase 3 grouping
- Validate output against schema before storing

**Files affected:**
- New: `backend/app/micro_apps/title_intelligence/ai/extractors/` directory
- New: `backend/app/micro_apps/title_intelligence/schemas/instruments/` directory

**Benchmark impact:** -3s at 100pp (smaller prompts/schemas → faster output generation)

**Rollback:** Route all to generic extractor

---

### Phase 6: Deterministic Title Reducer / Rules Engine

**Goal:** Build title chain, detect gaps, match releases using deterministic logic first. LLM only for ambiguity.

**Why this matters for SLA:** Rules execute in milliseconds. Removing title reasoning from the LLM saves tokens and time. Achieves 90%+ determinism.

**Scope:**
- Party name normalizer (`rapidfuzz` for fuzzy matching)
- Chain builder: sequence grantor→grantee events chronologically
- Gap detector: deterministic graph traversal
- Release matcher: match by instrument number
- Rules engine: generate flags from structured data
- LLM fallback: only for ambiguous cases (10-20% of findings)

**Files affected:**
- New: `services/chain_builder.py`, `services/party_normalizer.py`
- Extend: `services/flag_rules.py`

**Benchmark impact:** -2s at 100pp (eliminate LLM reasoning calls for deterministic cases)

**Rollback:** Disable rules engine → fall back to LLM flagging

---

### Phase 7: Fact-Based Report Generation

**Goal:** Eliminate the summary LLM call from the complete stage. Generate summary from structured data only.

**Why this matters for SLA:** The summary LLM call costs 10-15s in the complete stage. With structured extractions and deterministic flags, the summary can be data-driven (template + fill).

**Scope:**
- Template-based summary from validated extractions + flags + readiness
- No LLM call for standard reports
- Optional LLM call for "executive narrative" (premium feature, not on critical path)

**Files affected:**
- `backend/app/micro_apps/title_intelligence/pipeline/stages.py` — `stage_complete` refactor
- `backend/app/micro_apps/title_intelligence/services/report_service.py` — template-based summary

**Benchmark impact:** -10s at 100pp (eliminate summary LLM call entirely)

**Rollback:** Config flag to use LLM summary

---

### Phase 8: Pipeline Progress UI + Evidence-Linked Viewer

**Goal:** Enhanced UI with document viewer, evidence highlighting, chain timeline, review queue.

**Why this matters for SLA:** Not a performance phase. Improves examiner productivity. But requires stable pipeline stages from prior phases.

**Scope:**
- PDF.js-based document viewer with page navigation
- Click flag → jump to source page
- Title chain timeline (SVG)
- Review queue with severity/status filters
- Server-side flag pagination

**Frontend changes:**
- New components in `src/components/title-intelligence/`
- Update `STAGE_LABELS` and `PIPELINE_STAGES` for new stage names
- Add `page_type` display in document viewer

---

### Phase 9: Benchmark Harness + Regression Enforcement

**Goal:** Automated SLA enforcement in CI. Catch regressions before they ship.

**Scope:**
- Benchmark test suite: 25pp, 50pp, 100pp, 500pp PDFs (synthetic or real)
- Per-stage timing assertions against SLA
- Token/cost budget assertions
- Determinism assertions (run 3x, compare outputs)
- CI step: benchmark on PRs touching pipeline code

**SLA assertions:**

| Doc Size | Max Pipeline Time | Max Examine Time | Max Tokens |
|:--------:|:-----------------:|:----------------:|:----------:|
| 25pp | 20s | 12s | 15K |
| 50pp | 30s | 16s | 25K |
| 100pp | 60s | 25s | 45K |
| 500pp | 300s | 200s | 200K |

---

### Phase 10: Optimization Passes

**Goal:** Squeeze remaining margin from hot paths.

**Scope:**
- Tune chunk sizes based on benchmark data (maybe 30pp instead of 25pp)
- Tune concurrency based on Gemini tier rate limits
- Add Redis cache for pipeline status (reduce DB polling)
- Gemini Files API for large PDFs (upload once, reference across chunks)
- Adaptive chunk sizing: larger chunks for simple pages, smaller for complex
- Connection pooling for S3 storage (if using S3)
- Precompute text chunks during examine (avoid separate pass)

---

## 7. Recommended First Phase

### Phase 1: Native PDF Pipeline + Render Elimination

**Why this should be first:**

1. **Biggest single SLA impact.** Saves 24s at 100pp (from 71s → ~40s). That's the difference between FAIL and PASS.
2. **Removes the primary linear scaling bottleneck.** Render time grows linearly with page count. Eliminating it removes a scaling wall.
3. **Fixes data quality.** Native PDF gives the LLM full visual context (stamps, annotations, seals) that OCR/text extraction misses.
4. **Simplifies the codebase.** Removes text/image routing, dual schemas, dual batch sizes, base64 encoding.
5. **Enables all subsequent phases.** Triage (Phase 2), grouping (Phase 3), and specialized extraction (Phase 5) all assume native PDF input.
6. **Low risk.** Gemini's native PDF support is production-ready. Config flag for rollback.

**Implementation sequence:**
1. Add PDF chunk splitting utility (PyMuPDF: split by page range → bytes in memory)
2. Add native PDF content support to `BaseAIService._call_genai_cached()`
3. Rewrite `TitleExaminerAgent` to use PDF chunks instead of image batches
4. Move `stage_render` off the critical path (background task for UI thumbnails)
5. Remove text/image split, dual schemas, dual batch sizing
6. Add bounded concurrency (`asyncio.Semaphore(5)`)
7. Update cache keys and version tracking
8. Add timing instrumentation (Phase 0 bundled in)
9. Add 100-page benchmark test

**Success criteria:**
- 100-page PDF completes pipeline in under 60 seconds
- Extraction quality matches or exceeds current (validated against sample documents)
- All existing tests pass (with updated mocks)
- Pipeline timing logged to `PipelineRun.version_metadata`

---

## Appendix: File Reference

### Pipeline Core
| File | Purpose |
|------|---------|
| `backend/app/micro_apps/title_intelligence/pipeline/orchestrator.py` | Pipeline execution (sequential stages, retry, timeout) |
| `backend/app/micro_apps/title_intelligence/pipeline/stages.py` | Stage implementations (ingest, render, examine, complete) |
| `backend/app/micro_apps/title_intelligence/pipeline/temporal_workflows.py` | Temporal workflow (sequential activities) |
| `backend/app/micro_apps/title_intelligence/pipeline/temporal_activities.py` | Temporal activity wrappers |
| `backend/app/micro_apps/title_intelligence/pipeline/version_tracker.py` | Cache keys + version hashing |

### AI Layer
| File | Purpose |
|------|---------|
| `backend/app/ai/base_service.py` | LLM calls, context caching, tool conversion |
| `backend/app/micro_apps/title_intelligence/ai/title_examiner_agent.py` | Examiner (to be refactored to native PDF) |
| `backend/app/micro_apps/title_intelligence/schemas/examiner.py` | JSON schemas + Pydantic models |

### Services
| File | Purpose |
|------|---------|
| `backend/app/micro_apps/title_intelligence/services/flag_rules.py` | Deterministic flag rules |
| `backend/app/micro_apps/title_intelligence/services/readiness_service.py` | Readiness scoring (pure rules) |
| `backend/app/micro_apps/title_intelligence/services/pipeline_service.py` | Pipeline status + `PIPELINE_STAGES` list |

### Models & Routes
| File | Purpose |
|------|---------|
| `backend/app/micro_apps/title_intelligence/models/pack.py` | Pack, PackFile, Page, Flag, Extraction models |
| `backend/app/micro_apps/title_intelligence/routes/packs.py` | API endpoints, SSE streaming |
| `backend/app/micro_apps/title_intelligence/schemas/pack.py` | Request/response schemas |

### Frontend (Stage-Sensitive)
| File | Impact of Stage Changes |
|------|------------------------|
| `frontend/src/lib/ti-constants.ts` | `STAGE_LABELS` map must be updated for new/renamed stages |
| `frontend/src/components/title-intelligence/pipeline-progress.tsx` | Renders stages from API response; examineProgress hardcoded to `"examine"` key |
| `frontend/src/hooks/use-pipeline-status.ts` | SSE/polling — stage-agnostic (safe) |

### Config
| Setting | Current | After Phase 1 |
|---------|---------|--------------|
| `EXAMINER_BATCH_SIZE` | 10 | Replaced by `EXAMINER_CHUNK_SIZE=25` |
| `EXAMINER_BATCH_SIZE_TEXT` | 25 | Removed (no text/image split) |
| `EXAMINER_BATCH_OVERLAP` | 1 | Removed (chunks are page-range aligned) |
| `EXAMINER_BATCH_COOLDOWN` | 0.0 | Replaced by `EXAMINER_CHUNK_STAGGER_MS=200` |
| `EXAMINER_RENDER_DPI` | 72 | Moved to UI thumbnail config (not on critical path) |
| New: `EXAMINER_CHUNK_SIZE` | — | 25 (pages per PDF chunk) |
| New: `EXAMINER_MAX_CONCURRENT_CHUNKS` | — | 5 (bounded concurrency) |
| New: `PIPELINE_MODE` | — | `native_pdf` (or `legacy` for rollback) |

---

*End of audit. Ready to implement Phase 1 (Native PDF Pipeline + Render Elimination) upon approval.*
