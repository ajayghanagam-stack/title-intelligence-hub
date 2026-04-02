import uuid
from datetime import datetime

from pydantic import BaseModel, computed_field


SECTION_TYPE_LABELS: dict[str, str] = {
    "schedule_a": "Schedule A",
    "schedule_b": "Schedule B",
    "schedule_b1": "Schedule B-1",
    "schedule_b2": "Schedule B-2",
    "schedule_c": "Schedule C",
    "schedule_d": "Schedule D",
    "cover": "Cover Page",
    "legal_description": "Legal Description",
    "endorsements": "Endorsements",
    "other": "Other",
}


class SectionResponse(BaseModel):
    id: uuid.UUID
    pack_id: uuid.UUID
    section_type: str
    start_page: int
    end_page: int
    confidence: float
    created_at: datetime

    @computed_field
    @property
    def title(self) -> str:
        return SECTION_TYPE_LABELS.get(self.section_type, self.section_type)

    model_config = {"from_attributes": True}
