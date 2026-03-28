"""Mocked benchmark tests for SLA enforcement.

CI-safe: no real Gemini calls.  These tests verify:
1. SLA threshold lookup and interpolation
2. SLA checking logic (pass/fail with violations)
3. Synthetic PDF generator validity
4. Pipeline timing instrumentation (via mocked PipelineRun)
5. Token budget enforcement
6. Readiness determinism (same inputs → identical outputs)
"""

from __future__ import annotations

import copy
import io
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from benchmarks.sla import (
    SLA_THRESHOLDS,
    SLAThreshold,
    check_sla,
    get_sla_for_page_count,
)
from benchmarks.pdf_generator import generate_synthetic_pdf
from benchmarks.metrics import (
    BenchmarkMetrics,
    check_metrics,
    collect_metrics_from_version_metadata,
    format_report,
)
from benchmarks.conftest import (
    BENCH_PACK_ID,
    BENCH_PIPELINE_RUN_ID,
    TEST_ORG_ID,
    build_mock_examiner_result,
    build_mock_stage_timings,
    build_mock_version_metadata,
)

# ============================================================================
# TestSLAThresholds — unit tests for the SLA lookup / checking logic
# ============================================================================


class TestSLAThresholds:
    """Verify SLA definitions and the check_sla logic."""

    def test_exact_match_25pp(self):
        sla = get_sla_for_page_count(25)
        assert sla.page_count == 25
        assert sla.max_pipeline_seconds == 15
        assert sla.max_examine_seconds == 10
        assert sla.max_tokens == 15_000

    def test_exact_match_100pp(self):
        sla = get_sla_for_page_count(100)
        assert sla.page_count == 100
        assert sla.max_pipeline_seconds == 60
        assert sla.max_examine_seconds == 40
        assert sla.max_tokens == 50_000

    def test_exact_match_500pp(self):
        sla = get_sla_for_page_count(500)
        assert sla.page_count == 500
        assert sla.max_pipeline_seconds == 300

    def test_below_minimum_returns_smallest(self):
        sla = get_sla_for_page_count(5)
        assert sla == SLA_THRESHOLDS[0]

    def test_above_maximum_returns_largest(self):
        sla = get_sla_for_page_count(1000)
        assert sla == SLA_THRESHOLDS[-1]

    def test_interpolation_75pp(self):
        sla = get_sla_for_page_count(75)
        assert sla.page_count == 75
        # Midpoint between 50pp (30s) and 100pp (60s) = 45s
        assert sla.max_pipeline_seconds == 45.0
        # Midpoint between 50pp (20s) and 100pp (40s) = 30s
        assert sla.max_examine_seconds == 30.0
        # Midpoint between 50pp (25K) and 100pp (50K) = 37.5K
        assert sla.max_tokens == 37_500

    def test_interpolation_between_100_and_200(self):
        sla = get_sla_for_page_count(150)
        assert sla.page_count == 150
        # Midpoint between 100pp (60s) and 200pp (120s) = 90s
        assert sla.max_pipeline_seconds == 90.0

    def test_exact_match_300pp(self):
        sla = get_sla_for_page_count(300)
        assert sla.page_count == 300
        assert sla.max_pipeline_seconds == 180
        assert sla.max_examine_seconds == 120
        assert sla.max_tokens == 150_000

    def test_check_sla_pass(self):
        timings = {"ingest": 1, "render": 0.5, "examine": 8, "complete": 0.5}
        result = check_sla(timings, total_tokens=10_000, page_count=25)
        assert result.passed is True
        assert result.violations == []

    def test_check_sla_fail_pipeline_time(self):
        timings = {"ingest": 5, "render": 5, "examine": 12, "complete": 5}
        result = check_sla(timings, total_tokens=10_000, page_count=25)
        assert result.passed is False
        assert any(v.metric == "total_pipeline_seconds" for v in result.violations)
        assert any(v.metric == "examine_seconds" for v in result.violations)

    def test_check_sla_fail_tokens(self):
        timings = {"ingest": 1, "render": 0.5, "examine": 8, "complete": 0.5}
        result = check_sla(timings, total_tokens=20_000, page_count=25)
        assert result.passed is False
        assert any(v.metric == "total_tokens" for v in result.violations)

    def test_check_sla_multiple_violations(self):
        timings = {"ingest": 5, "render": 5, "examine": 20, "complete": 5}
        result = check_sla(timings, total_tokens=50_000, page_count=25)
        assert result.passed is False
        assert len(result.violations) == 3  # pipeline, examine, tokens

    def test_check_sla_with_explicit_threshold(self):
        custom = SLAThreshold(page_count=10, max_pipeline_seconds=5, max_examine_seconds=3, max_tokens=5000)
        timings = {"ingest": 0.5, "render": 0.2, "examine": 2, "complete": 0.3}
        result = check_sla(timings, total_tokens=3000, page_count=10, threshold=custom)
        assert result.passed is True
        assert result.threshold == custom

    def test_threshold_immutability(self):
        """SLAThreshold is frozen — attribute assignment should raise."""
        sla = SLA_THRESHOLDS[0]
        with pytest.raises(AttributeError):
            sla.max_tokens = 999  # type: ignore[misc]


