"""Configurable thresholds for LLM evaluation tests.

These thresholds define the minimum acceptable quality for pipeline outputs
when compared against golden datasets. Adjust conservatively — lowering
thresholds masks regressions.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalThresholds:
    """Acceptance thresholds for LLM eval comparisons."""

    # Extraction comparison
    extraction_match_rate: float = 0.90    # >=90% matched by (type, label)
    extraction_max_missing: float = 0.05   # <=5% missing extractions
    extraction_max_extra: float = 0.05     # <=5% extra extractions
    extraction_confidence_tolerance: float = 0.05  # ±0.05 confidence delta

    # Flag comparison
    flag_match_rate: float = 0.85          # >=85% matched by (type, severity)
    flag_max_missing: float = 0.10         # <=10% missing (false negatives worse)
    flag_max_extra: float = 0.15           # <=15% extra flags acceptable

    # Section comparison
    section_match_rate: float = 0.95       # >=95% matched by (type, start_page)
    section_end_page_tolerance: int = 1    # ±1 page for end_page boundary

    # Transcription comparison
    transcription_min_similarity: float = 0.95  # >=0.95 character-level similarity

    # Triage comparison
    triage_match_rate: float = 0.95        # >=95% page classifications match

    # Token efficiency (regression detection)
    token_regression_threshold: float = 0.20  # >20% increase = regression


# Default thresholds used by all eval tests
DEFAULT_THRESHOLDS = EvalThresholds()

# Strict thresholds for version bump validation
STRICT_THRESHOLDS = EvalThresholds(
    extraction_match_rate=0.95,
    flag_match_rate=0.90,
    section_match_rate=0.98,
    transcription_min_similarity=0.97,
    triage_match_rate=0.98,
    token_regression_threshold=0.10,
)
