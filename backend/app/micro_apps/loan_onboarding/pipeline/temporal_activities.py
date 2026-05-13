"""Temporal activities for Loan Onboarding pipeline.

Each activity wraps a single stage and uses the configured session factory +
storage. The workflow owns the orchestration; activities are thin adapters.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker
from temporalio import activity

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

logger = logging.getLogger(__name__)

# Module-level config — wired at worker startup
_session_factory: async_sessionmaker | None = None
_storage: StorageProvider | None = None


def configure_lo_activities(session_factory: async_sessionmaker, storage: StorageProvider) -> None:
    """Inject the session factory + storage used by every LO activity."""
    global _session_factory, _storage
    _session_factory = session_factory
    _storage = storage


def _require_config() -> tuple[async_sessionmaker, StorageProvider]:
    if _session_factory is None or _storage is None:
        raise RuntimeError(
            "LO activities are not configured — call configure_lo_activities() "
            "before running the worker."
        )
    return _session_factory, _storage


def _safe_heartbeat(detail: str) -> None:
    """Heartbeat only when running inside a Temporal activity context.

    `_run_stage` is also exercised by unit tests that call it directly (no
    activity context), so the raw `activity.heartbeat` call would raise
    `RuntimeError("Not in activity context")`.
    """
    if activity.in_activity():
        activity.heartbeat(detail)


async def _heartbeat_loop(stage_name: str, interval: float = 30.0) -> None:
    """Send periodic Temporal heartbeats while a stage is running.

    Each LO stage has heartbeat_timeout=5min set on its activity. Long Gemini
    calls (up to 300s/chunk + split-and-retry recursion) can easily exceed
    that. Without periodic heartbeats Temporal cancels the activity mid-
    request → CancelledError surfaces from aiohttp.
    """
    while True:
        await asyncio.sleep(interval)
        _safe_heartbeat(f"running_{stage_name}")


async def _run_stage(stage_fn, package_id: str, org_id: str, stage_name: str) -> dict:
    sf, storage = _require_config()
    package_uuid = uuid.UUID(package_id)
    org_uuid = uuid.UUID(org_id)
    async with sf() as db:
        await package_service.mark_pipeline_status(
            db, org_uuid, package_uuid,
            status="processing", pipeline_stage=stage_name, pipeline_error=None,
        )

    _safe_heartbeat(f"starting_{stage_name}")
    stage_started = time.time()
    heartbeat_task = asyncio.create_task(_heartbeat_loop(stage_name))
    try:
        # ingest manages its own sessions internally so it can release the
        # connection during S3 I/O — see stage_ingest docstring. Other stages
        # still get one session for the whole call.
        if stage_fn is stage_ingest:
            output = await stage_fn(package_uuid, org_uuid, sf, storage)
        else:
            async with sf() as db:
                output = await stage_fn(package_uuid, org_uuid, db, storage)
                await db.commit()
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
    elapsed = round(time.time() - stage_started, 3)
    _safe_heartbeat(f"completed_{stage_name}")

    # Merge this stage's timing into progress.stage_timings so the frontend
    # pipeline-progress UI flips each stage to "completed" as it finishes
    # (mark_pipeline_status overwrites progress wholesale, so read-merge-write).
    async with sf() as db:
        pkg = await package_service.get_package_or_raise(db, org_uuid, package_uuid)
        merged_progress = dict(pkg.progress or {})
        timings = dict(merged_progress.get("stage_timings") or {})
        timings[stage_name] = elapsed
        merged_progress["stage_timings"] = timings
        merged_progress["stage"] = stage_name
        out_dict = output if isinstance(output, dict) else {}
        if "pages" in out_dict:
            merged_progress["processed"] = out_dict.get("pages", 0)
        await package_service.mark_pipeline_status(
            db, org_uuid, package_uuid,
            pipeline_stage=stage_name,
            progress=merged_progress,
        )
    return output or {}


@activity.defn(name="lo_activity_ingest")
async def lo_activity_ingest(package_id: str, org_id: str) -> dict:
    return await _run_stage(stage_ingest, package_id, org_id, "ingest")


@activity.defn(name="lo_activity_classify")
async def lo_activity_classify(package_id: str, org_id: str) -> dict:
    return await _run_stage(stage_classify, package_id, org_id, "classify")


@activity.defn(name="lo_activity_stack")
async def lo_activity_stack(package_id: str, org_id: str) -> dict:
    return await _run_stage(stage_stack, package_id, org_id, "stack")


@activity.defn(name="lo_activity_validate")
async def lo_activity_validate(package_id: str, org_id: str) -> dict:
    return await _run_stage(stage_validate, package_id, org_id, "validate")


@activity.defn(name="lo_activity_extract")
async def lo_activity_extract(package_id: str, org_id: str) -> dict:
    return await _run_stage(stage_extract, package_id, org_id, "extract")


@activity.defn(name="lo_activity_review")
async def lo_activity_review(package_id: str, org_id: str) -> dict:
    return await _run_stage(stage_review, package_id, org_id, "review")


@activity.defn(name="lo_activity_mark_completed")
async def lo_activity_mark_completed(package_id: str, org_id: str, hitl_count: int) -> None:
    sf, _ = _require_config()
    final_status = "awaiting_review" if hitl_count > 0 else "completed"
    org_uuid = uuid.UUID(org_id)
    package_uuid = uuid.UUID(package_id)
    async with sf() as db:
        pkg = await package_service.get_package_or_raise(db, org_uuid, package_uuid)
        merged_progress = dict(pkg.progress or {})
        merged_progress["stage"] = "complete"
        merged_progress["hitl_count"] = hitl_count
        await package_service.mark_pipeline_status(
            db, org_uuid, package_uuid,
            status=final_status,
            pipeline_stage="complete",
            pipeline_error=None,
            progress=merged_progress,
        )


@activity.defn(name="lo_activity_mark_failed")
async def lo_activity_mark_failed(
    package_id: str, org_id: str, error_msg: str, failed_stage: str
) -> None:
    sf, _ = _require_config()
    async with sf() as db:
        await package_service.mark_pipeline_status(
            db, uuid.UUID(org_id), uuid.UUID(package_id),
            status="failed",
            pipeline_stage=failed_stage,
            pipeline_error=error_msg[:500],
        )


# ── Phase 3.2: Variant A remediation activities ──────────────────────
#
# These wrap ``services/remediation_service.py``. They are short-lived
# (each step ~0.5-3s per the PRD) and operate on a single file or stack.
# They run as activities of ``RemediateMissingDocWorkflow`` (a child
# workflow kicked off by ``POST /loans/{id}/remediate-missing-doc``).
#
# Three of the four are skeletons in this batch; see remediation_service
# module docstring for what's deferred to Batch 3.2b/c.


async def _run_remediation_step(
    fn,  # async callable taking (db, *args)
    package_id: str,
    org_id: str,
    *fn_args,
):
    """Open one session, dispatch the helper, commit, return the result.

    Mirrors ``_run_stage`` but without the package-wide pipeline_status
    update — remediation MUST NOT rewind ``loan.pipeline_stage`` per the
    spec's monotonic-advance contract (§3.5).
    """
    sf, _ = _require_config()
    org_uuid = uuid.UUID(org_id)
    package_uuid = uuid.UUID(package_id)
    async with sf() as db:
        result = await fn(db, org_uuid, package_uuid, *fn_args)
        await db.commit()
    return result


def _result_to_dict(result: Any) -> dict:
    """Coerce a frozen dataclass result to a JSON-serializable dict.

    Temporal activities' return values cross the activity boundary as
    JSON, so the dataclass must be flattened. UUIDs become strings.
    """
    out = {}
    for key, value in result.__dict__.items():
        if isinstance(value, uuid.UUID):
            out[key] = str(value)
        else:
            out[key] = value
    return out


@activity.defn(name="lo_activity_classify_single_doc")
async def lo_activity_classify_single_doc(
    package_id: str, org_id: str, file_id: str,
) -> dict:
    from app.micro_apps.loan_onboarding.services import remediation_service
    _, storage = _require_config()
    activity.heartbeat("classify_single_doc:start") if activity.in_activity() else None
    result = await _run_remediation_step(
        remediation_service.classify_single_doc,
        package_id, org_id,
        uuid.UUID(file_id), storage,
    )
    return _result_to_dict(result)


@activity.defn(name="lo_activity_doc_validation_recheck")
async def lo_activity_doc_validation_recheck(
    package_id: str, org_id: str, stack_id: str,
) -> dict:
    from app.micro_apps.loan_onboarding.services import remediation_service
    activity.heartbeat("doc_validation_recheck:start") if activity.in_activity() else None
    result = await _run_remediation_step(
        remediation_service.doc_validation_recheck,
        package_id, org_id,
        uuid.UUID(stack_id),
    )
    return _result_to_dict(result)


@activity.defn(name="lo_activity_extract_single_doc")
async def lo_activity_extract_single_doc(
    package_id: str, org_id: str, stack_id: str,
) -> dict:
    from app.micro_apps.loan_onboarding.services import remediation_service
    _, storage = _require_config()
    activity.heartbeat("extract_single_doc:start") if activity.in_activity() else None
    result = await _run_remediation_step(
        remediation_service.extract_single_doc,
        package_id, org_id,
        uuid.UUID(stack_id), storage,
    )
    return _result_to_dict(result)


@activity.defn(name="lo_activity_data_validation_partial")
async def lo_activity_data_validation_partial(
    package_id: str, org_id: str, stack_id: str,
) -> dict:
    from app.micro_apps.loan_onboarding.services import remediation_service
    activity.heartbeat("data_validation_partial:start") if activity.in_activity() else None
    result = await _run_remediation_step(
        remediation_service.data_validation_partial,
        package_id, org_id,
        uuid.UUID(stack_id),
    )
    return _result_to_dict(result)


# ── Phase 3.3: Variant B remediation activities ──────────────────────
#
# Variant B extends an existing stack with appended pages instead of
# creating a new one. Activities 3 / 4 / 5 of the workflow reuse the
# Variant A activities (``doc_validation_recheck``,
# ``extract_single_doc``, ``data_validation_partial``) — only the first
# two steps are new.


@activity.defn(name="lo_activity_append_pages")
async def lo_activity_append_pages(
    package_id: str, org_id: str, target_stack_id: str, file_id: str,
) -> dict:
    from app.micro_apps.loan_onboarding.services import remediation_service
    _, storage = _require_config()
    activity.heartbeat("append_pages:start") if activity.in_activity() else None
    result = await _run_remediation_step(
        remediation_service.append_pages,
        package_id, org_id,
        uuid.UUID(target_stack_id), uuid.UUID(file_id), storage,
    )
    return _result_to_dict(result)


@activity.defn(name="lo_activity_classify_recheck")
async def lo_activity_classify_recheck(
    package_id: str,
    org_id: str,
    target_stack_id: str,
    file_id: str,
    snapshot: dict,
) -> dict:
    from app.micro_apps.loan_onboarding.services import remediation_service
    _, storage = _require_config()
    activity.heartbeat("classify_recheck:start") if activity.in_activity() else None
    result = await _run_remediation_step(
        remediation_service.classify_recheck,
        package_id, org_id,
        uuid.UUID(target_stack_id), uuid.UUID(file_id), storage, snapshot,
    )
    return _result_to_dict(result)
