"""Tests for deterministic preset validation rules."""
import pytest

from app.micro_apps.loan_onboarding.ai.page_classifier_agent import OTHERS_KEY
from app.micro_apps.loan_onboarding.services.validation_presets import (
    RULES_VERSION,
    StackFacts,
    StackPageFacts,
    evaluate_all_presets,
    evaluate_preset,
)


def _make_stack(doc_type: str, page_shapes: list[tuple[int, str, list[str]]]) -> StackFacts:
    return StackFacts(
        stack_id="s1",
        doc_type=doc_type,
        pages=tuple(
            StackPageFacts(
                page_number=pn,
                page_role=role,
                detected_field_names=frozenset(fields),
            )
            for pn, role, fields in page_shapes
        ),
    )


def test_rules_version_is_versioned():
    assert RULES_VERSION.startswith("lo_validation_rules_")


# ── missing_signatures ─────────────────────────────────────────────────────


def test_missing_signatures_pass_when_signature_page_present():
    stack = _make_stack("URLA_1003", [
        (1, "first_page", []),
        (2, "signature_page", []),
    ])
    ev = evaluate_preset("missing_signatures", stack)
    assert ev.passed is True
    assert ev.location_page == 2


def test_missing_signatures_fail_when_none():
    stack = _make_stack("URLA_1003", [
        (1, "first_page", []),
        (2, "last_page", []),
    ])
    ev = evaluate_preset("missing_signatures", stack)
    assert ev.passed is False
    assert "No signature_page" in ev.evidence


# ── missing_pages ──────────────────────────────────────────────────────────


def test_missing_pages_pass_on_first_and_last():
    stack = _make_stack("URLA_1003", [
        (1, "first_page", []),
        (2, "continuation", []),
        (3, "last_page", []),
    ])
    ev = evaluate_preset("missing_pages", stack)
    assert ev.passed is True


def test_missing_pages_fail_when_no_last():
    stack = _make_stack("URLA_1003", [
        (1, "first_page", []),
        (2, "continuation", []),
    ])
    ev = evaluate_preset("missing_pages", stack)
    assert ev.passed is False
    assert "last_page" in ev.evidence


def test_missing_pages_single_page_with_first_role_passes():
    stack = _make_stack("W2", [(1, "first_page", [])])
    ev = evaluate_preset("missing_pages", stack)
    assert ev.passed is True


def test_missing_pages_single_page_unknown_role_fails():
    stack = _make_stack("W2", [(1, "unknown", [])])
    ev = evaluate_preset("missing_pages", stack)
    assert ev.passed is False


# ── missing_fields ─────────────────────────────────────────────────────────


def test_missing_fields_pass_when_all_present():
    stack = _make_stack("URLA_1003", [
        (1, "first_page", ["Borrower Name", "Loan Amount"]),
        (2, "last_page", ["Property Address"]),
    ])
    ev = evaluate_preset(
        "missing_fields",
        stack,
        {"required_fields": ["Borrower Name", "Loan Amount", "Property Address"]},
    )
    assert ev.passed is True


def test_missing_fields_fail_when_any_missing():
    stack = _make_stack("URLA_1003", [
        (1, "first_page", ["Borrower Name"]),
    ])
    ev = evaluate_preset(
        "missing_fields",
        stack,
        {"required_fields": ["Borrower Name", "Loan Amount"]},
    )
    assert ev.passed is False
    assert "Loan Amount" in ev.evidence


def test_missing_fields_empty_config_is_noop_pass():
    stack = _make_stack("URLA_1003", [(1, "first_page", [])])
    ev = evaluate_preset("missing_fields", stack, {"required_fields": []})
    assert ev.passed is True
    assert "skipped" in ev.evidence.lower()


# ── missing_fields per-doc-type (v4) ───────────────────────────────────────


def test_missing_fields_by_doc_pass_when_all_present_for_matching_doc():
    stack = _make_stack("URLA_1003", [
        (1, "first_page", ["Borrower Name", "Loan Amount"]),
        (2, "last_page", ["Property Address"]),
    ])
    ev = evaluate_preset(
        "missing_fields",
        stack,
        {
            "required_fields_by_doc": {
                "URLA_1003": ["Borrower Name", "Loan Amount", "Property Address"],
                "PAYSTUB": ["Gross Pay"],
            },
        },
    )
    assert ev.passed is True


def test_missing_fields_by_doc_only_enforces_matching_doc_type():
    """A stack of doc_type X must NOT be evaluated against doc_type Y's fields."""
    stack = _make_stack("PAYSTUB", [
        (1, "first_page", ["Gross Pay"]),
    ])
    ev = evaluate_preset(
        "missing_fields",
        stack,
        {
            "required_fields_by_doc": {
                # The URLA list would fail if applied; but the stack is PAYSTUB,
                # so only its own list ("Gross Pay") is enforced and passes.
                "URLA_1003": ["Borrower Name", "Loan Amount"],
                "PAYSTUB": ["Gross Pay"],
            },
        },
    )
    assert ev.passed is True


def test_missing_fields_by_doc_fail_when_required_field_missing_for_doc():
    stack = _make_stack("URLA_1003", [
        (1, "first_page", ["Borrower Name"]),
    ])
    ev = evaluate_preset(
        "missing_fields",
        stack,
        {
            "required_fields_by_doc": {
                "URLA_1003": ["Borrower Name", "Loan Amount"],
            },
        },
    )
    assert ev.passed is False
    assert "Loan Amount" in ev.evidence


