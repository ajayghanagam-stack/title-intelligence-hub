"""Tests for the Phase 3.5 monotonic stage-advance contract.

Covers the pure function (unit + property-based) and the integration
with ``mark_pipeline_status`` so a remediation write can't rewind the
loan past where it already advanced.
"""
from __future__ import annotations

import itertools
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.loan_onboarding.services import package_service
from app.micro_apps.loan_onboarding.services.stage_advance import (
    STAGE_ORDER,
    advance_stage,
    all_known_stages,
    is_monotonic_advance,
    is_terminal,
    stage_index,
)
from tests.conftest import TEST_ORG_ID
from tests.loan_onboarding.conftest import TEST_PACKAGE_ID


# ── Pure function unit tests ──────────────────────────────────────────


def test_stage_order_is_canonical():
    """Lock the stage order in tests so an accidental reorder gets caught."""
    assert STAGE_ORDER == (
        "ingest",
        "classify",
        "doc_validation",
        "extract",
        "data_validation",
        "decision_ready",
        "complete",
    )


def test_stage_index_unknown_returns_minus_one():
    assert stage_index("not_a_stage") == -1
    assert stage_index(None) == -1


def test_stage_index_aliases_resolve():
    # "validate" is an alias for "doc_validation"
    assert stage_index("validate") == stage_index("doc_validation")
    # "stack" merges into "classify"
    assert stage_index("stack") == stage_index("classify")
    # "review" → decision_ready
    assert stage_index("review") == stage_index("decision_ready")


def test_advance_forward_returns_target():
    assert advance_stage("ingest", "classify") == "classify"
    assert advance_stage("classify", "extract") == "extract"


def test_advance_backward_holds_current():
    assert advance_stage("extract", "ingest") == "extract"
    assert advance_stage("doc_validation", "classify") == "doc_validation"


def test_advance_same_stage_is_idempotent():
    assert advance_stage("classify", "classify") == "classify"


def test_advance_from_none_accepts_any_target():
    assert advance_stage(None, "classify") == "classify"
    assert advance_stage(None, "ingest") == "ingest"


def test_advance_target_none_returns_current():
    assert advance_stage("classify", None) == "classify"
    assert advance_stage(None, None) is None


def test_terminal_blocks_further_advance():
    assert advance_stage("complete", "ingest") == "complete"
    assert advance_stage("complete", "decision_ready") == "complete"
    # `complete` itself is in STAGE_ORDER but is_terminal — once you're
    # there you stay there even from a "forward" write.
    assert advance_stage("complete", "complete") == "complete"


def test_alias_writes_advance_correctly():
    # Writing the legacy "validate" name from "classify" should advance
    # to doc_validation (the canonical name).
    assert advance_stage("classify", "validate") == "validate"
    # Writing "stack" from extract is a backward move (stack→classify in
    # canonical order, classify < extract) → no advance.
    assert advance_stage("extract", "stack") == "extract"


def test_is_monotonic_advance_predicate():
    assert is_monotonic_advance("ingest", "classify") is True
    assert is_monotonic_advance("extract", "ingest") is False
    assert is_monotonic_advance(None, "ingest") is True
    assert is_monotonic_advance("complete", "anything") is False


def test_is_terminal_only_complete_and_failed():
    assert is_terminal("complete") is True
    assert is_terminal("failed") is True
    assert is_terminal("ingest") is False
    assert is_terminal(None) is False


# ── Property-based: monotonicity holds across all stage pairs ─────────


def test_advance_is_monotonic_across_all_pairs():
    """For any (current, target) pair from the known-stage domain, the
    persisted stage's index is never less than current's index — the
    contract spec from PRD §3.5.

    Uses an exhaustive cross product instead of hypothesis to avoid a
    new test dependency; the domain is ~13 stages so 169 pairs is fine.
    """
    stages = list(all_known_stages())
    for current, target in itertools.product(stages, stages):
        result = advance_stage(current, target)
        # Terminals freeze the stage — the property doesn't apply
        # because writes after `complete` are no-ops by design.
        if is_terminal(current):
            assert result == current, (
                f"Terminal current={current!r} must hold; got {result!r} "
                f"after writing {target!r}"
            )
            continue
        assert stage_index(result) >= stage_index(current), (
            f"Monotonic violation: current={current!r} target={target!r} "
            f"→ {result!r} (idx {stage_index(result)} < idx {stage_index(current)})"
        )


# ── Integration: mark_pipeline_status enforces monotonic advance ──────


@pytest.mark.asyncio
async def test_mark_pipeline_status_does_not_rewind(
    db_session: AsyncSession, sample_package,
):
    # Sample package starts at "uploading" with no pipeline_stage.
    await package_service.mark_pipeline_status(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
        status="processing", pipeline_stage="extract",
    )
    # A remediation flow tries to rewind to "classify" — must hold
    # at "extract".
    await package_service.mark_pipeline_status(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
        pipeline_stage="classify",
    )
    pkg = await package_service.get_package_or_raise(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
    )
    assert pkg.pipeline_stage == "extract"


@pytest.mark.asyncio
async def test_mark_pipeline_status_advances_forward(
    db_session: AsyncSession, sample_package,
):
    await package_service.mark_pipeline_status(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
        pipeline_stage="ingest",
    )
    await package_service.mark_pipeline_status(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
        pipeline_stage="extract",
    )
    pkg = await package_service.get_package_or_raise(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
    )
    assert pkg.pipeline_stage == "extract"


@pytest.mark.asyncio
async def test_mark_pipeline_status_failed_can_overwrite_terminal(
    db_session: AsyncSession, sample_package,
):
    """The ``status="failed"`` escape hatch — a failed run can stamp the
    failing stage even if the package previously reached `complete`.

    Without this, a retry that fails wouldn't be able to record where it
    failed, which would defeat error-reporting for retried packages.
    """
    await package_service.mark_pipeline_status(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
        status="completed", pipeline_stage="complete",
    )
    await package_service.mark_pipeline_status(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
        status="failed", pipeline_stage="extract",
        pipeline_error="something blew up",
    )
    pkg = await package_service.get_package_or_raise(
        db_session, TEST_ORG_ID, TEST_PACKAGE_ID,
    )
    assert pkg.status == "failed"
    assert pkg.pipeline_stage == "extract"
