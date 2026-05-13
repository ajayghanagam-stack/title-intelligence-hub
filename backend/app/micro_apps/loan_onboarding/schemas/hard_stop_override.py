"""Pydantic schemas for the Phase 3.4 hard-stop override surface.

Mirror of ``models/hard_stop_override.py``. The ``reason`` enum is the
closed list the admin UI dropdown sources from. ``supervisor_id`` is
*not* in the create body — the route takes it from the authenticated
user, so the operator can't spoof another supervisor's identity.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.micro_apps.loan_onboarding.models.hard_stop_override import OVERRIDE_REASONS


# Pydantic Literal mirrors the model's closed enum so a future addition
# only needs to be made in one place (the model) and the schema picks it
# up via type alias.
OverrideReason = Literal[OVERRIDE_REASONS]  # type: ignore[valid-type]


class HardStopOverrideCreate(BaseModel):
    reason: Literal[
        "business_exception",
        "late_delivery",
        "duplicate_elsewhere",
        "investor_waived",
        "other",
    ]
    note: str | None = Field(None, max_length=2000)


class HardStopOverrideResponse(BaseModel):
    id: UUID
    package_id: UUID
    hard_stop_key: str
    supervisor_id: UUID
    reason: str
    note: str | None
    decision: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
