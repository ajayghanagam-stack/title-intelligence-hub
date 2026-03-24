import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel


class EvidenceRef(BaseModel):
    page_number: int
    text_snippet: str


class ExtractionResponse(BaseModel):
    id: uuid.UUID
    pack_id: uuid.UUID
    extraction_type: str
    label: str
    value: dict[str, Any]
    evidence_refs: list[EvidenceRef] = []
    section_id: uuid.UUID | None = None
    confidence: float
    created_at: datetime

    model_config = {"from_attributes": True}
