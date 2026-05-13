"""Temporal workflow for the Loan Onboarding pipeline.

Stages: ingest → classify → stack → validate → review → mark_completed.
Each stage is an activity. The review activity returns the HITL count so
the workflow can pick the right terminal status (awaiting_review vs completed).
"""
from __future__ import annotations

import logging
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from app.micro_apps.loan_onboarding.pipeline.temporal_activities import (
        lo_activity_append_pages,
        lo_activity_classify,
        lo_activity_classify_recheck,
        lo_activity_classify_single_doc,
        lo_activity_data_validation_partial,
        lo_activity_doc_validation_recheck,
        lo_activity_extract,
        lo_activity_extract_single_doc,
        lo_activity_ingest,
        lo_activity_mark_completed,
        lo_activity_mark_failed,
        lo_activity_review,
        lo_activity_stack,
        lo_activity_validate,
    )

logger = logging.getLogger(__name__)

INFRA_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    maximum_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_attempts=3,
)

AI_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=2),
    maximum_interval=timedelta(seconds=60),
    backoff_coefficient=2.0,
    maximum_attempts=5,
)

FINALIZE_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_attempts=3,
)

HEARTBEAT_TIMEOUT = timedelta(minutes=5)

# (activity_fn, start_to_close_timeout, retry_policy, stage_name)
# Classify/validate/review run many parallel Gemini/Claude calls per stage,
# and on large mortgage bundles (1000+ pages) the wall time can exceed 15 min
# even when each individual call is fast. Heartbeats run every 30s so the
# 5min heartbeat_timeout still catches genuinely stuck workers.
PIPELINE_STAGES = [
    (lo_activity_ingest, timedelta(minutes=10), INFRA_RETRY, "ingest"),
    (lo_activity_classify, timedelta(minutes=30), AI_RETRY, "classify"),
    (lo_activity_stack, timedelta(minutes=5), INFRA_RETRY, "stack"),
    (lo_activity_validate, timedelta(minutes=30), AI_RETRY, "validate"),
    (lo_activity_extract, timedelta(minutes=30), AI_RETRY, "extract"),
    (lo_activity_review, timedelta(minutes=30), AI_RETRY, "review"),
]


@workflow.defn
class ProcessLoanWorkflow:
    """Durable workflow for processing a loan package through the pipeline."""

    @workflow.run
    async def run(self, package_id: str, org_id: str) -> None:
        workflow.logger.info(f"Starting LO pipeline for package {package_id}")

        failed_stage = "unknown"
        review_output: dict | None = None
        try:
            for activity_fn, timeout, retry_policy, stage_name in PIPELINE_STAGES:
                failed_stage = stage_name
                output = await workflow.execute_activity(
                    activity_fn,
                    args=[package_id, org_id],
                    start_to_close_timeout=timeout,
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=retry_policy,
                )
                if stage_name == "review":
                    review_output = output or {}

            hitl_count = int((review_output or {}).get("hitl_stacks", 0))
            await workflow.execute_activity(
                lo_activity_mark_completed,
                args=[package_id, org_id, hitl_count],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=FINALIZE_RETRY,
            )
            workflow.logger.info(
                f"LO pipeline completed for package {package_id} "
                f"(hitl_count={hitl_count})"
            )

        except Exception as e:
            error_msg = str(e)
            workflow.logger.error(
                f"LO pipeline failed at '{failed_stage}' for {package_id}: {error_msg}"
            )
            try:
                await workflow.execute_activity(
                    lo_activity_mark_failed,
                    args=[package_id, org_id, error_msg, failed_stage],
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=FINALIZE_RETRY,
                )
            except Exception as mark_err:
                workflow.logger.error(
                    f"Failed to mark package {package_id} as failed: {mark_err}"
                )
            raise


# ── Phase 3.2: Variant A — RemediateMissingDocWorkflow ────────────────


