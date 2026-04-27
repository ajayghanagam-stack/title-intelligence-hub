"""Golden-set / regression tests for deterministic Loan Onboarding outputs.

These pin the deterministic layers — stacking, preset validation rules, and
confidence blending — to byte-stable outputs for a fixed input. If any of
these tests fail, a prompt/model/rules change has altered behavior and the
cache versions (`RULES_VERSION`, stacking logic, or confidence weights) MUST
bump so downstream caches invalidate correctly.

These are the LO equivalent of `tests/title_search/test_determinism.py`.
"""
from __future__ import annotations

import pytest

from app.micro_apps.loan_onboarding.ai.page_classifier_agent import OTHERS_KEY
from app.micro_apps.loan_onboarding.services.confidence_scorer import (
    WEIGHT_CLASSIFICATION,
    WEIGHT_SPLIT,
    WEIGHT_VALIDATION,
    ConfidenceInputs,
    blend_confidence,
    split_accuracy_from_roles,
    validation_score_from_rules,
)
from app.micro_apps.loan_onboarding.services.stacking import (
    ClassifiedPage,
    build_stacks,
)
from app.micro_apps.loan_onboarding.services.validation_presets import (
    PRESET_IDS,
    RULES_VERSION,
    StackFacts,
    StackPageFacts,
    evaluate_all_presets,
    evaluate_preset,
)


# ---------------------------------------------------------------------------
# Version constants — any change here is a breaking cache-invalidation event.
# ---------------------------------------------------------------------------

def test_rules_version_is_pinned():
    """If this fails, a rule behavior change needs a RULES_VERSION bump."""
    assert RULES_VERSION == "lo_validation_rules_v6"


def test_preset_ids_are_pinned():
    assert PRESET_IDS == (
        "missing_signatures",
        "missing_pages",
        "missing_fields",
    )


def test_confidence_weights_sum_to_one_and_are_pinned():
    """Cache keys depend on these weights — any change needs a rules-version bump.

    v6: equal weighting (0.5 / 0.0 / 0.5). Classification and validation
    contribute equally so a failed validation pulls overall down by the same
    amount a strong classification lifts it — matches how operators read the
    two numbers side-by-side on the dashboard. Split is held at 0.0; it's
    surfaced in the breakdown for diagnostics but doesn't influence overall.
    """
    assert WEIGHT_CLASSIFICATION == pytest.approx(0.5)
    assert WEIGHT_SPLIT == pytest.approx(0.0)
    assert WEIGHT_VALIDATION == pytest.approx(0.5)
    assert (
        WEIGHT_CLASSIFICATION + WEIGHT_SPLIT + WEIGHT_VALIDATION
    ) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Golden stacking — fixed 10-page loan package
# ---------------------------------------------------------------------------

GOLDEN_CLASSIFICATIONS = [
    # 1003 (pages 1–3): first_page, continuation, signature_page
    ClassifiedPage(1, "URLA_1003", 0.95, "first_page"),
    ClassifiedPage(2, "URLA_1003", 0.93, "continuation"),
    ClassifiedPage(3, "URLA_1003", 0.92, "signature_page"),
    # Paystub #1 (pages 4) — single-page, tagged first_page
    ClassifiedPage(4, "PAYSTUB", 0.90, "first_page"),
    # Paystub #2 (pages 5) — single-page, tagged first_page (new instance)
    ClassifiedPage(5, "PAYSTUB", 0.88, "first_page"),
    # W-2 (page 6) — single-page
    ClassifiedPage(6, "W2", 0.91, "first_page"),
    # Unknown junk (pages 7–8) — Others bucket
    ClassifiedPage(7, OTHERS_KEY, 0.60, "unknown"),
    ClassifiedPage(8, OTHERS_KEY, 0.55, "unknown"),
    # Contract (pages 9–10)
    ClassifiedPage(9, "PURCHASE_CONTRACT", 0.70, "first_page"),
    ClassifiedPage(10, "PURCHASE_CONTRACT", 0.65, "last_page"),
]


