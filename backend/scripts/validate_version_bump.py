#!/usr/bin/env python3
"""Validate pipeline output against golden set after a version change.

Workflow for any prompt/model/rules change:
    1. Make your prompt/model/rules change
    2. Validate against golden set:
       python scripts/validate_version_bump.py
    3. If satisfied, update golden set:
       python scripts/validate_version_bump.py --update-golden
    4. Commit both code change + updated golden set

Usage:
    python scripts/validate_version_bump.py                    # validate
    python scripts/validate_version_bump.py --update-golden    # regenerate golden outputs
    python scripts/validate_version_bump.py --strict           # use strict thresholds
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Add backend to path
BACKEND_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from tests.title_intelligence.eval_config import DEFAULT_THRESHOLDS, STRICT_THRESHOLDS
from tests.title_intelligence.eval_helpers import (
    build_eval_report,
    compute_eval_fingerprint,
    compare_fingerprints,
)
from tests.title_intelligence.golden.loader import (
    load_golden_set,
    list_golden_sets,
    validate_golden_set_versions,
)


def validate_versions() -> list[str]:
    """Check all golden sets for version mismatches."""
    all_mismatches = []
    for name in list_golden_sets():
        ds = load_golden_set(name)
        mismatches = validate_golden_set_versions(ds)
        if mismatches:
            all_mismatches.append(f"  {name}: {', '.join(mismatches)}")
    return all_mismatches


def validate_golden_set(name: str, strict: bool = False) -> bool:
    """Run deterministic validation on a golden set (no LLM calls).

    Verifies that the rules engine, flag normalization, and chain building
    produce identical output when applied to the golden set's extractions.
    """
    ds = load_golden_set(name)
    thresholds = STRICT_THRESHOLDS if strict else DEFAULT_THRESHOLDS

    # Run deterministic pipeline on golden extractions
    from app.micro_apps.title_intelligence.services.flag_rules import (
        normalize_flags,
        generate_deterministic_flags,
        merge_llm_and_deterministic_flags,
    )

    # Generate deterministic flags from golden extractions
    det_flags = generate_deterministic_flags(ds.extractions)

    # Normalize the golden raw flags (simulating LLM output)
    llm_normalized = normalize_flags(ds.flags_raw)

    # Merge
    merged = merge_llm_and_deterministic_flags(llm_normalized, det_flags)

    # Compare merged flags against golden normalized flags
    report = build_eval_report(
        name,
        actual_flags=merged,
        expected_flags=ds.flags_normalized,
        actual_sections=ds.sections,
        expected_sections=ds.sections,
        actual_extractions=ds.extractions,
        expected_extractions=ds.extractions,
        thresholds=thresholds,
    )

    print(report.summary())

    # Fingerprint comparison
    current_fp = compute_eval_fingerprint(ds.extractions, merged, ds.sections)
    baseline_fp = compute_eval_fingerprint(ds.extractions, ds.flags_normalized, ds.sections)
    fp_report = compare_fingerprints(current_fp, baseline_fp)

    if fp_report["drift_detected"]:
        print(f"\nStructural drift detected for '{name}'!")
        print(f"  Baseline fingerprint: {baseline_fp[:16]}...")
        print(f"  Current fingerprint:  {current_fp[:16]}...")
        print("  This means the flag composition has changed.")
    else:
        print(f"\nNo structural drift for '{name}'.")

    return report.passed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate pipeline output against golden set after version changes"
    )
    parser.add_argument(
        "--update-golden",
        action="store_true",
        help="Show instructions for regenerating golden outputs",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Use strict thresholds for version bump validation",
    )
    parser.add_argument(
        "--dataset",
        help="Validate a specific golden dataset (default: all)",
    )
    args = parser.parse_args()

    if args.update_golden:
        print("To update golden sets after a version change:")
        print()
        print("1. Run the eval runner with --update-golden:")
        print("   python scripts/run_evals.py --update-golden")
        print()
        print("2. Verify the updated golden sets:")
        print("   python scripts/validate_version_bump.py")
        print()
        print("3. Commit both the code change and updated golden sets")
        return

    print("=" * 60)
    print("Version Bump Validation")
    print("=" * 60)
    print()

    # Step 1: Check version mismatches
    print("Checking golden set versions...")
    mismatches = validate_versions()
    if mismatches:
        print("\nWARNING: Golden set versions don't match current code:")
        for m in mismatches:
            print(m)
        print("\nThis is expected if you just changed prompts/models/rules.")
        print("Run validation to see the impact, then update golden sets.")
        print()

    # Step 2: Validate each golden set
    datasets = [args.dataset] if args.dataset else list_golden_sets()
    if not datasets:
        print("No golden datasets found. Create one first.")
        sys.exit(1)

    all_passed = True
    for name in datasets:
        print(f"\nValidating '{name}'...")
        print("-" * 40)
        passed = validate_golden_set(name, strict=args.strict)
        if not passed:
            all_passed = False

    print()
    print("=" * 60)
    if all_passed:
        print("All validations PASSED")
        print()
        print("If you made a version change, update golden sets with:")
        print("  python scripts/validate_version_bump.py --update-golden")
    else:
        print("Some validations FAILED")
        print()
        print("Review the diffs above. If the changes are expected,")
        print("update the golden sets. If not, fix the regression.")
        sys.exit(1)


if __name__ == "__main__":
    main()