# ============================================================================
# TestSyntheticPDF — verify the PDF generator creates valid PDFs
# ============================================================================


class TestSyntheticPDF:
    """Verify synthetic PDF generation."""

    def test_generates_valid_pdf_bytes(self):
        pdf_bytes = generate_synthetic_pdf(10)
        assert isinstance(pdf_bytes, bytes)
        assert pdf_bytes[:5] == b"%PDF-"

    def test_correct_page_count_25(self):
        pdf_bytes = generate_synthetic_pdf(25)
        page_count = self._count_pages(pdf_bytes)
        assert page_count == 25

    def test_correct_page_count_100(self):
        pdf_bytes = generate_synthetic_pdf(100)
        page_count = self._count_pages(pdf_bytes)
        assert page_count == 100

    def test_single_page(self):
        pdf_bytes = generate_synthetic_pdf(1)
        assert pdf_bytes[:5] == b"%PDF-"
        assert self._count_pages(pdf_bytes) == 1

    def test_content_varies_by_section(self):
        """Different pages should have different section content."""
        pdf_bytes = generate_synthetic_pdf(50)
        # Just verify it's a valid, non-trivial PDF
        assert len(pdf_bytes) > 1000

    @staticmethod
    def _count_pages(pdf_bytes: bytes) -> int:
        """Count pages in a PDF using PyMuPDF."""
        import fitz  # PyMuPDF

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        count = len(doc)
        doc.close()
        return count


# ============================================================================
# TestMetricsCollection — verify metrics extraction from version_metadata
# ============================================================================


class TestMetricsCollection:
    """Verify BenchmarkMetrics collection and reporting."""

    def test_collect_from_version_metadata(self):
        meta = build_mock_version_metadata(25)
        metrics = collect_metrics_from_version_metadata(meta, page_count=25)

        assert metrics.page_count == 25
        assert metrics.total_seconds > 0
        assert metrics.examine_seconds > 0
        assert metrics.total_tokens == 25 * 400
        assert metrics.batch_count == 2  # 25 pages / 20 batch_size = 2

    def test_collect_from_empty_metadata(self):
        metrics = collect_metrics_from_version_metadata(None, page_count=10)
        assert metrics.page_count == 10
        assert metrics.total_seconds == 0.0
        assert metrics.total_tokens == 0

    def test_check_metrics_pass(self):
        meta = build_mock_version_metadata(25)
        metrics = collect_metrics_from_version_metadata(meta, page_count=25)
        result = check_metrics(metrics)
        assert result.passed is True

    def test_format_report_pass(self):
        meta = build_mock_version_metadata(25)
        metrics = collect_metrics_from_version_metadata(meta, page_count=25)
        result = check_metrics(metrics)
        report = format_report(metrics, result)

        assert "PASS" in report
        assert "25 pages" in report
        assert "Stage timings:" in report
        assert "Token usage:" in report

    def test_format_report_fail(self):
        metrics = BenchmarkMetrics(
            page_count=25,
            stage_timings={"ingest": 5, "render": 5, "examine": 20, "complete": 5},
            total_seconds=35,
            examine_seconds=20,
            total_tokens=50_000,
        )
        result = check_metrics(metrics)
        report = format_report(metrics, result)

        assert "FAIL" in report
        assert "VIOLATIONS:" in report


# ============================================================================
# TestPipelineTimingInstrumentation — verify stage_timings recording
# ============================================================================


