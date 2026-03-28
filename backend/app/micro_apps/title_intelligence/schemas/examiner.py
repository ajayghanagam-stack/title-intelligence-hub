"""Pydantic schemas for the TitleExaminerAgent single-pass pipeline."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PageTranscription(BaseModel):
    """Transcription of a single page from Claude Vision."""

    page_number: int
    text: str


class ExaminerSection(BaseModel):
    """A detected document section."""

    section_type: str = Field(
        ...,
        description="One of: schedule_a, schedule_b1, schedule_b2, schedule_c, legal_description, endorsements",
    )
    start_page: int
    end_page: int
    confidence: float = 0.0


class ExaminerExtraction(BaseModel):
    """A structured data extraction."""

    extraction_type: str = Field(
        ...,
        description="One of: party, property, requirement, exception, endorsement, policy_info, compliance, chain_of_title",
    )
    label: str
    value: dict[str, Any]
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float = 0.0


class ExaminerFlag(BaseModel):
    """A risk flag detected during examination."""

    flag_type: str = Field(
        ...,
        description=(
            "One of: missing_endorsement, unacceptable_exception, unresolved_lien, "
            "unreleased_mortgage, cross_section_mismatch, requirement_missing_proof, "
            "name_discrepancy, marital_status_issue, incomplete_document, "
            "regulatory_compliance, chain_of_title_gap, document_defect, "
            "mineral_rights, trust_issue, estate_issue, vesting_issue, tax_issue"
        ),
    )
    severity: str = Field(
        ...,
        description="One of: critical, high, medium, low",
    )
    title: str
    description: str
    ai_explanation: str
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)


class ExaminerBatchResult(BaseModel):
    """Result from a single batch of pages."""

    page_transcriptions: list[PageTranscription] = Field(default_factory=list)
    sections: list[ExaminerSection] = Field(default_factory=list)
    extractions: list[ExaminerExtraction] = Field(default_factory=list)
    flags: list[ExaminerFlag] = Field(default_factory=list)
    # Instrumentation (populated after LLM call)
    llm_elapsed_seconds: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class ExaminerConsolidatedResult(BaseModel):
    """Consolidated result from all batches."""

    page_transcriptions: list[PageTranscription] = Field(default_factory=list)
    sections: list[ExaminerSection] = Field(default_factory=list)
    extractions: list[ExaminerExtraction] = Field(default_factory=list)
    flags: list[ExaminerFlag] = Field(default_factory=list)
    # Rate limit metrics (populated by RateLimitController)
    rate_limit_hits: int = 0
    total_retries: int = 0
