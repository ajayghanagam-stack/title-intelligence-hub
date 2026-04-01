import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.micro_apps.title_search.models.order import TAOrder
from app.micro_apps.title_search.services.order_service import get_order_or_raise
from app.micro_apps.title_search.schemas.order import (
    PipelineStatusResponse,
    PipelineStageStatusSchema,
)

SCRAPER_PIPELINE_STAGES = ["order", "retrieve", "parse", "chain", "package", "complete"]
GROUNDED_PIPELINE_STAGES = ["order", "research", "chain", "package", "complete"]


def _get_active_stages() -> list[str]:
    settings = get_settings()
    if settings.TSA_RESEARCH_MODE == "grounded":
        return GROUNDED_PIPELINE_STAGES
    return SCRAPER_PIPELINE_STAGES


# Legacy alias
PIPELINE_STAGES = SCRAPER_PIPELINE_STAGES


async def get_pipeline_status_or_raise(
    db: AsyncSession, org_id: uuid.UUID, order_id: uuid.UUID
) -> PipelineStatusResponse:
    order = await get_order_or_raise(db, org_id, order_id)

    # Terminal statuses where pipeline_stage is None but all stages finished
    terminal_statuses = {"completed", "review_required"}
    # Paused statuses where the pipeline is waiting for external input
    paused_statuses = {"awaiting_abstractor"}

    stages = []
    if order.status in terminal_statuses and order.pipeline_stage is None:
        # Pipeline finished — all stages completed
        stages = [
            PipelineStageStatusSchema(stage=s, status="completed")
            for s in _get_active_stages()
        ]
    elif order.status in paused_statuses:
        # Pipeline paused — show completed stages + paused current stage
        current_found = False
        for stage_name in _get_active_stages():
            if stage_name == order.pipeline_stage:
                current_found = True
                stages.append(PipelineStageStatusSchema(stage=stage_name, status="paused"))
            elif not current_found:
                stages.append(PipelineStageStatusSchema(stage=stage_name, status="completed"))
            else:
                stages.append(PipelineStageStatusSchema(stage=stage_name, status="pending"))
    elif order.pipeline_stage is None:
        # Pipeline hasn't started yet
        stages = [
            PipelineStageStatusSchema(stage=s, status="pending")
            for s in _get_active_stages()
        ]
    else:
        current_found = False
        for stage_name in _get_active_stages():
            if stage_name == order.pipeline_stage:
                current_found = True
                if order.status == "failed":
                    stages.append(PipelineStageStatusSchema(stage=stage_name, status="failed"))
                else:
                    stages.append(PipelineStageStatusSchema(stage=stage_name, status="running"))
            elif not current_found:
                stages.append(PipelineStageStatusSchema(stage=stage_name, status="completed"))
            else:
                stages.append(PipelineStageStatusSchema(stage=stage_name, status="pending"))

    return PipelineStatusResponse(
        order_id=order.id,
        status=order.status,
        pipeline_stage=order.pipeline_stage,
        stages=stages,
        pipeline_error=order.pipeline_error,
    )
