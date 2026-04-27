"""Claude-backed per-stack validator for natural-language rules.

Preset rules run deterministically via `services.validation_presets` — this
agent is only invoked for *custom* rules written in English by the loan
officer (e.g. "Make sure the property address on the appraisal matches the
1003"). Output conforms to a subset of the ValidationSchema: we produce one
`RuleEvaluation` per rule.

Design:
- Model defaults to `LO_VALIDATOR_MODEL` (Claude Sonnet).
- Temperature 0.0 and strict JSON schema keep output stable across runs.
- Agent is scoped to a single stack per call; the orchestrator fans out
  across stacks in parallel (semaphore-limited) at the stage level.
- Unknown / malformed responses collapse into a conservative `passed=False`
  evaluation — we never silently auto-pass an NL rule.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from app.ai.base_service import BaseAIService
from app.micro_apps.loan_onboarding.schemas.validation import (
    RuleEvaluation,
    RuleLocation,
)

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are a mortgage loan package rule verifier. Given a single document stack \
(contiguous pages of the same doc_type) and a natural-language rule written \
by the loan officer, decide whether the rule PASSES or FAILS based ONLY on \
the page text and detected_fields provided.

OUTPUT RULES:
1. Produce one JSON object with fields: rule_id, rule_source="custom", \
passed (bool), evidence (<=200 chars, quoted from source text), and an \
optional location {page, bbox}.
2. If the rule is ambiguous OR you do not have enough evidence to confirm it \
passes, return passed=false. Do not guess.
3. The evidence field must be a direct quote or paraphrase of the supporting \
content — never invent text. If you cannot find evidence, say "No evidence \
found in provided pages" and set passed=false.
4. Do not output any doc_type that was not provided. Do not output scores or \
probabilities.
"""


_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rule_id": {"type": "string"},
        "rule_source": {"type": "string", "enum": ["custom"]},
        "passed": {"type": "boolean"},
        "evidence": {"type": "string", "maxLength": 200},
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
    "required": ["rule_id", "rule_source", "passed", "evidence"],
}


class StackValidatorAgent(BaseAIService):
    """Evaluates a single natural-language rule against a single stack."""

    SYSTEM_PROMPT = SYSTEM_PROMPT

    def __init__(self, org_id: uuid.UUID, model_override: str | None = None):
        super().__init__(org_id, role="validator", provider_override="claude")
        if model_override:
            self.model = model_override

    async def validate_rule(
        self,
        stack_id: str,
        doc_type: str,
        page_snippets: list[dict[str, Any]],
        rule_id: str,
        rule_text: str,
        timeout: int = 60,
    ) -> RuleEvaluation:
        """Run one NL rule against one stack.

        page_snippets: list of {page_number, text, detected_fields:[{field_name,value,bbox}]}
        """
        user_blob = {
            "stack_id": stack_id,
            "doc_type": doc_type,
            "pages": page_snippets,
            "rule": {"rule_id": rule_id, "text": rule_text},
        }
        messages = [{
            "role": "user",
            "content": (
                f"Evaluate the rule below against the stack's pages and "
                f"return a single JSON object per the schema.\n\n"
                f"{user_blob}"
            ),
        }]
        try:
            raw = await self.call_json_structured(
                system_prompt=self.SYSTEM_PROMPT,
                messages=messages,
                json_schema=_RESULT_SCHEMA,
                max_tokens=1024,
                temperature=0.0,
                timeout=timeout,
            )
        except Exception as e:
            logger.warning(
                f"StackValidatorAgent call failed for rule_id={rule_id}: {e}"
            )
            return _conservative_fallback(rule_id, "LLM call failed; defaulting to fail")

        return _coerce(raw or {}, rule_id)


def _conservative_fallback(rule_id: str, reason: str) -> RuleEvaluation:
    return RuleEvaluation(
        rule_id=rule_id,
        rule_source="custom",
        passed=False,
        evidence=reason[:200],
        location=None,
    )


def _coerce(raw: dict[str, Any], expected_rule_id: str) -> RuleEvaluation:
    rid = str(raw.get("rule_id") or expected_rule_id)
    passed = bool(raw.get("passed", False))
    evidence = str(raw.get("evidence") or "")[:200]
    location: RuleLocation | None = None
    loc_raw = raw.get("location")
    if isinstance(loc_raw, dict):
        bbox = loc_raw.get("bbox")
        try:
            if isinstance(bbox, list) and len(bbox) == 4:
                location = RuleLocation(
                    page=int(loc_raw.get("page", 1)),
                    bbox=[float(x) for x in bbox],
                )
        except (TypeError, ValueError):
            location = None
    return RuleEvaluation(
        rule_id=rid,
        rule_source="custom",
        passed=passed,
        evidence=evidence or "No evidence provided",
        location=location,
    )
