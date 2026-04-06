"""Temporal activity wrappers for TSA pipeline stages.

Each activity wraps a pipeline stage function with proper DB session management.
TSA stages take (order_id, org_id, db) — no storage provider needed.
"""

import asyncio
import uuid
import logging
import traceback
from datetime import datetime, timezone

from sqlalchemy import select
from temporalio import activity

logger = logging.getLogger(__name__)

# Stage name mapping for order status updates
STAGE_NAMES = [
    "order", "research", "retrieve", "parse", "chain", "package", "complete",
]

# Configured at worker startup
_session_factory = None


def configure_ta_activities(session_factory):
    """Configure activities with DB session factory."""
    global _session_factory
    _session_factory = session_factory


async def _heartbeat_loop(stage_name: str, interval: float = 30.0):
    """Send periodic Temporal heartbeats while a stage is running."""
    while True:
        await asyncio.sleep(interval)
        activity.heartbeat(f"running_{stage_name}")


async def _run_ta_stage(stage_name: str, order_id: str, org_id: str):
    """Run a TSA pipeline stage with proper DB session management."""
    if not _session_factory:
        raise RuntimeError(
            "TSA activities not configured. Call configure_ta_activities() first."
        )

    from app.micro_apps.title_search.pipeline.orchestrator import (
        STAGE_HANDLERS,
        _PipelinePause,
    )
    from app.micro_apps.title_search.models.order import TAOrder

    order_uuid = uuid.UUID(order_id)
    org_uuid = uuid.UUID(org_id)

    handler = STAGE_HANDLERS.get(stage_name)
    if handler is None:
        raise RuntimeError(f"Unknown TSA stage: {stage_name}")

    # Update order status before running stage
    async with _session_factory() as db:
        order = (await db.execute(
            select(TAOrder).where(TAOrder.id == order_uuid, TAOrder.org_id == org_uuid)
        )).scalar_one_or_none()
        if order is None:
            logger.warning(
                f"Order {order_id} not found in DB — skipping stage '{stage_name}'"
            )
            return
        order.pipeline_stage = stage_name
        order.status = "processing"
        await db.commit()

    # Run the stage with background heartbeat
    async with _session_factory() as db:
        heartbeat_task = asyncio.create_task(_heartbeat_loop(stage_name))
        try:
            await handler(order_uuid, org_uuid, db)
            await db.commit()
        except _PipelinePause:
            # Pipeline pause (e.g., awaiting_abstractor) — convert to non-retryable
            # ApplicationError so the workflow can catch it and exit cleanly
            from temporalio.exceptions import ApplicationError
            async with _session_factory() as pause_db:
                order = (await pause_db.execute(
                    select(TAOrder).where(
                        TAOrder.id == order_uuid, TAOrder.org_id == org_uuid
                    )
                )).scalar_one_or_none()
                if order:
                    order.status = "awaiting_abstractor"
                    await pause_db.commit()
            raise ApplicationError(
                f"Pipeline paused at stage '{stage_name}': awaiting_abstractor",
                non_retryable=True,
            )
        except Exception as e:
            error_msg = str(e)
            MAX_ERROR_LEN = 5000
            if len(error_msg) > MAX_ERROR_LEN:
                error_msg = error_msg[:MAX_ERROR_LEN] + "... [truncated]"
            tb = traceback.format_exc()
            if len(tb) > MAX_ERROR_LEN:
                tb = tb[:MAX_ERROR_LEN] + "... [truncated]"
            logger.error(
                f"TSA stage '{stage_name}' failed for order {order_id}: {error_msg}\n{tb}"
            )
            raise RuntimeError(
                f"TSA stage '{stage_name}' failed: {error_msg}"
            ) from None
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    activity.heartbeat(f"completed_{stage_name}")


@activity.defn
async def ta_activity_order(order_id: str, org_id: str) -> None:
    logger.info(f"TSA Temporal activity: order for {order_id}")
    await _run_ta_stage("order", order_id, org_id)


@activity.defn
async def ta_activity_research(order_id: str, org_id: str) -> None:
    logger.info(f"TSA Temporal activity: research for {order_id}")
    await _run_ta_stage("research", order_id, org_id)


@activity.defn
async def ta_activity_retrieve(order_id: str, org_id: str) -> None:
    logger.info(f"TSA Temporal activity: retrieve for {order_id}")
    await _run_ta_stage("retrieve", order_id, org_id)


@activity.defn
async def ta_activity_parse(order_id: str, org_id: str) -> None:
    logger.info(f"TSA Temporal activity: parse for {order_id}")
    await _run_ta_stage("parse", order_id, org_id)


@activity.defn
async def ta_activity_chain(order_id: str, org_id: str) -> None:
    logger.info(f"TSA Temporal activity: chain for {order_id}")
    await _run_ta_stage("chain", order_id, org_id)


@activity.defn
async def ta_activity_package(order_id: str, org_id: str) -> None:
    logger.info(f"TSA Temporal activity: package for {order_id}")
    await _run_ta_stage("package", order_id, org_id)


@activity.defn
async def ta_activity_complete(order_id: str, org_id: str) -> None:
    logger.info(f"TSA Temporal activity: complete for {order_id}")
    await _run_ta_stage("complete", order_id, org_id)


