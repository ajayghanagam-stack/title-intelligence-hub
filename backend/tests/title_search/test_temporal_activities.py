"""Tests for TSA Temporal activity functions.

Tests the order status updates, audit events, pipeline pause handling,
and stage execution in TSA Temporal activities.
"""

import uuid
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_search.models.order import TAOrder
from app.models.audit_event import AuditEvent
from app.micro_apps.title_search.pipeline.temporal_activities import (
    configure_ta_activities,
    _run_ta_stage,
    ta_activity_mark_completed,
    ta_activity_mark_failed,
)

from tests.conftest import TEST_ORG_ID, TEST_USER_ID, test_session_factory
from tests.title_search.conftest import TEST_ORDER_ID


@pytest_asyncio.fixture
async def temporal_order(db_session: AsyncSession, seed_data):
    """Create an order in processing state for temporal tests."""
    order = TAOrder(
        id=TEST_ORDER_ID,
        org_id=TEST_ORG_ID,
        created_by=TEST_USER_ID,
        property_address="123 Temporal Ave, Test, TX 75001",
        county="Test",
        state_code="TX",
        status="processing",
        pipeline_stage="order",
    )
    db_session.add(order)
    await db_session.commit()
    return order


@pytest_asyncio.fixture
def configured_ta_activities(db_session: AsyncSession):
    """Configure TSA temporal activities with test session factory."""
    configure_ta_activities(test_session_factory)
    yield
    # Reset after test
    configure_ta_activities(None)


@pytest.mark.asyncio
async def test_run_ta_stage_updates_order_status(
    db_session: AsyncSession, seed_data, temporal_order, configured_ta_activities
):
    """_run_ta_stage should update order.pipeline_stage and status before calling handler."""
    mock_handler = AsyncMock()

    with patch("app.micro_apps.title_search.pipeline.temporal_activities.activity"):
        with patch.dict(
            "app.micro_apps.title_search.pipeline.orchestrator.STAGE_HANDLERS",
            {"test_stage": mock_handler},
        ):
            await _run_ta_stage("test_stage", str(TEST_ORDER_ID), str(TEST_ORG_ID))

    # Verify handler was called with UUID args
    mock_handler.assert_called_once()
    call_args = mock_handler.call_args
    assert call_args[0][0] == TEST_ORDER_ID
    assert call_args[0][1] == TEST_ORG_ID

    # Expire cached objects to see changes from activity's separate session
    db_session.expire_all()

    # Verify order status was updated
    result = await db_session.execute(
        select(TAOrder).where(TAOrder.id == TEST_ORDER_ID)
    )
    order = result.scalar_one()
    assert order.status == "processing"
    assert order.pipeline_stage == "test_stage"


@pytest.mark.asyncio
async def test_ta_activity_mark_completed(
    db_session: AsyncSession, seed_data, temporal_order, configured_ta_activities
):
    """ta_activity_mark_completed should set status=completed, clear pipeline_stage, write audit."""
    with patch("app.micro_apps.title_search.pipeline.temporal_activities.activity"):
        await ta_activity_mark_completed(str(TEST_ORDER_ID), str(TEST_ORG_ID))

    db_session.expire_all()

    result = await db_session.execute(
        select(TAOrder).where(TAOrder.id == TEST_ORDER_ID)
    )
    order = result.scalar_one()
    assert order.status == "completed"
    assert order.pipeline_stage is None

    # Verify audit event
    result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == TEST_ORG_ID,
            AuditEvent.action == "ta_pipeline_completed",
        )
    )
    event = result.scalar_one()
    assert event.target_type == "ta_order"
    assert event.target_id == TEST_ORDER_ID


@pytest.mark.asyncio
async def test_ta_activity_mark_failed(
    db_session: AsyncSession, seed_data, temporal_order, configured_ta_activities
):
    """ta_activity_mark_failed should set status=failed, pipeline_error, write audit."""
    error_msg = "Research stage timeout"
    stage_name = "research"

    with patch("app.micro_apps.title_search.pipeline.temporal_activities.activity"):
        await ta_activity_mark_failed(
            str(TEST_ORDER_ID), str(TEST_ORG_ID), error_msg, stage_name
        )

    db_session.expire_all()

    result = await db_session.execute(
        select(TAOrder).where(TAOrder.id == TEST_ORDER_ID)
    )
    order = result.scalar_one()
    assert order.status == "failed"
    assert "research" in order.pipeline_error

    # Verify audit event
    result = await db_session.execute(
        select(AuditEvent).where(
            AuditEvent.org_id == TEST_ORG_ID,
            AuditEvent.action == "ta_pipeline_failed",
        )
    )
    event = result.scalar_one()
    assert event.target_type == "ta_order"
    assert event.target_id == TEST_ORDER_ID
    assert event.metadata_["stage"] == "research"
    assert event.metadata_["error"] == error_msg


@pytest.mark.asyncio
async def test_pipeline_pause_converts_to_application_error(
    db_session: AsyncSession, seed_data, temporal_order, configured_ta_activities
):
    """_run_ta_stage should convert _PipelinePause to non-retryable ApplicationError."""
    from app.micro_apps.title_search.pipeline.orchestrator import _PipelinePause

    mock_handler = AsyncMock(side_effect=_PipelinePause("awaiting_abstractor"))

    with patch("app.micro_apps.title_search.pipeline.temporal_activities.activity"):
        with patch.dict(
            "app.micro_apps.title_search.pipeline.orchestrator.STAGE_HANDLERS",
            {"retrieve": mock_handler},
        ):
            from temporalio.exceptions import ApplicationError
            with pytest.raises(ApplicationError) as exc_info:
                await _run_ta_stage("retrieve", str(TEST_ORDER_ID), str(TEST_ORG_ID))
            assert exc_info.value.non_retryable is True
            assert "awaiting_abstractor" in str(exc_info.value)

    # Verify order was marked as awaiting_abstractor
    db_session.expire_all()
    result = await db_session.execute(
        select(TAOrder).where(TAOrder.id == TEST_ORDER_ID)
    )
    order = result.scalar_one()
    assert order.status == "awaiting_abstractor"


@pytest.mark.asyncio
async def test_run_ta_stage_raises_without_configuration():
    """_run_ta_stage should raise RuntimeError if activities not configured."""
    configure_ta_activities(None)
    with pytest.raises(RuntimeError, match="TSA activities not configured"):
        await _run_ta_stage("order", str(TEST_ORDER_ID), str(TEST_ORG_ID))