def test_missing_fields_by_doc_skips_unconfigured_doc_type():
    """If the stack's doc_type has no entry, treat as no-op pass."""
    stack = _make_stack("BANK_STATEMENT", [(1, "first_page", [])])
    ev = evaluate_preset(
        "missing_fields",
        stack,
        {
            "required_fields_by_doc": {
                "URLA_1003": ["Borrower Name"],
            },
        },
    )
    assert ev.passed is True
    assert "skipped" in ev.evidence.lower()
    assert "BANK_STATEMENT" in ev.evidence


def test_missing_fields_by_doc_skips_when_entry_is_empty_list():
    stack = _make_stack("URLA_1003", [(1, "first_page", [])])
    ev = evaluate_preset(
        "missing_fields",
        stack,
        {"required_fields_by_doc": {"URLA_1003": []}},
    )
    assert ev.passed is True
    assert "skipped" in ev.evidence.lower()


def test_missing_fields_by_doc_takes_precedence_over_legacy_flat():
    """When both shapes are present, by_doc wins so old-shape leakage doesn't override."""
    stack = _make_stack("URLA_1003", [(1, "first_page", ["Borrower Name"])])
    ev = evaluate_preset(
        "missing_fields",
        stack,
        {
            # Legacy list would pass — but per-doc list demands an extra field
            # which is missing. by_doc must win.
            "required_fields": ["Borrower Name"],
            "required_fields_by_doc": {"URLA_1003": ["Borrower Name", "Loan Amount"]},
        },
    )
    assert ev.passed is False
    assert "Loan Amount" in ev.evidence


# ── Others short-circuit ───────────────────────────────────────────────────


def test_others_stacks_short_circuit_to_pass():
    """Others is already HITL-flagged in stack stage — don't double-penalize."""
    stack = _make_stack(OTHERS_KEY, [(1, "unknown", [])])
    ev = evaluate_preset("missing_signatures", stack)
    assert ev.passed is True
    assert "Others" in ev.evidence


# ── applies_to_doc_keys scoping (v7) ──────────────────────────────────────


def test_applies_to_doc_keys_skips_when_doc_type_not_in_scope():
    """When the rule scope lists specific doc_types, stacks of other types
    no-op pass — the rule is "not configured" for them."""
    stack = _make_stack("PAYSTUB", [
        (1, "first_page", []),
        (2, "last_page", []),
    ])
    ev = evaluate_preset(
        "missing_signatures",
        stack,
        config={"applies_to_doc_keys": ["URLA_1003", "W2"]},
    )
    assert ev.passed is True
    assert "not configured" in ev.evidence
    assert "PAYSTUB" in ev.evidence


def test_applies_to_doc_keys_runs_when_doc_type_in_scope():
    """When the stack's doc_type is in scope, the rule evaluates normally."""
    stack = _make_stack("PAYSTUB", [
        (1, "first_page", []),
        (2, "last_page", []),
    ])
    ev = evaluate_preset(
        "missing_signatures",
        stack,
        config={"applies_to_doc_keys": ["PAYSTUB"]},
    )
    # No signature page → fails (real evaluation)
    assert ev.passed is False
    assert "No signature_page" in ev.evidence


def test_applies_to_doc_keys_empty_list_falls_through_to_legacy_behavior():
    """Empty list = no scope = legacy package-wide evaluation."""
    stack = _make_stack("PAYSTUB", [
        (1, "first_page", []),
        (2, "signature_page", []),
    ])
    ev = evaluate_preset(
        "missing_signatures",
        stack,
        config={"applies_to_doc_keys": []},
    )
    assert ev.passed is True
    assert "Signature page(s) found" in ev.evidence


def test_applies_to_doc_keys_missing_falls_through_to_legacy_behavior():
    """Missing key = no scope = legacy package-wide evaluation."""
    stack = _make_stack("PAYSTUB", [
        (1, "first_page", []),
        (2, "last_page", []),
    ])
    ev = evaluate_preset("missing_pages", stack, config={})
    assert ev.passed is True


# ── unknown rule id ────────────────────────────────────────────────────────


def test_unknown_rule_id_conservatively_fails():
    stack = _make_stack("URLA_1003", [(1, "first_page", [])])
    ev = evaluate_preset("does_not_exist", stack)
    assert ev.passed is False
    assert "Unknown preset" in ev.evidence


# ── evaluate_all_presets ───────────────────────────────────────────────────


def test_evaluate_all_presets_runs_multiple_rules():
    stack = _make_stack("PAYSTUB", [
        (1, "first_page", ["Gross Pay"]),
        (2, "last_page", []),
    ])
    rules = [
        ("missing_signatures", {}),
        ("missing_pages", {}),
        ("missing_fields", {"required_fields": ["Gross Pay"]}),
    ]
    evals = evaluate_all_presets(rules, stack)
    assert [e.rule_id for e in evals] == [
        "missing_signatures", "missing_pages", "missing_fields",
    ]
    assert [e.passed for e in evals] == [False, True, True]


def test_evaluate_is_deterministic():
    stack = _make_stack("URLA_1003", [
        (1, "first_page", ["Name"]),
        (2, "last_page", ["Amount"]),
    ])
    rules = [
        ("missing_fields", {"required_fields": ["Name", "Amount"]}),
        ("missing_pages", {}),
    ]
    ev1 = evaluate_all_presets(rules, stack)
    ev2 = evaluate_all_presets(rules, stack)
    assert [(e.rule_id, e.passed, e.evidence) for e in ev1] == [
        (e.rule_id, e.passed, e.evidence) for e in ev2
    ]
