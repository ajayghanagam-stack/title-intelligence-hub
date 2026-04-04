"""Fuzzy comparison framework for LLM eval testing.

Provides semantic comparison functions that account for acceptable LLM
output variation while catching regressions. Used by test_llm_evals.py
and scripts/validate_version_bump.py.
"""

from __future__ import annotations

import difflib
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from tests.title_intelligence.eval_config import EvalThresholds, DEFAULT_THRESHOLDS


# ---------------------------------------------------------------------------
# Diff result types
# ---------------------------------------------------------------------------


@dataclass
class ExtractionDiff:
    """Result of comparing actual vs expected extractions."""

    total_expected: int = 0
    total_actual: int = 0
    matched: int = 0
    missing: list[dict] = field(default_factory=list)   # in expected, not in actual
    extra: list[dict] = field(default_factory=list)      # in actual, not in expected
    changed: list[dict] = field(default_factory=list)    # matched key but different value

    @property
    def match_rate(self) -> float:
        return self.matched / self.total_expected if self.total_expected else 1.0

    @property
    def missing_rate(self) -> float:
        return len(self.missing) / self.total_expected if self.total_expected else 0.0

    @property
    def extra_rate(self) -> float:
        return len(self.extra) / max(self.total_actual, 1)


@dataclass
class FlagDiff:
    """Result of comparing actual vs expected flags."""

    total_expected: int = 0
    total_actual: int = 0
    matched: int = 0
    missing: list[dict] = field(default_factory=list)
    extra: list[dict] = field(default_factory=list)

    @property
    def match_rate(self) -> float:
        return self.matched / self.total_expected if self.total_expected else 1.0

    @property
    def missing_rate(self) -> float:
        return len(self.missing) / self.total_expected if self.total_expected else 0.0


@dataclass
class SectionDiff:
    """Result of comparing actual vs expected sections."""

    total_expected: int = 0
    total_actual: int = 0
    matched: int = 0
    missing: list[dict] = field(default_factory=list)
    extra: list[dict] = field(default_factory=list)

    @property
    def match_rate(self) -> float:
        return self.matched / self.total_expected if self.total_expected else 1.0


@dataclass
class TranscriptionDiff:
    """Result of comparing actual vs expected transcriptions."""

    total_pages: int = 0
    average_similarity: float = 1.0
    low_similarity_pages: list[dict] = field(default_factory=list)  # pages < threshold


