"""Temporal activity wrappers for pipeline stages.

Each activity wraps a pipeline stage function with proper DB session management.
Activity timeouts match V2:
- Render/OCR/Index: 10 min start-to-close, 3 retries
- AI activities: 20 min start-to-close, 5 retries, backoff coefficient 2
"""

import uuid
import logging
import traceback

from sqlalchemy import select
from temporalio import activity

from app.micro_apps.title_intelligence.pipeline.stages import (
    stage_ingest,
    stage_render,
    stage_ocr,
    stage_index,
    stage_ingestion_agent,
    stage_risk_agent,
    stage_complete,
)

logger = logging.getLogger(__name__)

# Stage name mapping for pack.current_stage updates
STAGE_NAMES = {
    stage_ingest: "ingest",
    stage_render: "render",
    stage_ocr: "ocr",
    stage_index: "index",
    stage_ingestion_agent: "ingestion_agent",
    stage_risk_agent: "risk_agent",
    stage_complete: "complete",
}

# These will be set at worker startup
_session_factory = None
_storage = None


def configure_activities(session_factory, storage):
    """Configure activities with DB session factory and storage provider."""
    global _session_factory, _storage
    _session_factory = session_factory
    _storage = storage


async def _run_stage(stage_fn, pack_id: str, org_id: str):
    """Run a pipeline stage with proper DB session management."""
    if not _session_factory or not _storage:
        raise RuntimeError("Activities not configured. Call configure_activities() first.")

    pack_uuid = uuid.UUID(pack_id)
    org_uuid = uuid.UUID(org_id)
    stage_name = STAGE_NAMES.get(stage_fn, "unknown")

    from app.micro_apps.title_intelligence.models.pack import Pack

    # Update pack status before running stage
    async with _session_factory() as db:
        pack = (await db.execute(
            select(Pack).where(Pack.id == pack_uuid, Pack.org_id == org_uuid)
        )).scalar_one_or_none()
        if pack is None:
            logger.warning(f"Pack {pack_id} not found in DB — skipping stage '{stage_name}'")
            return
        pack.current_stage = stage_name
        pack.status = "processing"
        await db.commit()

    # Run the stage
    async with _session_factory() as db:
        await stage_fn(pack_uuid, org_uuid, db, _storage)

    # Heartbeat after stage completion to signal liveness
    activity.heartbeat(f"completed_{stage_name}")


@activity.defn
async def activity_ingest(pack_id: str, org_id: str) -> None:
    logger.info(f"Temporal activity: ingest for pack {pack_id}")
    await _run_stage(stage_ingest, pack_id, org_id)


@activity.defn
async def activity_render(pack_id: str, org_id: str) -> None:
    logger.info(f"Temporal activity: render for pack {pack_id}")
    await _run_stage(stage_render, pack_id, org_id)


@activity.defn
async def activity_ocr(pack_id: str, org_id: str) -> None:
    logger.info(f"Temporal activity: ocr for pack {pack_id}")
    await _run_stage(stage_ocr, pack_id, org_id)


@activity.defn
async def activity_index(pack_id: str, org_id: str) -> None:
    logger.info(f"Temporal activity: index for pack {pack_id}")
    await _run_stage(stage_index, pack_id, org_id)


@activity.defn
async def activity_ingestion_agent(pack_id: str, org_id: str) -> None:
    logger.info(f"Temporal activity: ingestion_agent for pack {pack_id}")
    await _run_stage(stage_ingestion_agent, pack_id, org_id)


@activity.defn
async def activity_risk_agent(pack_id: str, org_id: str) -> None:
    logger.info(f"Temporal activity: risk_agent for pack {pack_id}")
    await _run_stage(stage_risk_agent, pack_id, org_id)


@activity.defn
async def activity_complete(pack_id: str, org_id: str) -> None:
    logger.info(f"Temporal activity: complete for pack {pack_id}")
    await _run_stage(stage_complete, pack_id, org_id)


