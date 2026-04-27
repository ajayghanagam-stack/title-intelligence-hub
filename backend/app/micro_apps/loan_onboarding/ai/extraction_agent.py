"""Claude-backed structured-field extractor for loan-onboarding stacks.

Runs after the validate stage when the package has `extraction_enabled=True`.
Per stack, the agent receives:
  - the doc_type
  - the list of field labels the loan officer configured (from
    `LOPackage.extraction_fields_by_doc[doc_type]`)
  - the page snippets (text + heuristic detected_fields) for the stack

…and emits one record per requested field with `value`, `confidence`,
`status`, and an optional page/bbox citation. Missing fields are emitted
explicitly as `status="missing"` with empty value — never silently
dropped, because the LOS feed depends on a stable column shape.

Design parallels `StackValidatorAgent`: temperature 0.0, strict JSON
schema, conservative fallback (status="missing") on any failure. The
orchestrator fans out across stacks in parallel via a semaphore.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from app.ai.base_service import BaseAIService
from app.micro_apps.loan_onboarding.schemas.extraction import (
    ExtractedField,
    FieldLocation,
    StackExtraction,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are a mortgage loan-document field extractor. For one document stack \
(contiguous pages of the same doc_type) and a list of requested field \
labels chosen by the loan officer, locate each field's value in the \
provided page text. Output a strict JSON object per the supplied schema.

OUTPUT RULES:
1. Emit exactly one record per requested field, in the same order the \
fields were requested. Never drop, merge, or invent fields.
2. For each field, set:
   - name: echoed verbatim from the request
   - value: the extracted value as a short string (<=200 chars, trimmed); \
empty string when not found
   - confidence: 0.0-1.0; reflect how clearly the value is supported by the \
provided text. 0.0 when not found.
   - status: one of "located" | "low_confidence" | "missing". Use "missing" \
when the field cannot be found. Use "low_confidence" when you found a \
candidate but are <0.8 confident.
   - location: optional — include {page, bbox:[x1,y1,x2,y2]} ONLY if you \
have direct evidence on a specific page. Omit it otherwise. Use bbox \
[0,0,0,0] if you know the page but not the box.
3. Never fabricate a value. If the field is not on any provided page, \
emit it as missing with empty value.
4. Do not output fields that were not requested. Do not output extra \
top-level keys.
"""


_FIELD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "maxLength": 200},
        "value": {"type": "string", "maxLength": 2000},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "status": {
            "type": "string",
            "enum": ["located", "low_confidence", "missing"],
        },
        "location": {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "minimum": 1},
                "bbox": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 4,
                    "maxItems": 4,
                },
            },
            "required": ["page", "bbox"],
        },
    },
    "required": ["name", "value", "confidence", "status"],
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


# Below this confidence we downgrade `status` from "located" to
# "low_confidence" even if the model marked it located. Mirrors the
# prototype's amber/red split on the dashboard.
LOW_CONFIDENCE_THRESHOLD = 0.8


class ExtractionAgent(BaseAIService):
    """Extracts a fixed list of fields from one stack."""

    SYSTEM_PROMPT = SYSTEM_PROMPT

    def __init__(self, org_id: uuid.UUID, model_override: str | None = None):
        super().__init__(org_id, role="validator", provider_override="claude")
        if model_override:
            self.model = model_override

    async def extract_fields(
        self,
        stack_id: str,
        doc_type: str,
        page_snippets: list[dict[str, Any]],
        requested_fields: list[str],
        timeout: int = 60,
    ) -> StackExtraction:
        """Extract `requested_fields` from one stack's page snippets.

        page_snippets shape: [{page_number, text, detected_fields: [...]}, ...]
        """
        if not requested_fields:
            return StackExtraction(stack_id=stack_id, doc_type=doc_type, fields=[])

        user_blob = {
            "stack_id": stack_id,
            "doc_type": doc_type,
            "requested_fields": requested_fields,
            "pages": page_snippets,
        }
        messages = [{
            "role": "user",
            "content": (
                "Extract the requested fields from the stack below and return "
                "a single JSON object per the schema. Emit one record per "
                "requested field, in order.\n\n"
                f"{user_blob}"
            ),
        }]
        try:
            raw = await self.call_json_structured(
                system_prompt=self.SYSTEM_PROMPT,
                messages=messages,
                json_schema=_RESULT_SCHEMA,
                max_tokens=2048,
                temperature=0.0,
                timeout=timeout,
            )
        except Exception as e:
            logger.warning(
                f"ExtractionAgent call failed for stack_id={stack_id}: {e}"
            )
            return _conservative_fallback(stack_id, doc_type, requested_fields)

        return _coerce(raw or {}, stack_id, doc_type, requested_fields)


def _conservative_fallback(
    stack_id: str, doc_type: str, requested_fields: list[str]
) -> StackExtraction:
    """All fields → missing on any failure. Never silently drop fields."""
    return StackExtraction(
        stack_id=stack_id,
        doc_type=doc_type,
        fields=[
            ExtractedField(name=name, value="", confidence=0.0, status="missing")
            for name in requested_fields
        ],
    )


def _coerce(
    raw: dict[str, Any],
    expected_stack_id: str,
    expected_doc_type: str,
    requested_fields: list[str],
) -> StackExtraction:
    """Coerce raw LLM output into a StackExtraction.

    Behavioral guarantees:
    - The output always has exactly one record per requested field, in the
      same order as `requested_fields`. Extra fields the model invented
      are dropped. Missing fields are filled with status="missing".
    - confidence is clamped to [0, 1].
    - status is downgraded to "low_confidence" when status="located" but
      confidence < LOW_CONFIDENCE_THRESHOLD.
    """
    raw_fields = raw.get("fields") or []
    by_name: dict[str, dict[str, Any]] = {}
    for f in raw_fields:
        if not isinstance(f, dict):
            continue
        name = str(f.get("name", "")).strip()
        if name:
            by_name[name] = f

    coerced: list[ExtractedField] = []
    for requested in requested_fields:
        rec = by_name.get(requested) or {}
        try:
            confidence = float(rec.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        value = str(rec.get("value") or "").strip()[:2000]
        status = str(rec.get("status") or "missing")
        if status not in ("located", "low_confidence", "missing"):
            status = "missing"

        # If there's no value, force missing regardless of model output —
        # an empty string is never a real located value.
        if not value:
            status = "missing"
            confidence = 0.0
        elif status == "located" and confidence < LOW_CONFIDENCE_THRESHOLD:
            status = "low_confidence"

        location: FieldLocation | None = None
        loc_raw = rec.get("location")
        if isinstance(loc_raw, dict):
            bbox = loc_raw.get("bbox")
            try:
                if isinstance(bbox, list) and len(bbox) == 4:
                    location = FieldLocation(
                        page=int(loc_raw.get("page", 1)),
                        bbox=[float(x) for x in bbox],
                    )
            except (TypeError, ValueError):
                location = None

        coerced.append(ExtractedField(
            name=requested,
            value=value,
            confidence=confidence,
            status=status,  # type: ignore[arg-type]
            location=location,
        ))

    return StackExtraction(
        stack_id=expected_stack_id,
        doc_type=expected_doc_type,
        fields=coerced,
    )
