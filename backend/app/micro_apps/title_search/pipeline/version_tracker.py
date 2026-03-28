"""Version tracking helpers for TSA pipeline runs.

Computes hashes and collects version metadata at pipeline start to enable
auditability and reproducibility of pipeline results.
"""

import hashlib
import json
import logging
from typing import Any

from app.config import Settings
from app.micro_apps.title_search.services.flag_rules import RULES_VERSION

logger = logging.getLogger(__name__)


def hash_string(s: str) -> str:
    """Return the SHA-256 hex digest of a string."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


async def compute_input_file_hash(storage, org_id, raw_documents) -> str:
    """Compute SHA-256 hash of all raw document contents for an order.

    Args:
        storage: StorageProvider instance
        org_id: Organization UUID
        raw_documents: List of TARawDocument model instances
    """
    h = hashlib.sha256()
    for rd in sorted(raw_documents, key=lambda r: str(r.id)):
        if rd.raw_content:
            h.update(rd.raw_content.encode("utf-8"))
        elif rd.storage_path:
            try:
                data = await storage.read(rd.storage_path)
                h.update(data)
            except Exception as e:
                logger.warning(f"Could not read file {rd.storage_path} for hashing: {e}")
    return h.hexdigest()


def compute_parse_cache_key(input_file_hash: str, version_info: dict[str, Any]) -> str:
    """Composite cache key for parser agent output.

    Combines raw document content hash with model, prompt, and tool schema hashes
    so any change to inputs or AI config produces a cache miss.
    """
    parts = (
        input_file_hash
        + version_info["ai_model"]
        + version_info["parser_prompt_hash"]
        + version_info["parser_tool_hash"]
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def compute_parse_output_hash(documents_dicts: list[dict]) -> str:
    """Order-independent hash of parsed document output.

    Used as input to the chain/anomaly cache key so changed extractions
    invalidate downstream caches.
    """
    sorted_docs = sorted(documents_dicts, key=lambda d: json.dumps(d, sort_keys=True))
    combined = json.dumps(sorted_docs, sort_keys=True)
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def compute_chain_cache_key(parse_output_hash: str, version_info: dict[str, Any]) -> str:
    """Composite cache key for chain builder + anomaly detector output.

    Combines parsed document hash with model, prompts, tools, and rules version.
    """
    parts = (
        parse_output_hash
        + version_info["ai_model"]
        + version_info["chain_prompt_hash"]
        + version_info["chain_tool_hash"]
        + version_info["anomaly_prompt_hash"]
        + version_info["anomaly_tool_hash"]
        + version_info["rules_version"]
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


_cached_version_info: dict[str, Any] | None = None
_cached_version_key: str | None = None


def collect_version_info(settings: Settings) -> dict[str, Any]:
    """Gather all component version metadata for a TSA pipeline run.

    Cached for process lifetime (invalidated only if platform/backend change).

    Returns a dict with keys matching TAPipelineRun columns.
    """
    global _cached_version_info, _cached_version_key

    cache_key = f"gemini:{settings.PIPELINE_BACKEND}"
    if _cached_version_info is not None and _cached_version_key == cache_key:
        return _cached_version_info

    from app.ai.base_service import MODEL
    from app.micro_apps.title_search.ai.document_parser_agent import (
        PARSER_SYSTEM_PROMPT, PARSER_TOOL,
    )
    from app.micro_apps.title_search.ai.chain_analysis_agent import (
        CHAIN_ANALYSIS_SYSTEM_PROMPT, CHAIN_ANALYSIS_JSON_SCHEMA,
    )

    platform = "gemini"
    model = MODEL

    # chain_prompt_hash and anomaly_prompt_hash both reference the combined
    # prompt for backward compat with TAPipelineRun columns.
    combined_prompt_hash = hash_string(CHAIN_ANALYSIS_SYSTEM_PROMPT)
    combined_schema_hash = hash_string(json.dumps(CHAIN_ANALYSIS_JSON_SCHEMA, sort_keys=True))

    _cached_version_info = {
        "ai_platform": platform,
        "ai_model": model,
        "parser_prompt_hash": hash_string(PARSER_SYSTEM_PROMPT),
        "chain_prompt_hash": combined_prompt_hash,
        "anomaly_prompt_hash": combined_prompt_hash,
        "parser_tool_hash": hash_string(json.dumps(PARSER_TOOL, sort_keys=True)),
        "chain_tool_hash": combined_schema_hash,
        "anomaly_tool_hash": combined_schema_hash,
        "rules_version": RULES_VERSION,
        "pipeline_backend": settings.PIPELINE_BACKEND,
        "version_metadata": {
            "ai_platform": platform,
            "ai_model": model,
            "rules_version": RULES_VERSION,
        },
    }
    _cached_version_key = cache_key
    return _cached_version_info
