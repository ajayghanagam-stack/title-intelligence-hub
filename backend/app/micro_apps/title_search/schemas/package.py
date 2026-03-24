import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.micro_apps.title_search.schemas.order import SearchScope

# Closed-set type for package status
PackageStatus = Literal["draft", "issued", "superseded"]


class PackageResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    package_number: str
    status: PackageStatus
    search_scope: SearchScope | None = None
    years_covered: int | None = None
    total_documents: int | None = None
    chain_complete: bool
    open_flags_count: int | None = None
    property_summary: dict | None = None
    storage_path_pdf: str | None = None
    storage_path_json: str | None = None
    issued_by: str | None = None
    issued_at: datetime | None = None
    issuer_id: uuid.UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
