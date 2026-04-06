"""Unified Temporal worker for all micro app pipelines.

Registers both TI (ProcessPackWorkflow) and TSA (ProcessOrderWorkflow) workflows,
each on its own task queue for independent scaling and isolation.

Run with: python -m app.pipeline.unified_worker
"""

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from app.config import get_settings

# -- TI imports --
from app.micro_apps.title_intelligence.pipeline.temporal_activities import (
    configure_activities as configure_ti_activities,
    activity_ingest,
    activity_render,
    activity_examine,
    activity_complete,
    activity_create_pipeline_run,
    activity_finalize_pipeline_run,
    activity_mark_completed,
    activity_mark_failed,
)
from app.micro_apps.title_intelligence.pipeline.temporal_workflows import (
    ProcessPackWorkflow,
)

# -- TSA imports --
from app.micro_apps.title_search.pipeline.temporal_activities import (
    configure_ta_activities,
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
from app.micro_apps.title_search.pipeline.temporal_workflows import (
    ProcessOrderWorkflow,
)

logger = logging.getLogger(__name__)

TI_ACTIVITIES = [
    activity_ingest,
    activity_render,
    activity_examine,
    activity_complete,
    activity_create_pipeline_run,
    activity_finalize_pipeline_run,
    activity_mark_completed,
    activity_mark_failed,
]

TSA_ACTIVITIES = [
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
]


async def run_worker():
    """Start the unified Temporal worker polling both task queues."""
    settings = get_settings()

    from app.core.deps import get_session_factory
    from app.micro_apps.title_intelligence.services.storage import get_storage

    session_factory = get_session_factory(settings)
    storage = get_storage()

    # Configure both sets of activities
    configure_ti_activities(session_factory, storage)
    configure_ta_activities(session_factory)

    client = await Client.connect(
        settings.TEMPORAL_ADDRESS,
        namespace=settings.TEMPORAL_NAMESPACE,
    )

    # TI worker — polls title-intelligence queue
    ti_worker = Worker(
        client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[ProcessPackWorkflow],
        activities=TI_ACTIVITIES,
        max_concurrent_activities=10,
        max_concurrent_workflow_tasks=5,
    )

    # TSA worker — polls title-search queue
    tsa_worker = Worker(
        client,
        task_queue=settings.TSA_TEMPORAL_TASK_QUEUE,
        workflows=[ProcessOrderWorkflow],
        activities=TSA_ACTIVITIES,
        max_concurrent_activities=10,
        max_concurrent_workflow_tasks=5,
    )

    logger.info(
        f"Starting unified Temporal worker on {settings.TEMPORAL_ADDRESS}, "
        f"namespace={settings.TEMPORAL_NAMESPACE}, "
        f"queues=[{settings.TEMPORAL_TASK_QUEUE}, {settings.TSA_TEMPORAL_TASK_QUEUE}]"
    )

    # Run both workers concurrently
    await asyncio.gather(ti_worker.run(), tsa_worker.run())


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    # Silence noisy third-party loggers
    for _noisy in (
        "httpx", "httpcore", "litellm", "LiteLLM", "LiteLLM Proxy",
        "LiteLLM Router", "google.genai", "google.auth", "google.api_core",
        "googleapis", "urllib3", "asyncpg", "grpc", "hpack", "anthropic",
        "watchfiles",
    ):
        _logger = logging.getLogger(_noisy)
        _logger.setLevel(logging.WARNING)
        _logger.handlers = [h for h in _logger.handlers if h.level > logging.INFO]
    asyncio.run(run_worker())
