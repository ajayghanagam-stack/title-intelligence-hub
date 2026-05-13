"""Pydantic schemas for the LO admin Global Settings surface.

One singleton row per org persisting the 8 tabs of the prototype's
``Global Settings`` page. Each tab maps to a JSONB column on
``lo_global_settings``; the JSONB blobs are structured per
``scripts/lo_prototype_data.build_default_global_settings`` and carry
both values and prototype-verbatim explanation text (labels +
descriptions) so the same data feeds both the admin UI and any AI
prompt context that needs to explain a setting.

PATCH is full-replacement per-section: clients send any subset of the
8 fields. Provided sections replace the column wholesale. Sub-shape is
intentionally flexible (``dict`` / ``list``) because the prototype mixes
heterogeneous controls (percent / range / select / toggle / readonly
badge / role list / integration list).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


# ── Composite response & update ─────────────────────────────────────────


class GlobalSettingsResponse(BaseModel):
    id: UUID
    ai_thresholds: dict[str, Any]
    stp_targets: dict[str, Any]
    exception_defaults: dict[str, Any]
    audit: dict[str, Any]
    roles: dict[str, Any]
    notifications: dict[str, Any]
    integrations: dict[str, Any]
    tenant: dict[str, Any]

    model_config = ConfigDict(from_attributes=True)


class GlobalSettingsUpdate(BaseModel):
    """PATCH payload — any subset of the 8 sections. Missing sections
    are left untouched; provided sections replace the column wholesale."""
    ai_thresholds: dict[str, Any] | None = None
    stp_targets: dict[str, Any] | None = None
    exception_defaults: dict[str, Any] | None = None
    audit: dict[str, Any] | None = None
    roles: dict[str, Any] | None = None
    notifications: dict[str, Any] | None = None
    integrations: dict[str, Any] | None = None
    tenant: dict[str, Any] | None = None
