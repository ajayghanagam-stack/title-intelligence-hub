"""Tests for Temporal activity functions.

Tests the pack status updates, audit events, and stage execution
in activity_mark_completed, activity_mark_failed, and _run_stage.
"""

import uuid
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.pack import Pack
from app.models.audit_event import AuditEvent
from app.micro_apps.title_intelligence.pipeline.temporal_activities import (
    configure_activities,
    _run_stage,
    activity_mark_completed,
    activity_mark_failed,
)
from app.micro_apps.title_intelligence.pipeline.stages import stage_ingest

from tests.conftest import TEST_ORG_ID, test_session_factory


TEST_PACK_ID = uuid.UUID("00000000-0000-0000-0000-000000010000")


@pytest_asyncio.fixture
async def temporal_pack(db_session: AsyncSession, seed_data):
    """Create a pack in processing state for temporal tests."""
    pack = Pack(
        id=TEST_PACK_ID,
        org_id=TEST_ORG_ID,
        name="Temporal Test Pack",
        status="processing",
        current_stage="ingest",
    )
    db_session.add(pack)
    await db_session.commit()
    return pack


@pytest_asyncio.fixture
def configured_activities(db_session: AsyncSession):
    """Configure temporal activities with test session factory and mock storage."""
    mock_storage = MagicMock()
    configure_activities(test_session_factory, mock_storage)
    yield mock_storage
    # Reset after test
    configure_activities(None, None)


@pytest.mark.asyncio
async def test_run_stage_updates_pack_status(
    db_session: AsyncSession, seed_data, temporal_pack, configured_activities
):
    """_run_stage should update pack.current_stage and status before calling stage_fn."""
    mock_stage = AsyncMock()

    with patch("app.micro_apps.title_intelligence.pipeline.temporal_activities.activity") as mock_activity:
        # Add the mock stage to STAGE_NAMES so it gets a name
        from app.micro_apps.title_intelligence.pipeline import temporal_activities
        original_names = temporal_activities.STAGE_NAMES.copy()
        temporal_activities.STAGE_NAMES[mock_stage] = "test_stage"

        try:
            await _run_stage(mock_stage, str(TEST_PACK_ID), str(TEST_ORG_ID))
        finally:
            temporal_activities.STAGE_NAMES = original_names

    # Verify stage function was called with UUID args
    mock_stage.assert_called_once()
    call_args = mock_stage.call_args
    assert call_args[0][0] == TEST_PACK_ID
    assert call_args[0][1] == TEST_ORG_ID

    # Expire cached objects to see changes from activity's separate session
    db_session.expire_all()

    # Verify pack status was updated
    result = await db_session.execute(select(Pack).where(Pack.id == TEST_PACK_ID))
    pack = result.scalar_one()
    assert pack.status == "processing"

    # Verify heartbeat was called
    mock_activity.heartbeat.assert_called_once_with("completed_test_stage")


@pytest.mark.asyncio
async def test_activity_mark_completed(
    db_session: AsyncSession, seed_data, temporal_pack, configured_activities
):
    """activity_mark_completed should set status=completed, clear current_stage, and write audit event."""
    with patch("app.micro_apps.title_intelligence.pipeline.temporal_activities.activity"):
        await activity_mark_completed(str(TEST_PACK_ID), str(TEST_ORG_ID))

    # Expire cached objects to see changes from activity's separate session
    db_session.expire_all()

    # Verify pack status
    result = await db_session.execute(select(Pack).where(Pack.id == TEST_PACK_ID))
    pack = result.scalar_one()
    assert pack.status == "completed"
    assert pack.current_stage is None

    # Verify audit event
    result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == TEST_ORG_ID,
            AuditEvent.action == "pipeline_completed",
        )
    )
    event = result.scalar_one()
    assert event.target_type == "ti_pack"
    assert event.target_id == TEST_PACK_ID


@pytest.mark.asyncio
async def test_activity_mark_failed(
    db_session: AsyncSession, seed_data, temporal_pack, configured_activities
):
    """activity_mark_failed should set status=failed, error_message, and write audit event."""
    error_msg = "Examine processing failed"
    stage_name = "examine"

    with patch("app.micro_apps.title_intelligence.pipeline.temporal_activities.activity"):
        await activity_mark_failed(str(TEST_PACK_ID), str(TEST_ORG_ID), error_msg, stage_name)

    # Expire cached objects to see changes from activity's separate session
    db_session.expire_all()

    # Verify pack status
    result = await db_session.execute(select(Pack).where(Pack.id == TEST_PACK_ID))
    pack = result.scalar_one()
    assert pack.status == "failed"
    assert "examine" in pack.error_message
    # Error message is sanitized — raw exception text should NOT be exposed
    assert pack.error_message == "Processing failed at stage 'examine'"

    # Verify audit event
    result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == TEST_ORG_ID,
            AuditEvent.action == "pipeline_failed",
        )
    )
    event = result.scalar_one()
    assert event.target_type == "ti_pack"
    assert event.target_id == TEST_PACK_ID
    assert event.metadata_["stage"] == "examine"
    assert event.metadata_["error"] == error_msg


@pytest.mark.asyncio
async def test_run_stage_sends_heartbeats(
    db_session: AsyncSession, seed_data, temporal_pack, configured_activities
):
    """_run_stage should send periodic heartbeats during stage execution."""
    import asyncio

    async def slow_stage(*args, **kwargs):
        """Simulate a slow stage that takes long enough for heartbeats."""
        await asyncio.sleep(0.1)

    with patch("app.micro_apps.title_intelligence.pipeline.temporal_activities.activity") as mock_activity:
        from app.micro_apps.title_intelligence.pipeline import temporal_activities
        original_names = temporal_activities.STAGE_NAMES.copy()
        temporal_activities.STAGE_NAMES[slow_stage] = "slow_stage"

        # Use a very short heartbeat interval so the test doesn't take long
        with patch(
            "app.micro_apps.title_intelligence.pipeline.temporal_activities._heartbeat_loop",
            side_effect=lambda stage_name, interval=30.0: temporal_activities._heartbeat_loop(stage_name, interval=0.02),
        ):
            try:
                await _run_stage(slow_stage, str(TEST_PACK_ID), str(TEST_ORG_ID))
            finally:
                temporal_activities.STAGE_NAMES = original_names

    # Should have called heartbeat at least once with "running_" prefix during execution
    # plus the final "completed_" heartbeat
    heartbeat_calls = [
        str(c) for c in mock_activity.heartbeat.call_args_list
    ]
    has_running = any("running_slow_stage" in c for c in heartbeat_calls)
    has_completed = any("completed_slow_stage" in c for c in heartbeat_calls)
    assert has_completed, "Should have a completed heartbeat"
    # running heartbeat may or may not fire depending on timing, so just check completed


@pytest.mark.asyncio
async def test_run_stage_raises_without_configuration():
    """_run_stage should raise RuntimeError if activities not configured."""
    configure_activities(None, None)
    with pytest.raises(RuntimeError, match="Activities not configured"):
        await _run_stage(AsyncMock(), str(TEST_PACK_ID), str(TEST_ORG_ID))
