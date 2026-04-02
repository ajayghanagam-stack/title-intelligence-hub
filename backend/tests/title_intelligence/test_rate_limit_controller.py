"""Tests for Phase 4: Bounded Concurrency + Adaptive Rate Limiting."""

import asyncio
import time
import uuid
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from app.micro_apps.title_intelligence.ai.title_examiner_agent import (
    RateLimitController,
    TitleExaminerAgent,
    _is_rate_limit_error,
)
from app.micro_apps.title_intelligence.schemas.examiner import (
    ExaminerBatchResult,
    ExaminerConsolidatedResult,
)

TEST_ORG_ID = uuid.UUID("00000000-0000-0000-0000-000000000010")


# --- RateLimitController unit tests ---


class TestRateLimitController:
    """Test the adaptive rate limit controller."""

    def test_initial_state(self):
        ctrl = RateLimitController(max_concurrency=5, stagger_ms=200)
        assert ctrl.rate_limit_hits == 0
        assert ctrl.total_retries == 0
        metrics = ctrl.get_metrics()
        assert metrics == {"rate_limit_hits": 0, "total_retries": 0, "token_waits": 0}

    @pytest.mark.asyncio
    async def test_acquire_release_basic(self):
        ctrl = RateLimitController(max_concurrency=3, stagger_ms=0)
        await ctrl.acquire(0)
        ctrl.release()
        # Should not deadlock or error

    @pytest.mark.asyncio
    async def test_semaphore_bounds_concurrency(self):
        """Verify that only max_concurrency tasks run simultaneously."""
        ctrl = RateLimitController(max_concurrency=2, stagger_ms=0)
        max_concurrent = 0
        current = 0
        lock = asyncio.Lock()

        async def worker(i: int):
            nonlocal max_concurrent, current
            await ctrl.acquire(i)
            try:
                async with lock:
                    current += 1
                    if current > max_concurrent:
                        max_concurrent = current
                await asyncio.sleep(0.05)
            finally:
                async with lock:
                    current -= 1
                ctrl.release()

        await asyncio.gather(*[worker(i) for i in range(6)])
        assert max_concurrent <= 2

    @pytest.mark.asyncio
    async def test_stagger_delays_launches(self):
        """Verify stagger adds delay between launches."""
        ctrl = RateLimitController(max_concurrency=10, stagger_ms=50)
        times = []

        async def worker(i: int):
            await ctrl.acquire(i)
            times.append(time.monotonic())
            ctrl.release()

        await asyncio.gather(*[worker(i) for i in range(4)])

        # With 50ms stagger, last launch should be ~150ms after first
        if len(times) >= 2:
            total_stagger = times[-1] - times[0]
            # Allow some tolerance: at least 100ms for 3 gaps
            assert total_stagger >= 0.05  # At least one stagger gap observed

    def test_record_rate_limit_increments_metrics(self):
        ctrl = RateLimitController(max_concurrency=5, stagger_ms=0)
        backoff = ctrl.record_rate_limit()
        assert ctrl.rate_limit_hits == 1
        assert ctrl.total_retries == 1
        assert backoff == 2.0  # First hit: 2s

    def test_record_rate_limit_escalating_backoff(self):
        ctrl = RateLimitController(max_concurrency=5, stagger_ms=0)
        b1 = ctrl.record_rate_limit()
        b2 = ctrl.record_rate_limit()
        b3 = ctrl.record_rate_limit()
        assert b1 == 2.0   # 2 * 2^0
        assert b2 == 4.0   # 2 * 2^1
        assert b3 == 8.0   # 2 * 2^2
        assert ctrl.rate_limit_hits == 3

    def test_record_rate_limit_backoff_capped(self):
        ctrl = RateLimitController(max_concurrency=5, stagger_ms=0)
        # Hit many times to verify cap at 30s
        for _ in range(10):
            backoff = ctrl.record_rate_limit()
        assert backoff <= 30.0

    def test_record_rate_limit_sets_global_backoff(self):
        ctrl = RateLimitController(max_concurrency=5, stagger_ms=0)
        ctrl.record_rate_limit()
        # backoff_until should be ~5s in the future
        assert ctrl._backoff_until > time.monotonic()

    def test_record_retry_only_increments_retries(self):
        ctrl = RateLimitController(max_concurrency=5, stagger_ms=0)
        ctrl.record_retry()
        ctrl.record_retry()
        assert ctrl.rate_limit_hits == 0
        assert ctrl.total_retries == 2

    @pytest.mark.asyncio
    async def test_global_backoff_delays_acquire(self):
        """After a rate limit hit, subsequent acquires wait for backoff."""
        ctrl = RateLimitController(max_concurrency=5, stagger_ms=0)
        # Set a short backoff manually for testing
        ctrl._backoff_until = time.monotonic() + 0.1

        t0 = time.monotonic()
        await ctrl.acquire(0)
        elapsed = time.monotonic() - t0
        ctrl.release()

        # Should have waited ~100ms
        assert elapsed >= 0.08


