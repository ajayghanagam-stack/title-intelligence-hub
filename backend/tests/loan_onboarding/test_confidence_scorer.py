"""Tests for the confidence scorer."""
import pytest

from app.micro_apps.loan_onboarding.services.confidence_scorer import (
    ConfidenceInputs,
    WEIGHT_CLASSIFICATION,
    WEIGHT_SPLIT,
    WEIGHT_VALIDATION,
    blend_confidence,
    split_accuracy_from_roles,
    validation_score_from_rules,
)
from app.micro_apps.loan_onboarding.services.validation_presets import (
    StackFacts,
    StackPageFacts,
)


def _stack(roles: list[str]) -> StackFacts:
    return StackFacts(
        stack_id="s",
        doc_type="URLA_1003",
        pages=tuple(
            StackPageFacts(
                page_number=i + 1,
                page_role=r,
                detected_field_names=frozenset(),
            )
            for i, r in enumerate(roles)
        ),
    )


def test_weights_sum_to_one():
    assert abs(WEIGHT_CLASSIFICATION + WEIGHT_SPLIT + WEIGHT_VALIDATION - 1.0) < 1e-9


def test_blend_is_weighted_average_clamped():
    inputs = ConfidenceInputs(classification=1.0, split_accuracy=1.0, validation=1.0)
    assert blend_confidence(inputs) == pytest.approx(1.0)
    inputs = ConfidenceInputs(classification=0.0, split_accuracy=0.0, validation=0.0)
    assert blend_confidence(inputs) == pytest.approx(0.0)


def test_blend_is_deterministic():
    inputs = ConfidenceInputs(classification=0.8, split_accuracy=0.9, validation=0.75)
    assert blend_confidence(inputs) == blend_confidence(inputs)


def test_validation_score_no_rules_is_neutral_one():
    assert validation_score_from_rules(0, 0) == 1.0


def test_validation_score_fraction_of_pass():
    assert validation_score_from_rules(3, 4) == pytest.approx(0.75)
    assert validation_score_from_rules(0, 4) == 0.0
    assert validation_score_from_rules(4, 4) == 1.0


# ── split_accuracy_from_roles heuristics ───────────────────────────────────


def test_split_single_page_first_role_is_high():
    assert split_accuracy_from_roles(_stack(["first_page"])) == pytest.approx(0.95)


def test_split_single_page_continuation_is_suspicious():
    assert split_accuracy_from_roles(_stack(["continuation"])) == pytest.approx(0.5)


def test_split_single_page_unknown_is_neutral():
    assert split_accuracy_from_roles(_stack(["unknown"])) == pytest.approx(0.7)


def test_split_ideal_multi_page_shape_is_high():
    s = _stack(["first_page", "continuation", "continuation", "last_page"])
    score = split_accuracy_from_roles(s)
    assert score >= 0.9


def test_split_missing_last_page_penalized_mildly():
    s = _stack(["first_page", "continuation", "continuation"])
    score = split_accuracy_from_roles(s)
    assert 0.7 < score < 1.0


def test_split_multiple_first_pages_penalized():
    s = _stack(["first_page", "first_page", "last_page"])
    score = split_accuracy_from_roles(s)
    assert score < 0.9


def test_split_all_unknown_is_neutral():
    s = _stack(["unknown"] * 5)
    assert split_accuracy_from_roles(s) == pytest.approx(0.7)
