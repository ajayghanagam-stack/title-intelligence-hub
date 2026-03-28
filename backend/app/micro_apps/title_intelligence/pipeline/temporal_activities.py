"""Temporal activity wrappers for pipeline stages.

Each activity wraps a pipeline stage function with proper DB session management.
Activity timeouts:
- Render: 10 min start-to-close, 3 retries
- Examine: 30 min start-to-close, 5 retries (single-pass Claude Vision)
- Other infra: 10 min start-to-close, 3 retries
"""

import asyncio
import uuid
import logging
import traceback

from sqlalchemy import select
from temporalio import activity

from app.micro_apps.title_intelligence.pipeline.stages import (
    stage_ingest,
    stage_render,
    stage_complete,
    stage_examine,
)

logger = logging.getLogger(__name__)

# Stage name mapping for pack.current_stage updates
STAGE_NAMES = {
    stage_ingest: "ingest",
    stage_render: "render",
    stage_examine: "examine",
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


async def _heartbeat_loop(stage_name: str, interval: float = 30.0):
    """Send periodic Temporal heartbeats while a stage is running."""
    while True:
        await asyncio.sleep(interval)
        activity.heartbeat(f"running_{stage_name}")


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

    # Run the stage with background heartbeat to prevent Temporal timeout
    async with _session_factory() as db:
        heartbeat_task = asyncio.create_task(_heartbeat_loop(stage_name))
        try:
            await stage_fn(pack_uuid, org_uuid, db, _storage)
        except Exception as e:
            # Truncate error details to prevent exceeding Temporal gRPC
            # max message size (4 MB). Deep SQLAlchemy/asyncpg tracebacks
            # with large SQL parameters can produce 10+ MB failure payloads.
            error_msg = str(e)
            MAX_ERROR_LEN = 5000
            if len(error_msg) > MAX_ERROR_LEN:
                error_msg = error_msg[:MAX_ERROR_LEN] + "... [truncated]"
            tb = traceback.format_exc()
            if len(tb) > MAX_ERROR_LEN:
                tb = tb[:MAX_ERROR_LEN] + "... [truncated]"
            logger.error(
                f"Stage '{stage_name}' failed for pack {pack_id}: {error_msg}\n{tb}"
            )
            raise RuntimeError(
                f"Stage '{stage_name}' failed: {error_msg}"
            ) from None
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

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
async def activity_examine(pack_id: str, org_id: str) -> None:
    logger.info(f"Temporal activity: examine for pack {pack_id}")
    await _run_stage(stage_examine, pack_id, org_id)


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

    # Separate PipelineRun model columns from extra metadata keys
    PIPELINE_RUN_COLUMNS = {
        "ai_platform", "ai_model", "ingestion_prompt_hash", "risk_prompt_hash",
        "extraction_tool_hash", "risk_tool_hash", "ocr_engine", "chunker_version",
        "rules_version", "pipeline_backend", "version_metadata",
    }
    model_fields = {k: v for k, v in version_info.items() if k in PIPELINE_RUN_COLUMNS}
    # Merge extra keys into version_metadata
    extra_keys = {k: v for k, v in version_info.items() if k not in PIPELINE_RUN_COLUMNS}
    if extra_keys:
        meta = dict(model_fields.get("version_metadata") or {})
        meta.update(extra_keys)
        model_fields["version_metadata"] = meta

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
            **model_fields,
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
