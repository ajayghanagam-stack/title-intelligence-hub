import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel

# Closed-set types for document classification
DocType = Literal[
    "deed", "mortgage", "lien", "judgment", "easement",
    "hoa", "satisfaction", "release", "assignment", "other",
]
ContentFormat = Literal["text", "pdf", "image", "html"]

DOC_TYPE_LABELS: dict[str, str] = {
    "deed": "Deed",
    "mortgage": "Mortgage",
    "lien": "Lien",
    "judgment": "Judgment",
    "easement": "Easement",
    "hoa": "HOA",
    "satisfaction": "Satisfaction",
    "release": "Release",
    "assignment": "Assignment",
    "other": "Other",
}


class RawDocumentResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    source_assignment_id: uuid.UUID | None = None
    source_url: str | None = None
    document_ref: str | None = None
    content_format: ContentFormat
    storage_path: str | None = None
    fetched_at: datetime

    model_config = {"from_attributes": True}


class DocumentResponse(BaseModel):
    id: uuid.UUID
    order_id: uuid.UUID
    raw_document_id: uuid.UUID | None = None
    doc_type: DocType
    recording_date: str | None = None
    recording_ref: str | None = None
    legal_description: str | None = None
    consideration: float | None = None
    grantor: dict | None = None
    grantee: dict | None = None
    summary: str | None = None
    confidence: float | None = None
    needs_review: bool
    doc_metadata: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentUpdate(BaseModel):
    doc_type: DocType | None = None
    recording_date: str | None = None
    recording_ref: str | None = None
    legal_description: str | None = None
    consideration: float | None = None
    grantor: dict | None = None
    grantee: dict | None = None
    summary: str | None = None
