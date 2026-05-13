"""Verify ``GROUNDING_CONTRACT_VERSION`` is folded into the extract cache key.

The Phase 1 day-1 commit was the cache-key bump — every pre-v2 cache
slot must miss after the bump, even if model/prompt/schema haven't
otherwise changed. This test pins that behavior.
"""
from __future__ import annotations

from app.micro_apps.loan_onboarding.pipeline.version_tracker import (
    GROUNDING_CONTRACT_VERSION,
    compute_extract_cache_key,
)


def _baseline_version_info(grounding: str) -> dict:
    return {
        "validator_model": "claude-sonnet-4-6",
        "extract_prompt_hash": "P",
        "extract_schema_hash": "S",
        "grounding_contract_version": grounding,
    }


def test_grounding_version_is_v2():
    # Hard-pinned so a typo elsewhere can't silently revert the bump.
    assert GROUNDING_CONTRACT_VERSION == "lo_grounding_v2"


def test_cache_key_changes_when_grounding_version_changes():
    a = compute_extract_cache_key(
        "stack_hash", ["borrower_name"], _baseline_version_info("lo_grounding_v1"),
    )
    b = compute_extract_cache_key(
        "stack_hash", ["borrower_name"], _baseline_version_info("lo_grounding_v2"),
    )
    assert a != b


def test_cache_key_stable_when_inputs_unchanged():
    info = _baseline_version_info(GROUNDING_CONTRACT_VERSION)
    a = compute_extract_cache_key("stack_hash", ["borrower_name"], info)
    b = compute_extract_cache_key("stack_hash", ["borrower_name"], info)
    assert a == b


def test_cache_key_changes_with_field_order():
    info = _baseline_version_info(GROUNDING_CONTRACT_VERSION)
    a = compute_extract_cache_key("h", ["borrower_name", "loan_amount"], info)
    b = compute_extract_cache_key("h", ["loan_amount", "borrower_name"], info)
    assert a != b


def test_cache_key_includes_model():
    base = _baseline_version_info(GROUNDING_CONTRACT_VERSION)
    other = dict(base, validator_model="claude-opus-4-6")
    a = compute_extract_cache_key("h", ["x"], base)
    b = compute_extract_cache_key("h", ["x"], other)
    assert a != b
