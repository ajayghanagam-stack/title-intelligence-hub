"""Version tracking + cache-key helpers for Loan Onboarding pipeline runs.

Mirrors `title_search/pipeline/version_tracker.py`. Purpose: make the pipeline
byte-deterministic on re-run by caching every LLM call keyed by a composite
hash of `(input content + model + prompt + schema + rules version)`. Any
change to the upstream inputs — package files, classifier model, validator
prompt, reasoner schema, deterministic rules version — produces a new hash
and therefore a cache miss. Nothing else is needed to invalidate caches.

The three LLM stages cached here:
- classify  → `PageClassifierAgent.classify_pdf_chunked`
- validate  → `StackValidatorAgent.validate_rule` (per stack × per custom rule)
- review    → `ReasoningAgent.reason`

Deterministic stages (ingest, stack, preset validation, confidence blend)
are already byte-stable by construction — see `test_determinism.py`.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from app.config import Settings
from app.micro_apps.loan_onboarding.services.confidence_scorer import (
    WEIGHT_CLASSIFICATION,
    WEIGHT_SPLIT,
    WEIGHT_VALIDATION,
)
from app.micro_apps.loan_onboarding.services.validation_presets import (
    RULES_VERSION,
)

logger = logging.getLogger(__name__)


def hash_string(s: str) -> str:
    """SHA-256 hex digest of a string."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def hash_bytes(b: bytes) -> str:
    """SHA-256 hex digest of bytes."""
    return hashlib.sha256(b).hexdigest()


def hash_json(obj: Any) -> str:
    """SHA-256 hex digest of a JSON-serializable object with stable key order."""
    return hash_string(json.dumps(obj, sort_keys=True, default=str))


async def compute_package_content_hash(storage, package_files) -> str:
    """Hash of every uploaded file's content, stable order.

    Files are hashed in `(filename, storage_path)` order so the digest does
    not depend on which file was uploaded first. Files without bytes (e.g.
    storage miss) contribute their storage_path as a fallback marker — this
    guarantees the hash changes if a file was swapped under the same name.
    """
    h = hashlib.sha256()
    for f in sorted(package_files, key=lambda x: (x.filename or "", x.storage_path or "")):
        h.update(b"\x00")  # separator to prevent concatenation ambiguity
        h.update((f.filename or "").encode("utf-8"))
        h.update(b"\x01")
        try:
            data = await storage.get_object(f.storage_path)
            h.update(data)
        except Exception as e:
            logger.warning(
                "Could not read file %s for content hash: %s", f.storage_path, e
            )
            h.update(f.storage_path.encode("utf-8"))
    return h.hexdigest()


# ── Cache-key builders ─────────────────────────────────────────────────────

