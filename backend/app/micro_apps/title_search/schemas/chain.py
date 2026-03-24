import uuid
from typing import Literal

from pydantic import BaseModel

# Closed-set types for chain link classification
LinkType = Literal["conveyance", "encumbrance", "release", "gap"]


class ChainLinkResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    document_id: uuid.UUID | None = None
    position: int
    link_type: LinkType
    from_party: dict | None = None
    to_party: dict | None = None
    effective_date: str | None = None
    is_gap: bool
    gap_description: str | None = None

    model_config = {"from_attributes": True}


class ChainResponse(BaseModel):
    order_id: uuid.UUID
    chain_links: list[ChainLinkResponse]
    chain_complete: bool
    total_links: int
    gap_count: int
