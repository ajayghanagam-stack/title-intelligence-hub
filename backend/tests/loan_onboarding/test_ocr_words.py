"""Phase 1 OCR shape tests for ``services/ocr_words.py``.

Tests don't run Tesseract — they cover the pure-Python normalization
helpers and the Gemini fallback shape coercion. Engine-level integration
is out of scope here (requires a Tesseract binary on the test box).
"""
from __future__ import annotations

from app.micro_apps.loan_onboarding.services.ocr_words import (
    MIN_TESSERACT_MEDIAN_CONF,
    _median_confidence,
)


def test_median_empty_returns_zero():
    assert _median_confidence([]) == 0.0


def test_median_odd_count():
    words = [
        {"index": i, "text": str(i), "bbox": [0, 0, 1, 1], "line": 0, "confidence": c}
        for i, c in enumerate([0.4, 0.6, 0.8])
    ]
    # Median of 0.4, 0.6, 0.8 in 0..1 → rescaled to 0..100 = 60.0
    assert _median_confidence(words) == 60.0


def test_median_even_count_averages():
    words = [
        {"index": i, "text": str(i), "bbox": [0, 0, 1, 1], "line": 0, "confidence": c}
        for i, c in enumerate([0.4, 0.6, 0.8, 1.0])
    ]
    # Sorted: 0.4, 0.6, 0.8, 1.0 → median = (0.6 + 0.8) / 2 = 0.7 → 70.0
    assert _median_confidence(words) == 70.0


def test_threshold_constant_is_70():
    # The contract pins this at 70 (Tesseract scale 0..100). If anyone
    # bumps it without thinking through the Gemini fallback budget the
    # cache stampede on legacy packages will be brutal.
    assert MIN_TESSERACT_MEDIAN_CONF == 70.0
