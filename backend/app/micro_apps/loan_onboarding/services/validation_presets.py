"""Deterministic preset validation rules for Loan Onboarding.

Mirrors the TSA `flag_rules.py` pattern: a single module that owns every
preset rule, a `RULES_VERSION` that must bump on any behavior change, and
pure functions that take structured inputs and return normalized rule
evaluations.

Preset rules available:
- `missing_signatures` — require at least one page with page_role="signature_page"
- `missing_pages` — require at least one first_page + one last_page in the stack
- `missing_fields` — require named fields present in detected_fields for a doc_type

Custom (natural-language) rules are evaluated separately by the
`StackValidatorAgent` — they do not live here.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.micro_apps.loan_onboarding.ai.page_classifier_agent import OTHERS_KEY


# v6: confidence_scorer weights equalized — classification + validation now
# weighted 0.5 / 0.5 so a failed validation drags the overall down by the
# same amount a strong classification lifts it. Cached overall_confidence
# values from v5 differ, so validate/reason results must be invalidated.
# v5: confidence_scorer weights rebalanced — split_accuracy dropped from the
# overall blend (weight set to 0.0), classification + validation renormalized
# to 0.55 / 0.45.
# v4: missing_fields rule now scopes its required-field list per doc_type
# via `required_fields_by_doc`. The legacy `required_fields` flat list is
# still accepted (treated as universal) for backward compatibility.
RULES_VERSION = "lo_validation_rules_v6"

# ── Rule registry ──────────────────────────────────────────────────────────

PRESET_IDS = (
    "missing_signatures",
    "missing_pages",
    "missing_fields",
)


@dataclass(frozen=True)
class StackPageFacts:
    """The minimal per-page shape a preset rule needs to evaluate a stack."""
    page_number: int
    page_role: str
    detected_field_names: frozenset[str]


@dataclass(frozen=True)
class StackFacts:
    """All inputs required to evaluate preset rules on a single stack."""
    stack_id: str
    doc_type: str
    pages: tuple[StackPageFacts, ...]

    @property
    def page_count(self) -> int:
        return len(self.pages)


@dataclass
class PresetEvaluation:
    """Output of a single preset rule evaluation."""
    rule_id: str
    passed: bool
    evidence: str  # <= 200 chars; quoted from page/field info
    location_page: int | None = None


# ── Individual preset evaluators ────────────────────────────────────────────


def _rule_missing_signatures(stack: StackFacts, config: dict[str, Any]) -> PresetEvaluation:
    """Pass if at least one page in the stack is tagged signature_page."""
    sig_pages = [p.page_number for p in stack.pages if p.page_role == "signature_page"]
    if sig_pages:
        return PresetEvaluation(
            rule_id="missing_signatures",
            passed=True,
            evidence=f"Signature page(s) found at page {sig_pages[0]}",
            location_page=sig_pages[0],
        )
    return PresetEvaluation(
        rule_id="missing_signatures",
        passed=False,
        evidence=f"No signature_page found in stack (pages {stack.pages[0].page_number}-{stack.pages[-1].page_number})"[:200],
        location_page=stack.pages[-1].page_number if stack.pages else None,
    )


def _rule_missing_pages(stack: StackFacts, config: dict[str, Any]) -> PresetEvaluation:
    """Pass if the stack has both a first_page and a last_page marker.

    A single-page stack passes if its role is first_page or last_page (common
    for single-page docs like W-2 summaries).
    """
    roles = {p.page_role for p in stack.pages}
    if stack.page_count == 1:
        passed = bool(roles & {"first_page", "last_page"})
        return PresetEvaluation(
            rule_id="missing_pages",
            passed=passed,
            evidence=(
                "Single-page stack — accepted"
                if passed
                else "Single-page stack has no first/last_page marker"
            ),
            location_page=stack.pages[0].page_number,
        )
    passed = "first_page" in roles and "last_page" in roles
    missing = [r for r in ("first_page", "last_page") if r not in roles]
    return PresetEvaluation(
        rule_id="missing_pages",
        passed=passed,
        evidence=(
            f"Both first_page and last_page markers present"
            if passed
            else f"Missing role(s) in stack: {', '.join(missing)}"
        )[:200],
        location_page=stack.pages[0].page_number,
    )


def _rule_missing_fields(stack: StackFacts, config: dict[str, Any]) -> PresetEvaluation:
    """Pass iff every required field name for this stack's doc_type appears in
    at least one page's detected_fields.

    Two config shapes are accepted:

    1. `config["required_fields_by_doc"]` (preferred, prototype-aligned):
       a dict mapping doc_type key → list of field names. Only the entry
       for the stack's `doc_type` is enforced; if the stack's doc_type is
       absent or its list is empty, the rule no-ops.

    2. `config["required_fields"]` (legacy): a flat list applied universally
       to every stack regardless of doc_type. Preserved so packages
       configured before v4 keep evaluating identically.

    If both are present, `required_fields_by_doc` wins. If neither is set,
    the rule is a no-op pass.
    """
    by_doc_raw = config.get("required_fields_by_doc")
    required: list[str]
    source: str
    if isinstance(by_doc_raw, dict):
        # Per-doc shape — only enforce the entry for THIS stack's doc_type.
        entry = by_doc_raw.get(stack.doc_type)
        required = [str(f) for f in (entry or [])]
        source = "by_doc"
    else:
        required = [str(f) for f in (config.get("required_fields") or [])]
        source = "flat"

    if not required:
        evidence = (
            f"No required fields configured for doc_type '{stack.doc_type}' — rule skipped"
            if source == "by_doc"
            else "No required_fields configured — rule skipped"
        )
        return PresetEvaluation(
            rule_id="missing_fields",
            passed=True,
            evidence=evidence[:200],
            location_page=stack.pages[0].page_number if stack.pages else None,
        )

    # union of field names across all pages in stack
    seen: set[str] = set()
    for p in stack.pages:
        seen.update(p.detected_field_names)
    missing = [f for f in required if f not in seen]
    if not missing:
        return PresetEvaluation(
            rule_id="missing_fields",
            passed=True,
            evidence=f"All {len(required)} required field(s) detected",
            location_page=stack.pages[0].page_number,
        )
    return PresetEvaluation(
        rule_id="missing_fields",
        passed=False,
        evidence=f"Missing required fields: {', '.join(missing[:5])}"[:200],
        location_page=stack.pages[0].page_number,
    )


_PRESET_DISPATCH = {
    "missing_signatures": _rule_missing_signatures,
    "missing_pages": _rule_missing_pages,
    "missing_fields": _rule_missing_fields,
}


def evaluate_preset(
    rule_id: str,
    stack: StackFacts,
    config: dict[str, Any] | None = None,
) -> PresetEvaluation:
    """Dispatch to the matching preset evaluator.

    Unknown rule ids produce a conservative `passed=False` evaluation so
    misconfigured rules fail loudly instead of silently approving stacks.
    """
    fn = _PRESET_DISPATCH.get(rule_id)
    if fn is None:
        return PresetEvaluation(
            rule_id=rule_id,
            passed=False,
            evidence=f"Unknown preset rule_id: {rule_id}",
            location_page=stack.pages[0].page_number if stack.pages else None,
        )
    # Others stacks short-circuit: presets don't apply to unmatched content.
    # Return a no-op "passed" so they don't double-penalize — HITL is already
    # forced in the stack stage.
    if stack.doc_type == OTHERS_KEY:
        return PresetEvaluation(
            rule_id=rule_id,
            passed=True,
            evidence="Rule skipped — stack is reserved 'Others' bucket",
            location_page=stack.pages[0].page_number if stack.pages else None,
        )
    return fn(stack, config or {})


def evaluate_all_presets(
    rules: Iterable[tuple[str, dict[str, Any]]],
    stack: StackFacts,
) -> list[PresetEvaluation]:
    """Evaluate a list of (rule_id, config) tuples against a single stack."""
    return [evaluate_preset(rid, stack, cfg) for rid, cfg in rules]
