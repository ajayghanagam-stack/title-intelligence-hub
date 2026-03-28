"""Fast page triage agent for classifying pages before deep extraction.

Sends the full PDF (or large chunks) to Gemini with a lightweight schema
to classify each page as content, blank, cover, signature, transmittal,
or boilerplate. Only 'content' pages proceed to the expensive examiner stage.

Typical cost: ~500 output tokens for 100 pages (~5s wall clock).
"""

import asyncio
import logging
import time
import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.ai.base_service import BaseAIService

logger = logging.getLogger(__name__)

# Valid page types — conservative: unknown defaults to "content"
VALID_PAGE_TYPES = frozenset({
    "content",
    "blank",
    "cover",
    "signature",
    "transmittal",
    "boilerplate",
})

# Valid document type hints for specialized extraction routing
VALID_DOC_TYPES = frozenset({
    "commitment",   # Title commitment schedules (A, B-I, B-II, C)
    "deed",         # Warranty, quitclaim, special warranty deeds
    "mortgage",     # Mortgages, deeds of trust
    "lien",         # Tax liens, mechanic's liens, judgments
    "release",      # Satisfactions, reconveyances, releases
    "easement",     # Easements, restrictions, CC&Rs
    "plat",         # Plat maps, surveys, legal descriptions
    "endorsement",  # Title insurance endorsements
    "generic",      # Unknown or mixed content
})

TRIAGE_SYSTEM_PROMPT = """\
You are a fast document page classifier for title commitment packages. \
Your job is to classify each page so that only meaningful content pages \
are sent for expensive deep examination, and to identify the document type \
for specialized extraction routing.

For each page, output page_number, page_type, and document_type_hint.

PAGE TYPES:
- **content** — Pages with substantive title information.
- **blank** — Completely blank or nearly blank pages.
- **cover** — Cover pages, title pages, transmittal cover sheets.
- **signature** — Pages that are only signature blocks or notary acknowledgments.
- **transmittal** — Transmittal letters or routing slips with no title content.
- **boilerplate** — Standard terms/conditions, general disclaimers, form instructions.

DOCUMENT TYPE HINTS (for content pages only):
- **commitment** — Title commitment schedules (A, B-I, B-II, C), policy info.
- **deed** — Warranty deeds, quitclaim deeds, special warranty deeds.
- **mortgage** — Mortgages, deeds of trust, security instruments.
- **lien** — Tax liens, mechanic's liens, judgments, assessments.
- **release** — Satisfactions, reconveyances, releases, discharges.
- **easement** — Easements, restrictions, CC&Rs, covenants.
- **plat** — Plat maps, surveys, legal description documents.
- **endorsement** — Title insurance endorsements.
- **generic** — Unknown or mixed content that doesn't fit above categories.

RULES:
1. When in doubt, classify page_type as "content" — never skip important pages.
2. When in doubt about document type, use "generic".
3. For non-content pages, set document_type_hint to "generic".
"""

TRIAGE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "pages": {
            "type": "array",
            "description": "Classification for each page in the document.",
            "items": {
                "type": "object",
                "properties": {
                    "page_number": {
                        "type": "integer",
                        "description": "1-based page number",
                    },
                    "page_type": {
                        "type": "string",
                        "enum": list(VALID_PAGE_TYPES),
                    },
                    "document_type_hint": {
                        "type": "string",
                        "enum": list(VALID_DOC_TYPES),
                        "description": "Document type for specialized extraction routing",
                    },
                },
                "required": ["page_number", "page_type", "document_type_hint"],
            },
        },
    },
    "required": ["pages"],
}


class TriagePageResult(BaseModel):
    """Classification result for a single page."""

    page_number: int
    page_type: str = "content"
    document_type_hint: str = "generic"