@dataclass
class EvalReport:
    """Aggregated eval report with pass/fail verdict."""

    dataset_name: str
    extraction_diff: ExtractionDiff | None = None
    flag_diff: FlagDiff | None = None
    section_diff: SectionDiff | None = None
    transcription_diff: TranscriptionDiff | None = None
    thresholds: EvalThresholds = field(default_factory=lambda: DEFAULT_THRESHOLDS)

    @property
    def passed(self) -> bool:
        """True if all comparisons meet threshold requirements."""
        checks = []
        t = self.thresholds

        if self.extraction_diff:
            checks.append(self.extraction_diff.match_rate >= t.extraction_match_rate)
            checks.append(self.extraction_diff.missing_rate <= t.extraction_max_missing)
            checks.append(self.extraction_diff.extra_rate <= t.extraction_max_extra)

        if self.flag_diff:
            checks.append(self.flag_diff.match_rate >= t.flag_match_rate)
            checks.append(self.flag_diff.missing_rate <= t.flag_max_missing)

        if self.section_diff:
            checks.append(self.section_diff.match_rate >= t.section_match_rate)

        if self.transcription_diff:
            checks.append(
                self.transcription_diff.average_similarity >= t.transcription_min_similarity
            )

        return all(checks) if checks else True

    def summary(self) -> str:
        """Human-readable summary of the eval report."""
        lines = [f"Eval Report: {self.dataset_name}", "=" * 50]

        if self.extraction_diff:
            d = self.extraction_diff
            lines.append(
                f"Extractions: {d.matched}/{d.total_expected} matched "
                f"({d.match_rate:.0%}), {len(d.missing)} missing, "
                f"{len(d.extra)} extra, {len(d.changed)} changed"
            )

        if self.flag_diff:
            d = self.flag_diff
            lines.append(
                f"Flags: {d.matched}/{d.total_expected} matched "
                f"({d.match_rate:.0%}), {len(d.missing)} missing, "
                f"{len(d.extra)} extra"
            )

        if self.section_diff:
            d = self.section_diff
            lines.append(
                f"Sections: {d.matched}/{d.total_expected} matched "
                f"({d.match_rate:.0%})"
            )

        if self.transcription_diff:
            d = self.transcription_diff
            lines.append(
                f"Transcriptions: avg similarity {d.average_similarity:.3f}, "
                f"{len(d.low_similarity_pages)} pages below threshold"
            )

        verdict = "PASS" if self.passed else "FAIL"
        lines.append(f"\nVerdict: {verdict}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Comparison functions
# ---------------------------------------------------------------------------


def compare_extractions(
    actual: list[dict],
    expected: list[dict],
    confidence_tolerance: float = 0.05,
) -> ExtractionDiff:
    """Compare actual extractions against expected golden set.

    Matches by (extraction_type, label) key. Values are compared semantically.
    """
    diff = ExtractionDiff(total_expected=len(expected), total_actual=len(actual))

    # Index expected by (type, label)
    expected_map: dict[tuple[str, str], dict] = {}
    for e in expected:
        key = (e.get("extraction_type", ""), e.get("label", ""))
        expected_map[key] = e

    # Index actual by (type, label)
    actual_map: dict[tuple[str, str], dict] = {}
    for a in actual:
        key = (a.get("extraction_type", ""), a.get("label", ""))
        actual_map[key] = a

    # Find matches, missing, extra
    for key, exp in expected_map.items():
        if key in actual_map:
            act = actual_map[key]
            # Check if values differ
            exp_conf = exp.get("confidence", 0)
            act_conf = act.get("confidence", 0)
            if exp_conf is not None and act_conf is not None:
                if abs(exp_conf - act_conf) > confidence_tolerance:
                    diff.changed.append({
                        "key": key,
                        "expected_confidence": exp_conf,
                        "actual_confidence": act_conf,
                    })
                else:
                    diff.matched += 1
            else:
                diff.matched += 1
        else:
            diff.missing.append({"key": key, "expected": exp})

    for key in actual_map:
        if key not in expected_map:
            diff.extra.append({"key": key, "actual": actual_map[key]})

    return diff


def compare_flags(
    actual: list[dict],
    expected: list[dict],
) -> FlagDiff:
    """Compare actual flags against expected golden set.

    Matches by (flag_type, severity). Description text may differ (LLM variance).
    """
    diff = FlagDiff(total_expected=len(expected), total_actual=len(actual))

    # Build multisets for matching
    expected_keys = [(f.get("flag_type", ""), f.get("severity", "")) for f in expected]
    actual_keys = [(f.get("flag_type", ""), f.get("severity", "")) for f in actual]

    # Greedy matching
    remaining_actual = list(actual_keys)
    for i, ekey in enumerate(expected_keys):
        if ekey in remaining_actual:
            remaining_actual.remove(ekey)
            diff.matched += 1
        else:
            diff.missing.append({"expected": expected[i]})

    for j, akey in enumerate(remaining_actual):
        # Find the original actual dict for unmatched keys
        for a in actual:
            a_key = (a.get("flag_type", ""), a.get("severity", ""))
            if a_key == akey:
                diff.extra.append({"actual": a})
                break

    return diff


def compare_sections(
    actual: list[dict],
    expected: list[dict],
    end_page_tolerance: int = 1,
) -> SectionDiff:
    """Compare actual sections against expected golden set.

    Matches by (section_type, start_page). End page may differ by ±tolerance.
    """
    diff = SectionDiff(total_expected=len(expected), total_actual=len(actual))

    expected_map: dict[tuple[str, int], dict] = {}
    for s in expected:
        key = (s.get("section_type", ""), s.get("start_page", 0))
        expected_map[key] = s

    actual_map: dict[tuple[str, int], dict] = {}
    for s in actual:
        key = (s.get("section_type", ""), s.get("start_page", 0))
        actual_map[key] = s

    for key, exp in expected_map.items():
        if key in actual_map:
            act = actual_map[key]
            exp_end = exp.get("end_page", 0)
            act_end = act.get("end_page", 0)
            if abs(exp_end - act_end) <= end_page_tolerance:
                diff.matched += 1
            else:
                diff.missing.append({"key": key, "expected_end": exp_end, "actual_end": act_end})
        else:
            diff.missing.append({"key": key, "expected": exp})

    for key in actual_map:
        if key not in expected_map:
            diff.extra.append({"key": key, "actual": actual_map[key]})

    return diff


def compare_transcriptions(
    actual: list[dict],
    expected: list[dict],
    min_similarity: float = 0.95,
) -> TranscriptionDiff:
    """Compare actual transcriptions against expected golden set.

    Uses character-level SequenceMatcher similarity per page.
    """
    diff = TranscriptionDiff(total_pages=len(expected))

    # Index by page_number
    expected_map = {t.get("page_number"): t.get("text", "") for t in expected}
    actual_map = {t.get("page_number"): t.get("text", "") for t in actual}

    similarities = []
    for page_num, exp_text in expected_map.items():
        act_text = actual_map.get(page_num, "")
        ratio = difflib.SequenceMatcher(None, exp_text, act_text).ratio()
        similarities.append(ratio)
        if ratio < min_similarity:
            diff.low_similarity_pages.append({
                "page_number": page_num,
                "similarity": ratio,
                "expected_len": len(exp_text),
                "actual_len": len(act_text),
            })

    diff.average_similarity = sum(similarities) / len(similarities) if similarities else 1.0
    return diff


# ---------------------------------------------------------------------------
# Fingerprinting for drift detection (Phase 4)
# ---------------------------------------------------------------------------


def compute_eval_fingerprint(
    extractions: list[dict],
    flags: list[dict],
    sections: list[dict],
) -> str:
    """Compute a structural fingerprint of pipeline output.

    Captures the shape of the output (types, counts) without exact values.
    Used for drift detection between runs.
    """
    extraction_types = sorted(e.get("extraction_type", "") for e in extractions)
    flag_types = sorted(f.get("flag_type", "") for f in flags)
    flag_severities = sorted(f.get("severity", "") for f in flags)
    section_types = sorted(s.get("section_type", "") for s in sections)

    fingerprint_data = {
        "extraction_types": extraction_types,
        "extraction_count": len(extractions),
        "flag_types": flag_types,
        "flag_severities": flag_severities,
        "flag_count": len(flags),
        "section_types": section_types,
        "section_count": len(sections),
    }

    return hashlib.sha256(
        json.dumps(fingerprint_data, sort_keys=True).encode()
    ).hexdigest()


def compare_fingerprints(current: str, baseline: str) -> dict[str, Any]:
    """Compare two eval fingerprints.

    Returns a report dict indicating whether the output structure has changed.
    """
    return {
        "match": current == baseline,
        "current": current,
        "baseline": baseline,
        "drift_detected": current != baseline,
    }


def build_eval_report(
    dataset_name: str,
    actual_extractions: list[dict] | None = None,
    expected_extractions: list[dict] | None = None,
    actual_flags: list[dict] | None = None,
    expected_flags: list[dict] | None = None,
    actual_sections: list[dict] | None = None,
    expected_sections: list[dict] | None = None,
    actual_transcriptions: list[dict] | None = None,
    expected_transcriptions: list[dict] | None = None,
    thresholds: EvalThresholds | None = None,
) -> EvalReport:
    """Build a complete eval report from actual vs expected comparisons."""
    t = thresholds or DEFAULT_THRESHOLDS
    report = EvalReport(dataset_name=dataset_name, thresholds=t)

    if actual_extractions is not None and expected_extractions is not None:
        report.extraction_diff = compare_extractions(
            actual_extractions, expected_extractions, t.extraction_confidence_tolerance
        )

    if actual_flags is not None and expected_flags is not None:
        report.flag_diff = compare_flags(actual_flags, expected_flags)

    if actual_sections is not None and expected_sections is not None:
        report.section_diff = compare_sections(
            actual_sections, expected_sections, t.section_end_page_tolerance
        )

    if actual_transcriptions is not None and expected_transcriptions is not None:
        report.transcription_diff = compare_transcriptions(
            actual_transcriptions, expected_transcriptions, t.transcription_min_similarity
        )

    return report
