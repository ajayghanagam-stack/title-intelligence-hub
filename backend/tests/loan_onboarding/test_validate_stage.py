"""Integration tests for stage_validate + stage_review."""
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.loan_onboarding.ai.page_classifier_agent import OTHERS_KEY
from app.micro_apps.loan_onboarding.ai.reasoning_agent import (
    PackageReasoningOutput,
    StackReasoning,
)
from app.micro_apps.loan_onboarding.ai.stack_validator_agent import (
    StackValidatorAgent,
)
from app.micro_apps.loan_onboarding.models.classification import LOClassification
from app.micro_apps.loan_onboarding.models.package_file import LOPackageFile
from app.micro_apps.loan_onboarding.models.page import LOPage
from app.micro_apps.loan_onboarding.models.package import LOPackage
from app.micro_apps.loan_onboarding.models.stack import LOStack
from app.micro_apps.loan_onboarding.models.validation_result import LOValidationResult
from app.micro_apps.loan_onboarding.models.validation_rule import LOValidationRule
from app.micro_apps.loan_onboarding.pipeline.stages import (
    stage_review,
    stage_stack,
    stage_validate,
)
from app.micro_apps.loan_onboarding.schemas.validation import RuleEvaluation
from app.services.storage import get_storage
from tests.conftest import TEST_ORG_ID
from tests.loan_onboarding.conftest import TEST_PACKAGE_ID


async def _seed_full_package(
    db: AsyncSession,
    classification_rows: list[tuple[int, str, float, str, list[dict]]],
) -> None:
    """Seed pages + classifications. Rules are already seeded by sample_package."""
    file_row = LOPackageFile(
        org_id=TEST_ORG_ID,
        package_id=TEST_PACKAGE_ID,
        filename="bundle.pdf",
        storage_path=f"{TEST_ORG_ID}/{TEST_PACKAGE_ID}/files/bundle.pdf",
        content_hash="x" * 64,
        size_bytes=100,
        page_count=len(classification_rows),
    )
    db.add(file_row)
    await db.flush()

    for pn, doc_type, conf, role, fields in classification_rows:
        page = LOPage(
            id=uuid.uuid4(),
            org_id=TEST_ORG_ID,
            package_id=TEST_PACKAGE_ID,
            file_id=file_row.id,
            page_number=pn,
            source_page_number=pn,
            heuristic_text=f"Page {pn} text for {doc_type}",
            text_length=50,
        )
        db.add(page)
        await db.flush()
        db.add(LOClassification(
            org_id=TEST_ORG_ID,
            package_id=TEST_PACKAGE_ID,
            page_id=page.id,
            page_number=pn,
            predicted_doc_type=doc_type,
            predicted_doc_type_alternatives=[],
            confidence=conf,
            page_role=role,
            detected_fields=fields,
        ))
    await db.commit()


