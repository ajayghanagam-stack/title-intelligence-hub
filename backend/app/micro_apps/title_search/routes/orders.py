import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_db, get_current_member, get_org_id, get_session_factory
from app.models.user import User
from app.micro_apps.title_search.schemas.order import (
    OrderCreate,
    OrderResponse,
    OrderListResponse,
    PipelineStatusResponse,
)
from app.micro_apps.title_search.services import order_service, pipeline_service
from app.micro_apps.title_search.pipeline.orchestrator import trigger_pipeline
from app.services.audit_service import log_event

router = APIRouter()


@router.post("/orders", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    body: OrderCreate,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    order = await order_service.create_order(
        db, org_id, member.id,
        property_address=body.property_address,
        county=body.county,
        state_code=body.state_code,
        parcel_number=body.parcel_number,
        legal_description=body.legal_description,
        search_scope=body.search_scope,
        search_years=body.search_years,
        linked_pack_id=body.linked_pack_id,
    )
    await log_event(
        db, org_id,
        action="order_created",
        target_type="ta_order",
        target_id=order.id,
        actor_id=member.id,
    )
    await db.commit()
    return order


@router.get("/orders", response_model=list[OrderListResponse])
async def list_orders(
    status_filter: str | None = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await order_service.list_orders(db, org_id, status=status_filter, page=page, size=size)


@router.get("/orders/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await order_service.get_order_or_raise(db, org_id, order_id)


@router.delete("/orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    await order_service.delete_order_or_raise(db, org_id, order_id)
    await log_event(
        db, org_id,
        action="order_deleted",
        target_type="ta_order",
        target_id=order_id,
        actor_id=member.id,
    )
    await db.commit()


@router.post("/orders/{order_id}/process", status_code=status.HTTP_202_ACCEPTED)
async def trigger_process(
    order_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    order = await order_service.require_order_for_processing(db, org_id, order_id)
    order.status = "processing"
    order.pipeline_stage = "order"
    order.pipeline_error = None
    await log_event(
        db, org_id,
        action="ta_pipeline_started",
        target_type="ta_order",
        target_id=order_id,
        actor_id=member.id,
    )
    await db.commit()

    session_factory = get_session_factory()
    await trigger_pipeline(order_id, org_id, session_factory, background_tasks=background_tasks)
    return {"message": "Processing started", "order_id": str(order_id)}


@router.get("/orders/{order_id}/pipeline", response_model=PipelineStatusResponse)
async def get_pipeline_status(
    order_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    member: User = Depends(get_current_member),
    org_id: uuid.UUID = Depends(get_org_id),
):
    return await pipeline_service.get_pipeline_status_or_raise(db, org_id, order_id)
