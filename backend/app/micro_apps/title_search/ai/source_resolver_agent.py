import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_search.models.county_source import TACountySource
from app.micro_apps.title_search.models.source_assignment import TASourceAssignment


async def resolve_sources_for_order(
    db: AsyncSession,
    org_id: uuid.UUID,
    order_id: uuid.UUID,
    county: str,
    state_code: str,
) -> list[TASourceAssignment]:
    """Resolve county sources and create assignments.

    For MVP, this uses direct DB lookup. In production, this would use an AI agent
    to classify source availability based on county/state.
    """
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

    if not county_sources:
        # No county sources configured — create a digital mock assignment
        # so the pipeline can proceed with mock retrieval in MVP mode.
        # In production, this would default to non_digital and pause for
        # a ground abstractor, but only when real county portals are wired in.
        assignment = TASourceAssignment(
            org_id=org_id,
            order_id=order_id,
            source_type="recorder",
            availability="digital",
            status="pending",
        )
        db.add(assignment)
        assignments.append(assignment)

    await db.flush()
    return assignments