def compute_classify_cache_key(
    package_content_hash: str,
    allowed_doc_types: list[str],
    version_info: dict[str, Any],
) -> str:
    """Cache key for the classify stage.

    Depends on:
      - package_content_hash (every uploaded PDF byte)
      - allowed_doc_types (the per-order enum shapes the model's output)
      - classifier model + prompt + schema
    """
    parts = (
        package_content_hash
        + "|" + version_info["classifier_model"]
        + "|" + ",".join(sorted(allowed_doc_types))
        + "|" + version_info["classify_prompt_hash"]
        + "|" + version_info["classify_schema_hash"]
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def compute_validate_rule_cache_key(
    stack_content_hash: str,
    rule_id: str,
    rule_text: str,
    version_info: dict[str, Any],
) -> str:
    """Cache key for a single (stack, custom_rule) validation pair.

    Keyed per-rule so adding a new rule to a package does not invalidate the
    cache for rules that did not change.
    """
    parts = (
        stack_content_hash
        + "|" + rule_id
        + "|" + hash_string(rule_text)
        + "|" + version_info["validator_model"]
        + "|" + version_info["validate_prompt_hash"]
        + "|" + version_info["validate_schema_hash"]
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def compute_stack_content_hash(
    doc_type: str,
    page_snippets: list[dict[str, Any]],
) -> str:
    """Hash of the exact payload the validator would see for a stack.

    Stable shape: doc_type + ordered list of pages, each with page_number,
    text (truncated to 3000 chars — matches the orchestrator), and sorted
    detected_fields keyed by `(field_name, value)`.
    """
    normalized_pages = []
    for p in sorted(page_snippets, key=lambda x: x.get("page_number", 0)):
        fields = sorted(
            (
                {
                    "field_name": str(f.get("field_name", "")),
                    "value": str(f.get("value", "")),
                }
                for f in (p.get("detected_fields") or [])
                if isinstance(f, dict)
            ),
            key=lambda x: (x["field_name"], x["value"]),
        )
        normalized_pages.append({
            "page_number": p.get("page_number"),
            "text": (p.get("text") or "")[:3000],
            "detected_fields": fields,
        })
    return hash_json({"doc_type": doc_type, "pages": normalized_pages})


def compute_extract_cache_key(
    stack_content_hash: str,
    requested_fields: list[str],
    version_info: dict[str, Any],
) -> str:
    """Cache key for a single stack's extraction call.

    Keyed per-stack-content + requested-fields tuple + model/prompt/schema
    so adding a new doc_type's fields invalidates only the affected stacks.
    Field order is preserved (the agent emits records in request order)
    so a re-ordered list legitimately produces a different cache slot.
    """
    parts = (
        stack_content_hash
        + "|" + "||".join(requested_fields)
        + "|" + version_info.get("validator_model", "")
        + "|" + version_info.get("extract_prompt_hash", "")
        + "|" + version_info.get("extract_schema_hash", "")
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def compute_reason_cache_key(
    package_summary_hash: str,
    version_info: dict[str, Any],
) -> str:
    """Cache key for the review (ReasoningAgent) call."""
    parts = (
        package_summary_hash
        + "|" + version_info["reasoner_model"]
        + "|" + version_info["reason_prompt_hash"]
        + "|" + version_info["reason_schema_hash"]
        + "|" + version_info["rules_version"]
    )
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()


def compute_package_summary_hash(package_summary: dict[str, Any]) -> str:
    """Hash of the ReasoningAgent's input payload with UUIDs stripped.

    The orchestrator substitutes stable `stack_key = f"s{stack_index}"` in
    place of UUIDs before calling the agent, so the summary hash is
    deterministic across runs even though LOStack rows are recreated with
    fresh UUIDs each time.
    """
    return hash_json(package_summary)


# ── Version-info snapshot ──────────────────────────────────────────────────

_cached_version_info: dict[str, Any] | None = None
_cached_version_key: str | None = None


def collect_version_info(settings: Settings) -> dict[str, Any]:
    """Gather every component's version metadata for an LO pipeline run.

    Cached for process lifetime (invalidated only if model IDs or backend
    change). Returns a flat dict suitable for direct use by the cache-key
    builders above and for persisting to `LOPipelineRun`.
    """
    global _cached_version_info, _cached_version_key

    classifier_model = settings.LO_CLASSIFIER_MODEL or ""
    validator_model = settings.LO_VALIDATOR_MODEL or ""
    reasoner_model = settings.LO_REASONER_MODEL or ""
    ai_platform = getattr(settings, "LO_AI_PROVIDER", None) or "hybrid"
    pipeline_backend = getattr(settings, "PIPELINE_BACKEND", "") or ""

    cache_key = (
        f"{ai_platform}|{classifier_model}|{validator_model}|"
        f"{reasoner_model}|{pipeline_backend}|{RULES_VERSION}"
    )
    if _cached_version_info is not None and _cached_version_key == cache_key:
        return _cached_version_info

    from app.micro_apps.loan_onboarding.ai.page_classifier_agent import (
        SYSTEM_PROMPT as CLASSIFY_PROMPT,
        _build_json_schema,
    )
    from app.micro_apps.loan_onboarding.ai.stack_validator_agent import (
        SYSTEM_PROMPT as VALIDATE_PROMPT,
        _RESULT_SCHEMA as VALIDATE_SCHEMA,
    )
    from app.micro_apps.loan_onboarding.ai.reasoning_agent import (
        SYSTEM_PROMPT as REASON_PROMPT,
        _JSON_SCHEMA as REASON_SCHEMA,
    )
    from app.micro_apps.loan_onboarding.ai.extraction_agent import (
        SYSTEM_PROMPT as EXTRACT_PROMPT,
        _RESULT_SCHEMA as EXTRACT_SCHEMA,
    )

    # The classifier schema is parameterized by the per-order enum, so we
    # hash a canonical form with a placeholder enum. Per-order enum bytes
    # are folded into the classify cache key separately.
    canonical_classify_schema = _build_json_schema(["__CANONICAL__"])

    confidence_weights_hash = hash_json({
        "classification": WEIGHT_CLASSIFICATION,
        "split": WEIGHT_SPLIT,
        "validation": WEIGHT_VALIDATION,
    })

    _cached_version_info = {
        "ai_platform": ai_platform,
        "classifier_model": classifier_model,
        "validator_model": validator_model,
        "reasoner_model": reasoner_model,
        "classify_prompt_hash": hash_string(CLASSIFY_PROMPT),
        "classify_schema_hash": hash_json(canonical_classify_schema),
        "validate_prompt_hash": hash_string(VALIDATE_PROMPT),
        "validate_schema_hash": hash_json(VALIDATE_SCHEMA),
        "reason_prompt_hash": hash_string(REASON_PROMPT),
        "reason_schema_hash": hash_json(REASON_SCHEMA),
        "extract_prompt_hash": hash_string(EXTRACT_PROMPT),
        "extract_schema_hash": hash_json(EXTRACT_SCHEMA),
        "rules_version": RULES_VERSION,
        "confidence_weights_hash": confidence_weights_hash,
        "pipeline_backend": pipeline_backend,
    }
    _cached_version_key = cache_key
    return _cached_version_info


def reset_version_info_cache() -> None:
    """Test helper — drop the cached version_info so tests can re-collect."""
    global _cached_version_info, _cached_version_key
    _cached_version_info = None
    _cached_version_key = None
