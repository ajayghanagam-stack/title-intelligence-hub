"""Reviewer-authored page override schemas."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


PageRoleOverride = Literal[
    "first_page", "continuation", "last_page", "signature_page"
]


class PageOverrideRequest(BaseModel):
    """Body for `POST /packages/{pid}/pages/{page_id}/override`.

    `assigned_doc_type` must be either one of the package's configured doc-type
    keys or the reserved "Others" bucket. A no-op move (target == current
    effective doc_type) is rejected with 400.
    """
    model_config = ConfigDict(extra="forbid")
    assigned_doc_type: str = Field(..., max_length=100)
    page_role_override: PageRoleOverride | None = None
    note: str | None = Field(default=None, max_length=2000)


class PageOverrideResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    package_id: uuid.UUID
    page_id: uuid.UUID
    assigned_doc_type: str
    previous_doc_type: str
    page_role_override: str | None
    reviewer_id: uuid.UUID | None
    note: str | None
    created_at: datetime
    updated_at: datetime


class RebuildSummary(BaseModel):
    """Returned by override + remove endpoints after re-stack/re-validate.

    Gives the UI immediate feedback about the blast radius of the move —
    how many stacks and HITL flags changed — without a second fetch.
    """
    model_config = ConfigDict(extra="forbid")
    stacks: int
    hitl_stacks: int
    pages: int
    preset_rules: int
    custom_rules: int


class PageOverrideWithRebuild(BaseModel):
    model_config = ConfigDict(extra="forbid")
    override: PageOverrideResponse | None
    rebuild: RebuildSummary
