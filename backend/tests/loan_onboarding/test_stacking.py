"""Tests for the deterministic stacking service + stage_stack integration."""
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.loan_onboarding.ai.page_classifier_agent import OTHERS_KEY
from app.micro_apps.loan_onboarding.models.classification import LOClassification
from app.micro_apps.loan_onboarding.models.page import LOPage
from app.micro_apps.loan_onboarding.models.package_file import LOPackageFile
from app.micro_apps.loan_onboarding.models.stack import LOStack
from app.micro_apps.loan_onboarding.pipeline.stages import stage_stack
from app.micro_apps.loan_onboarding.services.stacking import (
    ClassifiedPage,
    build_stacks,
)
from app.services.storage import get_storage
from tests.conftest import TEST_ORG_ID
from tests.loan_onboarding.conftest import TEST_PACKAGE_ID


# ── unit tests for build_stacks ─────────────────────────────────────────────


def test_build_stacks_single_type_single_stack():
    pages = [
        ClassifiedPage(1, "urla_1003", 0.9, "first_page"),
        ClassifiedPage(2, "urla_1003", 0.85, "continuation"),
        ClassifiedPage(3, "urla_1003", 0.95, "last_page"),
    ]
    stacks = build_stacks(pages, hitl_threshold=0.75)
    assert len(stacks) == 1
    s = stacks[0]
    assert s.stack_index == 0
    assert s.doc_type == "urla_1003"
    assert s.page_numbers == [1, 2, 3]
    assert s.first_page == 1
    assert s.last_page == 3
    assert s.classification_confidence == pytest.approx(0.9)
    assert s.requires_hitl is False


def test_build_stacks_breaks_on_doc_type_change():
    pages = [
        ClassifiedPage(1, "urla_1003", 0.9, "first_page"),
        ClassifiedPage(2, "urla_1003", 0.9, "continuation"),
        ClassifiedPage(3, "paystub", 0.88, "first_page"),
        ClassifiedPage(4, "paystub", 0.88, "last_page"),
        ClassifiedPage(5, "w2", 0.92, "first_page"),
    ]
    stacks = build_stacks(pages)
    assert [s.doc_type for s in stacks] == ["urla_1003", "paystub", "w2"]
    assert [s.page_numbers for s in stacks] == [[1, 2], [3, 4], [5]]
    assert [s.stack_index for s in stacks] == [0, 1, 2]


def test_build_stacks_collapses_same_doc_type_into_one_stack():
    """Multiple runs of the same doc_type collapse into a single stack.

    Previously this created one stack per `first_page` boundary, which
    produced duplicate entries in the UI (two "paystub" rows, two "Others"
    rows, etc.). The reviewer's mental model is "one entry per document
    type," so same-doc-type pages now merge regardless of position.
    """
    pages = [
        ClassifiedPage(1, "paystub", 0.9, "first_page"),
        ClassifiedPage(2, "paystub", 0.9, "last_page"),
        ClassifiedPage(3, "paystub", 0.9, "first_page"),  # new paystub instance
        ClassifiedPage(4, "paystub", 0.9, "last_page"),
    ]
    stacks = build_stacks(pages)
    assert len(stacks) == 1
    assert stacks[0].doc_type == "paystub"
    assert stacks[0].page_numbers == [1, 2, 3, 4]
    assert stacks[0].first_page == 1
    assert stacks[0].last_page == 4


def test_build_stacks_merges_non_contiguous_runs_of_same_doc_type():
    """A page of a different doc_type between two same-type runs does NOT
    split the stack — both runs land in the same doc_type stack.

    This handles the common Gemini failure mode of misclassifying a blank
    or signature page as Others in the middle of an otherwise-coherent
    document, which previously produced two "Title Commitment" entries
    plus one "Others" entry for what is really a single title commitment.
    """
    pages = [
        ClassifiedPage(1, "TITLE_COMMITMENT", 0.9, "first_page"),
        ClassifiedPage(2, "TITLE_COMMITMENT", 0.9, "continuation"),
        ClassifiedPage(3, "Others", 0.4, "unknown"),   # misclassified mid-doc
        ClassifiedPage(4, "TITLE_COMMITMENT", 0.9, "continuation"),
        ClassifiedPage(5, "TITLE_COMMITMENT", 0.9, "last_page"),
    ]
    stacks = build_stacks(pages)
    # Two stacks total: one for TITLE_COMMITMENT (pages 1,2,4,5), one for Others (page 3).
    assert [s.doc_type for s in stacks] == ["TITLE_COMMITMENT", "Others"]
    assert stacks[0].page_numbers == [1, 2, 4, 5]
    assert stacks[0].first_page == 1
    assert stacks[0].last_page == 5
    assert stacks[1].page_numbers == [3]


def test_build_stacks_others_always_requires_hitl_even_if_high_confidence():
    pages = [
        ClassifiedPage(1, OTHERS_KEY, 1.0, "unknown"),  # blank page classification
        ClassifiedPage(2, OTHERS_KEY, 1.0, "unknown"),
    ]
    stacks = build_stacks(pages, hitl_threshold=0.75)
    assert len(stacks) == 1
    assert stacks[0].doc_type == OTHERS_KEY
    assert stacks[0].requires_hitl is True


def test_build_stacks_low_confidence_triggers_hitl():
    pages = [
        ClassifiedPage(1, "urla_1003", 0.6, "first_page"),
        ClassifiedPage(2, "urla_1003", 0.7, "continuation"),
    ]
    stacks = build_stacks(pages, hitl_threshold=0.75)
    assert stacks[0].requires_hitl is True
    assert stacks[0].classification_confidence == pytest.approx(0.65)


