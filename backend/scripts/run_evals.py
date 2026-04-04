#!/usr/bin/env python3
"""CLI runner for LLM evaluation tests.

Runs pipeline against golden datasets, produces structured reports,
and optionally updates golden outputs.

Usage:
    python scripts/run_evals.py                    # run all evals
    python scripts/run_evals.py --dataset simple   # run one dataset
    python scripts/run_evals.py --update-golden    # regenerate golden outputs
    python scripts/run_evals.py --offline          # run only offline tests (no LLM)
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).parent.parent
GOLDEN_DIR = BACKEND_DIR / "tests" / "title_intelligence" / "golden"
REPORTS_DIR = BACKEND_DIR / "eval_reports"


def run_offline_evals() -> int:
    """Run offline eval tests (no LLM calls, validates framework + golden sets)."""
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/title_intelligence/test_llm_evals.py",
        "-v", "-m", "llm_eval",
        "-k", "TestGoldenSetIntegrity or TestEvalFramework",
    ]
    result = subprocess.run(cmd, cwd=str(BACKEND_DIR))
    return result.returncode


def run_llm_evals(dataset: str | None = None) -> int:
    """Run LLM eval tests (requires GOOGLE_API_KEY)."""
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/title_intelligence/test_llm_evals.py",
        "-v", "-m", "llm_eval",
    ]
    if dataset:
        cmd.extend(["-k", dataset])
    result = subprocess.run(cmd, cwd=str(BACKEND_DIR))
    return result.returncode


def update_golden_sets(dataset: str | None = None) -> None:
    """Regenerate golden outputs from current pipeline.

    Requires GOOGLE_API_KEY and input PDFs in golden dataset directories.
    Delegates to scripts/generate_golden.py which runs the actual pipeline.
    """
    cmd = [sys.executable, str(BACKEND_DIR / "scripts" / "generate_golden.py")]
    if dataset:
        cmd.extend(["--dataset", dataset])
    result = subprocess.run(cmd, cwd=str(BACKEND_DIR))
    sys.exit(result.returncode)


def generate_report(rc: int, dataset: str | None = None) -> None:
    """Save eval report to eval_reports/ directory."""
    REPORTS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report = {
        "timestamp": timestamp,
        "dataset": dataset or "all",
        "exit_code": rc,
        "passed": rc == 0,
    }
    report_path = REPORTS_DIR / f"eval_{timestamp}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved to: {report_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run LLM evaluation tests")
    parser.add_argument(
        "--dataset",
        help="Run evals for a specific golden dataset (e.g., 'simple_commitment')",
    )
    parser.add_argument(
        "--update-golden",
        action="store_true",
        help="Show instructions for regenerating golden outputs",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run only offline tests (no LLM calls)",
    )
    args = parser.parse_args()

    if args.update_golden:
        update_golden_sets(args.dataset)
        return

    print("=" * 60)
    print("Title Intelligence Eval Runner")
    print("=" * 60)
    print()

    if args.offline:
        print("Running offline eval tests...")
        rc = run_offline_evals()
    else:
        print("Running offline eval tests first...")
        rc = run_offline_evals()
        if rc != 0:
            print("\nOffline tests failed. Fix these before running LLM evals.")
            sys.exit(rc)

        print("\nRunning LLM eval tests...")
        rc = run_llm_evals(args.dataset)

    generate_report(rc, args.dataset)

    if rc == 0:
        print("\nAll evals PASSED")
    else:
        print(f"\nEvals FAILED (exit code {rc})")

    sys.exit(rc)


if __name__ == "__main__":
    main()
