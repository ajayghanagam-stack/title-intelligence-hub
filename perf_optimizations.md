# TI Pipeline Performance — 250 Pages in Under 2 Minutes

## Context

Current performance for first-time uploads (no cache hits):
- 51 pages: ~3 min
- 175 pages: ~15 min
- 250 pages: ~30 min

**Target**: 250 pages in ~2 minutes.

## Where Time Is Spent Today (250-page document)

| Stage | Current Time | Root Cause |
|-------|-------------|------------|
| **Render** | 4-8 min | Sequential `get_pixmap()` per page — CPU-bound, zero parallelism |
| **OCR** | 5-15 min | Vision API: only 5 pages at a time (`OCR_BATCH_SIZE=5`), ~5-10s per call |
| **Ingestion Agent** | 5-8 min | 250 pages = ~875K chars > `MAX_TEXT_PER_CALL` (80K) → interactive mode → 12-13 sequential AI roundtrips × 20-30s each |
| **Risk Agent** | 3-5 min | Sequential tool-calling loop, limited to 10 steps |
| Index, Ingest, Complete | <15s | Not bottlenecks |

---

## Optimizations (3 changes, ordered by impact)

### 1. Parallel Page Rendering via ThreadPoolExecutor

**File**: `backend/app/micro_apps/title_intelligence/pipeline/stages.py` — `stage_render` (lines 208-270)

**Problem**: Pages render one-by-one in a `for` loop. PyMuPDF `get_pixmap()` is CPU-bound. 250 pages × ~50-200ms each = 4-8 minutes.

**Fix**: Render pages in parallel using a thread pool with 8 workers:
- Extract embedded text + render pixmap + convert to JPEG all inside `asyncio.to_thread()`
- Process all pages concurrently using `asyncio.gather()` with a semaphore (limit 8)
- Storage writes for image + thumbnail already async

**Expected gain**: 4-8 min → ~30-60s (8x speedup)

---

### 2. Increase OCR Concurrency

**File**: `backend/app/micro_apps/title_intelligence/pipeline/stages.py` — `stage_ocr` (line 24)

**Problem**: `OCR_BATCH_SIZE = 5` limits concurrent Vision API calls. For 50 pages needing OCR: 10 batches × 5-10s = 50-100s.

**Fix**: Increase `OCR_BATCH_SIZE` from 5 → 20.

Most title commitments are text-rich PDFs — the render stage already extracts embedded text and 80-100% of pages skip OCR entirely. For the remaining pages, 20 concurrent Vision calls finishes in 1-2 batches instead of 10.

**Expected gain**: OCR stage drops from ~100s to ~10-25s

---

### 3. Raise Prefetched Mode Threshold for Ingestion Agent

**File**: `backend/app/micro_apps/title_intelligence/ai/ingestion_agent.py` (line 28)

**Problem**: `MAX_TEXT_PER_CALL = 80,000` chars. A 250-page doc has ~750K-875K chars, so it's forced into **interactive mode** — 12-13 sequential `read_page_range` tool calls, each a full AI roundtrip (20-30s). Total: 5-8 minutes.

**Fix**: Raise `MAX_TEXT_PER_CALL` from 80,000 → 400,000 chars. Claude Haiku 4.5 supports a 200K token context window (~800K chars). A 250-page document fits comfortably in a single prefetched call.

- **Before**: 12-13 interactive roundtrips × 25s = 5-8 min
- **After**: 1 prefetched call with all text = 30-60s

Also raise `max_steps` from 10 → 20 (line 117) and in risk_agent.py as a safety net for very large documents that still exceed the threshold.

**Expected gain**: Ingestion drops from 5-8 min → ~30-60s

---

## Combined Impact Estimate

| Stage | Before | After | Change |
|-------|--------|-------|--------|
| Ingest | 1s | 1s | — |
| **Render** | **4-8 min** | **30-60s** | Parallel threads (8 workers) |
| **OCR** | **50-100s** | **0-25s** | Batch 20 + most pages have embedded text |
| Index | 2s | 2s | — |
| **Ingestion Agent** | **5-8 min** | **30-60s** | Prefetched mode (single AI call) |
| **Risk Agent** | **3-5 min** | **30-60s** | Fewer tool calls, higher step limit |
| Complete | 10s | 10s | — |
| **Total** | **~30 min** | **~2-3 min** | **~12x faster** |

---

## Files to Modify

1. **`backend/app/micro_apps/title_intelligence/pipeline/stages.py`**
   - `stage_render`: Parallel rendering with `asyncio.to_thread()` + `Semaphore(8)`
   - `OCR_BATCH_SIZE`: 5 → 20
   - Add `RENDER_CONCURRENCY = 8` constant

2. **`backend/app/micro_apps/title_intelligence/ai/ingestion_agent.py`**
   - `MAX_TEXT_PER_CALL`: 80,000 → 400,000 (line 28)
   - `max_steps`: 10 → 20 (line 117)

3. **`backend/app/micro_apps/title_intelligence/ai/risk_agent.py`**
   - `max_steps`: 10 → 20

4. **`backend/tests/title_intelligence/test_parallel_render.py`** (new)
   - Test that parallel render produces same pages as sequential
   - Test semaphore limits concurrency

---

## Verification

1. `cd backend && pytest` — full suite passes (no regressions)
2. Upload 250-page PDF on local dev → pipeline completes in ~2-3 min
3. Deploy to prod, upload same document → verify ~2 min completion
4. Check logs for page render timing and "Ingestion agent completed in N steps" (should be 2-4 steps, not 10+)
