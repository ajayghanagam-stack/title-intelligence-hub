"""Single-pass Title Examiner agent using Claude Vision.

Replaces the OCR → index → ingestion → risk pipeline stages with a single
multimodal call where Claude reads page images directly and produces all
outputs (transcriptions, sections, extractions, flags) in one pass.

Uses Sonnet 4 (role="strong") for higher-quality analysis.
"""

import asyncio
import base64
import json
import logging
import time
import uuid
from typing import Any

from app.ai.base_service import BaseAIService
from app.config import get_settings
from app.micro_apps.title_intelligence.schemas.examiner import (
    ExaminerBatchResult,
    ExaminerConsolidatedResult,
    ExaminerExtraction,
    ExaminerFlag,
    ExaminerSection,
    PageTranscription,
)

logger = logging.getLogger(__name__)


class RateLimitController:
    """Adaptive concurrency controller with staggered launch and rate limit handling.

    Manages a semaphore that automatically reduces concurrency when 429 errors
    are detected, then gradually recovers. Tracks metrics for observability.
    """

    def __init__(
        self,
        max_concurrency: int = 5,
        stagger_ms: int = 200,
    ):
        self._max_concurrency = max_concurrency
        self._stagger_seconds = stagger_ms / 1000.0
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._launch_lock = asyncio.Lock()
        self._launch_count = 0

        # Metrics
        self.rate_limit_hits = 0
        self.total_retries = 0
        self._backoff_until: float = 0.0  # monotonic time when backoff expires
        self._consecutive_successes: int = 0

    async def acquire(self, batch_index: int) -> None:
        """Acquire a concurrency slot with staggered launch delay."""
        # Stagger: wait for previous launches to space out
        async with self._launch_lock:
            if self._launch_count > 0 and self._stagger_seconds > 0:
                await asyncio.sleep(self._stagger_seconds)
            self._launch_count += 1

        # Wait for global backoff if active
        now = time.monotonic()
        if self._backoff_until > now:
            wait = self._backoff_until - now
            logger.info(f"Batch {batch_index}: waiting {wait:.1f}s for rate limit cooldown")
            await asyncio.sleep(wait)

        await self._semaphore.acquire()

    def release(self) -> None:
        """Release a concurrency slot."""
        self._semaphore.release()

    def record_rate_limit(self) -> float:
        """Record a rate limit hit. Returns the backoff duration in seconds.

        On each hit, doubles the global backoff (starting at 2s, max 30s).
        The global backoff prevents all pending acquires from proceeding,
        which effectively throttles concurrency without manipulating the semaphore.
        """
        self.rate_limit_hits += 1
        self.total_retries += 1
        self._consecutive_successes = 0

        # Calculate backoff: 2s * 2^(hits-1), capped at 30s
        backoff = min(2.0 * (2 ** (self.rate_limit_hits - 1)), 30.0)
        self._backoff_until = time.monotonic() + backoff

        logger.warning(
            f"Rate limit hit #{self.rate_limit_hits}: "
            f"global backoff {backoff:.0f}s (all pending chunks will wait)"
        )

        return backoff

    def record_success(self) -> None:
        """Record a successful call. After 2 consecutive successes, gradually
        recover from rate limiting by decrementing rate_limit_hits."""
        self._consecutive_successes += 1
        if self._consecutive_successes >= 2 and self.rate_limit_hits > 0:
            self.rate_limit_hits -= 1
            self._consecutive_successes = 0
            logger.info(
                f"Rate limit recovery: hits decremented to {self.rate_limit_hits}"
            )

    def record_retry(self) -> None:
        """Record a non-rate-limit retry."""
        self.total_retries += 1

    def get_metrics(self) -> dict[str, int]:
        """Return rate limit metrics."""
        return {
            "rate_limit_hits": self.rate_limit_hits,
            "total_retries": self.total_retries,
        }


def _is_rate_limit_error(e: Exception) -> bool:
    """Check if an exception is a rate limit (429) error."""
    err_str = str(e).lower()
    return "429" in err_str or "rate" in err_str or "resource_exhausted" in err_str