@activity.defn
async def ta_activity_create_pipeline_run(order_id: str, org_id: str) -> str:
    """Create a TAPipelineRun record with version metadata. Returns the run ID."""
    if not _session_factory:
        raise RuntimeError(
            "TSA activities not configured. Call configure_ta_activities() first."
        )

    from app.config import get_settings
    from app.micro_apps.title_search.models.pipeline_run import TAPipelineRun
    from app.micro_apps.title_search.pipeline.version_tracker import collect_version_info

    order_uuid = uuid.UUID(order_id)
    org_uuid = uuid.UUID(org_id)
    settings = get_settings()
    version_info = collect_version_info(settings)

    async with _session_factory() as db:
        run = TAPipelineRun(
            org_id=org_uuid,
            order_id=order_uuid,
            ai_platform=version_info["ai_platform"],
            ai_model=version_info["ai_model"],
            parser_prompt_hash=version_info["parser_prompt_hash"],
            chain_prompt_hash=version_info["chain_prompt_hash"],
            anomaly_prompt_hash=version_info["anomaly_prompt_hash"],
            parser_tool_hash=version_info["parser_tool_hash"],
            chain_tool_hash=version_info["chain_tool_hash"],
            anomaly_tool_hash=version_info["anomaly_tool_hash"],
            rules_version=version_info["rules_version"],
            pipeline_backend=version_info["pipeline_backend"],
            version_metadata=version_info["version_metadata"],
            status="running",
        )
        db.add(run)
        await db.commit()
        await db.refresh(run)

    logger.info(f"Created TAPipelineRun {run.id} for order {order_id}")
    return str(run.id)


@activity.defn
async def ta_activity_finalize_pipeline_run(
    pipeline_run_id: str, org_id: str, status: str, error_message: str = "",
) -> None:
    """Update a TAPipelineRun record with final status."""
    if not _session_factory:
        raise RuntimeError(
            "TSA activities not configured. Call configure_ta_activities() first."
        )

    from app.micro_apps.title_search.models.pipeline_run import TAPipelineRun

    run_uuid = uuid.UUID(pipeline_run_id)
    org_uuid = uuid.UUID(org_id)

    async with _session_factory() as db:
        run = (await db.execute(
            select(TAPipelineRun).where(
                TAPipelineRun.id == run_uuid,
                TAPipelineRun.org_id == org_uuid,
            )
        )).scalar_one_or_none()
        if run is None:
            logger.warning(
                f"TAPipelineRun {pipeline_run_id} not found — skipping finalize"
            )
            return
        run.status = status
        run.completed_at = datetime.now(timezone.utc)
        if error_message:
            run.error_message = error_message
        await db.commit()

    logger.info(f"Finalized TAPipelineRun {pipeline_run_id} as {status}")


@activity.defn
async def ta_activity_mark_completed(order_id: str, org_id: str) -> None:
    """Mark order as completed and write audit event."""
    if not _session_factory:
        raise RuntimeError(
            "TSA activities not configured. Call configure_ta_activities() first."
        )

    from app.micro_apps.title_search.models.order import TAOrder
    from app.models.audit_event import AuditEvent

    order_uuid = uuid.UUID(order_id)
    org_uuid = uuid.UUID(org_id)

    async with _session_factory() as db:
        order = (await db.execute(
            select(TAOrder).where(TAOrder.id == order_uuid, TAOrder.org_id == org_uuid)
        )).scalar_one_or_none()
        if order is None:
            logger.warning(
                f"Order {order_id} not found in DB — skipping mark_completed"
            )
            return
        order.status = "completed"
        order.pipeline_stage = None
        db.add(AuditEvent(
            org_id=org_uuid,
            action="ta_pipeline_completed",
            target_type="ta_order",
            target_id=order_uuid,
        ))
        await db.commit()

    logger.info(f"TSA pipeline completed for order {order_id}")


@activity.defn
async def ta_activity_mark_failed(
    order_id: str, org_id: str, error: str, stage: str,
) -> None:
    """Mark order as failed and write audit event."""
    if not _session_factory:
        raise RuntimeError(
            "TSA activities not configured. Call configure_ta_activities() first."
        )

    from app.micro_apps.title_search.models.order import TAOrder
    from app.models.audit_event import AuditEvent

    order_uuid = uuid.UUID(order_id)
    org_uuid = uuid.UUID(org_id)

    async with _session_factory() as db:
        order = (await db.execute(
            select(TAOrder).where(TAOrder.id == order_uuid, TAOrder.org_id == org_uuid)
        )).scalar_one_or_none()
        if order is None:
            logger.warning(
                f"Order {order_id} not found in DB — skipping mark_failed"
            )
            return
        order.status = "failed"
        order.pipeline_error = f"Processing failed at stage '{stage}'"
        db.add(AuditEvent(
            org_id=org_uuid,
            action="ta_pipeline_failed",
            target_type="ta_order",
            target_id=order_uuid,
            metadata_={"stage": stage, "error": error},
        ))
        await db.commit()

    logger.error(f"TSA pipeline failed at stage '{stage}' for order {order_id}: {error}")
