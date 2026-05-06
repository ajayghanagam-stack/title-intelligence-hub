"""Page classifier agent for Loan Onboarding.

Uses Gemini (on Vertex AI when configured) to classify every page in a loan
package into one of the per-package doc types, with confidence and role hints.
Output conforms to the Classification Schema in
`app.micro_apps.loan_onboarding.schemas.classification`.

Design:
- Per-package doc-type enum is injected at construction time, so the model is
  constrained to pick from the loan officer's configured types (plus the
  reserved "Others" bucket for unmatched pages).
- Large packages are chunked and dispatched in parallel (semaphore-limited).
- Pages that were heuristically classified as blank in the ingest stage skip
  the LLM call entirely and are assigned predicted_doc_type="Others".
"""
import asyncio
import logging
import time
import uuid
from typing import Any

from app.ai.base_service import BaseAIService
from app.micro_apps.loan_onboarding.schemas.classification import (
    Classification,
    ClassificationBatchResult,
    PageRole,
)

logger = logging.getLogger(__name__)

# Valid page roles — must match the Literal in schemas/classification.py
VALID_PAGE_ROLES: tuple[str, ...] = (
    "first_page",
    "continuation",
    "last_page",
    "signature_page",
    "unknown",
)

# Reserved bucket for unmatched pages — never listed in the loan officer's config.
OTHERS_KEY = "Others"


class ClassifierChunkError(RuntimeError):
    """Raised when a chunk-level classification call fails or returns no usable data.

    Signals the outer dispatcher (`classify_pdf_chunked`) to recover by
    splitting the chunk rather than silently zeroing out every page.
    """

SYSTEM_PROMPT = """\
You are a mortgage loan package page classifier. Given a PDF of pages from a \
mixed loan bundle (applications, tax forms, pay stubs, appraisals, etc.), \
assign each page to exactly one document type from the provided enum.

For every page, produce:
  - page_number (1-indexed, matching the order in the input PDF)
  - predicted_doc_type: one value from the enum. Use "Others" if the page \
does not fit any listed type.
  - predicted_doc_type_alternatives: up to 2 runner-up types with their \
confidence scores (empty if you are certain).
  - confidence: your calibrated probability the predicted_doc_type is \
correct (0..1). Be honest — low confidence routes the stack to human review.
  - page_role: first_page, continuation, last_page, signature_page, or unknown. \
Use first_page for the starting page of a new document, last_page for the \
final page, continuation for middle pages, and signature_page for pages \
consisting primarily of signature blocks / notary acknowledgments.
  - detected_fields: up to 5 salient fields extracted from the page, each \
with a field_name, value, and bounding box [x1, y1, x2, y2] in pixel \
coordinates. Bounding boxes are optional — if you cannot localize precisely, \
omit the field.

RULES:
1. Every input page must have exactly one classification entry.
2. If you are uncertain between two listed types, pick the higher-confidence \
one and list the other as an alternative.
3. Never invent a doc_type that is not in the enum — fall back to "Others".
4. Calibrate confidence conservatively. A confidence < 0.75 will trigger \
human review, which is the intended behavior for ambiguous pages.
"""


def _build_json_schema(allowed_doc_types: list[str]) -> dict[str, Any]:
    """Construct the Classification JSON schema with the per-package enum."""
    enum = list(dict.fromkeys(list(allowed_doc_types) + [OTHERS_KEY]))  # dedupe, preserve order
    return {
        "type": "object",
        "properties": {
            "classifications": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "page_number": {"type": "integer", "minimum": 1},
                        "predicted_doc_type": {"type": "string", "enum": enum},
                        "predicted_doc_type_alternatives": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string", "enum": enum},
                                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                                },
                                "required": ["type", "confidence"],
                            },
                            "maxItems": 3,
                        },
                        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "page_role": {
                            "type": "string",
                            "enum": list(VALID_PAGE_ROLES),
                        },
                        "detected_fields": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "field_name": {"type": "string"},
                                    "value": {"type": "string"},
                                    "bbox": {
                                        "type": "array",
                                        "items": {"type": "number"},
                                        "minItems": 4,
                                        "maxItems": 4,
                                    },
                                },
                                "required": ["field_name", "value", "bbox"],
                            },
                            "maxItems": 8,
                        },
                    },
                    "required": [
                        "page_number", "predicted_doc_type", "confidence", "page_role",
                    ],
                },
            },
        },
        "required": ["classifications"],
    }