# Per-step timeouts mirror the PRD §3.2 budget (~1s, ~0.5s, ~3s, ~0.5s)
# with healthy headroom. The workflow is a *child* workflow kicked off
# from POST /loans/{id}/remediate-missing-doc; it never advances the
# package's pipeline_stage (§3.5 monotonic-advance contract).
REMEDIATION_AI_TIMEOUT = timedelta(minutes=2)   # classify, extract
REMEDIATION_RULE_TIMEOUT = timedelta(seconds=30)  # validation rechecks


@workflow.defn
class RemediateMissingDocWorkflow:
    """Variant A: operator uploaded a previously-missing required document.

    Inputs:
        package_id — the loan package id
        org_id     — tenant scope
        file_id    — the LOPackageFile that was just ingested

    Steps (per PRD §3.2):
        1. classify_single_doc(file_id)        → returns new_stack_id
        2. doc_validation_recheck(stack_id)    → row-only preset eval
        3. extract_single_doc(stack_id)        → field extraction
        4. data_validation_partial(stack_id)   → cross-doc rules touching this stack

    Output dict aggregates each step's result for the SSE consumer; the
    pipeline-progress UI reads this to flip per-stage labels.

    The workflow does **not** call ``lo_activity_mark_completed`` /
    ``mark_failed`` — those are owned by the main pipeline and would
    violate the monotonic-advance contract. Failure of a remediation
    step propagates as a workflow failure; the operator can retry.
    """

    @workflow.run
    async def run(self, package_id: str, org_id: str, file_id: str) -> dict:
        workflow.logger.info(
            f"RemediateMissingDocWorkflow start: pkg={package_id} file={file_id}"
        )

        # Step 1 — classify only the new file's pages
        classify_result = await workflow.execute_activity(
            lo_activity_classify_single_doc,
            args=[package_id, org_id, file_id],
            start_to_close_timeout=REMEDIATION_AI_TIMEOUT,
            retry_policy=AI_RETRY,
        )

        new_stack_id = classify_result.get("new_stack_id")
        if not new_stack_id:
            # Skeleton phase only — once 3.2b lands, classify must always
            # produce a stack (even Others). Raising here avoids silently
            # advancing through follow-up steps with no target stack.
            workflow.logger.warning(
                f"classify_single_doc returned no stack id "
                f"(status={classify_result.get('status')}); "
                f"skipping downstream remediation steps"
            )
            return {
                "classify": classify_result,
                "doc_validation_recheck": None,
                "extract": None,
                "data_validation_partial": None,
            }

        # Step 2 — preset rule recheck on the new stack only
        validate_result = await workflow.execute_activity(
            lo_activity_doc_validation_recheck,
            args=[package_id, org_id, new_stack_id],
            start_to_close_timeout=REMEDIATION_RULE_TIMEOUT,
            retry_policy=INFRA_RETRY,
        )

        # Step 3 — extract fields for the new stack
        extract_result = await workflow.execute_activity(
            lo_activity_extract_single_doc,
            args=[package_id, org_id, new_stack_id],
            start_to_close_timeout=REMEDIATION_AI_TIMEOUT,
            retry_policy=AI_RETRY,
        )

        # Step 4 — cross-doc rules touching this stack
        data_validate_result = await workflow.execute_activity(
            lo_activity_data_validation_partial,
            args=[package_id, org_id, new_stack_id],
            start_to_close_timeout=REMEDIATION_RULE_TIMEOUT,
            retry_policy=INFRA_RETRY,
        )

        workflow.logger.info(
            f"RemediateMissingDocWorkflow done: pkg={package_id} "
            f"stack={new_stack_id} hard_stops={validate_result.get('hard_stops')}"
        )
        return {
            "classify": classify_result,
            "doc_validation_recheck": validate_result,
            "extract": extract_result,
            "data_validation_partial": data_validate_result,
        }


# ── Phase 3.3: Variant B — RemediateMissingPagesWorkflow ──────────────


