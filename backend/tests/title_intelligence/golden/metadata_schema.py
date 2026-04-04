"""Pydantic schema for golden dataset metadata.json files.

Each golden dataset records the exact model, prompt, rules, and config
versions used to generate it. This enables version-drift detection:
if code changes but the golden set hasn't been regenerated, tests fail.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class GoldenMetadata(BaseModel):
    """Metadata for a golden dataset, stored in metadata.json."""

    # Dataset identity
    name: str = Field(description="Human-readable dataset name")
    description: str = Field(description="What this dataset tests")
    created_at: datetime = Field(description="When the golden set was generated")

    # PDF info
    pdf_filename: str = Field(description="Original PDF filename")
    total_pages: int = Field(description="Total page count")
    pdf_sha256: str = Field(description="SHA-256 hash of the input PDF")

    # AI config used during generation
    ai_provider: str = Field(description="AI_PROVIDER setting (gemini/claude/hybrid)")
    ai_model: str = Field(description="Full model identifier")
    pipeline_mode: str = Field(description="PIPELINE_MODE (native_pdf/legacy)")

    # Version hashes — must match current code or golden set is stale
    ingestion_prompt_hash: str = Field(description="SHA-256 of examiner system prompt")
    extraction_tool_hash: str = Field(description="SHA-256 of examiner tool schema")
    flag_rules_version: str = Field(description="RULES_VERSION from flag_rules.py")
    chain_builder_version: str = Field(description="CHAIN_BUILDER_VERSION")
    normalizer_version: str = Field(description="NORMALIZER_VERSION from party_normalizer.py")
    triage_prompt_hash: str = Field(default="", description="SHA-256 of triage prompt (if triage enabled)")
    extraction_registry_hash: str = Field(default="", description="SHA-256 of extraction registry")

    # Config snapshot
    triage_enabled: bool = Field(default=True)
    grouping_enabled: bool = Field(default=True)
    specialized_extraction: bool = Field(default=True)

    # Generation stats
    total_elapsed_seconds: float = Field(default=0.0, description="Pipeline wall time")
    total_input_tokens: int = Field(default=0, description="Total input tokens consumed")
    total_output_tokens: int = Field(default=0, description="Total output tokens consumed")

    # Arbitrary extra data
    extra: dict[str, Any] = Field(default_factory=dict)
