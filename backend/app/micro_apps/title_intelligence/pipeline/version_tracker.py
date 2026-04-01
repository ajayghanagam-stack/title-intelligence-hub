"""Version tracking helpers for pipeline runs.

Computes hashes and collects version metadata at pipeline start to enable
auditability and reproducibility of pipeline results.
"""

import hashlib
import json
import logging
from typing import Any

from app.config import Settings

logger = logging.getLogger(__name__)


def hash_string(s: str) -> str:
    """Return the SHA-256 hex digest of a string."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


async def compute_input_file_hash(storage, org_id, pack_files) -> str:
    """Compute SHA-256 hash of all pack file contents.

    Uses pre-computed content_hash from PackFile when available (set at upload
    time), falling back to reading file contents only for legacy records.

    Args:
        storage: StorageProvider instance
        org_id: Organization UUID
        pack_files: List of PackFile model instances
    """
    h = hashlib.sha256()
    for pf in sorted(pack_files, key=lambda f: f.filename):
        if getattr(pf, "content_hash", None):
            # Use pre-computed hash — avoids re-reading file from storage
            h.update(pf.content_hash.encode("utf-8"))
        else:
            try:
                data = await storage.read(pf.storage_path)
                h.update(data)
            except Exception as e:
                logger.warning(f"Could not read file {pf.storage_path} for hashing: {e}")
    return h.hexdigest()


def compute_ingestion_output_hash(sections_dicts: list[dict], extractions_dicts: list[dict]) -> str:
    """Order-independent hash of ingestion output (sections + extractions).

    Used as input to the summary cache key so changed extractions invalidate the summary cache.
    """
    # Sort by deterministic keys to ensure order independence
    sorted_sections = sorted(sections_dicts, key=lambda s: json.dumps(s, sort_keys=True))
    sorted_extractions = sorted(extractions_dicts, key=lambda e: json.dumps(e, sort_keys=True))
    combined = json.dumps({"sections": sorted_sections, "extractions": sorted_extractions}, sort_keys=True)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def compute_summary_cache_key(
    ingestion_output_hash: str, risk_output_hash: str, version_info: dict[str, Any]
) -> str:
    """Composite cache key for the finalization summary.

    Depends on extractions, flags (via their hashes), and model/prompt.
    The ReportAgent.generate_summary prompt is stable so we hash it at key-build time.
    """
    from app.micro_apps.title_intelligence.ai.report_agent import ReportAgent
    parts = (
        ingestion_output_hash
        + risk_output_hash
        + version_info["ai_model"]
        + hash_string(ReportAgent.SYSTEM_PROMPT if hasattr(ReportAgent, "SYSTEM_PROMPT") else "")
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def compute_examiner_cache_key(input_file_hash: str, version_info: dict[str, Any]) -> str:
    """Composite cache key for the examiner agent output.

    Combines file content hash with model, prompt, tool schema, rules version,
    deterministic engine versions, and triage prompt hash so any change produces
    a cache miss.
    """
    parts = (
        input_file_hash
        + version_info["ai_model"]
        + version_info["ingestion_prompt_hash"]
        + version_info["extraction_tool_hash"]
        + version_info["rules_version"]
        + version_info.get("triage_prompt_hash", "")
        + version_info.get("extraction_registry_hash", "")
        + version_info.get("flag_rules_version", "")
        + version_info.get("chain_builder_version", "")
        + version_info.get("normalizer_version", "")
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def collect_version_info(settings: Settings) -> dict[str, Any]:
    """Gather version metadata for a pipeline run.

    Returns a dict with keys matching PipelineRun columns.
    Dynamically resolves AI platform and model from the AI_PROVIDER setting.
    """
    from app.ai.base_service import _get_model_for_provider
    from app.micro_apps.title_intelligence.ai.title_examiner_agent import (
        TitleExaminerAgent,
    )

    provider = getattr(settings, "AI_PROVIDER", "gemini")
    platform = "anthropic" if provider == "claude" else "gemini"
    model = _get_model_for_provider(provider)
    pipeline_mode = getattr(settings, "PIPELINE_MODE", "legacy")
    triage_enabled = getattr(settings, "TRIAGE_ENABLED", True)
    grouping_enabled = getattr(settings, "GROUPING_ENABLED", True)
    specialized_extraction = getattr(settings, "SPECIALIZED_EXTRACTION_ENABLED", True)

    # Determine OCR engine based on provider and pipeline mode
    if provider == "claude":
        ocr_engine = "claude_vision"
    elif pipeline_mode == "native_pdf":
        ocr_engine = "gemini_native_pdf"
    else:
        ocr_engine = "gemini_vision"

    prompt_hash = hash_string(TitleExaminerAgent.SYSTEM_PROMPT)
    tool_hash = hash_string(
        json.dumps(TitleExaminerAgent.TOOL_SCHEMA, sort_keys=True)
    )

    # Include triage prompt hash when triage is enabled
    triage_prompt_hash = ""
    if triage_enabled and pipeline_mode == "native_pdf":
        from app.micro_apps.title_intelligence.ai.triage_agent import TriageAgent
        triage_prompt_hash = hash_string(TriageAgent.SYSTEM_PROMPT)

    # Include extraction registry hash when specialized extraction is enabled
    extraction_registry_hash = ""
    if specialized_extraction and pipeline_mode == "native_pdf":
        from app.micro_apps.title_intelligence.ai.extractors.registry import compute_registry_hash
        extraction_registry_hash = compute_registry_hash()

    # Deterministic rules engine versions
    from app.micro_apps.title_intelligence.services.flag_rules import RULES_VERSION
    from app.micro_apps.title_intelligence.services.chain_builder import CHAIN_BUILDER_VERSION
    from app.micro_apps.title_intelligence.services.party_normalizer import NORMALIZER_VERSION

    return {
        # PipelineRun model columns
        "ai_platform": platform,
        "ai_model": model,
        "ingestion_prompt_hash": prompt_hash,
        "risk_prompt_hash": prompt_hash,
        "extraction_tool_hash": tool_hash,
        "risk_tool_hash": tool_hash,
        "ocr_engine": ocr_engine,
        "chunker_version": "hierarchical_v1",
        "rules_version": "weighted_5cat_v2",
        "pipeline_backend": settings.PIPELINE_BACKEND,
        # Extended hashes stored in version_metadata JSONB (no dedicated columns)
        "triage_prompt_hash": triage_prompt_hash,
        "extraction_registry_hash": extraction_registry_hash,
        "flag_rules_version": RULES_VERSION,
        "chain_builder_version": CHAIN_BUILDER_VERSION,
        "normalizer_version": NORMALIZER_VERSION,
        "version_metadata": {
            "ai_platform": platform,
            "ai_model": model,
            "pipeline_mode": pipeline_mode,
            "triage_enabled": triage_enabled,
            "grouping_enabled": grouping_enabled,
            "specialized_extraction": specialized_extraction,
            "triage_prompt_hash": triage_prompt_hash,
            "extraction_registry_hash": extraction_registry_hash,
            "flag_rules_version": RULES_VERSION,
            "chain_builder_version": CHAIN_BUILDER_VERSION,
            "normalizer_version": NORMALIZER_VERSION,
        },
    }
