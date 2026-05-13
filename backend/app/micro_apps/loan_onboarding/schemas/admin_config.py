"""Pydantic schemas for the Phase 2 org-admin config CRUD surface.

Drives the four resolver-feeding tables:
  - ``lo_doc_type_catalog``    → ``DocTypeCatalog{Create,Update,Response}``
  - ``lo_extraction_schemas``  → ``ExtractionSchema{Create,Update,Response}``
  - ``lo_validation_rules_org``→ ``OrgValidationRule{Create,Update,Response}``
  - ``lo_program_profiles``    → ``ProgramProfile{Create,Update,Response}``

The shape mirrors the SQLAlchemy models 1:1 — we expose the same JSONB
blobs to the admin UI verbatim and let the tighten-only validators
police them at write time.
"""
from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ── Doc-type catalog ──────────────────────────────────────────────────


class DocTypeCatalogCreate(BaseModel):
    key: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=255)
    category: str = Field("other", max_length=50)
    auto_classify_enabled: bool = True
    expected_min_pages: int | None = None
    expected_max_pages: int | None = None

    @field_validator("key", mode="before")
    @classmethod
    def _canonicalize_key(cls, v: object) -> object:
        # Catalog keys are the canonical identifier — store lower-snake-case
        # so the resolver, classifier enum, and per-loan overlay always
        # compare against the same form. Admin UI imports occasionally send
        # UPPER_SNAKE — normalize once at the boundary.
        return v.strip().lower() if isinstance(v, str) else v


class DocTypeCatalogUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    category: str | None = Field(None, max_length=50)
    auto_classify_enabled: bool | None = None
    expected_min_pages: int | None = None
    expected_max_pages: int | None = None
    active: bool | None = None


class DocTypeCatalogResponse(BaseModel):
    id: UUID
    key: str
    name: str
    category: str
    auto_classify_enabled: bool
    expected_min_pages: int | None
    expected_max_pages: int | None
    active: bool
    # Live counter — number of LOStack rows (across all packages) whose
    # ``doc_type`` matches this catalog key. Populated by the list
    # endpoint; zero on the bare model.
    documents_processed: int = 0

    model_config = ConfigDict(from_attributes=True)


# ── Extraction schema ─────────────────────────────────────────────────


class ExtractionSchemaCreate(BaseModel):
    doc_type_id: UUID
    fields: list[dict[str, Any]] = Field(default_factory=list)


class ExtractionSchemaUpdate(BaseModel):
    fields: list[dict[str, Any]] | None = None
    active: bool | None = None


class ExtractionSchemaResponse(BaseModel):
    id: UUID
    doc_type_id: UUID
    fields: list[dict[str, Any]]
    version: int
    active: bool

    model_config = ConfigDict(from_attributes=True)


# ── Org validation rules ──────────────────────────────────────────────


class OrgValidationRuleCreate(BaseModel):
    scope: str = Field(..., max_length=50)
    rule: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    applies_to: str = Field("", max_length=255)
    condition: str = ""
    preset_id: str | None = Field(None, max_length=100)
    severity: Literal["hard", "soft"] = "hard"


class OrgValidationRuleUpdate(BaseModel):
    rule: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    applies_to: str | None = Field(None, max_length=255)
    condition: str | None = None
    preset_id: str | None = Field(None, max_length=100)
    severity: Literal["hard", "soft"] | None = None
    active: bool | None = None


class OrgValidationRuleResponse(BaseModel):
    id: UUID
    scope: str
    rule: str
    description: str
    applies_to: str
    condition: str
    preset_id: str | None
    severity: str
    active: bool

    model_config = ConfigDict(from_attributes=True)


# ── Program profiles ──────────────────────────────────────────────────


class ProgramProfileCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: Literal["loan_program", "investor_overlay"]
    stacks_with: UUID | None = None
    checklist: list[dict[str, Any]] = Field(default_factory=list)
    extraction_overrides: dict[str, Any] = Field(default_factory=dict)
    rule_overrides: list[dict[str, Any]] = Field(default_factory=list)


class ProgramProfileUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    stacks_with: UUID | None = None
    checklist: list[dict[str, Any]] | None = None
    extraction_overrides: dict[str, Any] | None = None
    rule_overrides: list[dict[str, Any]] | None = None
    active: bool | None = None


class ProgramProfileResponse(BaseModel):
    id: UUID
    name: str
    type: str
    stacks_with: UUID | None
    checklist: list[dict[str, Any]]
    extraction_overrides: dict[str, Any]
    rule_overrides: list[dict[str, Any]]
    active: bool

    model_config = ConfigDict(from_attributes=True)
