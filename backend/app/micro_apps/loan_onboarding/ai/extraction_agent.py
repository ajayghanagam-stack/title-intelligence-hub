"""Vision-grounded structured-field extractor (Phase 1).

The model receives, for one stack:
  - the page image(s) (so it can read values it can't see in OCR alone),
  - the compact OCR token table for the same pages
    (``[{index, text}, …]`` — bboxes deliberately stripped so the model
    never sees coordinates), and
  - the list of LOS-canonical field names the loan officer configured.

…and emits, per requested field:
  ``{value, evidence: {page, token_indices: [int, …]}, confidence}``.

The model never returns a bbox. Server-side, ``grounding_validator.py``
joins ``token_indices`` back to the original OCR word table to compute a
union bbox in 0..1 unit space — the only bbox that ever lands on
``LOExtraction.fields[].location``.

This replaces the legacy text-only extractor + post-hoc
``field_grounding.py`` substring search. See
``docs/phase0/grounding-contract.md`` for the full spec.
"""
from __future__ import annotations

import base64
import logging
import uuid
from typing import Any

from app.ai.base_service import BaseAIService
from app.micro_apps.loan_onboarding.schemas.extraction import (
    ExtractedField,
    StackExtraction,
)
from app.micro_apps.loan_onboarding.schemas.grounding import (
    EvidenceCitation,
    GroundedExtractionRaw,
    GroundedFieldRaw,
)
from app.micro_apps.loan_onboarding.services.grounding_validator import (
    ValidationContext,
    build_validation_context,
    validate_field,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You extract specific fields from a single mortgage-document stack and \
cite the OCR tokens that prove each value.

For every requested field you will return:
  - value: the field's value as a short string (≤ 200 chars). Empty \
string when not present on any provided page.
  - evidence: {page, token_indices} — the page number and the indices \
of the OCR tokens (from the supplied token table) that together spell \
the value. Tokens may be non-contiguous (e.g. \"Marcus\" + \"Webb\" \
across two columns). OMIT evidence entirely when value is empty.
  - confidence: 0.0–1.0 — your subjective confidence in the value.

HARD RULES (any violation invalidates the citation):
1. token_indices must point to tokens whose joined ``text`` (lower-case, \
whitespace-normalized) substantially overlaps the value you returned.
2. Never invent token indices. If you can't cite tokens that prove the \
value, return value=\"\" with no evidence.
3. Never output bboxes, pixel coordinates, or geometric data. The server \
re-derives coordinates from your token citation.
4. Emit exactly one record per requested field, in request order. Don't \
drop, merge, rename, or invent fields.
5. Keep value short — usually a single line of the document. Don't \
echo entire paragraphs.

OUTPUT FORMAT:
A single JSON object:
  {
    \"stack_id\": \"<echoed>\",
    \"doc_type\":  \"<echoed>\",
    \"fields\": [
       { \"name\": \"<echoed>\",
         \"value\": \"...\" | \"\",
         \"evidence\": {\"page\": int, \"token_indices\": [int, ...]} | omitted,
         \"confidence\": 0.0–1.0 }
    ]
  }
"""


# Strict JSON schema — bbox is NOT in the schema, so even if the model
# tried to return one it would fail validation.
_EVIDENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "page": {"type": "integer", "minimum": 1},
        "token_indices": {
            "type": "array",
            "items": {"type": "integer", "minimum": 0},
            "minItems": 1,
            "maxItems": 64,
        },
    },
    "required": ["page", "token_indices"],
}


_FIELD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "maxLength": 200},
        "value": {"type": "string", "maxLength": 2000},
        "evidence": _EVIDENCE_SCHEMA,
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
    },
    "required": ["name", "value", "confidence"],
}


_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "stack_id": {"type": "string"},
        "doc_type": {"type": "string"},
        "fields": {"type": "array", "items": _FIELD_SCHEMA},
    },
    "required": ["stack_id", "doc_type", "fields"],
}


# ── Per-stack input shape ─────────────────────────────────────────────


# A single page's payload as fed to the agent. ``image_bytes`` is the
# rendered page JPEG (the model reads coordinates from this); ``words``
# is the OCR token table from ``services/ocr_words.py``. The token text
# is what the model is allowed to cite — we strip ``bbox`` from the
# table sent to the model so it has no way to invent geometry.
def _strip_bboxes(words: list[dict]) -> list[dict[str, Any]]:
    """Drop ``bbox`` from each OCR word — model only sees text + index."""
    out: list[dict[str, Any]] = []
    for w in words:
        if not isinstance(w, dict):
            continue
        try:
            idx = int(w["index"])
            txt = str(w["text"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append({"index": idx, "text": txt})
    return out


class ExtractionAgent(BaseAIService):
    """Vision-grounded extractor — Claude with image + token table."""

    SYSTEM_PROMPT = SYSTEM_PROMPT

    def __init__(self, org_id: uuid.UUID, model_override: str | None = None):
        super().__init__(org_id, role="validator", provider_override="claude")
        if model_override:
            # litellm needs a provider-prefixed model id.
            self.model = (
                model_override if "/" in model_override else f"anthropic/{model_override}"
            )

    async def extract_fields(
        self,
        stack_id: str,
        doc_type: str,
        pages: list[dict[str, Any]],
        requested_fields: list[str],
        *,
        field_data_types: dict[str, str] | None = None,
        timeout: int = 60,
    ) -> StackExtraction:
        """Extract ``requested_fields`` from one stack.

        Args:
            stack_id: opaque echo, used by the model for self-consistency.
            doc_type: opaque echo (drives nothing in the prompt — the
                model treats every stack the same shape).
            pages: ``[{page_number, image_bytes, words}, ...]`` — one entry
                per page in the stack. ``page_number`` is 1-indexed within
                the stack. ``image_bytes`` is JPEG; ``words`` is the OCR
                token list per ``services/ocr_words.py``.
            requested_fields: LOS-canonical field names, in the order to
                emit them.
            field_data_types: optional ``{field_name: "currency"|"date"|...}``
                used by the validation gate's regex check (Phase 1 step 7).

        Returns a fully-validated ``StackExtraction`` — every field is
        already passed through ``grounding_validator.validate_field`` and
        carries either a server-computed bbox or ``status="ungrounded"``.
        Never raises on model failure — falls back to all-missing.
        """
        if not requested_fields:
            return StackExtraction(stack_id=stack_id, doc_type=doc_type, fields=[])

        if not pages:
            return _conservative_fallback(stack_id, doc_type, requested_fields)

        # Build the user-message content: alternating image + token table
        # blocks per page, then the field list.
        content: list[dict[str, Any]] = []
        compact_pages: list[dict[str, Any]] = []
        for p in pages:
            page_num = p.get("page_number")
            image_bytes = p.get("image_bytes")
            words = p.get("words") or []
            if not isinstance(page_num, int) or not image_bytes:
                continue
            content.append({
                "type": "text",
                "text": f"--- Page {page_num} image follows ---",
            })
            # OpenAI-format image block. litellm's validator
            # (validate_chat_completion_user_messages) rejects Anthropic's
            # native {"type":"image","source":{...}} shape — its allowlist
            # is ["text","image_url","input_audio",...]. litellm transforms
            # this into Anthropic's native block downstream when the
            # provider is anthropic/*.
            b64 = base64.b64encode(image_bytes).decode("ascii")
            content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            })
            compact_pages.append({
                "page_number": page_num,
                "tokens": _strip_bboxes(words),
            })

        if not compact_pages:
            return _conservative_fallback(stack_id, doc_type, requested_fields)

        instruction = {
            "stack_id": stack_id,
            "doc_type": doc_type,
            "requested_fields": requested_fields,
            "pages": compact_pages,
        }
        content.append({
            "type": "text",
            "text": (
                "Extract the requested fields. Cite OCR token indices "
                "(not bboxes) as evidence for every non-empty value. "
                "Return one JSON object per the schema.\n\n"
                f"{instruction}"
            ),
        })

        try:
            raw = await self.call_json_structured(
                system_prompt=self.SYSTEM_PROMPT,
                messages=[{"role": "user", "content": content}],
                json_schema=_RESULT_SCHEMA,
                max_tokens=4096,
                temperature=0.0,
                timeout=timeout,
            )
        except Exception as e:
            logger.warning(
                "ExtractionAgent call failed for stack_id=%s: %s", stack_id, e
            )
            return _conservative_fallback(stack_id, doc_type, requested_fields)

        # Coerce + validate.
        grounded = _coerce_grounded(
            raw or {}, stack_id, doc_type, requested_fields,
        )
        ctx = build_validation_context([
            {"page_number": p["page_number"], "ocr_words": p.get("words") or []}
            for p in pages
            if isinstance(p.get("page_number"), int)
        ])
        return _validate_all(
            grounded, ctx, field_data_types or {},
            stack_id=stack_id, doc_type=doc_type,
        )


# ── Coercion / validation glue ───────────────────────────────────────


def _coerce_grounded(
    raw: dict[str, Any],
    expected_stack_id: str,
    expected_doc_type: str,
    requested_fields: list[str],
) -> GroundedExtractionRaw:
    """Coerce raw model output into a strict ``GroundedExtractionRaw``.

    - Always emits exactly one record per requested field, in request
      order. Extra fields are dropped; missing ones become empty value.
    - Confidence clamped to [0, 1]. Bad evidence shapes are dropped (the
      validation gate then reports ``no_evidence_cite``).
    """
    raw_fields = raw.get("fields") or []
    by_name: dict[str, dict[str, Any]] = {}
    for f in raw_fields:
        if not isinstance(f, dict):
            continue
        name = str(f.get("name", "")).strip()
        if name:
            by_name[name] = f

    coerced: list[GroundedFieldRaw] = []
    for requested in requested_fields:
        rec = by_name.get(requested) or {}
        value = str(rec.get("value") or "").strip()[:2000]
        try:
            confidence = float(rec.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        evidence: EvidenceCitation | None = None
        ev_raw = rec.get("evidence")
        if isinstance(ev_raw, dict):
            try:
                page = int(ev_raw.get("page"))
                idx_list = ev_raw.get("token_indices") or []
                if isinstance(idx_list, list) and idx_list:
                    indices = [int(i) for i in idx_list if isinstance(i, (int, float))]
                    if indices:
                        evidence = EvidenceCitation(
                            page=page, token_indices=indices,
                        )
            except (TypeError, ValueError):
                evidence = None

        coerced.append(GroundedFieldRaw(
            name=requested,
            value=value,
            evidence=evidence,
            confidence=confidence,
        ))

    # GroundedExtractionRaw is fields-only with extra="forbid" — the
    # stack_id / doc_type kwargs are kept on this function's signature
    # purely as a defensive echo of what the model was told to return,
    # but they aren't part of the persisted shape.
    return GroundedExtractionRaw(fields=coerced)


def _validate_all(
    grounded: GroundedExtractionRaw,
    ctx: ValidationContext,
    field_data_types: dict[str, str],
    *,
    stack_id: str,
    doc_type: str,
) -> StackExtraction:
    """Run every coerced field through the validation gate."""
    out: list[ExtractedField] = []
    for f in grounded.fields:
        outcome = validate_field(
            f, ctx=ctx, data_type=field_data_types.get(f.name),
        )
        if outcome.rejected_reason:
            logger.info(
                "Grounding gate rejected field %r (stack=%s): %s",
                f.name, stack_id, outcome.rejected_reason,
            )
        out.append(outcome.field)
    return StackExtraction(
        stack_id=stack_id,
        doc_type=doc_type,
        fields=out,
    )


def _conservative_fallback(
    stack_id: str, doc_type: str, requested_fields: list[str]
) -> StackExtraction:
    """All fields → missing. Used when the LLM call or page payload fails."""
    return StackExtraction(
        stack_id=stack_id,
        doc_type=doc_type,
        fields=[
            ExtractedField(name=name, value="", confidence=0.0, status="missing")
            for name in requested_fields
        ],
    )
