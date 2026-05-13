"""Unit tests for the write-time tighten-only invariant validators.

Targets ``services/tighten_only.py``. Each test exercises one of the
violation codes the admin UI tooltip surfaces — tests double as the
spec for what the operator will see in the inline error panel.
"""
from __future__ import annotations

import pytest

from app.micro_apps.loan_onboarding.services.tighten_only import (
    TightenOnlyViolation,
    check_checklist_tightens,
    check_field_overrides_tighten,
    check_profile_shape,
)


# ── Checklist ─────────────────────────────────────────────────────────


def test_checklist_passes_when_proposed_promotes_to_required():
    """Optional-upstream → Required-proposed is allowed (tightens)."""
    upstream = [{"doc_type_key": "paystub", "required": False}]
    proposed = [{"doc_type_key": "paystub", "required": True}]
    check_checklist_tightens(upstream=upstream, proposed=proposed)  # no raise


def test_checklist_passes_when_proposed_keeps_required():
    upstream = [{"doc_type_key": "paystub", "required": True}]
    proposed = [{"doc_type_key": "paystub", "required": True}]
    check_checklist_tightens(upstream=upstream, proposed=proposed)


def test_checklist_rejects_demotion_to_optional():
    upstream = [{"doc_type_key": "paystub", "required": True}]
    proposed = [{"doc_type_key": "paystub", "required": False}]
    with pytest.raises(TightenOnlyViolation) as exc:
        check_checklist_tightens(upstream=upstream, proposed=proposed)
    assert exc.value.code == "checklist_lowers_required"
    # Tooltip: must name the offending key
    assert "paystub" in exc.value.message


def test_checklist_ignores_unknown_keys():
    """Proposed entries for keys not in upstream are accepted (additive)."""
    upstream = [{"doc_type_key": "paystub", "required": True}]
    proposed = [
        {"doc_type_key": "paystub", "required": True},
        {"doc_type_key": "w2", "required": False},  # new + optional → OK
    ]
    check_checklist_tightens(upstream=upstream, proposed=proposed)


# ── Field overrides ───────────────────────────────────────────────────


def test_field_min_confidence_passes_when_raised():
    upstream_mc = {("paystub", "borrower_name"): 0.50}
    upstream_req = {("paystub", "borrower_name"): True}
    proposed = {"paystub": {"borrower_name": {"min_confidence": 0.85}}}
    check_field_overrides_tighten(
        upstream_min_confidence=upstream_mc,
        upstream_required=upstream_req,
        proposed_overrides=proposed,
    )


def test_field_min_confidence_passes_when_unchanged():
    upstream_mc = {("paystub", "borrower_name"): 0.50}
    upstream_req = {("paystub", "borrower_name"): True}
    proposed = {"paystub": {"borrower_name": {"min_confidence": 0.50}}}
    check_field_overrides_tighten(
        upstream_min_confidence=upstream_mc,
        upstream_required=upstream_req,
        proposed_overrides=proposed,
    )


def test_field_min_confidence_rejects_lowering():
    upstream_mc = {("paystub", "borrower_name"): 0.85}
    upstream_req = {}
    proposed = {"paystub": {"borrower_name": {"min_confidence": 0.50}}}
    with pytest.raises(TightenOnlyViolation) as exc:
        check_field_overrides_tighten(
            upstream_min_confidence=upstream_mc,
            upstream_required=upstream_req,
            proposed_overrides=proposed,
        )
    assert exc.value.code == "min_confidence_lowers"
    assert "paystub.borrower_name" in exc.value.message
    assert "0.85" in exc.value.message


def test_field_required_rejects_demotion():
    upstream_mc = {}
    upstream_req = {("paystub", "borrower_name"): True}
    proposed = {"paystub": {"borrower_name": {"required": False}}}
    with pytest.raises(TightenOnlyViolation) as exc:
        check_field_overrides_tighten(
            upstream_min_confidence=upstream_mc,
            upstream_required=upstream_req,
            proposed_overrides=proposed,
        )
    assert exc.value.code == "field_lowers_required"


def test_field_overrides_silently_drop_garbage_shapes():
    """Non-dict values at any level should not crash the validator."""
    check_field_overrides_tighten(
        upstream_min_confidence={},
        upstream_required={},
        proposed_overrides={"paystub": "not a dict"},  # type: ignore[arg-type]
    )
    check_field_overrides_tighten(
        upstream_min_confidence={},
        upstream_required={},
        proposed_overrides={"paystub": {"borrower_name": "not a dict"}},  # type: ignore[arg-type]
    )


def test_field_unknown_keys_pass_through():
    """Override on a field that doesn't exist upstream is accepted."""
    check_field_overrides_tighten(
        upstream_min_confidence={},
        upstream_required={},
        proposed_overrides={"paystub": {"new_field": {"min_confidence": 0.9}}},
    )


# ── Profile shape ─────────────────────────────────────────────────────


def test_profile_loan_program_must_not_have_stacks_with():
    with pytest.raises(TightenOnlyViolation) as exc:
        check_profile_shape(type_="loan_program", stacks_with="some-uuid")
    assert exc.value.code == "loan_program_has_stacks_with"


def test_profile_investor_overlay_must_have_stacks_with():
    with pytest.raises(TightenOnlyViolation) as exc:
        check_profile_shape(type_="investor_overlay", stacks_with=None)
    assert exc.value.code == "investor_overlay_missing_stacks_with"


def test_profile_loan_program_without_stacks_with_passes():
    check_profile_shape(type_="loan_program", stacks_with=None)


def test_profile_investor_overlay_with_stacks_with_passes():
    check_profile_shape(type_="investor_overlay", stacks_with="some-uuid")