SYSTEM_PROMPT = """\
You are an expert licensed title examiner with 20+ years of experience. You examine \
title commitment packages (T-7 commitments, recorded instruments, deeds, DOTs, plats, \
CC&Rs, easements, affidavits) with the thoroughness of a senior examiner preparing a \
title opinion for a major transaction.

For every batch of pages, perform ALL of the following:

## 1. TRANSCRIBE every page
Transcribe ALL text faithfully. Preserve formatting, tables, recording stamps, notary \
blocks, clerk stamps, and marginal notes exactly as they appear.

## 2. IDENTIFY DOCUMENT SECTIONS
Valid types: schedule_a (commitment details/effective date/parties/property/policy amounts), \
schedule_b1 (requirements before policy issuance), schedule_b2 (exceptions from coverage), \
schedule_c (conditions/stipulations/additional requirements), legal_description (metes & \
bounds/lot/block/subdivision), endorsements (title insurance endorsements).

## 3. EXTRACT STRUCTURED DATA
Output extractions as typed arrays: parties[], properties[], requirements[], exceptions[], \
endorsements[], policy_info_items[], compliance_items[], chain_of_title_items[].
Each item has: label, value (with type-specific fields), evidence_refs, confidence.

Type-specific fields:
- parties — name, role, entity_type, marital_status, deceased, date_of_death
- properties — address, apn, county, state, legal_description, lot, block, subdivision
- requirements — number, description, category, risk_level, is_standard_boilerplate
- exceptions — number, description, category, risk_level, recording_reference
- endorsements — number, endorsement_type, coverage_amount
- policy_info_items — field_name, field_value
- compliance_items — item, status, details
- chain_of_title_items — document_type, grantor, grantee, recording_date, recording_reference, consideration

Each extraction needs: descriptive label, structured value object, evidence_refs with \
page_number and text_snippet.

## 4. DETECT RISK FLAGS
Flag everything needing attention before closing.

Valid flag types:
- missing_endorsement — required endorsement not present
- unacceptable_exception — exception jeopardizing insured's interest
- unresolved_lien — active lien/judgment without satisfaction evidence
- unreleased_mortgage — DOT/mortgage without recorded release/reconveyance
- cross_section_mismatch — inconsistency between sections (names, legal desc, amounts)
- requirement_missing_proof — requirement without satisfaction evidence
- name_discrepancy — party name differs across documents or from chain
- marital_status_issue — spousal joinder needed, community property concerns
- incomplete_document — blank fields, missing signatures, unfilled forms
- regulatory_compliance — FinCEN, foreign ownership, state-specific flags
- chain_of_title_gap — missing link, grantor/grantee mismatch in chain
- document_defect — recording defects, voided instruments, defective acknowledgments
- mineral_rights — severed mineral estate, oil/gas leases, subsurface rights needing buyer acknowledgment
- trust_issue — trust documentation gaps, successor trustee authority, trust not confirmed active
- estate_issue — probate, inheritance tax, deceased party estate administration
- vesting_issue — unauthorized vesting changes, capacity questions, entity formation gaps
- tax_issue — delinquent property taxes, special assessments, tax sale certificates

Severity: critical (blocks closing), high (must resolve before closing), \
medium (should address), low (informational).

Each flag needs: specific title, description, ai_explanation, evidence_refs with \
page_number and text_snippet for every piece of evidence.

### CRITICAL EXTRACTION RULES:
- **Populate the value object**: Every extraction MUST have a fully populated value object. NEVER return empty value objects.
- **Party roles**: seller, buyer, borrower, trustee, current_owner, prior_owner, executor, executrix, beneficiary, lender, title_company, underwriter, mineral_rights_holder, lessee, assignee
- **Party entity types**: individual, trust, estate, corporation, llc, partnership, government
- **Parties — be exhaustive**: Extract ALL named parties from the ENTIRE document, not just Schedule A. Include prior owners from the chain of title, deceased settlors/trustees with deceased=true and date_of_death, executors/executrices, mineral rights holders, lessees, and assignees.
- **Chain of Title — extract every instrument**: Extract EVERY recorded instrument referenced anywhere (deeds, mortgages, satisfactions, oil/gas leases, assignments, mineral deeds, extensions). Each needs document_type, grantor, grantee, recording_date, recording_reference.
- **Compliance — track status**: For each compliance item, set status: cleared (completed, no issues), pending (not yet done), paid (payment confirmed), waived, or required.
- **Requirements — categorize**: Set category (financial, documentation, legal, regulatory, standard), risk_level, and is_standard_boilerplate=true for standard commitment language.
- **Exceptions — categorize**: Set category (standard, survey, tax, easement, restriction, mineral_rights, regulatory, utility, environmental), risk_level, and recording_reference where available.
"""

# Shared sub-schemas for evidence_refs (with maxLength to limit output bloat)
_EVIDENCE_REF_SCHEMA = {
    "type": "object",
    "properties": {
        "page_number": {"type": "integer"},
        "text_snippet": {"type": "string", "maxLength": 200},
    },
    "required": ["page_number", "text_snippet"],
}

_SECTIONS_SCHEMA = {
    "type": "array",
    "description": "Document sections detected in these pages.",
    "items": {
        "type": "object",
        "properties": {
            "section_type": {
                "type": "string",
                "enum": [
                    "schedule_a", "schedule_b1", "schedule_b2",
                    "schedule_c", "legal_description", "endorsements",
                ],
            },
            "start_page": {"type": "integer"},
            "end_page": {"type": "integer"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["section_type", "start_page", "end_page"],
    },
}

# Mapping from typed array key → extraction_type
TYPED_EXTRACTION_KEYS = {
    "parties": "party",
    "properties": "property",
    "requirements": "requirement",
    "exceptions": "exception",
    "endorsements": "endorsement",
    "policy_info_items": "policy_info",
    "compliance_items": "compliance",
    "chain_of_title_items": "chain_of_title",
}


def _typed_extraction_schema(value_properties: dict) -> dict:
    """Build a typed extraction array schema with only the relevant value fields."""
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "label": {"type": "string"},
                "value": {
                    "type": "object",
                    "properties": value_properties,
                    "required": list(value_properties.keys()),
                },
                "evidence_refs": {"type": "array", "items": _EVIDENCE_REF_SCHEMA},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["label", "value"],
        },
    }


_PARTIES_SCHEMA = _typed_extraction_schema({
    "name": {"type": "string"},
    "role": {"type": "string"},
    "entity_type": {"type": "string"},
    "marital_status": {"type": "string"},
    "deceased": {"type": "boolean"},
    "date_of_death": {"type": "string"},
})

_PROPERTIES_SCHEMA = _typed_extraction_schema({
    "address": {"type": "string"},
    "apn": {"type": "string"},
    "county": {"type": "string"},
    "state": {"type": "string"},
    "legal_description": {"type": "string"},
    "lot": {"type": "string"},
    "block": {"type": "string"},
    "subdivision": {"type": "string"},
})

_REQUIREMENTS_SCHEMA = _typed_extraction_schema({
    "number": {"type": "string"},
    "description": {"type": "string"},
    "category": {"type": "string"},
    "risk_level": {"type": "string"},
    "is_standard_boilerplate": {"type": "boolean"},
})

