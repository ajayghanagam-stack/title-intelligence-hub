import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_search.models.order import TAOrder
from app.core.exceptions import NotFoundError, ConflictError, ValidationError


async def create_order(
    db: AsyncSession,
    org_id: uuid.UUID,
    created_by: uuid.UUID,
    property_address: str,
    county: str,
    state_code: str,
    parcel_number: str | None = None,
    legal_description: str | None = None,
    search_scope: str = "full",
    search_years: int = 60,
    linked_pack_id: uuid.UUID | None = None,
) -> TAOrder:
    # Validate linked_pack_id if provided
    if linked_pack_id:
        from app.micro_apps.title_intelligence.models.pack import Pack
        result = await db.execute(
            select(Pack).where(Pack.id == linked_pack_id, Pack.org_id == org_id)
        )
        if not result.scalar_one_or_none():
            raise ValidationError(f"Linked pack not found: {linked_pack_id}")

    order = TAOrder(
        org_id=org_id,
        created_by=created_by,
        property_address=property_address,
        county=county,
        state_code=state_code,
        parcel_number=parcel_number,
        legal_description=legal_description,
        search_scope=search_scope,
        search_years=search_years,
        linked_pack_id=linked_pack_id,
        status="pending",
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    return order


async def get_order(
    db: AsyncSession, org_id: uuid.UUID, order_id: uuid.UUID
) -> TAOrder | None:
    result = await db.execute(
        select(TAOrder).where(TAOrder.id == order_id, TAOrder.org_id == org_id)
    )
    return result.scalar_one_or_none()


async def get_order_or_raise(
    db: AsyncSession, org_id: uuid.UUID, order_id: uuid.UUID
) -> TAOrder:
    order = await get_order(db, org_id, order_id)
    if not order:
        raise NotFoundError("Order", order_id)
    return order


async def list_orders(
    db: AsyncSession,
    org_id: uuid.UUID,
    status: str | None = None,
    page: int = 1,
    size: int = 20,
) -> list[TAOrder]:
    query = select(TAOrder).where(TAOrder.org_id == org_id)
    if status:
        query = query.where(TAOrder.status == status)
    query = query.order_by(TAOrder.created_at.desc()).offset((page - 1) * size).limit(size)
    result = await db.execute(query)
    return list(result.scalars().all())


async def delete_order_or_raise(
    db: AsyncSession, org_id: uuid.UUID, order_id: uuid.UUID
) -> None:
    order = await get_order_or_raise(db, org_id, order_id)
    if order.status != "pending":
        raise ConflictError("Only pending orders can be deleted")
    await db.delete(order)
    await db.commit()


async def require_order_for_processing(
    db: AsyncSession, org_id: uuid.UUID, order_id: uuid.UUID
) -> TAOrder:
    order = await get_order_or_raise(db, org_id, order_id)
    if order.status == "processing":
        raise ConflictError("Order is already being processed")
    if order.status not in ("pending", "failed"):
        raise ConflictError(f"Order cannot be processed in status: {order.status}")
    return order
