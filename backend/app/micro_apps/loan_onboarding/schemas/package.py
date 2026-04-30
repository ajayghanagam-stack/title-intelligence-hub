"""Package CRUD schemas and pipeline status."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.micro_apps.loan_onboarding.schemas.compliance import LoanContextIn


class DocTypeSpec(BaseModel):
    """One entry in the per-package list of expected document types."""
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=200)
    required: bool = False
    # Optional structured hint for the classifier ("W-2", "Form 1040", etc.)
    description: str | None = None


RuleSource = Literal["preset", "custom"]


class ValidationRuleSpec(BaseModel):
    """One rule attached to the package.

    For preset rules, `rule_id` is a known key (e.g. "missing_signatures") and
    `config` carries scope parameters. For custom rules, `rule_id` is a slug
    generated client-side and `description` holds the natural-language text.
    """
    model_config = ConfigDict(extra="forbid")
    rule_source: RuleSource
    rule_id: str = Field(min_length=1, max_length=100)
    description: str | None = None
    config: dict = Field(default_factory=dict)
    doc_type: str | None = None
    enabled: bool = True


class PackageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    borrower_name: str | None = None
    loan_reference: str | None = None
    hitl_threshold: float = Field(default=0.96, ge=0.0, le=1.0)
    doc_types: list[DocTypeSpec] = Field(min_length=1)
    validation_rules: list[ValidationRuleSpec] = Field(default_factory=list)
    # Field extraction config (Section D in the new-package form). Independent
    # of validation. When `extraction_enabled` is True the extraction stage
    # pulls the listed field labels out of each stack and emits a downloadable
    # feed (JSON / CSV / MISMO XML). The map is keyed by doc_type key.
    extraction_enabled: bool = True
    extraction_fields_by_doc: dict[str, list[str]] = Field(default_factory=dict)
    # Optional loan context — drives the persona-aware compliance engine.
    # When present, the backend persists it on `LOPackage.loan_context` so the
    # compliance report can render correct program/state/scenario context.
    loan_context: LoanContextIn | None = None


class PackageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    org_id: uuid.UUID
    created_by: uuid.UUID
    name: str
    borrower_name: str | None
    loan_reference: str | None
    hitl_threshold: float
    doc_types: list[DocTypeSpec] = Field(default_factory=list)
    status: str
    pipeline_stage: str | None
    pipeline_error: str | None
    progress: dict | None
    hitl_count: int = 0
    extraction_enabled: bool = True
    extraction_fields_by_doc: dict[str, list[str]] = Field(default_factory=dict)
    loan_context: LoanContextIn | None = None
    created_at: datetime
    updated_at: datetime


class PackageListResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    name: str
    borrower_name: str | None
    loan_reference: str | None
    status: str
    pipeline_stage: str | None
    created_at: datetime
    updated_at: datetime


class ProgressSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    stage: str
    processed: int
    total: int
    hitl_count: int = 0


class PipelineStageStatus(BaseModel):
    stage: str
    status: Literal["pending", "running", "completed", "failed"]


class PipelineStageTiming(BaseModel):
    stage: str
    elapsed_seconds: float | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


class PipelineStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    package_id: uuid.UUID
    status: str
    pipeline_stage: str | None
    pipeline_error: str | None
    progress: dict | None
    stages: list[PipelineStageStatus] = Field(default_factory=list)
    stage_timings: list[PipelineStageTiming] = Field(default_factory=list)
    processed: int = 0
    total: int = 0
    hitl_count: int = 0


class PackageFileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    package_id: uuid.UUID
    filename: str
    size_bytes: int
    page_count: int
    content_hash: str | None
    created_at: datetime
