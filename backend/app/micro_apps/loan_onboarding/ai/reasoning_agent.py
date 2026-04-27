"""Cross-document reasoning agent for Loan Onboarding (Claude Opus).

The validate stage produces per-stack rule results. The review stage calls
this agent to:

1. Look across every stack in the package (cross-doc reasoning)
2. Flag missing required doc_types
3. Spot inconsistencies between stacks (e.g. borrower name on 1003 vs paystub)
4. Produce a final HITL recommendation per stack

Output is a structured `PackageReasoningOutput` with a list of per-stack
`StackReasoning` entries and a list of `package_level_issues`.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.ai.base_service import BaseAIService

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """\
You are a senior mortgage loan reviewer. Given every document stack in a \
loan package (with doc_type, preset+custom rule results, detected fields, \
and overall_confidence), perform cross-document reasoning and return:

- per-stack decisions: accept | needs_review | reject
- per-stack reasoning: one sentence explaining the decision
- package-level issues: missing required doc_types, cross-document \
inconsistencies (borrower name mismatches, income figures that don't add up, \
property address discrepancies), and any other concerns a human reviewer \
should see.

RULES:
1. A stack with rule_failures should be needs_review or reject — never accept.
2. A stack with overall_confidence below the package's HITL threshold must be \
needs_review.
3. Your reasoning must cite specific evidence from the supplied data. Do not \
invent facts.
4. Be conservative: when in doubt, escalate to needs_review (not reject).
"""


StackDecision = Literal["accept", "needs_review", "reject"]


class StackReasoning(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stack_id: str
    decision: StackDecision
    reasoning: str = Field(max_length=500)


class PackageLevelIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issue_type: str  # e.g. "missing_required_doc_type", "borrower_name_mismatch"
    description: str = Field(max_length=500)
    affected_stack_ids: list[str] = Field(default_factory=list)


class PackageReasoningOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stacks: list[StackReasoning]
    package_level_issues: list[PackageLevelIssue] = Field(default_factory=list)


_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "stacks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "stack_id": {"type": "string"},
                    "decision": {
                        "type": "string",
                        "enum": ["accept", "needs_review", "reject"],
                    },
                    "reasoning": {"type": "string", "maxLength": 500},
                },
                "required": ["stack_id", "decision", "reasoning"],
            },
        },
        "package_level_issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "issue_type": {"type": "string"},
                    "description": {"type": "string", "maxLength": 500},
                    "affected_stack_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["issue_type", "description"],
            },
        },
    },
    "required": ["stacks"],
}


class ReasoningAgent(BaseAIService):
    """Claude Opus cross-document reasoner."""

    SYSTEM_PROMPT = SYSTEM_PROMPT

    def __init__(self, org_id: uuid.UUID, model_override: str | None = None):
        super().__init__(org_id, role="reasoner", provider_override="claude")
        if model_override:
            self.model = model_override

    async def reason(
        self,
        package_summary: dict[str, Any],
        timeout: int = 120,
    ) -> PackageReasoningOutput:
        """Cross-document reasoning pass.

        `package_summary` should contain:
          - required_doc_types: list[str]
          - hitl_threshold: float
          - stacks: list of {stack_id, doc_type, first_page, last_page,
                             overall_confidence, rules_passed, rules_total,
                             field_snippets: {...}}
        """
        messages = [{
            "role": "user",
            "content": (
                "Here is the full package. Produce a cross-document "
                "reasoning report per the schema.\n\n"
                f"{package_summary}"
            ),
        }]
        try:
            raw = await self.call_json_structured(
                system_prompt=self.SYSTEM_PROMPT,
                messages=messages,
                json_schema=_JSON_SCHEMA,
                max_tokens=4096,
                temperature=0.0,
                timeout=timeout,
            )
        except Exception as e:
            logger.warning(f"ReasoningAgent call failed: {e}. Falling back to needs_review for all stacks.")
            return _fallback_output(package_summary)

        return _coerce(raw or {}, package_summary)


def _fallback_output(package_summary: dict[str, Any]) -> PackageReasoningOutput:
    """Safe fallback: every stack → needs_review. Never auto-accept on failure."""
    stacks = [
        StackReasoning(
            stack_id=str(s.get("stack_id") or ""),
            decision="needs_review",
            reasoning="Reasoning agent unavailable — conservatively routed to HITL",
        )
        for s in (package_summary.get("stacks") or [])
    ]
    return PackageReasoningOutput(
        stacks=stacks,
        package_level_issues=[PackageLevelIssue(
            issue_type="reasoning_unavailable",
            description="Cross-document reasoning did not complete; review all stacks manually",
        )],
    )


def _coerce(raw: dict[str, Any], package_summary: dict[str, Any]) -> PackageReasoningOutput:
    # Build a set of expected stack_ids so we can pad missing entries.
    expected = {str(s.get("stack_id") or "") for s in (package_summary.get("stacks") or [])}

    stacks_raw = raw.get("stacks") or []
    out_stacks: list[StackReasoning] = []
    seen: set[str] = set()
    for entry in stacks_raw:
        if not isinstance(entry, dict):
            continue
        sid = str(entry.get("stack_id") or "")
        if not sid or sid in seen:
            continue
        seen.add(sid)
        decision = entry.get("decision") or "needs_review"
        if decision not in ("accept", "needs_review", "reject"):
            decision = "needs_review"
        out_stacks.append(StackReasoning(
            stack_id=sid,
            decision=decision,  # type: ignore[arg-type]
            reasoning=str(entry.get("reasoning") or "")[:500] or "No reasoning provided",
        ))

    # Any expected stacks the model omitted → conservative needs_review.
    # sorted() here is load-bearing — iterating a set directly is hash-random
    # and would make _coerce output non-deterministic across runs.
    for sid in sorted(expected - seen):
        out_stacks.append(StackReasoning(
            stack_id=sid,
            decision="needs_review",
            reasoning="Stack omitted by reasoning agent — escalating to HITL",
        ))

    issues_raw = raw.get("package_level_issues") or []
    out_issues: list[PackageLevelIssue] = []
    for entry in issues_raw:
        if not isinstance(entry, dict):
            continue
        out_issues.append(PackageLevelIssue(
            issue_type=str(entry.get("issue_type") or "unknown"),
            description=str(entry.get("description") or "")[:500],
            affected_stack_ids=[str(x) for x in (entry.get("affected_stack_ids") or [])],
        ))

    return PackageReasoningOutput(stacks=out_stacks, package_level_issues=out_issues)