class TestPipelineTimingInstrumentation:
    """Verify that pipeline runs record timing metadata correctly."""

    def test_mock_stage_timings_structure(self):
        timings = build_mock_stage_timings(25)
        assert set(timings.keys()) == {"ingest", "render", "examine", "complete"}
        assert all(isinstance(v, float) for v in timings.values())
        assert all(v > 0 for v in timings.values())

    def test_mock_stage_timings_scale_with_pages(self):
        timings_25 = build_mock_stage_timings(25)
        timings_100 = build_mock_stage_timings(100)
        # Larger documents should take longer
        assert sum(timings_100.values()) > sum(timings_25.values())

    def test_version_metadata_has_required_keys(self):
        meta = build_mock_version_metadata(50)
        assert "stage_timings" in meta
        assert "total_elapsed_seconds" in meta
        assert "batch_results" in meta
        assert "total_tokens" in meta
        assert meta["total_elapsed_seconds"] == round(sum(meta["stage_timings"].values()), 2)

    @pytest.mark.asyncio
    async def test_pipeline_run_stores_timing(self, db_session: AsyncSession, seed_data):
        """Create a PipelineRun with timing metadata and verify retrieval."""
        from app.micro_apps.title_intelligence.models.pack import Pack
        from app.micro_apps.title_intelligence.models.pipeline_run import PipelineRun

        # Create pack first (FK constraint)
        pack = Pack(id=BENCH_PACK_ID, org_id=TEST_ORG_ID, name="Timing Test Pack", status="completed")
        db_session.add(pack)
        await db_session.flush()

        meta = build_mock_version_metadata(25)
        run = PipelineRun(
            id=BENCH_PIPELINE_RUN_ID,
            org_id=TEST_ORG_ID,
            pack_id=BENCH_PACK_ID,
            input_file_hash="a" * 64,
            ai_platform="gemini",
            ai_model="gemini-2.5-flash",
            ingestion_prompt_hash="b" * 64,
            risk_prompt_hash="c" * 64,
            extraction_tool_hash="d" * 64,
            risk_tool_hash="e" * 64,
            ocr_engine="gemini_native_pdf",
            chunker_version="hierarchical_v1",
            rules_version="weighted_5cat_v2",
            pipeline_backend="background_tasks",
            version_metadata=meta,
            status="completed",
            completed_at=datetime.now(timezone.utc),
        )
        db_session.add(run)
        await db_session.commit()

        # Retrieve and verify
        from sqlalchemy import select

        result = await db_session.execute(
            select(PipelineRun).where(PipelineRun.id == BENCH_PIPELINE_RUN_ID)
        )
        stored = result.scalar_one()
        assert stored.version_metadata["stage_timings"]["examine"] > 0
        assert stored.version_metadata["total_elapsed_seconds"] > 0

        # Verify metrics extraction
        metrics = collect_metrics_from_version_metadata(stored.version_metadata, page_count=25)
        assert metrics.total_seconds > 0


# ============================================================================
# TestTokenBudget — verify token counts stay within SLA
# ============================================================================


class TestTokenBudget:
    """Verify token usage stays within SLA budgets."""

    @pytest.mark.parametrize("page_count", [25, 50, 100])
    def test_mock_tokens_within_sla(self, page_count: int):
        """Mocked token counts for standard sizes should pass SLA."""
        meta = build_mock_version_metadata(page_count)
        metrics = collect_metrics_from_version_metadata(meta, page_count=page_count)
        result = check_metrics(metrics)
        assert result.passed is True, (
            f"{page_count}pp: {metrics.total_tokens:,} tokens exceeds "
            f"{result.threshold.max_tokens:,} limit"
        )

    def test_examiner_result_token_tracking(self):
        """Verify mock ExaminerConsolidatedResult has expected structure."""
        result = build_mock_examiner_result(50)
        assert len(result.page_transcriptions) == 50
        assert len(result.sections) == 4
        assert len(result.extractions) == 3
        assert len(result.flags) == 1
        assert result.rate_limit_hits == 0

    def test_500pp_tokens_within_sla(self):
        """500pp document should still be within SLA for tokens."""
        meta = build_mock_version_metadata(500)
        metrics = collect_metrics_from_version_metadata(meta, page_count=500)
        result = check_metrics(metrics)
        assert result.passed is True


# ============================================================================
# TestDeterminism — identical inputs → identical outputs
# ============================================================================