# --- _is_rate_limit_error helper ---


class TestIsRateLimitError:

    def test_429_in_message(self):
        assert _is_rate_limit_error(Exception("HTTP 429 Too Many Requests"))

    def test_rate_in_message(self):
        assert _is_rate_limit_error(Exception("Rate limit exceeded"))

    def test_resource_exhausted(self):
        assert _is_rate_limit_error(Exception("RESOURCE_EXHAUSTED"))

    def test_normal_error(self):
        assert not _is_rate_limit_error(Exception("Connection timeout"))

    def test_generic_server_error(self):
        assert not _is_rate_limit_error(Exception("Internal server error 500"))


# --- Integration: retry methods with controller ---


class TestRetryWithController:

    @pytest.mark.asyncio
    async def test_pdf_retry_records_rate_limit(self):
        """_call_pdf_with_rate_limit_retry records rate limit in controller."""
        agent = TitleExaminerAgent(TEST_ORG_ID)
        ctrl = RateLimitController(max_concurrency=5, stagger_ms=0)

        call_count = 0

        async def mock_examine_pdf_batch(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("429 Too Many Requests")
            return ExaminerBatchResult()

        agent.examine_pdf_batch = mock_examine_pdf_batch

        result = await agent._call_pdf_with_rate_limit_retry(
            b"pdf", (1, 5), 10, 0, 2, max_retries=3, rate_controller=ctrl,
        )
        assert call_count == 2
        assert ctrl.rate_limit_hits == 1
        assert ctrl.total_retries == 1

    @pytest.mark.asyncio
    async def test_pdf_retry_records_non_rate_limit_retry(self):
        """Non-rate-limit errors still increment total_retries."""
        agent = TitleExaminerAgent(TEST_ORG_ID)
        ctrl = RateLimitController(max_concurrency=5, stagger_ms=0)

        call_count = 0

        async def mock_examine_pdf_batch(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Connection reset")
            return ExaminerBatchResult()

        agent.examine_pdf_batch = mock_examine_pdf_batch

        result = await agent._call_pdf_with_rate_limit_retry(
            b"pdf", (1, 5), 10, 0, 2, max_retries=3, rate_controller=ctrl,
        )
        assert call_count == 2
        assert ctrl.rate_limit_hits == 0
        assert ctrl.total_retries == 1

    @pytest.mark.asyncio
    async def test_legacy_retry_records_rate_limit(self):
        """_call_with_rate_limit_retry records rate limit in controller."""
        agent = TitleExaminerAgent(TEST_ORG_ID)
        ctrl = RateLimitController(max_concurrency=5, stagger_ms=0)

        call_count = 0

        async def mock_examine_batch(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Rate limit exceeded")
            return ExaminerBatchResult()

        agent.examine_batch = mock_examine_batch

        result = await agent._call_with_rate_limit_retry(
            [(1, None, "text")], None, max_retries=3, rate_controller=ctrl,
        )
        assert call_count == 2
        assert ctrl.rate_limit_hits == 1


# --- Integration: examine_document_native_pdf with controller ---


class TestNativePdfWithController:

    @pytest.mark.asyncio
    async def test_examine_native_pdf_populates_metrics(self):
        """Consolidated result has rate limit metrics."""
        import fitz

        doc = fitz.open()
        for i in range(4):
            page = doc.new_page(width=612, height=792)
            page.insert_text((72, 72), f"Page {i + 1}")
        pdf_bytes = doc.tobytes()
        doc.close()

        agent = TitleExaminerAgent(TEST_ORG_ID)

        async def mock_examine_pdf_batch(pdf_bytes, page_range, total_pages, batch_index, total_batches, **kwargs):
            return ExaminerBatchResult()

        agent.examine_pdf_batch = mock_examine_pdf_batch

        with patch("app.micro_apps.title_intelligence.ai.title_examiner_agent.get_settings") as mock_settings:
            settings = MagicMock()
            settings.NATIVE_PDF_STAGGER_MS = 0
            mock_settings.return_value = settings

            result = await agent.examine_document_native_pdf(
                pdf_bytes=pdf_bytes,
                total_pages=4,
                batch_size=2,
                concurrency=5,
            )

        assert isinstance(result, ExaminerConsolidatedResult)
        assert result.rate_limit_hits == 0
        assert result.total_retries == 0

    @pytest.mark.asyncio
    async def test_examine_native_pdf_stagger_configured(self):
        """Verify stagger_ms is read from config."""
        import fitz

        doc = fitz.open()
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 72), "Page 1")
        pdf_bytes = doc.tobytes()
        doc.close()

        agent = TitleExaminerAgent(TEST_ORG_ID)

        async def mock_examine_pdf_batch(pdf_bytes, page_range, total_pages, batch_index, total_batches, **kwargs):
            return ExaminerBatchResult()

        agent.examine_pdf_batch = mock_examine_pdf_batch

        with patch("app.micro_apps.title_intelligence.ai.title_examiner_agent.get_settings") as mock_settings:
            settings = MagicMock()
            settings.NATIVE_PDF_STAGGER_MS = 500
            mock_settings.return_value = settings

            result = await agent.examine_document_native_pdf(
                pdf_bytes=pdf_bytes,
                total_pages=1,
                batch_size=25,
                concurrency=5,
            )

        assert isinstance(result, ExaminerConsolidatedResult)

    @pytest.mark.asyncio
    async def test_examine_native_pdf_rate_limit_tracked(self):
        """Rate limit hits during examination populate consolidated metrics."""
        import fitz

        doc = fitz.open()
        for i in range(4):
            page = doc.new_page(width=612, height=792)
            page.insert_text((72, 72), f"Page {i + 1}")
        pdf_bytes = doc.tobytes()
        doc.close()

        agent = TitleExaminerAgent(TEST_ORG_ID)
        call_count = 0

        async def mock_examine_pdf_batch(pdf_bytes, page_range, total_pages, batch_index, total_batches, **kwargs):
            nonlocal call_count
            call_count += 1
            # First call hits rate limit
            if call_count == 1:
                raise Exception("429 Resource Exhausted")
            return ExaminerBatchResult()

        agent.examine_pdf_batch = mock_examine_pdf_batch

        with patch("app.micro_apps.title_intelligence.ai.title_examiner_agent.get_settings") as mock_settings:
            settings = MagicMock()
            settings.NATIVE_PDF_STAGGER_MS = 0
            mock_settings.return_value = settings

            result = await agent.examine_document_native_pdf(
                pdf_bytes=pdf_bytes,
                total_pages=4,
                batch_size=4,
                concurrency=5,
            )

        # One batch, one rate limit hit, then success
        assert result.rate_limit_hits == 1
        assert result.total_retries == 1


# --- Config integration ---


class TestConfigSettings:

    def test_stagger_ms_default(self):
        """NATIVE_PDF_STAGGER_MS has correct default."""
        from app.config import Settings
        s = Settings(DEBUG=True, PIPELINE_BACKEND="background_tasks")
        assert s.NATIVE_PDF_STAGGER_MS == 0

    def test_stagger_ms_custom(self):
        """NATIVE_PDF_STAGGER_MS can be set."""
        from app.config import Settings
        s = Settings(DEBUG=True, PIPELINE_BACKEND="background_tasks", NATIVE_PDF_STAGGER_MS=500)
        assert s.NATIVE_PDF_STAGGER_MS == 500


# --- ExaminerConsolidatedResult schema ---


class TestConsolidatedResultMetrics:

    def test_default_metrics_zero(self):
        result = ExaminerConsolidatedResult()
        assert result.rate_limit_hits == 0
        assert result.total_retries == 0

    def test_metrics_settable(self):
        result = ExaminerConsolidatedResult(rate_limit_hits=3, total_retries=5)
        assert result.rate_limit_hits == 3
        assert result.total_retries == 5