def test_build_stacks_is_deterministic_and_sorts_input():
    """Same input (even out-of-order) → byte-identical output every call."""
    pages = [
        ClassifiedPage(3, "paystub", 0.9, "first_page"),
        ClassifiedPage(1, "urla_1003", 0.9, "first_page"),
        ClassifiedPage(2, "urla_1003", 0.9, "continuation"),
    ]
    s1 = build_stacks(pages)
    s2 = build_stacks(pages)
    assert [(s.doc_type, s.page_numbers) for s in s1] == [
        (s.doc_type, s.page_numbers) for s in s2
    ]
    assert [s.page_numbers for s in s1] == [[1, 2], [3]]


def test_build_stacks_empty_input():
    assert build_stacks([]) == []


def test_build_stacks_accepts_dict_rows():
    """Callers can pass dicts as well as ClassifiedPage objects."""
    stacks = build_stacks([
        {"page_number": 1, "predicted_doc_type": "w2", "confidence": 0.8, "page_role": "first_page"},
        {"page_number": 2, "predicted_doc_type": "w2", "confidence": 0.9, "page_role": "last_page"},
    ])
    assert len(stacks) == 1
    assert stacks[0].doc_type == "w2"
    assert stacks[0].page_numbers == [1, 2]


# ── stage_stack integration (against DB) ────────────────────────────────────


async def _seed_classifications(
    db: AsyncSession,
    rows: list[tuple[int, str, float, str]],
) -> None:
    """Seed LOPage + LOClassification rows for the test package.

    Each row is (page_number, predicted_doc_type, confidence, page_role).
    """
    # We need a parent LOPackageFile row for the FK; reuse or create one.
    file_row = (await db.execute(
        select(LOPackageFile).where(LOPackageFile.package_id == TEST_PACKAGE_ID)
    )).scalar_one_or_none()
    if file_row is None:
        file_row = LOPackageFile(
            org_id=TEST_ORG_ID,
            package_id=TEST_PACKAGE_ID,
            filename="stacking_fixture.pdf",
            storage_path=f"{TEST_ORG_ID}/{TEST_PACKAGE_ID}/files/stacking_fixture.pdf",
            content_hash="s" * 64,
            size_bytes=100,
            page_count=len(rows),
        )
        db.add(file_row)
        await db.flush()

    for pn, doc_type, conf, role in rows:
        page = LOPage(
            id=uuid.uuid4(),
            org_id=TEST_ORG_ID,
            package_id=TEST_PACKAGE_ID,
            file_id=file_row.id,
            page_number=pn,
            source_page_number=pn,
            heuristic_text="x" * 100,
            text_length=100,
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
            detected_fields=[],
        ))
    await db.commit()


@pytest.mark.asyncio
async def test_stage_stack_groups_classifications_into_stacks(
    sample_package, db_session: AsyncSession
):
    await _seed_classifications(db_session, [
        (1, "urla_1003", 0.92, "first_page"),
        (2, "urla_1003", 0.90, "continuation"),
        (3, "urla_1003", 0.88, "last_page"),
        (4, "paystub", 0.85, "first_page"),
        (5, "paystub", 0.80, "last_page"),
        (6, OTHERS_KEY, 1.0, "unknown"),  # blank page
    ])

    storage = get_storage()
    out = await stage_stack(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()

    assert out == {"pages": 6, "stacks": 3, "hitl_stacks": 1}

    rows = (await db_session.execute(
        select(LOStack)
        .where(LOStack.package_id == TEST_PACKAGE_ID)
        .order_by(LOStack.stack_index)
    )).scalars().all()
    assert [r.doc_type for r in rows] == ["urla_1003", "paystub", OTHERS_KEY]
    assert [r.first_page for r in rows] == [1, 4, 6]
    assert [r.last_page for r in rows] == [3, 5, 6]
    assert [r.page_numbers for r in rows] == [[1, 2, 3], [4, 5], [6]]
    assert [r.stack_index for r in rows] == [0, 1, 2]
    # Only the Others stack requires HITL (the other two are high-confidence)
    assert [r.requires_hitl for r in rows] == [False, False, True]
    assert all(r.status == "classified" for r in rows)


@pytest.mark.asyncio
async def test_stage_stack_is_idempotent(sample_package, db_session: AsyncSession):
    await _seed_classifications(db_session, [
        (1, "urla_1003", 0.9, "first_page"),
        (2, "urla_1003", 0.9, "last_page"),
    ])

    storage = get_storage()
    await stage_stack(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()
    await stage_stack(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()

    rows = (await db_session.execute(
        select(LOStack).where(LOStack.package_id == TEST_PACKAGE_ID)
    )).scalars().all()
    assert len(rows) == 1  # no duplicates on re-run


@pytest.mark.asyncio
async def test_stage_stack_requires_classifications_first(
    sample_package, db_session: AsyncSession
):
    storage = get_storage()
    with pytest.raises(ValueError, match="No classifications to stack"):
        await stage_stack(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)


@pytest.mark.asyncio
async def test_stage_stack_respects_package_hitl_threshold(
    sample_package, db_session: AsyncSession
):
    """If classification_confidence < package.hitl_threshold, stack is HITL-flagged."""
    # Package default hitl_threshold is 0.75 (set in conftest). Seed with 0.7 avg.
    await _seed_classifications(db_session, [
        (1, "urla_1003", 0.7, "first_page"),
        (2, "urla_1003", 0.7, "last_page"),
    ])

    storage = get_storage()
    await stage_stack(TEST_PACKAGE_ID, TEST_ORG_ID, db_session, storage)
    await db_session.commit()

    row = (await db_session.execute(
        select(LOStack).where(LOStack.package_id == TEST_PACKAGE_ID)
    )).scalar_one()
    assert row.requires_hitl is True
    assert row.classification_confidence == pytest.approx(0.7)