def test_build_stacks_golden_shape():
    stacks = build_stacks(GOLDEN_CLASSIFICATIONS, hitl_threshold=0.75)

    # Exactly five stacks — one per doc_type: URLA_1003, PAYSTUB (both
    # instances merged), W2, Others, PURCHASE_CONTRACT. Stacks are emitted
    # in order of the doc_type's first page appearance.
    assert len(stacks) == 5

    # Stack 0: URLA_1003, pages 1-3
    assert stacks[0].stack_index == 0
    assert stacks[0].doc_type == "URLA_1003"
    assert stacks[0].page_numbers == [1, 2, 3]
    assert stacks[0].requires_hitl is False  # avg 0.933 >= 0.75

    # Stack 1: both paystubs collapsed into one PAYSTUB stack (pages 4, 5)
    assert stacks[1].doc_type == "PAYSTUB"
    assert stacks[1].page_numbers == [4, 5]
    assert stacks[1].first_page == 4
    assert stacks[1].last_page == 5

    # Stack 2: W-2
    assert stacks[2].doc_type == "W2"
    assert stacks[2].page_numbers == [6]

    # Stack 3: Others — always HITL regardless of confidence
    assert stacks[3].doc_type == OTHERS_KEY
    assert stacks[3].page_numbers == [7, 8]
    assert stacks[3].requires_hitl is True

    # Stack 4: Contract — avg 0.675 < 0.75 → HITL
    assert stacks[4].doc_type == "PURCHASE_CONTRACT"
    assert stacks[4].page_numbers == [9, 10]
    assert stacks[4].requires_hitl is True


def test_build_stacks_is_byte_stable_across_calls():
    """Same input → byte-identical output. Required for cache-key stability."""
    s1 = build_stacks(GOLDEN_CLASSIFICATIONS, hitl_threshold=0.75)
    s2 = build_stacks(GOLDEN_CLASSIFICATIONS, hitl_threshold=0.75)
    assert s1 == s2


def test_build_stacks_is_input_order_independent():
    """Shuffled input → same output (the impl sorts defensively)."""
    reversed_pages = list(reversed(GOLDEN_CLASSIFICATIONS))
    ordered = build_stacks(GOLDEN_CLASSIFICATIONS, hitl_threshold=0.75)
    shuffled = build_stacks(reversed_pages, hitl_threshold=0.75)
    assert ordered == shuffled


# ---------------------------------------------------------------------------
# Golden preset evaluations
# ---------------------------------------------------------------------------


def _facts(doc_type: str, pages: list[tuple[int, str, set[str]]]) -> StackFacts:
    return StackFacts(
        stack_id="s1",
        doc_type=doc_type,
        pages=tuple(
            StackPageFacts(page_number=pn, page_role=role, detected_field_names=frozenset(fields))
            for pn, role, fields in pages
        ),
    )


def test_missing_signatures_pass_when_signature_page_present():
    stack = _facts("URLA_1003", [(1, "first_page", set()), (2, "signature_page", set())])
    result = evaluate_preset("missing_signatures", stack, {})
    assert result.passed is True
    assert result.location_page == 2


def test_missing_signatures_fail_when_absent():
    stack = _facts("URLA_1003", [(1, "first_page", set()), (2, "continuation", set())])
    result = evaluate_preset("missing_signatures", stack, {})
    assert result.passed is False
    assert "No signature_page" in result.evidence


def test_missing_pages_pass_when_both_markers_present():
    stack = _facts("URLA_1003", [(1, "first_page", set()), (2, "last_page", set())])
    assert evaluate_preset("missing_pages", stack, {}).passed is True


def test_missing_pages_fail_when_missing_last():
    stack = _facts("URLA_1003", [(1, "first_page", set()), (2, "continuation", set())])
    result = evaluate_preset("missing_pages", stack, {})
    assert result.passed is False
    assert "last_page" in result.evidence


def test_missing_fields_pass_when_all_required_present():
    stack = _facts(
        "URLA_1003",
        [(1, "first_page", {"borrower_name", "loan_amount", "property_address"})],
    )
    result = evaluate_preset(
        "missing_fields", stack,
        {"required_fields": ["borrower_name", "loan_amount"]},
    )
    assert result.passed is True


def test_missing_fields_fail_with_subset():
    stack = _facts("URLA_1003", [(1, "first_page", {"borrower_name"})])
    result = evaluate_preset(
        "missing_fields", stack,
        {"required_fields": ["borrower_name", "loan_amount", "property_address"]},
    )
    assert result.passed is False
    assert "loan_amount" in result.evidence


def test_others_bucket_short_circuits_all_presets():
    """Others stacks never fail a preset — HITL is already forced upstream."""
    stack = _facts(OTHERS_KEY, [(1, "unknown", set()), (2, "unknown", set())])
    for rid in PRESET_IDS:
        result = evaluate_preset(rid, stack, {"required_fields": ["never"]})
        assert result.passed is True, f"{rid} should short-circuit for Others"
        assert "Others" in result.evidence