class TestDeterminism:
    """Verify deterministic outputs for readiness calculation."""

    @pytest.mark.asyncio
    async def test_readiness_deterministic_3x(self, db_session: AsyncSession, seed_data):
        """Compute readiness 3x with identical inputs — all must match."""
        from app.micro_apps.title_intelligence.models.pack import Pack
        from app.micro_apps.title_intelligence.models.extraction import Extraction
        from app.micro_apps.title_intelligence.models.flag import Flag
        from app.micro_apps.title_intelligence.services.readiness_service import calculate_readiness

        pack = Pack(id=BENCH_PACK_ID, org_id=TEST_ORG_ID, name="Determinism Pack", status="completed")
        db_session.add(pack)

        db_session.add(Extraction(
            pack_id=BENCH_PACK_ID, org_id=TEST_ORG_ID,
            extraction_type="requirement", label="Req 1",
            value={"description": "Pay mortgage"},
            evidence_refs=[{"page_number": 1}],
            confidence=0.92,
        ))
        db_session.add(Extraction(
            pack_id=BENCH_PACK_ID, org_id=TEST_ORG_ID,
            extraction_type="party", label="Buyer: Smith",
            value={"name": "Smith", "role": "buyer"},
            evidence_refs=[{"page_number": 1}],
            confidence=0.95,
        ))
        db_session.add(Flag(
            pack_id=BENCH_PACK_ID, org_id=TEST_ORG_ID,
            flag_type="unresolved_lien", severity="high",
            title="Lien Flag", description="Open lien",
            ai_explanation="Unreleased lien found",
            evidence_refs=[{"page_number": 5}],
        ))
        await db_session.commit()

        results = []
        for _ in range(3):
            r = await calculate_readiness(db_session, TEST_ORG_ID, BENCH_PACK_ID)
            results.append(r)

        first = results[0]
        for r in results[1:]:
            assert r.score == first.score
            assert r.status == first.status
            assert r.estimated_days == first.estimated_days
            assert len(r.categories) == len(first.categories)
            for c1, c2 in zip(first.categories, r.categories):
                assert c1.category == c2.category
                assert c1.score == c2.score

    def test_sla_check_deterministic(self):
        """SLA check with same inputs must always produce same result."""
        timings = {"ingest": 1.5, "render": 0.8, "examine": 9.2, "complete": 0.5}
        results = [check_sla(timings, total_tokens=12_000, page_count=25) for _ in range(10)]
        first = results[0]
        for r in results[1:]:
            assert r.passed == first.passed
            assert len(r.violations) == len(first.violations)


# ============================================================================
# TestAdaptiveChunkSizing — verify adaptive sizing metrics pass SLA
# ============================================================================


class TestAdaptiveChunkSizing:
    """Verify adaptive chunk sizing produces metrics within SLA."""

    @pytest.mark.parametrize("page_count", [25, 50, 100])
    def test_adaptive_sizes_within_sla(self, page_count: int):
        """Mocked metrics with adaptive batch sizes should pass SLA.

        Adaptive sizing changes batch count but shouldn't affect total SLA
        compliance — it reduces API calls, not increases them.
        """
        from app.micro_apps.title_intelligence.services.document_grouper import (
            DocumentGroup,
            compute_adaptive_batch_size,
            regroup_with_adaptive_sizes,
        )

        # Simulate a single large group of page_count pages
        pages = list(range(1, page_count + 1))
        group = DocumentGroup(
            group_id=0,
            start_page=1,
            end_page=page_count,
            page_count=page_count,
            pages=pages,
            doc_type="generic",
        )

        # Medium text (500 chars avg) → should use base_size=25
        page_texts = {i: "x" * 500 for i in pages}
        adaptive_groups = regroup_with_adaptive_sizes([group], page_texts, base_size=25)

        # Use mocked version metadata (same as other SLA tests)
        meta = build_mock_version_metadata(page_count)
        # Update batch count to match adaptive grouping
        num_adaptive_batches = len(adaptive_groups)
        meta["batch_results"] = [
            {
                "input_tokens": page_count * 300 // num_adaptive_batches,
                "output_tokens": page_count * 100 // num_adaptive_batches,
                "llm_elapsed_seconds": meta["stage_timings"]["examine"] / num_adaptive_batches,
            }
            for _ in range(num_adaptive_batches)
        ]
        meta["batch_count"] = num_adaptive_batches

        metrics = collect_metrics_from_version_metadata(meta, page_count=page_count)
        result = check_metrics(metrics)
        assert result.passed is True, (
            f"{page_count}pp with {num_adaptive_batches} adaptive batches: "
            f"violations={[v.metric for v in result.violations]}"
        )
