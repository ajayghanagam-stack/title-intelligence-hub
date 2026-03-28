import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_intelligence.models.pack import Pack
from app.micro_apps.title_intelligence.schemas.pack import (
    PipelineStageStatus,
    PipelineStatusResponse,
)
from app.core.exceptions import NotFoundError

PIPELINE_STAGES = [
    "ingest",
    "render",
    "examine",
    "complete",
]


async def get_pipeline_status(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID
) -> PipelineStatusResponse | None:
    result = await db.execute(
        select(Pack).where(Pack.id == pack_id, Pack.org_id == org_id)
    )
    pack = result.scalar_one_or_none()
    if not pack:
        return None

    current = pack.current_stage
    pack_status = pack.status
    stages: list[PipelineStageStatus] = []

    # Get the index of the current stage (or -1 if not set)
    current_idx = PIPELINE_STAGES.index(current) if current and current in PIPELINE_STAGES else -1

    for idx, stage_name in enumerate(PIPELINE_STAGES):
        if pack_status == "completed":
            stages.append(PipelineStageStatus(stage=stage_name, status="completed"))
        elif pack_status == "failed" and stage_name == current:
            stages.append(PipelineStageStatus(stage=stage_name, status="failed"))
        elif current_idx >= 0 and idx < current_idx:
            stages.append(PipelineStageStatus(stage=stage_name, status="completed"))
        elif stage_name == current and pack_status == "processing":
            stages.append(PipelineStageStatus(stage=stage_name, status="running"))
        else:
            stages.append(PipelineStageStatus(stage=stage_name, status="pending"))

    return PipelineStatusResponse(
        pack_id=pack_id,
        status=pack_status,
        current_stage=current,
        stages=stages,
        examine_progress=pack.examine_progress if current == "examine" else None,
        error_message=pack.error_message,
    )


async def get_pipeline_status_or_raise(
    db: AsyncSession, org_id: uuid.UUID, pack_id: uuid.UUID
) -> PipelineStatusResponse:
    result = await get_pipeline_status(db, org_id, pack_id)
    if not result:
        raise NotFoundError("Pack", pack_id)
    return result
