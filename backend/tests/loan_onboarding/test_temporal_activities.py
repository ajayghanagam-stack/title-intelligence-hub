"""Tests for LO Temporal activity wrappers.

Verifies that:
- `configure_lo_activities()` is required before any activity runs
- `_run_stage` updates package.pipeline_stage/status and commits stage output
- mark_completed picks `awaiting_review` when hitl_count > 0, `completed` otherwise
- mark_failed writes the stage name + truncated error message
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.loan_onboarding.models.package import LOPackage
from app.micro_apps.loan_onboarding.pipeline import temporal_activities as ta
from tests.conftest import TEST_ORG_ID, test_session_factory
from tests.loan_onboarding.conftest import TEST_PACKAGE_ID


@pytest_asyncio.fixture
async def configured_lo_activities(db_session: AsyncSession):
    """Wire test session factory + a stub storage into the module globals."""
    storage_stub = object()
    ta.configure_lo_activities(test_session_factory, storage_stub)  # type: ignore[arg-type]
    yield
    # Reset
    ta._session_factory = None
    ta._storage = None


@pytest.mark.asyncio
async def test_require_config_raises_when_unset():
    ta._session_factory = None
    ta._storage = None
    with pytest.raises(RuntimeError, match="not configured"):
        ta._require_config()


@pytest.mark.asyncio
async def test_run_stage_sets_processing_then_persists_output(
    db_session: AsyncSession, sample_package, configured_lo_activities
):
    async def fake_stage(package_uuid, org_uuid, db, storage):
        return {"pages": 42, "marker": "ok"}

    result = await ta._run_stage(
        fake_stage, str(TEST_PACKAGE_ID), str(TEST_ORG_ID), "ingest"
    )

    assert result == {"pages": 42, "marker": "ok"}

    db_session.expire_all()
    pkg = (await db_session.execute(
        select(LOPackage).where(LOPackage.id == TEST_PACKAGE_ID)
    )).scalar_one()
    assert pkg.status == "processing"
    assert pkg.pipeline_stage == "ingest"
    assert pkg.pipeline_error is None


@pytest.mark.asyncio
async def test_run_stage_returns_empty_dict_when_stage_returns_none(
    db_session: AsyncSession, sample_package, configured_lo_activities
):
    async def fake_stage(*_):
        return None

    result = await ta._run_stage(
        fake_stage, str(TEST_PACKAGE_ID), str(TEST_ORG_ID), "classify"
    )
    assert result == {}


@pytest.mark.asyncio
async def test_mark_completed_awaiting_when_hitl_positive(
    db_session: AsyncSession, sample_package, configured_lo_activities
):
    await ta.lo_activity_mark_completed(
        str(TEST_PACKAGE_ID), str(TEST_ORG_ID), 3
    )
    db_session.expire_all()
    pkg = (await db_session.execute(
        select(LOPackage).where(LOPackage.id == TEST_PACKAGE_ID)
    )).scalar_one()
    assert pkg.status == "awaiting_review"
    assert pkg.pipeline_stage == "complete"
    assert pkg.pipeline_error is None


@pytest.mark.asyncio
async def test_mark_completed_done_when_hitl_zero(
    db_session: AsyncSession, sample_package, configured_lo_activities
):
    await ta.lo_activity_mark_completed(
        str(TEST_PACKAGE_ID), str(TEST_ORG_ID), 0
    )
    db_session.expire_all()
    pkg = (await db_session.execute(
        select(LOPackage).where(LOPackage.id == TEST_PACKAGE_ID)
    )).scalar_one()
    assert pkg.status == "completed"
    assert pkg.pipeline_stage == "complete"


@pytest.mark.asyncio
async def test_mark_failed_writes_truncated_error(
    db_session: AsyncSession, sample_package, configured_lo_activities
):
    long_err = "x" * 1000
    await ta.lo_activity_mark_failed(
        str(TEST_PACKAGE_ID), str(TEST_ORG_ID), long_err, "classify"
    )
    db_session.expire_all()
    pkg = (await db_session.execute(
        select(LOPackage).where(LOPackage.id == TEST_PACKAGE_ID)
    )).scalar_one()
    assert pkg.status == "failed"
    assert pkg.pipeline_stage == "classify"
    assert pkg.pipeline_error is not None
    assert len(pkg.pipeline_error) <= 500
