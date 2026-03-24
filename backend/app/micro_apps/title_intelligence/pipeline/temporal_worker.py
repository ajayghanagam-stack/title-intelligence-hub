"""Temporal worker setup for pipeline activities.

Run with: python -m app.micro_apps.title_intelligence.pipeline.temporal_worker
"""

import asyncio
import logging

from temporalio.client import Client
from temporalio.worker import Worker

from app.config import get_settings
from app.micro_apps.title_intelligence.pipeline.temporal_activities import (
    configure_activities,
    activity_ingest,
    activity_render,
    activity_ocr,
    activity_index,
    activity_ingestion_agent,
    activity_risk_agent,
    activity_complete,
    activity_create_pipeline_run,
    activity_finalize_pipeline_run,
    activity_mark_completed,
    activity_mark_failed,
)
from app.micro_apps.title_intelligence.pipeline.temporal_workflows import ProcessPackWorkflow

logger = logging.getLogger(__name__)

ACTIVITIES = [
    activity_ingest,
    activity_render,
    activity_ocr,
    activity_index,
    activity_ingestion_agent,
    activity_risk_agent,
    activity_complete,
    activity_create_pipeline_run,
    activity_finalize_pipeline_run,
    activity_mark_completed,
    activity_mark_failed,
]


async def run_worker():
    """Start the Temporal worker."""
    settings = get_settings()

    from app.core.deps import get_session_factory
    from app.micro_apps.title_intelligence.services.storage import get_storage

    session_factory = get_session_factory(settings)
    storage = get_storage()
    configure_activities(session_factory, storage)

    client = await Client.connect(
        settings.TEMPORAL_ADDRESS,
        namespace=settings.TEMPORAL_NAMESPACE,
    )

    worker = Worker(
        client,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        workflows=[ProcessPackWorkflow],
        activities=ACTIVITIES,
    )

    logger.info(
        f"Starting Temporal worker on {settings.TEMPORAL_ADDRESS}, "
        f"namespace={settings.TEMPORAL_NAMESPACE}, "
        f"task_queue={settings.TEMPORAL_TASK_QUEUE}"
    )

    await worker.run()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())
