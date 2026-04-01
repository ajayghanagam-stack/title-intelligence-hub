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
    city: str | None = None,
    zip_code: str | None = None,
    borrower_name: str | None = None,
    parcel_number: str | None = None,
    legal_description: str | None = None,
    search_scope: str = "full",
    search_years: int = 60,
    order_reference: str | None = None,
    effective_date=None,
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
        city=city,
        zip_code=zip_code,
        county=county,
        state_code=state_code,
        borrower_name=borrower_name,
        parcel_number=parcel_number,
        legal_description=legal_description,
        search_scope=search_scope,
        search_years=search_years,
        order_reference=order_reference,
        effective_date=effective_date,
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

    # Clean up storage artifacts (uploaded files, generated PDFs, and AI caches)
    try:
        from app.services.storage import get_storage
        from app.config import get_settings
        from app.micro_apps.title_search.pipeline.version_tracker import (
            collect_version_info,
            compute_research_cache_key,
        )
        storage = get_storage()

        # Delete order-scoped files (uploads, raw docs, generated PDFs)
        await storage.delete_dir(f"{org_id}/{order_id}")

        # Delete org-level AI caches for this order's research key
        # (keyed by address+county+state, lives at {org_id}/ai_cache/ta_*/...)
        settings = get_settings()
        version_info = collect_version_info(settings)
        research_key = compute_research_cache_key(
            order.property_address, order.county or "", order.state_code or "",
            version_info,
        )
        research_cache = storage.make_ai_cache_path(org_id, order_id, "ta_research", research_key)
        await storage.delete(research_cache)

        # Also wipe parse and chain caches for this order
        for stage in ("ta_parse", "ta_chain"):
            await storage.delete_dir(f"{org_id}/ai_cache/{stage}")
    except Exception:
        pass  # Storage cleanup is best-effort; DB deletion proceeds regardless

    # Delete child records explicitly (SQLite doesn't enforce ON DELETE CASCADE)
    from sqlalchemy import delete as sa_delete
    from app.micro_apps.title_search.models.review import TAReview
    from app.micro_apps.title_search.models.flag import TAFlag
    from app.micro_apps.title_search.models.chain_link import TAChainLink
    from app.micro_apps.title_search.models.package import TAPackage
    from app.micro_apps.title_search.models.document import TADocument
    from app.micro_apps.title_search.models.raw_document import TARawDocument
    from app.micro_apps.title_search.models.source_assignment import TASourceAssignment
    from app.micro_apps.title_search.models.pipeline_run import TAPipelineRun

    for model in (TAReview, TAFlag, TAChainLink, TAPackage, TADocument, TARawDocument, TASourceAssignment, TAPipelineRun):
        await db.execute(sa_delete(model).where(model.order_id == order_id))

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
