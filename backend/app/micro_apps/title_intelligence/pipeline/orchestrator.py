"""Pipeline orchestrator with dual backend support.

Routes to Temporal (durable workflows) or BackgroundTasks (simple) based on
PIPELINE_BACKEND setting.
"""

import uuid
import asyncio
import traceback
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.micro_apps.title_intelligence.models.pack import Pack, PackFile
from app.micro_apps.title_intelligence.models.pipeline_run import PipelineRun
from app.micro_apps.title_intelligence.services.storage import StorageProvider
from app.models.audit_event import AuditEvent
from app.core.logging import get_logger
from app.micro_apps.title_intelligence.pipeline.stages import (
    stage_ingest,
    stage_render,
    stage_ocr,
    stage_index,
    stage_ingestion_agent,
    stage_risk_agent,
    stage_complete,
)
from app.micro_apps.title_intelligence.pipeline.version_tracker import (
    collect_version_info,
    compute_input_file_hash,
)

PIPELINE_STAGES = [
    ("ingest", stage_ingest, 3),
    ("render", stage_render, 3),
    ("ocr", stage_ocr, 5),
    ("index", stage_index, 3),
    ("ingestion_agent", stage_ingestion_agent, 5),
    ("risk_agent", stage_risk_agent, 5),
    ("complete", stage_complete, 3),
]

# Global pipeline timeout: 30 minutes
PIPELINE_TIMEOUT = 30 * 60


async def trigger_pipeline(
    pack_id: uuid.UUID,
    org_id: uuid.UUID,
    session_factory: async_sessionmaker,
    storage: StorageProvider,
    background_tasks=None,
):
    """Route pipeline execution to the configured backend.

    Args:
        pack_id: Pack to process
        org_id: Organization ID
        session_factory: DB session factory
        storage: Storage provider
        background_tasks: FastAPI BackgroundTasks (required for background_tasks backend)
    """
    from app.config import get_settings
    settings = get_settings()

    if settings.PIPELINE_BACKEND == "temporal":
        await _trigger_temporal(pack_id, org_id, settings)
    else:
        if background_tasks:
            background_tasks.add_task(run_pipeline, pack_id, org_id, session_factory, storage)
        else:
            # Run directly if no background_tasks provided
            await run_pipeline(pack_id, org_id, session_factory, storage)


async def _trigger_temporal(pack_id: uuid.UUID, org_id: uuid.UUID, settings):
    """Start a Temporal workflow for the pipeline."""
    try:
        from temporalio.client import Client
        from app.micro_apps.title_intelligence.pipeline.temporal_workflows import ProcessPackWorkflow

        client = await Client.connect(
            settings.TEMPORAL_ADDRESS,
            namespace=settings.TEMPORAL_NAMESPACE,
        )

        run_id = uuid.uuid4().hex[:8]
        await client.start_workflow(
            ProcessPackWorkflow.run,
            args=[str(pack_id), str(org_id)],
            id=f"process-pack-{pack_id}-{run_id}",
            task_queue=settings.TEMPORAL_TASK_QUEUE,
        )

        log = get_logger(__name__, org_id=org_id, pack_id=pack_id)
        log.info("Started Temporal workflow")
    except ImportError:
        raise RuntimeError(
            "PIPELINE_BACKEND=temporal requires the 'temporalio' package. "
            "Install it with: pip install temporalio"
        )


