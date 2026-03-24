import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_search.models.chain_link import TAChainLink
from app.micro_apps.title_search.schemas.chain import ChainResponse, ChainLinkResponse


async def get_chain(
    db: AsyncSession, org_id: uuid.UUID, order_id: uuid.UUID
) -> ChainResponse:
    result = await db.execute(
        select(TAChainLink).where(
            TAChainLink.order_id == order_id,
            TAChainLink.org_id == org_id,
        ).order_by(TAChainLink.position)
    )
    links = list(result.scalars().all())

    gap_count = sum(1 for l in links if l.is_gap)
    chain_complete = len(links) > 0 and gap_count == 0

    return ChainResponse(
        order_id=order_id,
        chain_links=[ChainLinkResponse.model_validate(l) for l in links],
        chain_complete=chain_complete,
        total_links=len(links),
        gap_count=gap_count,
    )