# ── stage_validate ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stage_validate_runs_preset_rules(
    sample_package, db_session: AsyncSession
):
    """Preset rule `missing_signatures` is already seeded on sample_package."""
    await _seed_full_package(db_session, [
        (1, "URLA_1003", 0.9, "first_page", []),
        (2, "URLA_1003", 0.9, "last_page", []),
    ])
    storage = get_storage()
    await stage_stack(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()

    out = await stage_validate(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()

    assert out["stacks"] == 1
    assert out["preset_rules"] == 1  # missing_signatures seeded in conftest
    assert out["custom_rules"] == 0

    results = (await db_session.execute(
        select(LOValidationResult).where(
            LOValidationResult.package_id == TEST_PACKAGE_ID
        )
    )).scalars().all()
    assert len(results) == 1
    result = results[0]
    # Rule evaluation present
    assert len(result.rules_evaluated) == 1
    rule_row = result.rules_evaluated[0]
    assert rule_row["rule_id"] == "missing_signatures"
    assert rule_row["rule_source"] == "preset"
    # No signature page was seeded → rule fails
    assert rule_row["passed"] is False
    # Confidence breakdown has all three fields
    assert set(result.confidence_breakdown.keys()) == {
        "classification", "split_accuracy", "validation"
    }
    # Failing rule → stack requires HITL
    assert result.requires_hitl is True


@pytest.mark.asyncio
async def test_stage_validate_passes_when_signature_page_present(
    sample_package, db_session: AsyncSession
):
    await _seed_full_package(db_session, [
        (1, "URLA_1003", 0.95, "first_page", []),
        (2, "URLA_1003", 0.95, "signature_page", []),
    ])
    storage = get_storage()
    await stage_stack(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()

    await stage_validate(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()

    result = (await db_session.execute(
        select(LOValidationResult).where(
            LOValidationResult.package_id == TEST_PACKAGE_ID
        )
    )).scalar_one()
    assert result.rules_evaluated[0]["passed"] is True
    # High confidence + passing rules → no HITL
    assert result.requires_hitl is False


@pytest.mark.asyncio
async def test_stage_validate_is_idempotent(
    sample_package, db_session: AsyncSession
):
    await _seed_full_package(db_session, [
        (1, "URLA_1003", 0.9, "first_page", []),
        (2, "URLA_1003", 0.9, "signature_page", []),
    ])
    storage = get_storage()
    await stage_stack(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()
    await stage_validate(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()
    await stage_validate(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()

    rows = (await db_session.execute(
        select(LOValidationResult).where(
            LOValidationResult.package_id == TEST_PACKAGE_ID
        )
    )).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_stage_validate_runs_custom_nl_rules_through_agent(
    sample_package, db_session: AsyncSession
):
    # Add a custom NL rule
    db_session.add(LOValidationRule(
        org_id=TEST_ORG_ID,
        package_id=TEST_PACKAGE_ID,
        rule_source="custom",
        rule_id="borrower_name_match",
        description="Borrower name must appear on every page",
        config={},
        enabled=True,
    ))
    await db_session.commit()

    await _seed_full_package(db_session, [
        (1, "URLA_1003", 0.95, "first_page", []),
        (2, "URLA_1003", 0.95, "signature_page", []),
    ])
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

    result = (await db_session.execute(
        select(LOValidationResult).where(
            LOValidationResult.package_id == TEST_PACKAGE_ID
        )
    )).scalar_one()
    rule_ids = [r["rule_id"] for r in result.rules_evaluated]
    assert "missing_signatures" in rule_ids
    assert "borrower_name_match" in rule_ids
    mock_validate.assert_called_once()


@pytest.mark.asyncio
async def test_stage_validate_requires_stacks_first(
    sample_package, db_session: AsyncSession
):
    storage = get_storage()
    with pytest.raises(ValueError, match="No stacks to validate"):
        await stage_validate(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)


# ── stage_review ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stage_review_accepts_clean_stacks(
    sample_package, db_session: AsyncSession
):
    await _seed_full_package(db_session, [
        (1, "URLA_1003", 0.95, "first_page", []),
        (2, "URLA_1003", 0.95, "signature_page", []),
    ])
    storage = get_storage()
    await stage_stack(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()
    await stage_validate(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()

    stack = (await db_session.execute(
        select(LOStack).where(LOStack.package_id == TEST_PACKAGE_ID)
    )).scalar_one()
    assert stack.requires_hitl is False  # clean stack after validate

    from app.micro_apps.loan_onboarding.ai import reasoning_agent as ra_mod

    mock_reason = AsyncMock(return_value=PackageReasoningOutput(
        stacks=[StackReasoning(
            stack_id=f"s{stack.stack_index}",
            decision="accept",
            reasoning="All rules passed, high confidence.",
        )],
        package_level_issues=[],
    ))
    with patch.object(ra_mod.ReasoningAgent, "reason", mock_reason):
        out = await stage_review(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
        await db_session.commit()

    assert out == {"stacks": 1, "hitl_stacks": 0, "package_level_issues": 0}

    stack = (await db_session.execute(
        select(LOStack).where(LOStack.package_id == TEST_PACKAGE_ID)
    )).scalar_one()
    assert stack.status == "accepted"
    pkg = (await db_session.execute(
        select(LOPackage).where(LOPackage.id == TEST_PACKAGE_ID)
    )).scalar_one()
    assert pkg.status == "completed"


@pytest.mark.asyncio
async def test_stage_review_honors_hitl_floor_on_others(
    sample_package, db_session: AsyncSession
):
    """Even if the reasoner says 'accept', an Others stack stays needs_review."""
    await _seed_full_package(db_session, [
        (1, OTHERS_KEY, 1.0, "unknown", []),
    ])
    storage = get_storage()
    await stage_stack(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()
    await stage_validate(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()

    stack = (await db_session.execute(
        select(LOStack).where(LOStack.package_id == TEST_PACKAGE_ID)
    )).scalar_one()
    assert stack.requires_hitl is True  # Others always HITL

    from app.micro_apps.loan_onboarding.ai import reasoning_agent as ra_mod
    mock_reason = AsyncMock(return_value=PackageReasoningOutput(
        stacks=[StackReasoning(
            stack_id=f"s{stack.stack_index}",
            decision="accept",  # <-- agent says accept
            reasoning="Looks fine.",
        )],
        package_level_issues=[],
    ))
    with patch.object(ra_mod.ReasoningAgent, "reason", mock_reason):
        await stage_review(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
        await db_session.commit()

    stack = (await db_session.execute(
        select(LOStack).where(LOStack.package_id == TEST_PACKAGE_ID)
    )).scalar_one()
    # Floor won — still needs review
    assert stack.status == "needs_review"
    pkg = (await db_session.execute(
        select(LOPackage).where(LOPackage.id == TEST_PACKAGE_ID)
    )).scalar_one()
    assert pkg.status == "awaiting_review"


@pytest.mark.asyncio
async def test_stage_review_persists_package_level_issues(
    sample_package, db_session: AsyncSession
):
    await _seed_full_package(db_session, [
        (1, "URLA_1003", 0.95, "first_page", []),
        (2, "URLA_1003", 0.95, "signature_page", []),
    ])
    storage = get_storage()
    await stage_stack(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()
    await stage_validate(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()

    stack = (await db_session.execute(
        select(LOStack).where(LOStack.package_id == TEST_PACKAGE_ID)
    )).scalar_one()

    from app.micro_apps.loan_onboarding.ai import reasoning_agent as ra_mod
    from app.micro_apps.loan_onboarding.ai.reasoning_agent import PackageLevelIssue
    mock_reason = AsyncMock(return_value=PackageReasoningOutput(
        stacks=[StackReasoning(
            stack_id=f"s{stack.stack_index}",
            decision="needs_review",
            reasoning="Borrower name mismatch suspected.",
        )],
        package_level_issues=[PackageLevelIssue(
            issue_type="missing_required_doc_type",
            description="PAYSTUB was required but not found in package",
        )],
    ))
    with patch.object(ra_mod.ReasoningAgent, "reason", mock_reason):
        await stage_review(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
        await db_session.commit()

    pkg = (await db_session.execute(
        select(LOPackage).where(LOPackage.id == TEST_PACKAGE_ID)
    )).scalar_one()
    issues = pkg.progress.get("package_level_issues")
    assert len(issues) == 1
    assert issues[0]["issue_type"] == "missing_required_doc_type"


@pytest.mark.asyncio
async def test_stage_review_requires_stacks(
    sample_package, db_session: AsyncSession
):
    storage = get_storage()
    with pytest.raises(ValueError, match="No stacks to review"):
        await stage_review(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