def _extract_subpdf(pdf_bytes: bytes, start_idx: int, end_idx_inclusive: int) -> bytes:
    """Build a PDF containing pages [start_idx..end_idx_inclusive] (0-indexed).

    Used by the split-on-failure path so we can retry a subrange of a failed
    batch without re-fetching the source files from storage.
    """
    import fitz  # pymupdf

    src = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        out = fitz.open()
        try:
            out.insert_pdf(src, from_page=start_idx, to_page=end_idx_inclusive)
            return out.tobytes()
        finally:
            out.close()
    finally:
        src.close()


def _coerce_classification(
    raw: dict[str, Any],
    allowed_set: set[str],
    expected_page_number: int | None = None,
) -> Classification:
    """Clamp LLM output to the schema, falling back to safe defaults."""
    doc_type = str(raw.get("predicted_doc_type") or OTHERS_KEY)
    if doc_type not in allowed_set:
        doc_type = OTHERS_KEY

    # Alternatives: keep only valid types
    alts_raw = raw.get("predicted_doc_type_alternatives") or []
    alts: list[dict[str, Any]] = []
    for a in alts_raw:
        t = a.get("type") if isinstance(a, dict) else None
        if t in allowed_set:
            try:
                c = float(a.get("confidence", 0.0))
            except (TypeError, ValueError):
                c = 0.0
            alts.append({"type": t, "confidence": max(0.0, min(1.0, c))})

    try:
        conf = float(raw.get("confidence", 0.0))
    except (TypeError, ValueError):
        conf = 0.0
    conf = max(0.0, min(1.0, conf))

    role_raw = str(raw.get("page_role") or "unknown")
    role: PageRole = role_raw if role_raw in VALID_PAGE_ROLES else "unknown"  # type: ignore[assignment]

    fields_raw = raw.get("detected_fields") or []
    fields: list[dict[str, Any]] = []
    for f in fields_raw:
        if not isinstance(f, dict):
            continue
        bbox = f.get("bbox")
        if not (isinstance(bbox, list) and len(bbox) == 4):
            continue
        try:
            bbox_f = [float(x) for x in bbox]
        except (TypeError, ValueError):
            continue
        name = f.get("field_name")
        value = f.get("value")
        if not name or value is None:
            continue
        fields.append({
            "field_name": str(name),
            "value": str(value),
            "bbox": bbox_f,
        })

    try:
        page_number = int(raw.get("page_number", expected_page_number or 1))
    except (TypeError, ValueError):
        page_number = expected_page_number or 1

    return Classification(
        page_number=page_number,
        predicted_doc_type=doc_type,
        predicted_doc_type_alternatives=alts,
        confidence=conf,
        page_role=role,
        detected_fields=fields,
    )