def test_unknown_rule_id_fails_conservatively():
    stack = _facts("URLA_1003", [(1, "first_page", set())])
    result = evaluate_preset("nonexistent_rule", stack, {})
    assert result.passed is False
    assert "Unknown preset rule_id" in result.evidence


def test_evaluate_all_presets_preserves_order():
    """Output order must match input order for byte-stable cache keys."""
    stack = _facts("URLA_1003", [(1, "first_page", set()), (2, "signature_page", set())])
    results = evaluate_all_presets(
        [
            ("missing_pages", {}),
            ("missing_signatures", {}),
            ("missing_fields", {"required_fields": []}),
        ],
        stack,
    )
    assert [r.rule_id for r in results] == [
        "missing_pages",
        "missing_signatures",
        "missing_fields",
    ]


# ---------------------------------------------------------------------------
# Golden confidence blending
# ---------------------------------------------------------------------------


def test_blend_confidence_is_deterministic():
    inputs = ConfidenceInputs(classification=0.9, split_accuracy=0.8, validation=1.0)
    # v6: equal-weight average of classification + validation only.
    # 0.5*0.9 + 0.0*0.8 + 0.5*1.0 = 0.45 + 0.0 + 0.5 = 0.95
    assert blend_confidence(inputs) == pytest.approx(0.95)


def test_blend_confidence_clamps_to_unit_interval():
    assert blend_confidence(ConfidenceInputs(2.0, 2.0, 2.0)) == 1.0
    assert blend_confidence(ConfidenceInputs(-1.0, -1.0, -1.0)) == 0.0


def test_split_accuracy_golden_values():
    # Ideal shape: one first_page, last_page
    ideal = _facts("URLA_1003", [(1, "first_page", set()), (2, "last_page", set())])
    assert split_accuracy_from_roles(ideal) == pytest.approx(1.0)

    # Single-page first_page
    single = _facts("PAYSTUB", [(1, "first_page", set())])
    assert split_accuracy_from_roles(single) == pytest.approx(0.95)

    # All unknown
    unknown = _facts("W2", [(1, "unknown", set()), (2, "unknown", set())])
    assert split_accuracy_from_roles(unknown) == pytest.approx(0.7)


def test_validation_score_edge_cases():
    assert validation_score_from_rules(0, 0) == 1.0
    assert validation_score_from_rules(3, 4) == pytest.approx(0.75)
    assert validation_score_from_rules(0, 5) == 0.0


# ---------------------------------------------------------------------------
# Re-run stability — cache keys + ordering invariants
# ---------------------------------------------------------------------------

import uuid
from unittest.mock import AsyncMock, patch

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.loan_onboarding.ai.reasoning_agent import (
    PackageLevelIssue,
    PackageReasoningOutput,
    StackReasoning,
    _coerce,
)
from app.micro_apps.loan_onboarding.ai.stack_validator_agent import (
    StackValidatorAgent,
)
from app.micro_apps.loan_onboarding.models.classification import LOClassification
from app.micro_apps.loan_onboarding.models.package_file import LOPackageFile
from app.micro_apps.loan_onboarding.models.page import LOPage
from app.micro_apps.loan_onboarding.models.validation_result import LOValidationResult
from app.micro_apps.loan_onboarding.models.validation_rule import LOValidationRule
from app.micro_apps.loan_onboarding.pipeline.stages import (
    stage_stack,
    stage_validate,
)
from app.micro_apps.loan_onboarding.pipeline.version_tracker import (
    compute_reason_cache_key,
    compute_stack_content_hash,
    compute_validate_rule_cache_key,
    hash_json,
)
from app.micro_apps.loan_onboarding.schemas.validation import RuleEvaluation
from app.services.storage import get_storage
from tests.conftest import TEST_ORG_ID
from tests.loan_onboarding.conftest import TEST_PACKAGE_ID


# ── Cache-key stability ────────────────────────────────────────────────────