class TriageResult(BaseModel):
    """Classification result for an entire document."""

    pages: list[TriagePageResult] = Field(default_factory=list)
    llm_elapsed_seconds: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class TriageAgent(BaseAIService):
    """Lightweight page classifier using Gemini.

    Sends the full PDF to Gemini with a compact schema to classify each page.
    Much cheaper than full examination (~500 output tokens for 100 pages).
    """

    SYSTEM_PROMPT = TRIAGE_SYSTEM_PROMPT
    JSON_SCHEMA = TRIAGE_JSON_SCHEMA

    def __init__(self, org_id: uuid.UUID):
        super().__init__(org_id, role="strong")
        self._cache_name: str | None = None

    async def _ensure_context_cache(self) -> str | None:
        """Create or retrieve a Gemini context cache for the triage prompt."""
        if self._cache_name is not None:
            return self._cache_name
        try:
            self._cache_name = await self.create_context_cache(
                system_prompt=self.SYSTEM_PROMPT,
                json_schema=self.JSON_SCHEMA,
                ttl_seconds=600,
            )
            return self._cache_name
        except Exception as e:
            logger.warning(f"Triage context cache creation failed: {e}")
            return None

    async def classify_pages(
        self,
        pdf_bytes: bytes,
        total_pages: int,
    ) -> TriageResult:
        """Classify all pages in a PDF document.

        Args:
            pdf_bytes: Full PDF file bytes.
            total_pages: Total number of pages in the PDF.

        Returns:
            TriageResult with per-page classifications.
        """
        content: list[dict[str, Any]] = []
        content.append({
            "type": "text",
            "text": (
                f"Classify each of the {total_pages} pages in this PDF document. "
                f"Output a JSON array with one entry per page (pages 1 through {total_pages})."
            ),
        })
        content.append({"type": "pdf", "pdf": {"data": pdf_bytes}})

        messages = [{"role": "user", "content": content}]

        t0 = time.monotonic()
        usage: dict[str, Any] = {}

        # Try cached call first
        cache_name = await self._ensure_context_cache()
        if cache_name:
            try:
                result, usage = await self.call_json_structured_cached(
                    cache_name=cache_name,
                    messages=messages,
                    json_schema=self.JSON_SCHEMA,
                    max_tokens=4096,
                    temperature=0.0,
                    timeout=120,
                    return_usage=True,
                )
                elapsed = time.monotonic() - t0
                return self._parse_result(result, total_pages, elapsed, usage)
            except Exception as e:
                logger.warning(f"Cached triage call failed, falling back: {e}")
                t0 = time.monotonic()

        # Fallback: uncached call
        result, usage = await self.call_json_structured(
            system_prompt=self.SYSTEM_PROMPT,
            messages=messages,
            json_schema=self.JSON_SCHEMA,
            max_tokens=4096,
            temperature=0.0,
            timeout=120,
            return_usage=True,
        )
        elapsed = time.monotonic() - t0
        return self._parse_result(result, total_pages, elapsed, usage)

    def _parse_result(
        self,
        raw: dict[str, Any],
        total_pages: int,
        elapsed: float,
        usage: dict[str, Any],
    ) -> TriageResult:
        """Parse raw LLM output into TriageResult with validation."""
        pages_raw = raw.get("pages", [])

        # Build lookup from LLM response
        page_info: dict[int, tuple[str, str]] = {}  # pn → (page_type, doc_type_hint)
        for entry in pages_raw:
            pn = entry.get("page_number")
            pt = entry.get("page_type", "content")
            dt = entry.get("document_type_hint", "generic")
            if pn is not None:
                # Validate page_type — default to "content" for unknown types
                if pt not in VALID_PAGE_TYPES:
                    pt = "content"
                # Validate doc_type — default to "generic" for unknown types
                if dt not in VALID_DOC_TYPES:
                    dt = "generic"
                page_info[pn] = (pt, dt)

        # Ensure every page has a classification (default to "content" / "generic")
        page_results = []
        for pn in range(1, total_pages + 1):
            pt, dt = page_info.get(pn, ("content", "generic"))
            page_results.append(TriagePageResult(
                page_number=pn,
                page_type=pt,
                document_type_hint=dt,
            ))

        skipped = sum(1 for p in page_results if p.page_type != "content")
        logger.info(
            f"Triage complete: {total_pages} pages, {skipped} non-content "
            f"({skipped / total_pages * 100:.0f}%) in {elapsed:.1f}s"
        )

        return TriageResult(
            pages=page_results,
            llm_elapsed_seconds=round(elapsed, 3),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )

    async def classify_pages_parallel(
        self,
        pdf_bytes: bytes,
        total_pages: int,
        chunk_size: int = 50,
        concurrency: int = 4,
    ) -> TriageResult:
        """Classify pages with parallel chunking for large PDFs.

        If total_pages <= chunk_size, delegates to classify_pages() directly.
        For larger PDFs, splits into N chunks and dispatches parallel calls.

        Args:
            pdf_bytes: Full PDF file bytes.
            total_pages: Total number of pages in the PDF.
            chunk_size: Max pages per triage chunk.
            concurrency: Max parallel triage LLM calls.

        Returns:
            TriageResult with per-page classifications.
        """
        if total_pages <= chunk_size:
            return await self.classify_pages(pdf_bytes, total_pages)

        import fitz

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        actual_pages = len(doc)

        # Build chunks: (chunk_bytes, start_page_1based, num_pages_in_chunk)
        chunks: list[tuple[bytes, int, int]] = []
        for start in range(0, actual_pages, chunk_size):
            end = min(start + chunk_size, actual_pages)
            chunk_doc = fitz.open()
            chunk_doc.insert_pdf(doc, from_page=start, to_page=end - 1)
            chunk_bytes = chunk_doc.tobytes()
            chunk_doc.close()
            chunks.append((chunk_bytes, start + 1, end - start))

        doc.close()

        logger.info(
            f"Parallel triage: splitting {total_pages} pages into "
            f"{len(chunks)} chunks (chunk_size={chunk_size}, concurrency={concurrency})"
        )

        # Pre-warm context cache before parallel dispatch
        await self._ensure_context_cache()

        sem = asyncio.Semaphore(concurrency)
        chunk_results: list[tuple[int, int, TriageResult | None]] = []  # (start_page, num_pages, result)

        async def _classify_chunk(
            chunk_bytes: bytes, start_page: int, num_pages: int
        ) -> tuple[int, int, TriageResult | None]:
            async with sem:
                try:
                    result = await self.classify_pages(chunk_bytes, num_pages)
                    return (start_page, num_pages, result)
                except Exception as e:
                    logger.warning(
                        f"Triage chunk (pages {start_page}-{start_page + num_pages - 1}) "
                        f"failed: {e}. Defaulting those pages to 'content'."
                    )
                    return (start_page, num_pages, None)

        tasks = [
            _classify_chunk(cb, sp, np)
            for cb, sp, np in chunks
        ]

        chunk_results = await asyncio.gather(*tasks)
        return self._merge_chunk_results(chunk_results, total_pages)

    def _merge_chunk_results(
        self,
        chunk_results: list[tuple[int, int, TriageResult | None]],
        total_pages: int,
    ) -> TriageResult:
        """Merge results from parallel triage chunks.

        Args:
            chunk_results: List of (start_page, num_pages, result_or_none).
            total_pages: Total pages in the full document.

        Returns:
            Merged TriageResult with globally remapped page numbers.
        """
        # Build global page map from chunk results
        page_info: dict[int, tuple[str, str]] = {}  # global_pn → (page_type, doc_type_hint)
        total_input_tokens = 0
        total_output_tokens = 0
        max_elapsed = 0.0

        for start_page, num_pages, result in chunk_results:
            if result is None:
                # Failed chunk — default all pages to "content" / "generic"
                for offset in range(num_pages):
                    global_pn = start_page + offset
                    page_info[global_pn] = ("content", "generic")
                continue

            # Remap chunk-local page numbers to global
            for page_result in result.pages:
                global_pn = start_page + page_result.page_number - 1
                page_info[global_pn] = (
                    page_result.page_type,
                    page_result.document_type_hint,
                )

            if result.input_tokens:
                total_input_tokens += result.input_tokens
            if result.output_tokens:
                total_output_tokens += result.output_tokens
            if result.llm_elapsed_seconds:
                max_elapsed = max(max_elapsed, result.llm_elapsed_seconds)

        # Build final page results (default missing to "content" / "generic")
        page_results = []
        for pn in range(1, total_pages + 1):
            pt, dt = page_info.get(pn, ("content", "generic"))
            page_results.append(TriagePageResult(
                page_number=pn,
                page_type=pt,
                document_type_hint=dt,
            ))

        skipped = sum(1 for p in page_results if p.page_type != "content")
        logger.info(
            f"Parallel triage complete: {total_pages} pages, {skipped} non-content "
            f"({skipped / total_pages * 100:.0f}%) in {max_elapsed:.1f}s wall time "
            f"({len(chunk_results)} chunks)"
        )

        return TriageResult(
            pages=page_results,
            llm_elapsed_seconds=round(max_elapsed, 3),
            input_tokens=total_input_tokens or None,
            output_tokens=total_output_tokens or None,
        )