_EXCEPTIONS_SCHEMA = _typed_extraction_schema({
    "number": {"type": "string"},
    "description": {"type": "string"},
    "category": {"type": "string"},
    "risk_level": {"type": "string"},
    "recording_reference": {"type": "string"},
})

_ENDORSEMENTS_SCHEMA = _typed_extraction_schema({
    "number": {"type": "string"},
    "endorsement_type": {"type": "string"},
    "coverage_amount": {"type": "string"},
})

_POLICY_INFO_SCHEMA = _typed_extraction_schema({
    "field_name": {"type": "string"},
    "field_value": {"type": "string"},
})

_COMPLIANCE_SCHEMA = _typed_extraction_schema({
    "item": {"type": "string"},
    "status": {"type": "string"},
    "details": {"type": "string"},
})

_CHAIN_OF_TITLE_SCHEMA = _typed_extraction_schema({
    "document_type": {"type": "string"},
    "grantor": {"type": "string"},
    "grantee": {"type": "string"},
    "recording_date": {"type": "string"},
    "recording_reference": {"type": "string"},
    "consideration": {"type": "string"},
})

_FLAGS_SCHEMA = {
    "type": "array",
    "description": "Risk flags detected in these pages.",
    "items": {
        "type": "object",
        "properties": {
            "flag_type": {
                "type": "string",
                "enum": [
                    "missing_endorsement", "unacceptable_exception",
                    "unresolved_lien", "unreleased_mortgage",
                    "cross_section_mismatch", "requirement_missing_proof",
                    "name_discrepancy", "marital_status_issue",
                    "incomplete_document", "regulatory_compliance",
                    "chain_of_title_gap", "document_defect",
                    "mineral_rights", "trust_issue",
                    "estate_issue", "vesting_issue", "tax_issue",
                ],
            },
            "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "ai_explanation": {"type": "string"},
            "evidence_refs": {"type": "array", "items": _EVIDENCE_REF_SCHEMA},
        },
        "required": ["flag_type", "severity", "title", "description", "ai_explanation", "evidence_refs"],
    },
}

_PAGE_TRANSCRIPTIONS_SCHEMA = {
    "type": "array",
    "description": "Full text transcription of each page.",
    "items": {
        "type": "object",
        "properties": {
            "page_number": {"type": "integer"},
            "text": {"type": "string"},
        },
        "required": ["page_number", "text"],
    },
}

# Typed extraction array schemas keyed by array name
_TYPED_EXTRACTION_SCHEMAS = {
    "parties": _PARTIES_SCHEMA,
    "properties": _PROPERTIES_SCHEMA,
    "requirements": _REQUIREMENTS_SCHEMA,
    "exceptions": _EXCEPTIONS_SCHEMA,
    "endorsements": _ENDORSEMENTS_SCHEMA,
    "policy_info_items": _POLICY_INFO_SCHEMA,
    "compliance_items": _COMPLIANCE_SCHEMA,
    "chain_of_title_items": _CHAIN_OF_TITLE_SCHEMA,
}

# Full schema — includes page_transcriptions (for batches with image pages)
EXAMINATION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "page_transcriptions": _PAGE_TRANSCRIPTIONS_SCHEMA,
        "sections": _SECTIONS_SCHEMA,
        **_TYPED_EXTRACTION_SCHEMAS,
        "flags": _FLAGS_SCHEMA,
    },
    "required": [
        "page_transcriptions", "sections",
        "parties", "properties", "requirements", "exceptions",
        "endorsements", "policy_info_items", "compliance_items",
        "chain_of_title_items", "flags",
    ],
}

# Text-only schema — no page_transcriptions (for batches where all pages have embedded text)
EXAMINATION_JSON_SCHEMA_TEXT_ONLY = {
    "type": "object",
    "properties": {
        "sections": _SECTIONS_SCHEMA,
        **_TYPED_EXTRACTION_SCHEMAS,
        "flags": _FLAGS_SCHEMA,
    },
    "required": [
        "sections",
        "parties", "properties", "requirements", "exceptions",
        "endorsements", "policy_info_items", "compliance_items",
        "chain_of_title_items", "flags",
    ],
}

# Legacy tool definition (kept for backward compatibility / tool-use mode)
SUBMIT_EXAMINATION_RESULTS_TOOL = {
    "name": "submit_examination_results",
    "description": "Submit the examination results for the current batch of pages.",
    "input_schema": EXAMINATION_JSON_SCHEMA,
}


