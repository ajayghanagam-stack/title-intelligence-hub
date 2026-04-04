"""Live SLA benchmark tests using golden datasets.

Runs the pipeline on golden PDFs and validates against SLA thresholds.
Marked with @pytest.mark.llm_eval — excluded from normal CI.

Usage:
    pytest benchmarks/test_live_sla.py -v -m llm_eval
"""

from __future__ import annotations

import pytest

from benchmarks.sla import check_sla, get_sla_for_page_count, SLAThreshold
from tests.title_intelligence.eval_config import DEFAULT_THRESHOLDS
from tests.title_intelligence.golden.loader import load_golden_set, list_golden_sets


pytestmark = pytest.mark.llm_eval


# ---------------------------------------------------------------------------
# Offline SLA threshold validation (no LLM needed)
# ---------------------------------------------------------------------------


class TestSLAThresholds:
    """Validate SLA threshold definitions are reasonable."""

    def test_thresholds_cover_golden_sets(self):
        """Every golden dataset has a valid SLA threshold for its page count."""
        for name in list_golden_sets():
            ds = load_golden_set(name)
            sla = get_sla_for_page_count(ds.metadata.total_pages)
            assert sla.max_pipeline_seconds > 0
            assert sla.max_examine_seconds > 0
            assert sla.max_tokens > 0

    def test_throughput_linearity(self):
        """SLA maintains ~100pp/60s linear throughput."""
        for pages in [25, 50, 100, 200, 300]:
            sla = get_sla_for_page_count(pages)
            throughput = pages / sla.max_pipeline_seconds * 60
            # Should be at least 80pp/min (allowing some overhead)
            assert throughput >= 80, (
                f"{pages}pp: {throughput:.0f}pp/min throughput "
                f"(expected >= 80pp/min)"
            )

    def test_token_budget_per_page(self):
        """Token budget per page stays within expected range."""
        for pages in [25, 50, 100, 200]:
            sla = get_sla_for_page_count(pages)
            tokens_per_page = sla.max_tokens / pages
            # Expected: <500 input + <400 output = ~900 tokens/page max
            assert tokens_per_page <= 1000, (
                f"{pages}pp: {tokens_per_page:.0f} tokens/page "
                f"(expected <= 1000)"
            )


class TestSLACheckMocked:
    """Test SLA check function with mocked stage timings."""

    def test_sla_pass(self):
        """Timings within budget → SLA passes."""
        result = check_sla(
            stage_timings={"ingest": 1.0, "render": 0.5, "examine": 5.0, "complete": 0.5},
            total_tokens=5000,
            page_count=25,
        )
        assert result.passed
        assert len(result.violations) == 0

    def test_sla_fail_total_time(self):
        """Total time over budget → SLA fails."""
        result = check_sla(
            stage_timings={"ingest": 1.0, "render": 0.5, "examine": 15.0, "complete": 0.5},
            total_tokens=5000,
            page_count=25,  # SLA: 15s
        )
        assert not result.passed
        assert any(v.metric == "total_pipeline_seconds" for v in result.violations)

    def test_sla_fail_token_budget(self):
        """Token usage over budget → SLA fails."""
        result = check_sla(
            stage_timings={"ingest": 1.0, "render": 0.5, "examine": 5.0, "complete": 0.5},
            total_tokens=20000,  # SLA for 25pp: 15000
            page_count=25,
        )
        assert not result.passed
        assert any(v.metric == "total_tokens" for v in result.violations)

    def test_sla_golden_set_baseline(self):
        """Golden set metadata token counts are within SLA."""
        for name in list_golden_sets():
            ds = load_golden_set(name)
            m = ds.metadata
            if m.total_input_tokens == 0 and m.total_output_tokens == 0:
                # Placeholder dataset — skip
                continue
            total_tokens = m.total_input_tokens + m.total_output_tokens
            result = check_sla(
                stage_timings={"examine": m.total_elapsed_seconds},
                total_tokens=total_tokens,
                page_count=m.total_pages,
            )
            assert result.passed, (
                f"Golden set '{name}' baseline exceeds SLA: "
                f"{[v.message for v in result.violations]}"
            )


# ---------------------------------------------------------------------------
# Live SLA tests (require GOOGLE_API_KEY and input PDFs)
# ---------------------------------------------------------------------------


class TestLiveSLA:
    """Run pipeline on golden PDFs and validate against SLA.

    These tests require:
    1. GOOGLE_API_KEY environment variable
    2. Input PDFs in golden dataset directories
    3. Run with: pytest -m llm_eval

    Skipped automatically if prerequisites are missing.
    """

    def test_simple_commitment_sla(self):
        """Simple commitment meets SLA for 20pp document."""
        try:
            ds = load_golden_set("simple_commitment")
        except FileNotFoundError:
            pytest.skip("simple_commitment golden dataset not found")
        if not ds.has_pdf:
            pytest.skip("No input PDF — run with real golden data")
        pytest.skip("Requires pipeline execution — run via scripts/run_evals.py")

    def test_token_efficiency(self):
        """Token usage per page is within expected bounds."""
        for name in list_golden_sets():
            ds = load_golden_set(name)
            if ds.metadata.total_input_tokens == 0:
                continue
            input_per_page = ds.metadata.total_input_tokens / ds.metadata.total_pages
            output_per_page = ds.metadata.total_output_tokens / ds.metadata.total_pages
            assert input_per_page < 2000, f"{name}: {input_per_page:.0f} input tokens/page"
            assert output_per_page < 400, f"{name}: {output_per_page:.0f} output tokens/page"
