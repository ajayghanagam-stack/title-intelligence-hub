"""Pipeline orchestrator for Loan Onboarding.

Dispatches to Temporal (durable) or FastAPI BackgroundTasks based on the
PIPELINE_BACKEND setting. The sequential execution loop below is the
background_tasks backend; the Temporal backend is wired up in Phase 8.
"""
import asyncio
import time
import traceback
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.logging import get_logger
from app.micro_apps.loan_onboarding.pipeline.stages import (
    stage_classify,
    stage_extract,
    stage_ingest,
    stage_review,
    stage_stack,
    stage_validate,
)
from app.micro_apps.loan_onboarding.services import package_service
from app.services.storage import StorageProvider

# (stage_name, stage_fn, max_attempts)
PIPELINE_STAGES = [
    ("ingest", stage_ingest, 3),
    ("classify", stage_classify, 5),
    ("stack", stage_stack, 3),
    ("validate", stage_validate, 5),
    ("extract", stage_extract, 5),
    ("review", stage_review, 3),
]

# Global pipeline timeout: 60 minutes (larger loan packages can take longer)
PIPELINE_TIMEOUT = 60 * 60


async def trigger_pipeline(
    package_id: uuid.UUID,
    org_id: uuid.UUID,
    session_factory: async_sessionmaker,
    storage: StorageProvider,
    background_tasks=None,
) -> None:
    """Route pipeline execution to the configured backend."""
    from app.config import get_settings

    settings = get_settings()

    if settings.PIPELINE_BACKEND == "temporal":
        await _trigger_temporal(package_id, org_id, settings)
        return

    if background_tasks is not None:
        background_tasks.add_task(run_pipeline, package_id, org_id, session_factory, storage)
    else:
        # Run inline — used by tests and by the Temporal activity wrapper
        await run_pipeline(package_id, org_id, session_factory, storage)


async def _trigger_temporal(package_id: uuid.UUID, org_id: uuid.UUID, settings) -> None:
    """Start a Temporal workflow for the loan package (wired in Phase 8)."""
    try:
        from temporalio.client import Client

        from app.micro_apps.loan_onboarding.pipeline.temporal_workflows import (
            ProcessLoanWorkflow,
        )
    except ImportError as e:
        raise RuntimeError(
            "PIPELINE_BACKEND=temporal requires the 'temporalio' package and "
            "Phase 8 Temporal wiring. Install temporalio or switch to "
            "PIPELINE_BACKEND=background_tasks."
        ) from e

    client = await Client.connect(
        settings.TEMPORAL_ADDRESS, namespace=settings.TEMPORAL_NAMESPACE
    )
    run_id = uuid.uuid4().hex[:8]
    await client.start_workflow(
        ProcessLoanWorkflow.run,
        args=[str(package_id), str(org_id)],
        id=f"process-loan-package-{package_id}-{run_id}",
        task_queue=settings.LO_TEMPORAL_TASK_QUEUE,
    )
    get_logger(__name__, org_id=org_id, pack_id=package_id).info(
        "Started Temporal workflow for Loan Onboarding"
    )