def test_compute_stack_content_hash_is_stable_and_field_order_independent():
    """Same semantic content → identical hash, regardless of field input order."""
    pages_a = [
        {
            "page_number": 2,
            "text": "second page text",
            "detected_fields": [
                {"field_name": "loan_amount", "value": "250000"},
                {"field_name": "borrower_name", "value": "Jane"},
            ],
        },
        {
            "page_number": 1,
            "text": "first page text",
            "detected_fields": [
                {"field_name": "borrower_name", "value": "Jane"},
            ],
        },
    ]
    pages_b = [
        {
            "page_number": 1,
            "text": "first page text",
            "detected_fields": [
                {"field_name": "borrower_name", "value": "Jane"},
            ],
        },
        {
            "page_number": 2,
            "text": "second page text",
            "detected_fields": [
                # reversed field order
                {"field_name": "borrower_name", "value": "Jane"},
                {"field_name": "loan_amount", "value": "250000"},
            ],
        },
    ]
    assert compute_stack_content_hash("URLA_1003", pages_a) == \
        compute_stack_content_hash("URLA_1003", pages_b)


def test_compute_stack_content_hash_changes_on_field_value_change():
    base = [{
        "page_number": 1,
        "text": "page",
        "detected_fields": [{"field_name": "borrower_name", "value": "Jane"}],
    }]
    mutated = [{
        "page_number": 1,
        "text": "page",
        "detected_fields": [{"field_name": "borrower_name", "value": "John"}],
    }]
    assert compute_stack_content_hash("URLA_1003", base) != \
        compute_stack_content_hash("URLA_1003", mutated)


def test_compute_validate_rule_cache_key_changes_on_rule_text_change():
    version_info = {
        "validator_model": "claude-sonnet-4-6",
        "validate_prompt_hash": "a" * 64,
        "validate_schema_hash": "b" * 64,
    }
    k1 = compute_validate_rule_cache_key("stack-hash", "r1", "text one", version_info)
    k2 = compute_validate_rule_cache_key("stack-hash", "r1", "text TWO", version_info)
    assert k1 != k2


def test_compute_reason_cache_key_changes_on_rules_version_bump():
    v1 = {
        "reasoner_model": "claude-opus-4-6",
        "reason_prompt_hash": "p",
        "reason_schema_hash": "s",
        "rules_version": "lo_validation_rules_v1",
    }
    v2 = dict(v1, rules_version="lo_validation_rules_v2")
    assert compute_reason_cache_key("summary-hash", v1) != \
        compute_reason_cache_key("summary-hash", v2)


# ── Reasoning agent _coerce pad-order stability ────────────────────────────


def test_coerce_pads_missing_stacks_in_deterministic_order():
    """Reasoning agent coerce must sort padded stack_ids — set iteration
    order is hash-random and would leak non-determinism into output."""
    package_summary = {
        "stacks": [
            {"stack_id": "s2"},
            {"stack_id": "s0"},
            {"stack_id": "s1"},
        ]
    }
    # Agent returned only s1 — s0 and s2 must be padded
    raw = {
        "stacks": [
            {"stack_id": "s1", "decision": "accept", "reasoning": "ok"},
        ]
    }
    out1 = _coerce(raw, package_summary)
    out2 = _coerce(raw, package_summary)
    # Both runs identical
    assert [s.stack_id for s in out1.stacks] == [s.stack_id for s in out2.stacks]
    # Padded entries come after the agent-provided one, in sorted order
    returned_ids = [s.stack_id for s in out1.stacks]
    assert returned_ids == ["s1", "s0", "s2"]


# ── stage_validate cache MISS → HIT replay ─────────────────────────────────


async def _seed_validate_fixture(db: AsyncSession) -> None:
    """Seed a 2-page package + a custom NL rule so stage_validate needs LLM."""
    db.add(LOValidationRule(
        org_id=TEST_ORG_ID,
        package_id=TEST_PACKAGE_ID,
        rule_source="custom",
        rule_id="borrower_name_match",
        description="Borrower name must appear on every page",
        config={},
        enabled=True,
    ))
    file_row = LOPackageFile(
        org_id=TEST_ORG_ID,
        package_id=TEST_PACKAGE_ID,
        filename="bundle.pdf",
        storage_path=f"{TEST_ORG_ID}/{TEST_PACKAGE_ID}/files/bundle.pdf",
        content_hash="x" * 64,
        size_bytes=100,
        page_count=2,
    )
    db.add(file_row)
    await db.flush()
    for pn, role in [(1, "first_page"), (2, "signature_page")]:
        page = LOPage(
            id=uuid.uuid4(),
            org_id=TEST_ORG_ID,
            package_id=TEST_PACKAGE_ID,
            file_id=file_row.id,
            page_number=pn,
            source_page_number=pn,
            heuristic_text=f"Borrower: Jane Smith. Page {pn}.",
            text_length=50,
        )
        db.add(page)
        await db.flush()
        db.add(LOClassification(
            org_id=TEST_ORG_ID,
            package_id=TEST_PACKAGE_ID,
            page_id=page.id,
            page_number=pn,
            predicted_doc_type="URLA_1003",
            predicted_doc_type_alternatives=[],
            confidence=0.95,
            page_role=role,
            detected_fields=[{"field_name": "borrower_name", "value": "Jane Smith"}],
        ))
    await db.commit()