async def run_pipeline(
    pack_id: uuid.UUID,
    org_id: uuid.UUID,
    session_factory: async_sessionmaker,
    storage: StorageProvider,
):
    """Run all pipeline stages sequentially with retry logic (BackgroundTasks backend)."""
    log = get_logger(__name__, org_id=org_id, pack_id=pack_id)
    try:
        await asyncio.wait_for(
            _run_pipeline_inner(pack_id, org_id, session_factory, storage),
            timeout=PIPELINE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        log.error(f"Pipeline timed out after {PIPELINE_TIMEOUT}s")
        try:
            async with session_factory() as db:
                pack = (await db.execute(
                    select(Pack).where(Pack.id == pack_id, Pack.org_id == org_id)
                )).scalar_one()
                pack.status = "failed"
                pack.error_message = f"Pipeline timed out after {PIPELINE_TIMEOUT // 60} minutes"
                await _fail_latest_pipeline_run(
                    db, pack_id, org_id, f"Pipeline timed out after {PIPELINE_TIMEOUT // 60} minutes"
                )
                await db.commit()
        except Exception as e:
            log.error(f"Failed to mark pack as timed out: {e}")
    except Exception as e:
        log.error(f"Unexpected pipeline error: {e}\n{traceback.format_exc()}")
        try:
            async with session_factory() as db:
                pack = (await db.execute(
                    select(Pack).where(Pack.id == pack_id, Pack.org_id == org_id)
                )).scalar_one()
                pack.status = "failed"
                pack.error_message = "An unexpected error occurred during pipeline processing"
                await _fail_latest_pipeline_run(
                    db, pack_id, org_id, f"Unexpected error: {e}"
                )
                await db.commit()
        except Exception as inner_e:
            log.error(f"Failed to mark pack as failed: {inner_e}")


async def _fail_latest_pipeline_run(
    db: AsyncSession,
    pack_id: uuid.UUID,
    org_id: uuid.UUID,
    error_message: str,
) -> None:
    """Mark the most recent running PipelineRun for this pack as failed."""
    result = await db.execute(
        select(PipelineRun)
        .where(
            PipelineRun.pack_id == pack_id,
            PipelineRun.org_id == org_id,
            PipelineRun.status == "running",
        )
        .order_by(PipelineRun.started_at.desc())
        .limit(1)
    )
    run = result.scalar_one_or_none()
    if run:
        run.status = "failed"
        run.completed_at = datetime.now(timezone.utc)
        run.error_message = error_message


async def _run_pipeline_inner(
    pack_id: uuid.UUID,
    org_id: uuid.UUID,
    session_factory: async_sessionmaker,
    storage: StorageProvider,
):
    """Inner pipeline logic — separated so we can wrap with timeout."""
    from app.config import get_settings

    # Create PipelineRun record with version metadata
    pipeline_run_id: uuid.UUID | None = None
    try:
        settings = get_settings()
        version_info = collect_version_info(settings)

        async with session_factory() as db:
            # Compute input file hash
            pack_files = (await db.execute(
                select(PackFile).where(PackFile.pack_id == pack_id, PackFile.org_id == org_id)
            )).scalars().all()
            input_file_hash = await compute_input_file_hash(storage, org_id, pack_files)

            pipeline_run = PipelineRun(
                org_id=org_id,
                pack_id=pack_id,
                input_file_hash=input_file_hash,
                status="running",
                **version_info,
            )
            db.add(pipeline_run)
            await db.commit()
            await db.refresh(pipeline_run)
            pipeline_run_id = pipeline_run.id

        get_logger(__name__, org_id=org_id, pack_id=pack_id).info(
            f"Created PipelineRun {pipeline_run_id}"
        )
    except Exception as e:
        get_logger(__name__, org_id=org_id, pack_id=pack_id).warning(
            f"Failed to create PipelineRun record: {e}"
        )

    for stage_name, stage_fn, max_retries in PIPELINE_STAGES:
        log = get_logger(__name__, org_id=org_id, pack_id=pack_id, stage=stage_name)
        # Update current stage
        log.info("Starting stage")
        async with session_factory() as db:
            pack = (await db.execute(
                select(Pack).where(Pack.id == pack_id, Pack.org_id == org_id)
            )).scalar_one()
            pack.current_stage = stage_name
            pack.status = "processing"
            await db.commit()

        # Run stage with retries
        success = False
        last_error = None
        for attempt in range(max_retries):
            try:
                async with session_factory() as db:
                    await stage_fn(pack_id, org_id, db, storage)
                success = True
                log.info("Stage completed")
                break
            except Exception as e:
                last_error = e
                log.warning(
                    f"Attempt {attempt + 1}/{max_retries} failed: {e}\n{traceback.format_exc()}"
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

        if not success:
            async with session_factory() as db:
                pack = (await db.execute(
                    select(Pack).where(Pack.id == pack_id, Pack.org_id == org_id)
                )).scalar_one()
                pack.status = "failed"
                pack.error_message = f"Processing failed at stage '{stage_name}'"
                db.add(AuditEvent(
                    org_id=org_id,
                    action="pipeline_failed",
                    target_type="ti_pack",
                    target_id=pack_id,
                    metadata_={"stage": stage_name, "error": str(last_error)},
                ))
                # Finalize PipelineRun as failed
                if pipeline_run_id:
                    run = await db.get(PipelineRun, pipeline_run_id)
                    if run:
                        run.status = "failed"
                        run.completed_at = datetime.now(timezone.utc)
                        run.error_message = f"Failed at stage '{stage_name}': {last_error}"
                await db.commit()
            log.error(f"Pipeline failed: {last_error}")
            return

    # All stages completed
    async with session_factory() as db:
        pack = (await db.execute(
            select(Pack).where(Pack.id == pack_id, Pack.org_id == org_id)
        )).scalar_one()
        pack.status = "completed"
        pack.current_stage = None
        db.add(AuditEvent(
            org_id=org_id,
            action="pipeline_completed",
            target_type="ti_pack",
            target_id=pack_id,
            metadata_={"readiness_score": pack.readiness_score},
        ))
        # Finalize PipelineRun as completed
        if pipeline_run_id:
            run = await db.get(PipelineRun, pipeline_run_id)
            if run:
                run.status = "completed"
                run.completed_at = datetime.now(timezone.utc)
        await db.commit()

    get_logger(__name__, org_id=org_id, pack_id=pack_id).info("Pipeline completed")