async def run_pipeline(
    package_id: uuid.UUID,
    org_id: uuid.UUID,
    session_factory: async_sessionmaker,
    storage: StorageProvider,
) -> None:
    """Run the full pipeline with a wall-clock timeout."""
    log = get_logger(__name__, org_id=org_id, pack_id=package_id)
    try:
        await asyncio.wait_for(
            _run_pipeline_inner(package_id, org_id, session_factory, storage),
            timeout=PIPELINE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        log.error(f"Pipeline timed out after {PIPELINE_TIMEOUT}s")
        await _fail_package(
            session_factory, package_id, org_id,
            f"Pipeline timed out after {PIPELINE_TIMEOUT // 60} minutes",
        )
    except Exception as e:
        log.error(f"Unexpected pipeline error: {e}\n{traceback.format_exc()}")
        await _fail_package(
            session_factory, package_id, org_id,
            "An unexpected error occurred during pipeline processing",
        )


async def _run_pipeline_inner(
    package_id: uuid.UUID,
    org_id: uuid.UUID,
    session_factory: async_sessionmaker,
    storage: StorageProvider,
) -> None:
    """Run each stage sequentially with per-stage retry and status updates."""
    log = get_logger(__name__, org_id=org_id, pack_id=package_id)

    stage_timings: dict[str, float] = {}
    stage_outputs: dict[str, dict] = {}
    started_at = time.time()

    for stage_name, stage_fn, max_attempts in PIPELINE_STAGES:
        # Skip unimplemented stages gracefully — lets Phase 4 exercise ingest alone.
        # Once Phase 5/6 land, the NotImplementedError guard here becomes dead code.
        stage_started = time.time()
        try:
            output = await _run_stage_with_retry(
                stage_name, stage_fn, max_attempts,
                package_id, org_id, session_factory, storage, log,
            )
        except NotImplementedError as e:
            log.warning(f"Stage '{stage_name}' not yet implemented: {e}. Halting pipeline.")
            async with session_factory() as db:
                await package_service.mark_pipeline_status(
                    db, org_id, package_id,
                    status="awaiting_review",
                    pipeline_stage=stage_name,
                    pipeline_error=f"Stage '{stage_name}' not yet implemented",
                )
            return

        stage_timings[stage_name] = round(time.time() - stage_started, 3)
        if isinstance(output, dict):
            stage_outputs[stage_name] = output

        async with session_factory() as db:
            await package_service.mark_pipeline_status(
                db, org_id, package_id,
                pipeline_stage=stage_name,
                progress={
                    "stage": stage_name,
                    "stage_timings": dict(stage_timings),
                    "processed": stage_outputs.get(stage_name, {}).get("pages", 0),
                    "total": stage_outputs.get("ingest", {}).get("pages", 0),
                    "hitl_count": 0,
                },
            )

    # Pipeline complete — respect stage_review's HITL count for final status
    total_elapsed = round(time.time() - started_at, 3)
    hitl_count = stage_outputs.get("review", {}).get("hitl_stacks", 0)
    final_status = "awaiting_review" if hitl_count > 0 else "completed"
    # stage_review already persists package.progress (issues/decisions) + status;
    # re-read and merge so we preserve those fields.
    async with session_factory() as db:
        pkg = await package_service.get_package_or_raise(db, org_id, package_id)
        merged_progress = dict(pkg.progress or {})
        merged_progress.update({
            "stage": "complete",
            "stage_timings": stage_timings,
            "total_elapsed_seconds": total_elapsed,
            "processed": stage_outputs.get("ingest", {}).get("pages", 0),
            "total": stage_outputs.get("ingest", {}).get("pages", 0),
            "hitl_count": hitl_count,
        })
        await package_service.mark_pipeline_status(
            db, org_id, package_id,
            status=final_status,
            pipeline_stage="complete",
            pipeline_error=None,
            progress=merged_progress,
        )
    log.info(f"Pipeline completed in {total_elapsed}s (timings={stage_timings})")

    # Warm the per-page thumbnail cache so the first viewer doesn't pay the
    # PyMuPDF render cost on every thumb. Done AFTER the package is marked
    # completed so the user sees the packet ready immediately; the warm-up
    # then runs as a tail of the pipeline. Best-effort — any failure is
    # logged but never raised, since /thumb still has a render-on-miss
    # fallback so a missed warm-up just degrades to the previous behavior.
    try:
        from app.micro_apps.loan_onboarding.services.thumbnail_cache import (
            warm_package_thumbnails,
        )

        warmup = await warm_package_thumbnails(
            package_id, org_id, session_factory, storage
        )
        log.info(
            f"Thumbnail cache warmed: rendered={warmup['rendered']} "
            f"skipped={warmup['skipped']} failed={warmup['failed']}"
        )
    except Exception as e:
        log.warning(f"Thumbnail warmup failed (non-fatal): {e}")


async def _run_stage_with_retry(
    stage_name: str,
    stage_fn,
    max_attempts: int,
    package_id: uuid.UUID,
    org_id: uuid.UUID,
    session_factory: async_sessionmaker,
    storage: StorageProvider,
    log,
):
    """Run a single stage with exponential backoff on failure."""
    async with session_factory() as db:
        await package_service.mark_pipeline_status(
            db, org_id, package_id,
            status="processing",
            pipeline_stage=stage_name,
            pipeline_error=None,
        )

    attempt = 0
    while True:
        attempt += 1
        try:
            # ingest manages its own sessions internally so it can release the
            # connection during S3 I/O — see stage_ingest docstring. Other
            # stages still get one session for the whole call.
            if stage_fn is stage_ingest:
                output = await stage_fn(package_id, org_id, session_factory, storage)
            else:
                async with session_factory() as db:
                    output = await stage_fn(package_id, org_id, db, storage)
                    await db.commit()
            return output
        except NotImplementedError:
            # Don't retry unimplemented stages — surface immediately to the caller
            raise
        except Exception as e:
            if attempt >= max_attempts:
                log.error(f"Stage '{stage_name}' failed after {attempt} attempts: {e}")
                await _fail_package(
                    session_factory, package_id, org_id,
                    f"Stage '{stage_name}' failed: {e}",
                )
                raise
            # Exponential backoff: 2s, 4s, 8s, ...
            backoff = 2 ** attempt
            log.warning(
                f"Stage '{stage_name}' failed (attempt {attempt}/{max_attempts}): {e} — "
                f"retrying in {backoff}s"
            )
            await asyncio.sleep(backoff)


async def _fail_package(
    session_factory: async_sessionmaker,
    package_id: uuid.UUID,
    org_id: uuid.UUID,
    error_message: str,
) -> None:
    try:
        async with session_factory() as db:
            await package_service.mark_pipeline_status(
                db, org_id, package_id,
                status="failed",
                pipeline_error=error_message,
            )
    except Exception:
        # Best-effort — never mask the original exception.
        pass