@pytest.mark.asyncio
async def test_stage_validate_cache_miss_then_hit_replays_identically(
    sample_package, db_session: AsyncSession
):
    """First run: LLM called once, cache written. Second run: LLM not called,
    cached result replayed → rules_evaluated byte-identical."""
    await _seed_validate_fixture(db_session)
    storage = get_storage()
    await stage_stack(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()

    mock_validate = AsyncMock(return_value=RuleEvaluation(
        rule_id="borrower_name_match",
        rule_source="custom",
        passed=True,
        evidence="Borrower name 'Jane Smith' found on page 1",
        location=None,
    ))

    # First run — cache miss, LLM invoked
    with patch.object(StackValidatorAgent, "validate_rule", mock_validate):
        await stage_validate(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
        await db_session.commit()
        first_call_count = mock_validate.call_count
    result_1 = (await db_session.execute(
        select(LOValidationResult).where(
            LOValidationResult.package_id == TEST_PACKAGE_ID
        )
    )).scalar_one()
    rules_1 = result_1.rules_evaluated
    breakdown_1 = result_1.confidence_breakdown

    # Drop the validation result rows so stage_validate re-runs from scratch.
    await db_session.execute(
        delete(LOValidationResult).where(
            LOValidationResult.package_id == TEST_PACKAGE_ID
        )
    )
    await db_session.commit()

    # Second run — cache HIT, LLM must NOT be invoked
    mock_validate_2 = AsyncMock(side_effect=AssertionError(
        "LLM called on second run — cache HIT failed"
    ))
    with patch.object(StackValidatorAgent, "validate_rule", mock_validate_2):
        await stage_validate(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
        await db_session.commit()
        assert mock_validate_2.call_count == 0

    result_2 = (await db_session.execute(
        select(LOValidationResult).where(
            LOValidationResult.package_id == TEST_PACKAGE_ID
        )
    )).scalar_one()

    # Byte-identical rules_evaluated and confidence_breakdown
    assert result_2.rules_evaluated == rules_1
    assert result_2.confidence_breakdown == breakdown_1
    # Hash the JSON projections too — guards against dict-ordering leaks.
    assert hash_json(result_2.rules_evaluated) == hash_json(rules_1)
    assert first_call_count >= 1  # sanity: first run did invoke the LLM


@pytest.mark.asyncio
async def test_stage_validate_two_runs_produce_identical_output(
    sample_package, db_session: AsyncSession
):
    """Sanity: even without cache (fresh each time), deterministic inputs +
    deterministic LLM mock → identical output across runs."""
    await _seed_validate_fixture(db_session)
    storage = get_storage()
    await stage_stack(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()

    mock_validate = AsyncMock(return_value=RuleEvaluation(
        rule_id="borrower_name_match",
        rule_source="custom",
        passed=True,
        evidence="Borrower name 'Jane Smith' found on page 1",
        location=None,
    ))
    with patch.object(StackValidatorAgent, "validate_rule", mock_validate):
        await stage_validate(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
        await db_session.commit()
    rules_a = (await db_session.execute(
        select(LOValidationResult).where(
            LOValidationResult.package_id == TEST_PACKAGE_ID
        )
    )).scalar_one().rules_evaluated

    # Second run — cache HIT replays, output identical byte-for-byte
    with patch.object(StackValidatorAgent, "validate_rule", mock_validate):
        await stage_validate(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
        await db_session.commit()
    rules_b = (await db_session.execute(
        select(LOValidationResult).where(
            LOValidationResult.package_id == TEST_PACKAGE_ID
        )
    )).scalar_one().rules_evaluated

    # Order of rule entries matters (guards against the earlier as_completed
    # leak where NL eval order was non-deterministic).
    assert [r["rule_id"] for r in rules_a] == [r["rule_id"] for r in rules_b]
    assert rules_a == rules_b
