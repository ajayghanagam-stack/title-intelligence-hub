"""Temporal workflow definition for the 7-stage pipeline.

Activity timeouts match V2:
- Render/OCR/Index: 10 min start-to-close, 3 retries
- AI activities: 20 min start-to-close, 5 retries, backoff coefficient 2
"""

import logging
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from app.micro_apps.title_intelligence.pipeline.temporal_activities import (
        activity_ingest,
        activity_render,
        activity_ocr,
        activity_index,
        activity_ingestion_agent,
        activity_risk_agent,
        activity_complete,
        activity_mark_completed,
        activity_mark_failed,
        activity_create_pipeline_run,
        activity_finalize_pipeline_run,
    )

logger = logging.getLogger(__name__)

# Retry policies matching V2
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

# No retry for mark_completed/mark_failed — they are final state transitions
FINALIZE_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_attempts=3,
)

# Heartbeat timeout — if no heartbeat within this window, Temporal considers activity stuck
HEARTBEAT_TIMEOUT = timedelta(minutes=5)

# Stage definitions: (activity_fn, timeout, retry_policy, stage_name)
STAGES = [
    (activity_ingest, timedelta(minutes=10), INFRA_RETRY, "ingest"),
    (activity_render, timedelta(minutes=10), INFRA_RETRY, "render"),
    (activity_ocr, timedelta(minutes=10), INFRA_RETRY, "ocr"),
    (activity_index, timedelta(minutes=10), INFRA_RETRY, "index"),
    (activity_ingestion_agent, timedelta(minutes=20), AI_RETRY, "ingestion_agent"),
    (activity_risk_agent, timedelta(minutes=20), AI_RETRY, "risk_agent"),
    (activity_complete, timedelta(minutes=10), INFRA_RETRY, "complete"),
]


@workflow.defn
class ProcessPackWorkflow:
    """Durable workflow for processing a title pack through 7 stages."""

    @workflow.run
    async def run(self, pack_id: str, org_id: str) -> None:
        workflow.logger.info(f"Starting pipeline workflow for pack {pack_id}")

        # Create PipelineRun record before stages
        pipeline_run_id: str | None = None
        try:
            pipeline_run_id = await workflow.execute_activity(
                activity_create_pipeline_run,
                args=[pack_id, org_id],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=FINALIZE_RETRY,
            )
        except Exception as e:
            workflow.logger.warning(f"Failed to create PipelineRun for pack {pack_id}: {e}")

        try:
            for activity_fn, timeout, retry_policy, stage_name in STAGES:
                await workflow.execute_activity(
                    activity_fn,
                    args=[pack_id, org_id],
                    start_to_close_timeout=timeout,
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=retry_policy,
                )

            # All stages completed — mark pack as completed with audit event
            await workflow.execute_activity(
                activity_mark_completed,
                args=[pack_id, org_id],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=FINALIZE_RETRY,
            )

            # Finalize PipelineRun as completed
            if pipeline_run_id:
                try:
                    await workflow.execute_activity(
                        activity_finalize_pipeline_run,
                        args=[pipeline_run_id, "completed"],
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=FINALIZE_RETRY,
                    )
                except Exception as e:
                    workflow.logger.warning(f"Failed to finalize PipelineRun: {e}")

            workflow.logger.info(f"Pipeline workflow completed for pack {pack_id}")

        except Exception as e:
            workflow.logger.error(f"Pipeline workflow failed for pack {pack_id}: {e}")

            # Determine which stage failed (last stage in the list that was attempted)
            failed_stage = "unknown"
            for _, _, _, stage_name in STAGES:
                failed_stage = stage_name

            # Mark pack as failed with audit event
            try:
                await workflow.execute_activity(
                    activity_mark_failed,
                    args=[pack_id, org_id, str(e), failed_stage],
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=FINALIZE_RETRY,
                )
            except Exception as mark_err:
                workflow.logger.error(
                    f"Failed to mark pack {pack_id} as failed: {mark_err}"
                )

            # Finalize PipelineRun as failed
            if pipeline_run_id:
                try:
                    await workflow.execute_activity(
                        activity_finalize_pipeline_run,
                        args=[pipeline_run_id, "failed", str(e)],
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=FINALIZE_RETRY,
                    )
                except Exception as fin_err:
                    workflow.logger.warning(f"Failed to finalize PipelineRun: {fin_err}")

            raise
