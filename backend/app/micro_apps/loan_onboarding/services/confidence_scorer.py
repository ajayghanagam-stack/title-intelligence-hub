"""Confidence scoring for validated stacks.

The ConfidenceBreakdown schema (from the brief) carries three components:

    classification  — mean per-page classification confidence (from LOClassification)
    split_accuracy  — how confident we are that the stack's page boundaries are correct
                      (still computed and surfaced for engineering inspection,
                      but does NOT contribute to overall_confidence)
    validation      — fraction of rules that passed

`overall_confidence` is a weighted blend of classification + validation only,
clamped to [0.0, 1.0]. Split-accuracy was dropped from the blend (v5) because
it's a deterministic role-distribution heuristic — useful for diagnosing the
classifier, but it doesn't reflect actual stack quality the way operators
read the score on the dashboard.

Split-accuracy heuristic (still exposed in the breakdown for diagnostics):
since we don't yet have a per-boundary split confidence from the LLM, we
approximate it from the `page_role` distribution:
  - a clean stack has one first_page, zero or more continuations, and one
    last_page (or is a single page with first/last role)
  - missing or extra role markers reduce the score
  - a stack where every page is "unknown" gets a neutral 0.7
"""
from __future__ import annotations

from dataclasses import dataclass

from app.micro_apps.loan_onboarding.services.validation_presets import StackFacts


# Weights sum to 1.0. Equal weighting (v6): classification and validation
# count the same — a failed validation pulls overall down by the same amount
# a strong classification pulls it up, matching how operators read the two
# numbers on the dashboard. Split is held at 0.0; the constant is kept so
# existing version-metadata callers and tests keep working without churning
# imports. If these weights change, bump RULES_VERSION in validation_presets.py
# so cache keys reflect the new weighting.
WEIGHT_CLASSIFICATION = 0.5
WEIGHT_SPLIT = 0.0
WEIGHT_VALIDATION = 0.5


@dataclass(frozen=True)
class ConfidenceInputs:
    classification: float
    split_accuracy: float
    validation: float


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def split_accuracy_from_roles(stack: StackFacts) -> float:
    """Cheap heuristic — approximate split quality from page_role distribution."""
    if not stack.pages:
        return 0.0
    roles = [p.page_role for p in stack.pages]
    role_set = set(roles)

    if stack.page_count == 1:
        # Single-page stack — accepted if the LLM tagged it as a first_page,
        # last_page, or signature_page. Unknown is neutral.
        role = roles[0]
        if role in ("first_page", "last_page", "signature_page"):
            return 0.95
        if role == "continuation":
            return 0.5   # continuation with no anchors is suspicious
        return 0.7       # unknown → neutral

    # Multi-page stacks: ideal shape has exactly one first_page, optional
    # signature pages, and a last_page.
    first_count = sum(1 for r in roles if r == "first_page")
    last_count = sum(1 for r in roles if r == "last_page")
    unknown_count = sum(1 for r in roles if r == "unknown")

    score = 1.0
    if first_count != 1:
        score -= 0.15 * abs(first_count - 1)
    if last_count > 1:
        score -= 0.1 * (last_count - 1)
    if last_count == 0:
        # Missing end marker — mild penalty; model often forgets last_page.
        score -= 0.1
    if unknown_count == stack.page_count:
        return 0.7
    # Large stacks with lots of unknowns are suspicious
    unknown_ratio = unknown_count / stack.page_count
    score -= 0.2 * unknown_ratio

    return _clamp(score)


def validation_score_from_rules(passed: int, total: int) -> float:
    """Fraction of rules that passed. If no rules applied, return 1.0 (neutral)."""
    if total <= 0:
        return 1.0
    return _clamp(passed / total)


def blend_confidence(inputs: ConfidenceInputs) -> float:
    """Weighted blend → overall_confidence. Always clamped to [0, 1].

    Split-accuracy is intentionally excluded (its weight is 0.0) — it's a
    role-distribution heuristic that's surfaced separately in the breakdown
    for diagnostics, not folded into the user-facing score.
    """
    return _clamp(
        WEIGHT_CLASSIFICATION * inputs.classification
        + WEIGHT_SPLIT * inputs.split_accuracy
        + WEIGHT_VALIDATION * inputs.validation
    )
