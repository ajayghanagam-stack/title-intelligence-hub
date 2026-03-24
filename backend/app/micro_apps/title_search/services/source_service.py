import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_search.models.county_source import TACountySource
from app.micro_apps.title_search.models.source_assignment import TASourceAssignment
from app.core.exceptions import NotFoundError, ConflictError


# ── County Source CRUD (platform admin) ──

async def create_county_source(
    db: AsyncSession,
    county: str,
    state_code: str,
    source_type: str,
    availability: str = "digital",
    portal_url: str | None = None,
    portal_type: str | None = None,
    search_config: dict | None = None,
    is_active: bool = True,
) -> TACountySource:
    # Check unique constraint
    result = await db.execute(
        select(TACountySource).where(
            TACountySource.county == county,
            TACountySource.state_code == state_code,
            TACountySource.source_type == source_type,
        )
    )
    if result.scalar_one_or_none():
        raise ConflictError(
            f"County source already exists: {county}, {state_code}, {source_type}"
        )

    source = TACountySource(
        county=county,
        state_code=state_code,
        source_type=source_type,
        availability=availability,
        portal_url=portal_url,
        portal_type=portal_type,
        search_config=search_config,
        is_active=is_active,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


async def list_county_sources(
    db: AsyncSession,
    state_code: str | None = None,
    source_type: str | None = None,
    availability: str | None = None,
) -> list[TACountySource]:
    query = select(TACountySource)
    if state_code:
        query = query.where(TACountySource.state_code == state_code)
    if source_type:
        query = query.where(TACountySource.source_type == source_type)
    if availability:
        query = query.where(TACountySource.availability == availability)
    query = query.order_by(TACountySource.state_code, TACountySource.county)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_county_source_or_raise(
    db: AsyncSession, source_id: uuid.UUID
) -> TACountySource:
    result = await db.execute(
        select(TACountySource).where(TACountySource.id == source_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        raise NotFoundError("CountySource", source_id)
    return source


async def update_county_source(
    db: AsyncSession, source_id: uuid.UUID, **updates
) -> TACountySource:
    source = await get_county_source_or_raise(db, source_id)
    for key, value in updates.items():
        if value is not None:
            setattr(source, key, value)
    await db.commit()
    await db.refresh(source)
    return source


# ── Source Assignment Management ──

async def get_source_assignment_or_raise(
    db: AsyncSession,
    org_id: uuid.UUID,
    order_id: uuid.UUID,
    source_id: uuid.UUID,
) -> TASourceAssignment:
    """Get a source assignment by ID, scoped to org and order."""
    result = await db.execute(
        select(TASourceAssignment).where(
            TASourceAssignment.id == source_id,
            TASourceAssignment.order_id == order_id,
            TASourceAssignment.org_id == org_id,
        )
    )
    source = result.scalar_one_or_none()
    if not source:
        raise NotFoundError("SourceAssignment", source_id)
    return source

async def get_source_assignments(
    db: AsyncSession, org_id: uuid.UUID, order_id: uuid.UUID
) -> list[TASourceAssignment]:
    result = await db.execute(
        select(TASourceAssignment).where(
            TASourceAssignment.order_id == order_id,
            TASourceAssignment.org_id == org_id,
        )
    )
    return list(result.scalars().all())


async def resolve_sources(
    db: AsyncSession, org_id: uuid.UUID, order_id: uuid.UUID,
    county: str, state_code: str,
) -> list[TASourceAssignment]:
    """Find matching county sources and create source assignments for an order."""
    result = await db.execute(
        select(TACountySource).where(
            TACountySource.county == county,
            TACountySource.state_code == state_code,
            TACountySource.is_active == True,
        )
    )
    county_sources = list(result.scalars().all())

    assignments = []
    for cs in county_sources:
        assignment = TASourceAssignment(
            org_id=org_id,
            order_id=order_id,
            source_type=cs.source_type,
            availability=cs.availability,
            portal_config_id=cs.id,
            status="pending",
        )
        db.add(assignment)
        assignments.append(assignment)

    # If no county sources found, create a default digital mock assignment
    # so the pipeline can proceed with mock retrieval in MVP mode.
    if not county_sources:
        assignment = TASourceAssignment(
            org_id=org_id,
            order_id=order_id,
            source_type="recorder",
            availability="digital",
            status="pending",
        )
        db.add(assignment)
        assignments.append(assignment)

    await db.commit()
    return assignments
