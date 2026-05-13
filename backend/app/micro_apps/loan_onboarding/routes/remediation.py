"""Operator-facing remediation endpoints (Phase 3.2 / 3.3).

These let a reviewer remediate a doc-validation hard stop without
restarting the whole pipeline:

- ``POST /packages/{package_id}/remediate-missing-doc`` (Variant A) —
  multipart upload of a single missing document. Ingests the file's
  pages, appends them to the package's global page numbering, then
  kicks the ``RemediateMissingDocWorkflow`` (Temporal) or runs the same
  4 steps inline (background_tasks).
- ``POST /packages/{package_id}/remediate-missing-pages`` (Variant B) —
  multipart upload of additional pages for an existing stack. The new
  pages are appended (deterministic) and re-classified; if the merged
  doc-type or confidence drifts, the upload is atomically rolled back.

Neither endpoint advances ``LOPackage.pipeline_stage`` — that's the
§3.5 monotonic-advance contract.
"""
from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile, status

from app.config import get_settings
from app.core.deps import get_current_member, get_db, get_org_id, get_session_factory
from app.core.exceptions import NotFoundError, ValidationError
from app.micro_apps.loan_onboarding.services import (
    file_service,
    package_service,
    remediation_service,
)
from app.models.user import User
from app.services.audit_service import log_event
from app.services.storage import StorageProvider, get_storage
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()
logger = logging.getLogger(__name__)

# Statuses from which a remediation upload is allowed. Pre-completion the
# operator should be using the main upload + process flow; failed packages
# need a retry, not a remediation. ``processing`` is excluded so two
# concurrent runs can't race the stack rebuild.
_REMEDIATION_OK_STATUSES = frozenset({"awaiting_review", "completed"})