@activity.defn
async def activity_create_pipeline_run(pack_id: str, org_id: str) -> str:
    """Create a PipelineRun record with version metadata. Returns the run ID."""
    if not _session_factory or not _storage:
        raise RuntimeError("Activities not configured. Call configure_activities() first.")

    from app.config import get_settings
    from app.micro_apps.title_intelligence.models.pack import PackFile
    from app.micro_apps.title_intelligence.models.pipeline_run import PipelineRun
    from app.micro_apps.title_intelligence.pipeline.version_tracker import (
        collect_version_info,
        compute_input_file_hash,
    )

    pack_uuid = uuid.UUID(pack_id)
    org_uuid = uuid.UUID(org_id)
    settings = get_settings()
    version_info = collect_version_info(settings)

    async with _session_factory() as db:
        pack_files = (await db.execute(
            select(PackFile).where(PackFile.pack_id == pack_uuid, PackFile.org_id == org_uuid)
        )).scalars().all()
        input_file_hash = await compute_input_file_hash(_storage, org_uuid, pack_files)

        pipeline_run = PipelineRun(
            org_id=org_uuid,
            pack_id=pack_uuid,
            input_file_hash=input_file_hash,
            status="running",
            **version_info,
        )
        db.add(pipeline_run)
        await db.commit()
        await db.refresh(pipeline_run)

    logger.info(f"Created PipelineRun {pipeline_run.id} for pack {pack_id}")
    return str(pipeline_run.id)


@activity.defn
async def activity_finalize_pipeline_run(
    pipeline_run_id: str, status: str, error_message: str = "",
) -> None:
    """Update a PipelineRun record with final status."""
    if not _session_factory:
        raise RuntimeError("Activities not configured. Call configure_activities() first.")

    from datetime import datetime, timezone
    from app.micro_apps.title_intelligence.models.pipeline_run import PipelineRun

    run_uuid = uuid.UUID(pipeline_run_id)

    async with _session_factory() as db:
        run = await db.get(PipelineRun, run_uuid)
        if run is None:
            logger.warning(f"PipelineRun {pipeline_run_id} not found — skipping finalize")
            return
        run.status = status
        run.completed_at = datetime.now(timezone.utc)
        if error_message:
            run.error_message = error_message
        await db.commit()

    logger.info(f"Finalized PipelineRun {pipeline_run_id} as {status}")


@activity.defn
async def activity_mark_completed(pack_id: str, org_id: str) -> None:
    """Mark pack as completed and write audit event."""
    if not _session_factory:
        raise RuntimeError("Activities not configured. Call configure_activities() first.")

    from app.micro_apps.title_intelligence.models.pack import Pack
    from app.models.audit_event import AuditEvent

    pack_uuid = uuid.UUID(pack_id)
    org_uuid = uuid.UUID(org_id)

    async with _session_factory() as db:
        pack = (await db.execute(
            select(Pack).where(Pack.id == pack_uuid, Pack.org_id == org_uuid)
        )).scalar_one_or_none()
        if pack is None:
            logger.warning(f"Pack {pack_id} not found in DB — skipping mark_completed")
            return
        pack.status = "completed"
        pack.current_stage = None
        db.add(AuditEvent(
            org_id=org_uuid,
            action="pipeline_completed",
            target_type="ti_pack",
            target_id=pack_uuid,
            metadata_={"readiness_score": pack.readiness_score},
        ))
        await db.commit()

    logger.info(f"Pipeline completed for pack {pack_id}")


@activity.defn
async def activity_mark_failed(pack_id: str, org_id: str, error: str, stage: str) -> None:
    """Mark pack as failed and write audit event."""
    if not _session_factory:
        raise RuntimeError("Activities not configured. Call configure_activities() first.")

    from app.micro_apps.title_intelligence.models.pack import Pack
    from app.models.audit_event import AuditEvent

    pack_uuid = uuid.UUID(pack_id)
    org_uuid = uuid.UUID(org_id)

    async with _session_factory() as db:
        pack = (await db.execute(
            select(Pack).where(Pack.id == pack_uuid, Pack.org_id == org_uuid)
        )).scalar_one_or_none()
        if pack is None:
            logger.warning(f"Pack {pack_id} not found in DB — skipping mark_failed")
            return
        pack.status = "failed"
        pack.error_message = f"Processing failed at stage '{stage}'"
        db.add(AuditEvent(
            org_id=org_uuid,
            action="pipeline_failed",
            target_type="ti_pack",
            target_id=pack_uuid,
            metadata_={"stage": stage, "error": error},
        ))
        await db.commit()

    logger.error(f"Pipeline failed at stage '{stage}' for pack {pack_id}: {error}")