class TitleExaminerAgent(BaseAIService):
    """Single-pass title examiner using Gemini Vision.

    Reads page images directly and produces transcriptions, sections,
    extractions, and flags in one pass per batch.
    """

    SYSTEM_PROMPT = SYSTEM_PROMPT
    TOOL_SCHEMA = SUBMIT_EXAMINATION_RESULTS_TOOL
    JSON_SCHEMA = EXAMINATION_JSON_SCHEMA
    JSON_SCHEMA_TEXT_ONLY = EXAMINATION_JSON_SCHEMA_TEXT_ONLY

    def __init__(self, org_id: uuid.UUID):
        super().__init__(org_id, role="strong")
        self._cache_name: str | None = None  # Gemini context cache handle
        self._cache_lock = asyncio.Lock()

    def _get_batch_config(self) -> dict[str, int]:
        """Return batch sizes and concurrency settings based on AI provider."""
        settings = get_settings()
        if self._provider == "claude":
            return {
                "batch_size_image": settings.CLAUDE_EXAMINER_BATCH_SIZE,
                "batch_size_text": settings.CLAUDE_EXAMINER_BATCH_SIZE_TEXT,
                "concurrency": settings.CLAUDE_EXAMINER_CONCURRENCY,
                "stagger_ms": settings.CLAUDE_EXAMINER_STAGGER_MS,
            }
        return {
            "batch_size_image": settings.EXAMINER_BATCH_SIZE,
            "batch_size_text": settings.EXAMINER_BATCH_SIZE_TEXT,
            "concurrency": getattr(settings, "NATIVE_PDF_CONCURRENCY", 5),
            "stagger_ms": int(settings.EXAMINER_BATCH_COOLDOWN * 1000),
        }

    async def _ensure_context_cache(self, schema: dict[str, Any]) -> str | None:
        """Create or retrieve a Gemini context cache for the system prompt + schema.

        Thread-safe via asyncio.Lock — safe for concurrent pre-warm + batch calls.
        Returns the cache name if caching is available, None otherwise.
        """
        if self._cache_name is not None:
            return self._cache_name

        async with self._cache_lock:
            # Double-check after acquiring lock
            if self._cache_name is not None:
                return self._cache_name

            try:
                self._cache_name = await self.create_context_cache(
                    system_prompt=self.SYSTEM_PROMPT,
                    json_schema=schema,
                    ttl_seconds=600,  # 10 minutes — enough for one pipeline run
                )
                return self._cache_name
            except Exception as e:
                logger.warning(f"Context cache creation failed (will use uncached): {e}")
                return None

    async def examine_batch(
        self,
        page_images: list[tuple[int, bytes | None, str | None]],
        batch_context: dict[str, Any] | None = None,
    ) -> ExaminerBatchResult:
        """Examine a batch of pages (text or image).

        Uses Gemini context caching when available to avoid re-sending
        the system prompt with every batch.

        Args:
            page_images: List of (page_number, jpeg_bytes | None, text | None) tuples.
                Exactly one of jpeg_bytes or text is set per page.
            batch_context: Static batch position context (no dependency on other batches).

        Returns:
            ExaminerBatchResult with transcriptions, sections, extractions, flags.
        """
        settings = get_settings()
        configured_max_tokens = getattr(settings, "EXAMINER_MAX_OUTPUT_TOKENS", 16384)
        call_timeout = getattr(settings, "EXAMINER_CALL_TIMEOUT", 300)

        max_output_tokens = configured_max_tokens

        # Build multimodal message content
        content: list[dict[str, Any]] = []

        # Add static batch context if available
        if batch_context:
            context_text = self._format_static_context(batch_context)
            content.append({"type": "text", "text": context_text})

        # Determine batch content type for schema selection
        page_numbers = [pn for pn, _, _ in page_images]
        text_page_numbers = [pn for pn, _, t in page_images if t]
        image_page_numbers = [pn for pn, img, _ in page_images if img]
        is_text_only = bool(text_page_numbers) and not image_page_numbers

        instruction = (
            f"Examine the following {len(page_images)} pages "
            f"(pages {page_numbers[0]}-{page_numbers[-1]}). "
            f"Identify sections, extract structured data, and flag any issues."
        )
        if is_text_only:
            instruction += (
                "\n\nAll pages already have extracted text provided. "
                "Focus on sections, extractions, and flags."
            )
        elif text_page_numbers and image_page_numbers:
            instruction += (
                f"\n\nPages {', '.join(str(p) for p in text_page_numbers)} already have "
                f"extracted text provided — do NOT re-transcribe those pages "
                f"(omit them from page_transcriptions). Only transcribe the image-based "
                f"pages: {', '.join(str(p) for p in image_page_numbers)}."
            )
        else:
            instruction += "\n\nTranscribe all text from the page images."

        content.append({"type": "text", "text": instruction})

        # Add page content — text for embedded-text pages, images for scanned pages
        for page_number, image_bytes, text in page_images:
            content.append({"type": "text", "text": f"--- Page {page_number} ---"})
            if text:
                content.append({"type": "text", "text": text})
            else:
                b64 = base64.b64encode(image_bytes).decode("utf-8")
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                })

        messages = [{"role": "user", "content": content}]

        # Use text-only schema (no page_transcriptions) for all-text batches
        schema = self.JSON_SCHEMA_TEXT_ONLY if is_text_only else self.JSON_SCHEMA

        # Try cached call first, fall back to uncached
        cache_name = await self._ensure_context_cache(schema)
        t0 = time.monotonic()
        usage: dict[str, Any] = {}

        if cache_name:
            try:
                result, usage = await self.call_json_structured_cached(
                    cache_name=cache_name,
                    messages=messages,
                    json_schema=schema,
                    max_tokens=max_output_tokens,
                    temperature=0.0,
                    timeout=call_timeout,
                    return_usage=True,
                )
                elapsed = time.monotonic() - t0
                batch_result = self._parse_batch_result(result)
                batch_result.llm_elapsed_seconds = round(elapsed, 3)
                batch_result.input_tokens = usage.get("input_tokens")
                batch_result.output_tokens = usage.get("output_tokens")
                return batch_result
            except Exception as e:
                logger.warning(f"Cached call failed, falling back to uncached: {e}")
                t0 = time.monotonic()

        # Fallback: uncached call via litellm
        result, usage = await self.call_json_structured(
            system_prompt=self.SYSTEM_PROMPT,
            messages=messages,
            json_schema=schema,
            max_tokens=max_output_tokens,
            temperature=0.0,
            timeout=call_timeout,
            return_usage=True,
        )
        elapsed = time.monotonic() - t0

        batch_result = self._parse_batch_result(result)
        batch_result.llm_elapsed_seconds = round(elapsed, 3)
        batch_result.input_tokens = usage.get("input_tokens")
        batch_result.output_tokens = usage.get("output_tokens")
        return batch_result

    def _parse_batch_result(self, raw: dict[str, Any]) -> ExaminerBatchResult:
        """Parse raw LLM output into a typed ExaminerBatchResult.

        Handles both the new typed array format (parties[], properties[], etc.)
        and the legacy polymorphic format (extractions[] with extraction_type).
        """
        transcriptions = [
            PageTranscription(page_number=t["page_number"], text=t.get("text", ""))
            for t in raw.get("page_transcriptions", [])
        ]
        sections = [
            ExaminerSection(
                section_type=s["section_type"],
                start_page=s["start_page"],
                end_page=s["end_page"],
                confidence=s.get("confidence", 0.0),
            )
            for s in raw.get("sections", [])
        ]

        # Parse typed extraction arrays → unified ExaminerExtraction list
        extractions: list[ExaminerExtraction] = []
        for array_key, ext_type in TYPED_EXTRACTION_KEYS.items():
            for e in raw.get(array_key, []):
                extractions.append(ExaminerExtraction(
                    extraction_type=ext_type,
                    label=e["label"],
                    value=e.get("value", {}),
                    evidence_refs=e.get("evidence_refs", []),
                    confidence=e.get("confidence", 0.0),
                ))

        # Backward-compat: also read legacy "extractions" key (old cache format)
        for e in raw.get("extractions", []):
            extractions.append(ExaminerExtraction(
                extraction_type=e["extraction_type"],
                label=e["label"],
                value=e.get("value", {}),
                evidence_refs=e.get("evidence_refs", []),
                confidence=e.get("confidence", 0.0),
            ))

        flags = [
            ExaminerFlag(
                flag_type=f["flag_type"],
                severity=f["severity"],
                title=f["title"],
                description=f["description"],
                ai_explanation=f["ai_explanation"],
                evidence_refs=f.get("evidence_refs", []),
            )
            for f in raw.get("flags", [])
        ]
        return ExaminerBatchResult(
            page_transcriptions=transcriptions,
            sections=sections,
            extractions=extractions,
            flags=flags,
        )

    def _build_static_batch_context(
        self,
        batch_index: int,
        total_batches: int,
        total_pages: int,
    ) -> dict[str, Any] | None:
        """Build position-only context for a batch (no dependency on prior results).

        Returns None for single-batch documents (no context needed).
        """
        if total_batches <= 1:
            return None
        return {
            "batch_position": f"Batch {batch_index + 1} of {total_batches}",
            "total_pages": total_pages,
        }

    def _format_static_context(self, context: dict[str, Any]) -> str:
        """Format static batch context as text for the LLM prompt."""
        return (
            f"DOCUMENT CONTEXT: You are examining {context['batch_position']} "
            f"({context['total_pages']} total pages). "
            f"Other batches are being examined in parallel. "
            f"Report ALL sections, extractions, and flags you find in THIS batch — "
            f"duplicates will be merged automatically."
        )

    def consolidate(
        self, batch_results: list[ExaminerBatchResult]
    ) -> ExaminerConsolidatedResult:
        """Merge results from multiple batches into a single consolidated result.

        - Page transcriptions: use the later batch's version for overlap pages
        - Sections: merge overlapping/adjacent sections of the same type
        - Extractions: deduplicate by (extraction_type, label), keep higher confidence
        - Flags: concatenate all (normalization happens later via flag_rules)
        """
        # Page transcriptions — later batch wins for overlap pages
        transcription_map: dict[int, PageTranscription] = {}
        for br in batch_results:
            for t in br.page_transcriptions:
                transcription_map[t.page_number] = t
        all_transcriptions = [
            transcription_map[pn] for pn in sorted(transcription_map)
        ]

        # Sections — merge overlapping/adjacent of same type
        all_sections: list[ExaminerSection] = []
        for br in batch_results:
            for s in br.sections:
                merged = False
                for existing in all_sections:
                    if (
                        existing.section_type == s.section_type
                        and s.start_page <= existing.end_page + 1
                        and s.end_page >= existing.start_page - 1
                    ):
                        existing.start_page = min(existing.start_page, s.start_page)
                        existing.end_page = max(existing.end_page, s.end_page)
                        existing.confidence = max(existing.confidence, s.confidence)
                        merged = True
                        break
                if not merged:
                    all_sections.append(s.model_copy())

        # Extractions — deduplicate by (extraction_type, label), keep higher confidence
        extraction_map: dict[tuple[str, str], ExaminerExtraction] = {}
        for br in batch_results:
            for e in br.extractions:
                key = (e.extraction_type, e.label)
                if key not in extraction_map or e.confidence > extraction_map[key].confidence:
                    extraction_map[key] = e
        all_extractions = list(extraction_map.values())

        # Flags — concatenate all (normalization via flag_rules later)
        all_flags: list[ExaminerFlag] = []
        for br in batch_results:
            all_flags.extend(br.flags)

        return ExaminerConsolidatedResult(
            page_transcriptions=all_transcriptions,
            sections=all_sections,
            extractions=all_extractions,
            flags=all_flags,
        )

    @staticmethod
    def _build_smart_batches(
        page_data: list[tuple[int, bytes | None, str | None]],
        batch_size_image: int,
        batch_size_text: int,
        overlap: int,
    ) -> list[list[tuple[int, bytes | None, str | None]]]:
        """Build batches with different sizes for text vs image pages.

        Groups consecutive same-type pages together, then batches each group
        at the appropriate size. This reduces total API calls for documents
        that are mostly text (typical digitally-produced PDFs).
        """
        if not page_data:
            return []

        # Group consecutive pages by type (text vs image)
        groups: list[tuple[str, list[tuple[int, bytes | None, str | None]]]] = []
        for page in page_data:
            page_type = "text" if page[2] else "image"
            if groups and groups[-1][0] == page_type:
                groups[-1][1].append(page)
            else:
                groups.append((page_type, [page]))

        # Batch each group at the appropriate size
        batches: list[list[tuple[int, bytes | None, str | None]]] = []
        for group_type, group_pages in groups:
            size = batch_size_text if group_type == "text" else batch_size_image
            start = 0
            while start < len(group_pages):
                end = min(start + size, len(group_pages))
                batches.append(list(group_pages[start:end]))
                start = end - overlap if end < len(group_pages) else end

        return batches

    async def examine_document(
        self,
        pages: list[Any],
        storage: Any,
        on_batch_complete: Any | None = None,
    ) -> ExaminerConsolidatedResult:
        """Orchestrate batch examination of an entire document.

        Batches run concurrently. Results are yielded progressively via
        on_batch_complete callback as each batch finishes (using asyncio.as_completed).

        Uses hybrid text+vision: pages with embedded text (ocr_text >= 50 chars)
        are sent as text, scanned pages are sent as images. Text-only batches
        use a larger batch size (EXAMINER_BATCH_SIZE_TEXT) since they're cheaper.

        Args:
            pages: List of Page ORM objects (must have page_number, image_uri, ocr_text).
            storage: StorageProvider instance for reading page images.
            on_batch_complete: Optional async callback(batch_index, batch_result)
                called as each batch completes. Used for progressive DB writes.

        Returns:
            ExaminerConsolidatedResult with all outputs.
        """
        settings = get_settings()
        batch_config = self._get_batch_config()
        batch_size_image = batch_config["batch_size_image"]
        batch_size_text = batch_config["batch_size_text"]
        concurrency = batch_config["concurrency"]
        stagger_ms = batch_config["stagger_ms"]
        overlap = getattr(settings, "EXAMINER_BATCH_OVERLAP", 1)

        # Sort pages by page_number
        sorted_pages = sorted(pages, key=lambda p: p.page_number)

        # Load page data — text for embedded-text pages, image for scanned pages
        async def _load_page(page: Any) -> tuple[int, bytes | None, str | None]:
            if page.ocr_text and len(page.ocr_text) >= 50:
                return (page.page_number, None, page.ocr_text)
            else:
                image_bytes = await storage.read(page.image_uri)
                return (page.page_number, image_bytes, None)

        page_data = await asyncio.gather(*[_load_page(p) for p in sorted_pages])
        page_data = sorted(page_data, key=lambda x: x[0])

        if not page_data:
            return ExaminerConsolidatedResult()

        # Log text vs image page counts
        text_count = sum(1 for _, _, t in page_data if t)
        image_count = len(page_data) - text_count
        logger.info(f"Page loading: {text_count} text pages, {image_count} image pages")

        # Build smart batches — larger for text, smaller for images
        batches = self._build_smart_batches(
            page_data, batch_size_image, batch_size_text, overlap
        )

        total_pages = len(page_data)

        # Set up adaptive rate limit controller
        rate_controller = RateLimitController(
            max_concurrency=concurrency,
            stagger_ms=stagger_ms,
        )

        logger.info(
            f"Examining {total_pages} pages in {len(batches)} batches "
            f"(text_batch={batch_size_text}, image_batch={batch_size_image}, "
            f"overlap={overlap}, concurrency={concurrency}, stagger={stagger_ms}ms)"
        )

        # Launch all batches concurrently, yield results progressively
        async def _examine_batch_task(
            i: int, batch: list[tuple[int, bytes | None, str | None]]
        ) -> tuple[int, ExaminerBatchResult]:
            await rate_controller.acquire(i)
            try:
                context = self._build_static_batch_context(i, len(batches), total_pages)
                logger.info(
                    f"Batch {i + 1}/{len(batches)}: pages "
                    f"{batch[0][0]}-{batch[-1][0]} ({len(batch)} pages)"
                )
                result = await self._call_with_rate_limit_retry(
                    batch, context, rate_controller=rate_controller,
                )
                rate_controller.record_success()
                return (i, result)
            finally:
                rate_controller.release()

        # Use as_completed for progressive streaming
        tasks = [_examine_batch_task(i, batch) for i, batch in enumerate(batches)]
        batch_results: list[ExaminerBatchResult] = [None] * len(batches)  # type: ignore[list-item]

        for coro in asyncio.as_completed(tasks):
            batch_idx, result = await coro
            batch_results[batch_idx] = result
            if on_batch_complete:
                await on_batch_complete(batch_idx, result)

        # Pre-fill transcriptions for text-embedded pages (LLM was told to skip these)
        for br in batch_results:
            existing_pages = {t.page_number for t in br.page_transcriptions}
            for pn, _, text in page_data:
                if text and pn not in existing_pages:
                    br.page_transcriptions.append(
                        PageTranscription(page_number=pn, text=text)
                    )

        consolidated = self.consolidate(batch_results)

        # Populate rate limit metrics
        metrics = rate_controller.get_metrics()
        consolidated.rate_limit_hits = metrics["rate_limit_hits"]
        consolidated.total_retries = metrics["total_retries"]

        return consolidated

    async def examine_pdf_batch(
        self,
        pdf_bytes: bytes,
        page_range: tuple[int, int],
        total_pages: int,
        batch_index: int,
        total_batches: int,
        system_prompt_override: str | None = None,
        json_schema_override: dict[str, Any] | None = None,
    ) -> ExaminerBatchResult:
        """Examine a batch of pages sent as a native PDF chunk.

        Args:
            pdf_bytes: Raw bytes of the PDF chunk (subset of pages).
            page_range: (start_page, end_page) 1-based inclusive.
            total_pages: Total pages in the full document.
            batch_index: 0-based batch index.
            total_batches: Total number of batches.
            system_prompt_override: Custom system prompt for specialized extraction.
            json_schema_override: Custom JSON schema for specialized extraction.

        Returns:
            ExaminerBatchResult with transcriptions, sections, extractions, flags.
        """
        settings = get_settings()
        configured_max_tokens = getattr(settings, "EXAMINER_MAX_OUTPUT_TOKENS", 16384)
        call_timeout = getattr(settings, "EXAMINER_CALL_TIMEOUT", 300)

        max_output_tokens = configured_max_tokens

        content: list[dict[str, Any]] = []

        # Add batch context for multi-batch documents
        context = self._build_static_batch_context(batch_index, total_batches, total_pages)
        if context:
            content.append({"type": "text", "text": self._format_static_context(context)})

        # Instruction text
        start_page, end_page = page_range
        instruction = (
            f"Examine the following pages {start_page}-{end_page} "
            f"(of {total_pages} total). "
            f"Transcribe all text, identify sections, extract structured data, "
            f"and flag any issues. Page numbers in your output should be absolute "
            f"(starting from {start_page})."
        )
        content.append({"type": "text", "text": instruction})

        # Add PDF as inline content
        content.append({"type": "pdf", "pdf": {"data": pdf_bytes}})

        messages = [{"role": "user", "content": content}]

        # Use override schema/prompt if provided (specialized extraction)
        prompt = system_prompt_override or self.SYSTEM_PROMPT
        schema = json_schema_override or self.JSON_SCHEMA

        t0 = time.monotonic()
        usage: dict[str, Any] = {}

        # Try cached call first
        cache_name = await self._ensure_context_cache(schema)
        if cache_name:
            try:
                result, usage = await self.call_json_structured_cached(
                    cache_name=cache_name,
                    messages=messages,
                    json_schema=schema,
                    max_tokens=max_output_tokens,
                    temperature=0.0,
                    timeout=call_timeout,
                    return_usage=True,
                )
                elapsed = time.monotonic() - t0
                batch_result = self._parse_batch_result(result)
                batch_result.llm_elapsed_seconds = round(elapsed, 3)
                batch_result.input_tokens = usage.get("input_tokens")
                batch_result.output_tokens = usage.get("output_tokens")
                return batch_result
            except Exception as e:
                logger.warning(f"Cached PDF call failed, falling back to uncached: {e}")
                t0 = time.monotonic()

        # Fallback: uncached call
        result, usage = await self.call_json_structured(
            system_prompt=prompt,
            messages=messages,
            json_schema=schema,
            max_tokens=max_output_tokens,
            temperature=0.0,
            timeout=call_timeout,
            return_usage=True,
        )
        elapsed = time.monotonic() - t0

        batch_result = self._parse_batch_result(result)
        batch_result.llm_elapsed_seconds = round(elapsed, 3)
        batch_result.input_tokens = usage.get("input_tokens")
        batch_result.output_tokens = usage.get("output_tokens")
        return batch_result

    async def examine_document_native_pdf(
        self,
        pdf_bytes: bytes,
        total_pages: int,
        batch_size: int,
        concurrency: int,
        on_batch_complete: Any | None = None,
        page_ranges: list[tuple[int, int]] | None = None,
        chunk_doc_types: list[str] | None = None,
    ) -> ExaminerConsolidatedResult:
        """Orchestrate native PDF examination by splitting into chunks.

        Splits the PDF into page-range chunks using PyMuPDF, sends each
        chunk directly to Gemini as a PDF, and consolidates results.

        Args:
            pdf_bytes: Full PDF file bytes.
            total_pages: Total pages in the PDF.
            batch_size: Pages per chunk (used only when page_ranges is None).
            concurrency: Max parallel Gemini calls.
            on_batch_complete: Optional async callback(batch_index, batch_result).
            page_ranges: Optional list of (start_page, end_page) tuples (1-based
                inclusive) for document-aligned chunking. When provided, overrides
                fixed-size batch_size splitting.
            chunk_doc_types: Optional list of document types, one per chunk
                (aligned with page_ranges). Used for specialized extraction routing.

        Returns:
            ExaminerConsolidatedResult with all outputs.
        """
        import fitz

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        actual_pages = len(doc)

        # Build chunk list: (chunk_bytes, page_range)
        chunks: list[tuple[bytes, tuple[int, int]]] = []

        if page_ranges:
            # Document-aligned chunking — use provided page ranges
            for start_page, end_page in page_ranges:
                # Convert 1-based inclusive to 0-based for fitz
                chunk_doc = fitz.open()
                chunk_doc.insert_pdf(doc, from_page=start_page - 1, to_page=end_page - 1)
                chunk_bytes = chunk_doc.tobytes()
                chunk_doc.close()
                chunks.append((chunk_bytes, (start_page, end_page)))
        else:
            # Fixed-size chunking (default behavior)
            for start in range(0, actual_pages, batch_size):
                end = min(start + batch_size, actual_pages)
                chunk_doc = fitz.open()
                chunk_doc.insert_pdf(doc, from_page=start, to_page=end - 1)
                chunk_bytes = chunk_doc.tobytes()
                chunk_doc.close()
                # page_range is 1-based inclusive
                chunks.append((chunk_bytes, (start + 1, end)))

        doc.close()

        total_batches = len(chunks)
        chunking_mode = "document-aligned" if page_ranges else f"fixed-size ({batch_size}pp)"

        # Set up adaptive rate limit controller with staggered launch
        stagger_ms = getattr(get_settings(), "NATIVE_PDF_STAGGER_MS", 200)
        rate_controller = RateLimitController(
            max_concurrency=concurrency,
            stagger_ms=stagger_ms,
        )

        # Resolve specialized extraction configs per chunk
        specialized = getattr(get_settings(), "SPECIALIZED_EXTRACTION_ENABLED", True)
        chunk_configs: list[tuple[str | None, dict | None]] = []  # (prompt, schema) per chunk
        if specialized and chunk_doc_types and len(chunk_doc_types) == total_batches:
            from app.micro_apps.title_intelligence.ai.extractors.registry import get_extraction_config
            for dt in chunk_doc_types:
                cfg = get_extraction_config(dt)
                if cfg.doc_type != "generic":
                    chunk_configs.append((cfg.system_prompt, cfg.json_schema))
                else:
                    chunk_configs.append((None, None))
            specialized_count = sum(1 for p, _ in chunk_configs if p is not None)
            logger.info(
                f"Specialized extraction: {specialized_count}/{total_batches} chunks "
                f"use focused prompts"
            )
        else:
            chunk_configs = [(None, None)] * total_batches

        logger.info(
            f"Native PDF: splitting {actual_pages} pages into {total_batches} chunks "
            f"({chunking_mode}, concurrency={concurrency}, stagger={stagger_ms}ms)"
        )

        async def _pdf_batch_task(
            i: int, chunk_bytes: bytes, page_range: tuple[int, int]
        ) -> tuple[int, ExaminerBatchResult]:
            await rate_controller.acquire(i)
            try:
                prompt_override, schema_override = chunk_configs[i]
                doc_type_label = chunk_doc_types[i] if chunk_doc_types and i < len(chunk_doc_types) else "generic"
                logger.debug(
                    f"PDF batch {i + 1}/{total_batches}: pages {page_range[0]}-{page_range[1]} "
                    f"(doc_type={doc_type_label})"
                )
                result = await self._call_pdf_with_rate_limit_retry(
                    chunk_bytes, page_range, actual_pages, i, total_batches,
                    rate_controller=rate_controller,
                    system_prompt_override=prompt_override,
                    json_schema_override=schema_override,
                )
                rate_controller.record_success()
                return (i, result)
            finally:
                rate_controller.release()

        tasks = [
            _pdf_batch_task(i, chunk_bytes, page_range)
            for i, (chunk_bytes, page_range) in enumerate(chunks)
        ]
        batch_results: list[ExaminerBatchResult] = [None] * total_batches  # type: ignore[list-item]

        for coro in asyncio.as_completed(tasks):
            batch_idx, result = await coro
            batch_results[batch_idx] = result
            if on_batch_complete:
                await on_batch_complete(batch_idx, result)

        consolidated = self.consolidate(batch_results)

        # Populate rate limit metrics from controller
        metrics = rate_controller.get_metrics()
        consolidated.rate_limit_hits = metrics["rate_limit_hits"]
        consolidated.total_retries = metrics["total_retries"]
        if metrics["rate_limit_hits"] > 0:
            logger.warning(
                f"Rate limit summary: {metrics['rate_limit_hits']} hits, "
                f"{metrics['total_retries']} total retries"
            )

        return consolidated

    async def _call_pdf_with_rate_limit_retry(
        self,
        pdf_bytes: bytes,
        page_range: tuple[int, int],
        total_pages: int,
        batch_index: int,
        total_batches: int,
        max_retries: int = 3,
        rate_controller: RateLimitController | None = None,
        system_prompt_override: str | None = None,
        json_schema_override: dict[str, Any] | None = None,
    ) -> ExaminerBatchResult:
        """Call examine_pdf_batch with exponential backoff on rate limit errors."""
        backoff = 5.0
        for attempt in range(max_retries + 1):
            try:
                return await self.examine_pdf_batch(
                    pdf_bytes, page_range, total_pages, batch_index, total_batches,
                    system_prompt_override=system_prompt_override,
                    json_schema_override=json_schema_override,
                )
            except Exception as e:
                if _is_rate_limit_error(e) and attempt < max_retries:
                    if rate_controller:
                        backoff = rate_controller.record_rate_limit()
                    logger.warning(
                        f"Rate limited on PDF batch {batch_index + 1} "
                        f"(attempt {attempt + 1}), backing off {backoff:.0f}s"
                    )
                    await asyncio.sleep(backoff)
                    if not rate_controller:
                        backoff *= 2
                elif attempt < max_retries:
                    if rate_controller:
                        rate_controller.record_retry()
                    logger.warning(
                        f"PDF batch {batch_index + 1} failed "
                        f"(attempt {attempt + 1}): {e}"
                    )
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
        raise RuntimeError("Exhausted rate limit retries")

    async def _call_with_rate_limit_retry(
        self,
        batch: list[tuple[int, bytes | None, str | None]],
        batch_context: dict[str, Any] | None,
        max_retries: int = 3,
        rate_controller: RateLimitController | None = None,
    ) -> ExaminerBatchResult:
        """Call examine_batch with exponential backoff on rate limit (429) errors."""
        backoff = 5.0
        for attempt in range(max_retries + 1):
            try:
                return await self.examine_batch(batch, batch_context)
            except Exception as e:
                if _is_rate_limit_error(e) and attempt < max_retries:
                    if rate_controller:
                        backoff = rate_controller.record_rate_limit()
                    logger.warning(
                        f"Rate limited on batch (attempt {attempt + 1}), "
                        f"backing off {backoff:.0f}s"
                    )
                    await asyncio.sleep(backoff)
                    if not rate_controller:
                        backoff *= 2
                elif attempt < max_retries:
                    if rate_controller:
                        rate_controller.record_retry()
                    logger.warning(f"Batch failed (attempt {attempt + 1}): {e}")
                    await asyncio.sleep(2 ** attempt)
                else:
                    raise
        # Should not reach here, but satisfy type checker
        raise RuntimeError("Exhausted rate limit retries")
