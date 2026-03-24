"""Version tracking helpers for pipeline runs.

Computes hashes and collects version metadata at pipeline start to enable
auditability and reproducibility of pipeline results.
"""

import hashlib
import functools
import json
import logging
import subprocess
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


@functools.lru_cache(maxsize=1)
def _get_tesseract_version(tesseract_path: str | None = None) -> str:
    """Get Tesseract version string. Cached for process lifetime."""
    tesseract_cmd = tesseract_path or "tesseract"
    try:
        result = subprocess.run(
            [tesseract_cmd, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        # Tesseract outputs version to stderr
        output = result.stderr or result.stdout
        first_line = output.strip().split("\n")[0] if output else "unknown"
        return first_line
    except Exception as e:
        logger.warning(f"Could not determine tesseract version: {e}")
        return "unknown"


def compute_ingestion_cache_key(input_file_hash: str, version_info: dict[str, Any]) -> str:
    """Composite cache key for ingestion agent output.

    Combines file content hash with model, prompt, and tool schema hashes
    so any change to inputs or AI config produces a cache miss.
    """
    parts = (
        input_file_hash
        + version_info["ai_model"]
        + version_info["ingestion_prompt_hash"]
        + version_info["extraction_tool_hash"]
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def compute_ingestion_output_hash(sections_dicts: list[dict], extractions_dicts: list[dict]) -> str:
    """Order-independent hash of ingestion output (sections + extractions).

    Used as input to the risk cache key so changed extractions invalidate risk cache.
    """
    # Sort by deterministic keys to ensure order independence
    sorted_sections = sorted(sections_dicts, key=lambda s: json.dumps(s, sort_keys=True))
    sorted_extractions = sorted(extractions_dicts, key=lambda e: json.dumps(e, sort_keys=True))
    combined = json.dumps({"sections": sorted_sections, "extractions": sorted_extractions}, sort_keys=True)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def compute_risk_cache_key(ingestion_output_hash: str, version_info: dict[str, Any]) -> str:
    """Composite cache key for risk agent output.

    Combines ingestion output hash with model, prompt, tool schema, and rules version.
    """
    parts = (
        ingestion_output_hash
        + version_info["ai_model"]
        + version_info["risk_prompt_hash"]
        + version_info["risk_tool_hash"]
        + version_info["rules_version"]
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def compute_summary_cache_key(
    ingestion_output_hash: str, risk_output_hash: str, readiness_score: int, version_info: dict[str, Any]
) -> str:
    """Composite cache key for the finalization summary.

    Depends on extractions, flags (via their hashes), readiness score, and model/prompt.
    The ReportAgent.generate_summary prompt is stable so we hash it at key-build time.
    """
    from app.micro_apps.title_intelligence.ai.report_agent import ReportAgent
    parts = (
        ingestion_output_hash
        + risk_output_hash
        + str(readiness_score)
        + version_info["ai_model"]
        + hash_string(ReportAgent.SYSTEM_PROMPT if hasattr(ReportAgent, "SYSTEM_PROMPT") else "")
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


_cached_version_info: dict[str, Any] | None = None
_cached_version_key: str | None = None


def collect_version_info(settings: Settings) -> dict[str, Any]:
    """Gather all component version metadata for a pipeline run.

    Cached for process lifetime (invalidated only if platform/backend change).

    Returns a dict with keys matching PipelineRun columns:
        ai_platform, ai_model, ingestion_prompt_hash, risk_prompt_hash,
        ocr_engine, chunker_version, rules_version, pipeline_backend,
        version_metadata
    """
    global _cached_version_info, _cached_version_key

    cache_key = f"{settings.AI_PLATFORM}:{settings.PIPELINE_BACKEND}:{settings.TESSERACT_PATH}"
    if _cached_version_info is not None and _cached_version_key == cache_key:
        return _cached_version_info

    from app.ai.base_service import PLATFORM_MODELS
    from app.micro_apps.title_intelligence.ai.ingestion_agent import IngestionAgent
    from app.micro_apps.title_intelligence.ai.risk_agent import RiskAgent
    from app.micro_apps.title_intelligence.ai.tools.database import (
        CREATE_SECTIONS_TOOL,
        CREATE_EXTRACTIONS_TOOL,
        CREATE_FLAGS_TOOL,
    )

    platform = settings.AI_PLATFORM
    model = PLATFORM_MODELS.get(platform, {}).get("default", "unknown")

    extraction_tool_hash = hash_string(
        json.dumps(CREATE_SECTIONS_TOOL, sort_keys=True)
        + json.dumps(CREATE_EXTRACTIONS_TOOL, sort_keys=True)
    )
    risk_tool_hash = hash_string(
        json.dumps(CREATE_FLAGS_TOOL, sort_keys=True)
    )

    _cached_version_info = {
        "ai_platform": platform,
        "ai_model": model,
        "ingestion_prompt_hash": hash_string(IngestionAgent.SYSTEM_PROMPT),
        "risk_prompt_hash": hash_string(RiskAgent.SYSTEM_PROMPT),
        "extraction_tool_hash": extraction_tool_hash,
        "risk_tool_hash": risk_tool_hash,
        "ocr_engine": _get_tesseract_version(settings.TESSERACT_PATH),
        "chunker_version": "hierarchical_v1",
        "rules_version": "weighted_5cat_v2",
        "pipeline_backend": settings.PIPELINE_BACKEND,
        "version_metadata": {
            "ai_platform": platform,
            "ai_model": model,
        },
    }
    _cached_version_key = cache_key
    return _cached_version_info
