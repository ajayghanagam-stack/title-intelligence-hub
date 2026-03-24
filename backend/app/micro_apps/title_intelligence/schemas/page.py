import uuid
from datetime import datetime

from pydantic import BaseModel


class PageResponse(BaseModel):
    id: uuid.UUID
    pack_id: uuid.UUID
    file_id: uuid.UUID
    page_number: int
    image_uri: str
    thumb_uri: str
    ocr_uri: str | None = None
    ocr_text: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