class PageClassifierAgent(BaseAIService):
    """Gemini-based per-page classifier scoped to a per-package doc_type enum."""

    SYSTEM_PROMPT = SYSTEM_PROMPT

    def __init__(
        self,
        org_id: uuid.UUID,
        allowed_doc_types: list[str],
        model_override: str | None = None,
    ):
        # Always route through Gemini (Vertex AI when configured) — classify is
        # the vision-heavy step and Claude doesn't accept raw PDF blocks.
        super().__init__(org_id, role="classifier", provider_override="gemini")
        if not allowed_doc_types:
            raise ValueError("allowed_doc_types must contain at least one type")
        if OTHERS_KEY in allowed_doc_types:
            raise ValueError(
                f"'{OTHERS_KEY}' is reserved — do not list it in allowed_doc_types; "
                "it is added automatically."
            )
        self._allowed_doc_types = list(allowed_doc_types)
        self._allowed_set: set[str] = set(self._allowed_doc_types) | {OTHERS_KEY}
        self._json_schema = _build_json_schema(self._allowed_doc_types)

        # Optional model override — lets callers pin LO_CLASSIFIER_MODEL.
        # Settings hold a bare alias ("gemini-2.5-flash"); litellm needs a
        # provider-prefixed id, so add "gemini/" when one is missing.
        if model_override:
            self.model = (
                model_override if "/" in model_override else f"gemini/{model_override}"
            )

    async def classify_pdf(
        self,
        pdf_bytes: bytes,
        page_numbers: list[int],
        timeout: int | None = None,
    ) -> ClassificationBatchResult:
        """Classify every page in the supplied PDF.

        `page_numbers` is the 1-indexed global numbering the caller wants
        stamped on the output — the PDF itself is assumed to be ordered so
        that its i-th page corresponds to page_numbers[i].

        Raises `ClassifierChunkError` when the model returns no
        classifications (empty object, truncation, timeout, or parse
        failure). The caller is expected to split and retry rather than
        silently filling with zero-confidence Others — a uniform block of
        Others/0.0 is almost always an infrastructure failure, not a real
        verdict.
        """
        if not page_numbers:
            return ClassificationBatchResult(classifications=[])

        n_pages = len(page_numbers)
        # Adaptive token budget: ~1000 tokens/page covers the full schema with
        # headroom (predicted_doc_type + confidence + role + up to 8 fields
        # with bboxes + alternatives). The previous 500/page budget was a hot
        # spot for output truncation on real loan packets — large packages
        # like Benavides 89543 (592 pages) had ~half their 20-page chunks
        # truncate at the 10K cap, triggering recursive split-and-retry that
        # turned a ~6-min classify into ~12 min. Gemini 2.5 Flash supports up
        # to 65K output tokens, so a 48K cap leaves plenty of slack.
        max_tokens = max(12_000, min(48_000, 1000 * n_pages))
        # Adaptive timeout: ~3s/page vision budget + 30s base, capped at 5min.
        effective_timeout = timeout or min(300, 30 + 3 * n_pages)

        messages = [{
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        f"Classify every page of this {n_pages}-page PDF. "
                        f"Output one entry per page, numbered 1 through "
                        f"{n_pages} (the i-th entry corresponds to the "
                        f"i-th page of the input PDF)."
                    ),
                },
                {"type": "pdf", "pdf": {"data": pdf_bytes}},
            ],
        }]

        t0 = time.monotonic()
        try:
            raw = await self.call_json_structured(
                system_prompt=self.SYSTEM_PROMPT,
                messages=messages,
                json_schema=self._json_schema,
                max_tokens=max_tokens,
                temperature=0.0,
                timeout=effective_timeout,
            )
        except Exception as e:
            raise ClassifierChunkError(
                f"classifier call raised: {type(e).__name__}: {e}"
            ) from e

        raws = (raw or {}).get("classifications") or []
        # An empty response signals truncation / JSON-parse failure at the
        # provider level (see gemini_provider._call_genai_direct's
        # JSONDecodeError branch, which returns {} after retries). Treat it
        # as a recoverable failure so the caller can split-and-retry.
        if not raws:
            raise ClassifierChunkError(
                f"classifier returned empty response for {n_pages}-page chunk "
                f"(pages {page_numbers[0]}-{page_numbers[-1]}). Likely "
                f"output truncation — retrying with smaller splits."
            )
        # Short response → partial truncation. Better to split-and-retry than
        # silently zero-fill the missing tail.
        if len(raws) < n_pages * 0.7:  # >30% missing
            raise ClassifierChunkError(
                f"classifier returned {len(raws)}/{n_pages} entries for pages "
                f"{page_numbers[0]}-{page_numbers[-1]}. Likely output "
                f"truncation — retrying with smaller splits."
            )

        # Map classifier's 1-indexed output page_number → caller's global page_number
        results: list[Classification] = []
        for i, pn in enumerate(page_numbers):
            local = raws[i] if i < len(raws) else {}
            clf = _coerce_classification(local, self._allowed_set, expected_page_number=pn)
            # Overwrite page_number with caller's global numbering
            clf = clf.model_copy(update={"page_number": pn})
            results.append(clf)

        elapsed = time.monotonic() - t0
        logger.info(f"Classified {n_pages} pages in {elapsed:.2f}s (max_tokens={max_tokens})")
        return ClassificationBatchResult(classifications=results)

    def _fallback_batch(self, page_numbers: list[int]) -> ClassificationBatchResult:
        """Produce a safe fallback batch when the LLM call fails."""
        return ClassificationBatchResult(
            classifications=[
                Classification(
                    page_number=pn,
                    predicted_doc_type=OTHERS_KEY,
                    predicted_doc_type_alternatives=[],
                    confidence=0.0,
                    page_role="unknown",
                    detected_fields=[],
                )
                for pn in page_numbers
            ],
        )

    async def classify_pdf_chunked(
        self,
        pdf_bytes_per_chunk: list[tuple[bytes, list[int]]],
        concurrency: int = 4,
        timeout: int | None = None,
    ) -> ClassificationBatchResult:
        """Classify multiple PDF chunks in parallel, merging the results.

        Each chunk is a `(pdf_bytes, page_numbers)` tuple. The `page_numbers`
        list carries the global numbering to stamp on the classifier output.

        Failed chunks are recovered by recursively splitting the chunk
        (halving the page range and rebuilding the sub-PDF) down to
        single-page classify calls. Only after a single-page call still
        fails do we fall back to Others/0.0 — meaning that a 0% confidence
        Others in the output is now a very strong signal that Gemini
        genuinely cannot handle that specific page, not that a 40-page
        batch overflowed the token budget.
        """
        if not pdf_bytes_per_chunk:
            return ClassificationBatchResult(classifications=[])

        sem = asyncio.Semaphore(max(1, concurrency))

        async def _classify_with_split(
            pdf: bytes, pns: list[int], depth: int = 0
        ) -> list[Classification]:
            """Try a chunk; on failure, split in half and retry each half.

            Recurses down to single-page calls. `depth` is only used for
            readable log breadcrumbs.
            """
            async with sem:
                try:
                    res = await self.classify_pdf(pdf, pns, timeout=timeout)
                    return res.classifications
                except ClassifierChunkError as e:
                    if len(pns) == 1:
                        logger.warning(
                            f"[classify depth={depth}] single-page classify "
                            f"failed for page {pns[0]} — assigning Others/0.0: {e}"
                        )
                        return self._fallback_batch(pns).classifications
                    logger.warning(
                        f"[classify depth={depth}] chunk of {len(pns)} pages "
                        f"({pns[0]}-{pns[-1]}) failed; splitting. Cause: {e}"
                    )
                except Exception as e:
                    if len(pns) == 1:
                        logger.error(
                            f"[classify depth={depth}] single-page classify "
                            f"raised unexpected error for page {pns[0]} — "
                            f"assigning Others/0.0: {type(e).__name__}: {e}"
                        )
                        return self._fallback_batch(pns).classifications
                    logger.warning(
                        f"[classify depth={depth}] chunk of {len(pns)} pages "
                        f"({pns[0]}-{pns[-1]}) raised {type(e).__name__}: {e}; "
                        f"splitting."
                    )

            # Release semaphore before rebuilding sub-PDFs and recursing —
            # otherwise deep splits could starve the concurrency pool.
            mid = len(pns) // 2
            left_pns, right_pns = pns[:mid], pns[mid:]
            left_pdf = _extract_subpdf(pdf, 0, mid - 1)
            right_pdf = _extract_subpdf(pdf, mid, len(pns) - 1)

            left_res, right_res = await asyncio.gather(
                _classify_with_split(left_pdf, left_pns, depth + 1),
                _classify_with_split(right_pdf, right_pns, depth + 1),
            )
            return left_res + right_res

        results = await asyncio.gather(
            *[_classify_with_split(pdf, pns) for pdf, pns in pdf_bytes_per_chunk]
        )
        merged: list[Classification] = []
        for chunk in results:
            merged.extend(chunk)
        # Sort by global page number for stable output
        merged.sort(key=lambda c: c.page_number)
        return ClassificationBatchResult(classifications=merged)
