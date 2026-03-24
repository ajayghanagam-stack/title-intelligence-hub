import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ChatSend(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000)


class CitationRef(BaseModel):
    page_number: int
    text_snippet: str


class ChatMessageResponse(BaseModel):
    id: uuid.UUID
    pack_id: uuid.UUID
    role: str
    content: str
    citations: list[CitationRef] | None = None
    user_id: uuid.UUID | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
