"""Temporal workflow definition for TSA pipeline execution.

Pipeline stages depend on research mode:
- Grounded: order → research → chain → package → complete
- Scraper:  order → retrieve → parse → chain → package → complete

Activity timeouts:
- Research: 15 min start-to-close, 2 retries (Claude web search)
- Other stages: 10 min start-to-close, 3 retries
"""

import logging
from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from app.micro_apps.title_search.pipeline.temporal_activities import (
        ta_activity_order,
        ta_activity_research,
        ta_activity_retrieve,
        ta_activity_parse,
        ta_activity_chain,
        ta_activity_package,
        ta_activity_complete,
        ta_activity_create_pipeline_run,
        ta_activity_finalize_pipeline_run,
        ta_activity_mark_completed,
        ta_activity_mark_failed,
    )

logger = logging.getLogger(__name__)

# Retry policies
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

RESEARCH_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5),
    maximum_interval=timedelta(seconds=60),
    backoff_coefficient=2.0,
    maximum_attempts=2,
)

FINALIZE_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=1),
    maximum_interval=timedelta(seconds=10),
    backoff_coefficient=2.0,
    maximum_attempts=3,
)

HEARTBEAT_TIMEOUT = timedelta(minutes=5)

# Stage definitions per research mode:
# (activity_fn, timeout, retry_policy, stage_name)
GROUNDED_STAGES = [
    (ta_activity_order, timedelta(minutes=10), INFRA_RETRY, "order"),
    (ta_activity_research, timedelta(minutes=15), RESEARCH_RETRY, "research"),
    (ta_activity_chain, timedelta(minutes=10), AI_RETRY, "chain"),
    (ta_activity_package, timedelta(minutes=10), INFRA_RETRY, "package"),
    (ta_activity_complete, timedelta(minutes=10), INFRA_RETRY, "complete"),
]

SCRAPER_STAGES = [
    (ta_activity_order, timedelta(minutes=10), INFRA_RETRY, "order"),
    (ta_activity_retrieve, timedelta(minutes=10), INFRA_RETRY, "retrieve"),
    (ta_activity_parse, timedelta(minutes=10), AI_RETRY, "parse"),
    (ta_activity_chain, timedelta(minutes=10), AI_RETRY, "chain"),
    (ta_activity_package, timedelta(minutes=10), INFRA_RETRY, "package"),
    (ta_activity_complete, timedelta(minutes=10), INFRA_RETRY, "complete"),
]


@workflow.defn
class ProcessOrderWorkflow:
    """Durable workflow for processing a title search order through the pipeline."""

    @workflow.run
    async def run(self, order_id: str, org_id: str, research_mode: str) -> None:
        workflow.logger.info(f"Starting TSA pipeline workflow for order {order_id}")

        stages = GROUNDED_STAGES if research_mode == "grounded" else SCRAPER_STAGES

        # Create TAPipelineRun record before stages
        pipeline_run_id: str | None = None
        try:
            pipeline_run_id = await workflow.execute_activity(
                ta_activity_create_pipeline_run,
                args=[order_id, org_id],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=FINALIZE_RETRY,
            )
        except Exception as e:
            workflow.logger.warning(f"Failed to create TAPipelineRun for order {order_id}: {e}")

        failed_stage = "unknown"
        try:
            for activity_fn, timeout, retry_policy, stage_name in stages:
                failed_stage = stage_name
                await workflow.execute_activity(
                    activity_fn,
                    args=[order_id, org_id],
                    start_to_close_timeout=timeout,
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=retry_policy,
                )

            # All stages completed
            await workflow.execute_activity(
                ta_activity_mark_completed,
                args=[order_id, org_id],
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=FINALIZE_RETRY,
            )

            if pipeline_run_id:
                try:
                    await workflow.execute_activity(
                        ta_activity_finalize_pipeline_run,
                        args=[pipeline_run_id, org_id, "completed"],
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=FINALIZE_RETRY,
                    )
                except Exception as e:
                    workflow.logger.warning(f"Failed to finalize TAPipelineRun: {e}")

            workflow.logger.info(f"TSA pipeline workflow completed for order {order_id}")

        except Exception as e:
            error_msg = str(e)
            workflow.logger.error(
                f"TSA pipeline workflow failed at stage '{failed_stage}' "
                f"for order {order_id}: {error_msg}"
            )

            # Check if this is a pipeline pause (non-retryable ApplicationError)
            from temporalio.exceptions import ApplicationError
            if isinstance(e, ApplicationError) and e.non_retryable:
                # Pipeline paused (e.g., awaiting_abstractor) — not a failure
                if pipeline_run_id:
                    try:
                        await workflow.execute_activity(
                            ta_activity_finalize_pipeline_run,
                            args=[pipeline_run_id, org_id, "paused", error_msg],
                            start_to_close_timeout=timedelta(minutes=2),
                            retry_policy=FINALIZE_RETRY,
                        )
                    except Exception as fin_err:
                        workflow.logger.warning(f"Failed to finalize TAPipelineRun: {fin_err}")
                return

            # Mark order as failed
            try:
                await workflow.execute_activity(
                    ta_activity_mark_failed,
                    args=[order_id, org_id, error_msg, failed_stage],
                    start_to_close_timeout=timedelta(minutes=2),
                    retry_policy=FINALIZE_RETRY,
                )
            except Exception as mark_err:
                workflow.logger.error(
                    f"Failed to mark order {order_id} as failed: {mark_err}"
                )

            if pipeline_run_id:
                try:
                    await workflow.execute_activity(
                        ta_activity_finalize_pipeline_run,
                        args=[pipeline_run_id, org_id, "failed", error_msg],
                        start_to_close_timeout=timedelta(minutes=2),
                        retry_policy=FINALIZE_RETRY,
                    )
                except Exception as fin_err:
                    workflow.logger.warning(f"Failed to finalize TAPipelineRun: {fin_err}")

            raise