@workflow.defn
class RemediateMissingPagesWorkflow:
    """Variant B: operator uploaded missing pages for an existing document.

    Inputs:
        package_id      — the loan package id
        org_id          — tenant scope
        target_stack_id — the stack the new pages should extend
        file_id         — the LOPackageFile that was just uploaded

    Steps (per PRD §3.3):
        1. append_pages(target_stack_id, file_id)         deterministic
        2. classify_recheck(target_stack_id, file_id)     LLM, may roll back
           ↳ if rolled_back → skip 3/4/5 and return early
        3. doc_validation_recheck(target_stack_id)        preset eval
        4. extract_recheck(target_stack_id) ≡ extract_single_doc
        5. data_validation_partial(target_stack_id)

    Like Variant A, this workflow never advances the package's
    ``pipeline_stage``. A ``rolled_back`` outcome is *not* a workflow
    failure — it's a successful "we caught the bad upload" — so the
    workflow returns normally with the rollback metadata in the output
    dict.
    """

    @workflow.run
    async def run(
        self,
        package_id: str,
        org_id: str,
        target_stack_id: str,
        file_id: str,
    ) -> dict:
        workflow.logger.info(
            f"RemediateMissingPagesWorkflow start: pkg={package_id} "
            f"stack={target_stack_id} file={file_id}"
        )

        # Step 1 — append the new pages (deterministic, no LLM).
        append_result = await workflow.execute_activity(
            lo_activity_append_pages,
            args=[package_id, org_id, target_stack_id, file_id],
            start_to_close_timeout=REMEDIATION_RULE_TIMEOUT,
            retry_policy=INFRA_RETRY,
        )

        # Step 2 — recheck classification on just the new pages.
        recheck_result = await workflow.execute_activity(
            lo_activity_classify_recheck,
            args=[
                package_id,
                org_id,
                target_stack_id,
                file_id,
                append_result.get("snapshot") or {},
            ],
            start_to_close_timeout=REMEDIATION_AI_TIMEOUT,
            retry_policy=AI_RETRY,
        )

        if (recheck_result.get("status") or "").lower() == "rolled_back":
            workflow.logger.info(
                f"RemediateMissingPagesWorkflow rolled back: "
                f"pkg={package_id} stack={target_stack_id} "
                f"reason={recheck_result.get('rollback_reason')}"
            )
            return {
                "append_pages": append_result,
                "classify_recheck": recheck_result,
                "doc_validation_recheck": None,
                "extract": None,
                "data_validation_partial": None,
            }

        # Step 3 — preset rule recheck on the merged stack.
        validate_result = await workflow.execute_activity(
            lo_activity_doc_validation_recheck,
            args=[package_id, org_id, target_stack_id],
            start_to_close_timeout=REMEDIATION_RULE_TIMEOUT,
            retry_policy=INFRA_RETRY,
        )

        # Step 4 — re-extract on the merged stack (delete-then-insert).
        extract_result = await workflow.execute_activity(
            lo_activity_extract_single_doc,
            args=[package_id, org_id, target_stack_id],
            start_to_close_timeout=REMEDIATION_AI_TIMEOUT,
            retry_policy=AI_RETRY,
        )

        # Step 5 — cross-doc rules touching the merged stack.
        data_validate_result = await workflow.execute_activity(
            lo_activity_data_validation_partial,
            args=[package_id, org_id, target_stack_id],
            start_to_close_timeout=REMEDIATION_RULE_TIMEOUT,
            retry_policy=INFRA_RETRY,
        )

        workflow.logger.info(
            f"RemediateMissingPagesWorkflow done: pkg={package_id} "
            f"stack={target_stack_id} "
            f"hard_stops={validate_result.get('hard_stops')}"
        )
        return {
            "append_pages": append_result,
            "classify_recheck": recheck_result,
            "doc_validation_recheck": validate_result,
            "extract": extract_result,
            "data_validation_partial": data_validate_result,
        }
