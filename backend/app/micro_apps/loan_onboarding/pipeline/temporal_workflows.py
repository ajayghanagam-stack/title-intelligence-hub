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
        lo_activity_classify,
        lo_activity_extract,
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