@router.post(
    "/packages/{package_id}/remediate-missing-doc",
    status_code=status.HTTP_202_ACCEPTED,
)
async def remediate_missing_doc(
    package_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    """Accept a single missing document and run the Variant A workflow.

    Response shape:
        {
          "file_id": "...",
          "pages_added": int,
          "first_page_number": int,
          "last_page_number": int,
          "workflow_id": "..." | null,    # null when running inline
          "backend": "temporal" | "background_tasks",
        }

    The workflow itself (classify → doc_validation_recheck → extract →
    data_validation_partial) runs asynchronously; clients should poll
    the existing ``GET /packages/{id}/stacks`` + ``/extractions``
    endpoints to observe progress and final state.
    """
    settings = get_settings()
    package = await package_service.get_visible_package_or_raise(
        db, org_id, package_id, member,
    )

    if package.status not in _REMEDIATION_OK_STATUSES:
        raise ValidationError(
            f"Package cannot be remediated from status '{package.status}'. "
            f"Allowed statuses: {sorted(_REMEDIATION_OK_STATUSES)}"
        )

    # Phase 1 — persist the upload + read its bytes.
    data = await file.read()
    max_size = settings.LO_FILE_UPLOAD_MAX_SIZE
    if len(data) > max_size:
        raise ValidationError(
            f"File '{file.filename}' exceeds max size of {max_size} bytes"
        )

    # store_uploaded_file commits internally (it always has — to flush
    # the write before we kick off downstream work).
    file_row = await file_service.store_uploaded_file(
        db, storage,
        org_id=org_id, package_id=package_id,
        filename=file.filename or "remediation.pdf",
        content=data, content_type=file.content_type,
    )

    # Phase 2 — ingest pages for just this file (append global numbering).
    ingest_result = await remediation_service.ingest_single_file(
        db, org_id, package_id, file_row.id, storage,
    )

    await log_event(
        db, org_id,
        action="lo_remediation_uploaded",
        target_type="lo_package",
        target_id=package_id,
        actor_id=member.id,
        metadata={
            "file_id": str(file_row.id),
            "filename": file_row.filename,
            "pages_added": ingest_result.pages_added,
            "first_page_number": ingest_result.first_page_number,
            "last_page_number": ingest_result.last_page_number,
        },
    )
    await db.commit()

    # Phase 3 — dispatch to the configured pipeline backend.
    workflow_id: str | None = None
    backend = settings.PIPELINE_BACKEND

    if backend == "temporal":
        workflow_id = await _start_temporal_workflow(
            settings, package_id, org_id, file_row.id,
        )
    else:
        # Inline / background_tasks backend — schedule the same 4 helpers
        # the workflow runs, sequentially. Tests configure
        # PIPELINE_BACKEND=background_tasks so this path is exercised.
        session_factory = get_session_factory()
        background_tasks.add_task(
            _run_remediation_inline,
            org_id, package_id, file_row.id,
            session_factory, storage,
        )

    return {
        "file_id": str(file_row.id),
        "pages_added": ingest_result.pages_added,
        "first_page_number": ingest_result.first_page_number,
        "last_page_number": ingest_result.last_page_number,
        "workflow_id": workflow_id,
        "backend": backend,
    }


async def _start_temporal_workflow(
    settings, package_id: uuid.UUID, org_id: uuid.UUID, file_id: uuid.UUID,
) -> str:
    """Connect to the Temporal cluster and start ``RemediateMissingDocWorkflow``."""
    from temporalio.client import Client

    from app.micro_apps.loan_onboarding.pipeline.temporal_workflows import (
        RemediateMissingDocWorkflow,
    )

    client = await Client.connect(
        settings.TEMPORAL_ADDRESS, namespace=settings.TEMPORAL_NAMESPACE,
    )
    run_id = uuid.uuid4().hex[:8]
    workflow_id = f"remediate-missing-doc-{package_id}-{run_id}"
    await client.start_workflow(
        RemediateMissingDocWorkflow.run,
        args=[str(package_id), str(org_id), str(file_id)],
        id=workflow_id,
        task_queue=settings.LO_TEMPORAL_TASK_QUEUE,
    )
    return workflow_id


async def _run_remediation_inline(
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    file_id: uuid.UUID,
    session_factory,
    storage: StorageProvider,
) -> None:
    """Run the 4-step Variant A remediation sequentially in-process.

    Background-task fallback for the ``PIPELINE_BACKEND=background_tasks``
    backend. Mirrors the Temporal workflow's step order; failures are
    logged but never re-raised — the operator polls package state for
    success/failure rather than expecting a sync HTTP response.
    """
    try:
        async with session_factory() as db:
            classify = await remediation_service.classify_single_doc(
                db, org_id, package_id, file_id, storage,
            )
            await db.commit()

        new_stack_id = classify.new_stack_id
        if new_stack_id is None:
            logger.warning(
                "remediation: classify produced no stack for file %s; halting",
                file_id,
            )
            return

        async with session_factory() as db:
            await remediation_service.doc_validation_recheck(
                db, org_id, package_id, new_stack_id,
            )
            await db.commit()

        async with session_factory() as db:
            await remediation_service.extract_single_doc(
                db, org_id, package_id, new_stack_id, storage,
            )
            await db.commit()

        async with session_factory() as db:
            await remediation_service.data_validation_partial(
                db, org_id, package_id, new_stack_id,
            )
            await db.commit()
    except Exception as e:  # pragma: no cover — surfaced via package state
        logger.exception(
            "remediation: inline run failed for package=%s file=%s: %s",
            package_id, file_id, e,
        )


# ── Variant B (3.3): missing-pages endpoint ───────────────────────────


@router.post(
    "/packages/{package_id}/remediate-missing-pages",
    status_code=status.HTTP_202_ACCEPTED,
)
async def remediate_missing_pages(
    package_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    target_stack_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
    storage: StorageProvider = Depends(get_storage),
):
    """Accept missing pages for an existing stack and run the Variant B workflow.

    Response shape:
        {
          "file_id": "...",
          "target_stack_id": "...",
          "pages_added": int,
          "first_page_number": int,
          "last_page_number": int,
          "workflow_id": "..." | null,    # null when running inline
          "backend": "temporal" | "background_tasks",
        }

    Step ordering (workflow vs inline) is identical to Variant A —
    classify_recheck → doc_validation_recheck → extract_recheck →
    data_validation_partial — with the additional ``append_pages``
    deterministic prelude. A rollback in step 2 short-circuits 3/4/5
    and is reflected via package state on subsequent polls.
    """
    settings = get_settings()
    package = await package_service.get_visible_package_or_raise(
        db, org_id, package_id, member,
    )

    if package.status not in _REMEDIATION_OK_STATUSES:
        raise ValidationError(
            f"Package cannot be remediated from status '{package.status}'. "
            f"Allowed statuses: {sorted(_REMEDIATION_OK_STATUSES)}"
        )

    # Validate the target stack belongs to this package + tenant before
    # we touch storage. Rejecting unknown ids early avoids creating an
    # orphan LOPackageFile row that the workflow would later fail on.
    from app.micro_apps.loan_onboarding.models.stack import LOStack
    target = (await db.execute(
        select(LOStack).where(
            LOStack.id == target_stack_id,
            LOStack.package_id == package_id,
            LOStack.org_id == org_id,
        )
    )).scalar_one_or_none()
    if target is None:
        raise NotFoundError("LoanStack", target_stack_id)

    # Phase 1 — persist the upload + read its bytes.
    data = await file.read()
    max_size = settings.LO_FILE_UPLOAD_MAX_SIZE
    if len(data) > max_size:
        raise ValidationError(
            f"File '{file.filename}' exceeds max size of {max_size} bytes"
        )

    file_row = await file_service.store_uploaded_file(
        db, storage,
        org_id=org_id, package_id=package_id,
        filename=file.filename or "remediation_pages.pdf",
        content=data, content_type=file.content_type,
    )

    # Phase 2 — append the new file's pages into the merged stack.
    # The classifier recheck + downstream steps are dispatched
    # asynchronously; the inline path mirrors the workflow.
    append_result = await remediation_service.append_pages(
        db, org_id, package_id, target_stack_id, file_row.id, storage,
    )

    await log_event(
        db, org_id,
        action="lo_remediation_pages_uploaded",
        target_type="lo_package",
        target_id=package_id,
        actor_id=member.id,
        metadata={
            "file_id": str(file_row.id),
            "filename": file_row.filename,
            "target_stack_id": str(target_stack_id),
            "pages_added": append_result.pages_added,
            "first_page_number": append_result.first_page_number,
            "last_page_number": append_result.last_page_number,
        },
    )
    await db.commit()

    # Phase 3 — dispatch to the configured pipeline backend.
    workflow_id: str | None = None
    backend = settings.PIPELINE_BACKEND

    if backend == "temporal":
        workflow_id = await _start_temporal_workflow_b(
            settings, package_id, org_id, target_stack_id, file_row.id,
        )
    else:
        session_factory = get_session_factory()
        background_tasks.add_task(
            _run_remediation_b_inline,
            org_id, package_id, target_stack_id, file_row.id,
            append_result.snapshot, session_factory, storage,
        )

    return {
        "file_id": str(file_row.id),
        "target_stack_id": str(target_stack_id),
        "pages_added": append_result.pages_added,
        "first_page_number": append_result.first_page_number,
        "last_page_number": append_result.last_page_number,
        "workflow_id": workflow_id,
        "backend": backend,
    }


async def _start_temporal_workflow_b(
    settings,
    package_id: uuid.UUID,
    org_id: uuid.UUID,
    target_stack_id: uuid.UUID,
    file_id: uuid.UUID,
) -> str:
    """Connect to Temporal and start ``RemediateMissingPagesWorkflow``."""
    from temporalio.client import Client

    from app.micro_apps.loan_onboarding.pipeline.temporal_workflows import (
        RemediateMissingPagesWorkflow,
    )

    client = await Client.connect(
        settings.TEMPORAL_ADDRESS, namespace=settings.TEMPORAL_NAMESPACE,
    )
    run_id = uuid.uuid4().hex[:8]
    workflow_id = f"remediate-missing-pages-{package_id}-{run_id}"
    await client.start_workflow(
        RemediateMissingPagesWorkflow.run,
        args=[
            str(package_id), str(org_id),
            str(target_stack_id), str(file_id),
        ],
        id=workflow_id,
        task_queue=settings.LO_TEMPORAL_TASK_QUEUE,
    )
    return workflow_id


async def _run_remediation_b_inline(
    org_id: uuid.UUID,
    package_id: uuid.UUID,
    target_stack_id: uuid.UUID,
    file_id: uuid.UUID,
    snapshot: dict,
    session_factory,
    storage: StorageProvider,
) -> None:
    """Run the 4 post-append Variant B steps sequentially in-process.

    ``append_pages`` already ran synchronously in the request handler
    (so the response carries the page-range metadata), so this picks up
    at step 2. Snapshot is passed in from the handler — we don't re-read
    it from the stack here because the inherited classifications would
    skew it.
    """
    try:
        async with session_factory() as db:
            recheck = await remediation_service.classify_recheck(
                db, org_id, package_id, target_stack_id, file_id,
                storage, snapshot,
            )
            await db.commit()

        if recheck.status == "rolled_back":
            logger.info(
                "remediation B: rolled back pkg=%s stack=%s reason=%s",
                package_id, target_stack_id, recheck.rollback_reason,
            )
            return

        async with session_factory() as db:
            await remediation_service.doc_validation_recheck(
                db, org_id, package_id, target_stack_id,
            )
            await db.commit()

        async with session_factory() as db:
            await remediation_service.extract_single_doc(
                db, org_id, package_id, target_stack_id, storage,
            )
            await db.commit()

        async with session_factory() as db:
            await remediation_service.data_validation_partial(
                db, org_id, package_id, target_stack_id,
            )
            await db.commit()
    except Exception as e:  # pragma: no cover — surfaced via package state
        logger.exception(
            "remediation B: inline run failed for package=%s stack=%s file=%s: %s",
            package_id, target_stack_id, file_id, e,
        )
