"""Unit tests for the Phase 1 deterministic grounding gate.

Covers each of the 8 fail-fast checks in
``services/grounding_validator.py`` plus the union-bbox / overlap helpers.
Pure CPU; no fixtures, no DB.
"""
from __future__ import annotations

from app.micro_apps.loan_onboarding.schemas.grounding import (
    EvidenceCitation,
    GroundedFieldRaw,
)
from app.micro_apps.loan_onboarding.services.grounding_validator import (
    LOCATED_MIN_CONFIDENCE,
    MIN_VALUE_TOKEN_OVERLAP,
    TENTATIVE_MIN_CONFIDENCE,
    build_validation_context,
    validate_field,
    _normalize,
    _union_bbox,
    _value_token_overlap,
)


# ── Fixtures ─────────────────────────────────────────────────────────


def _word(idx: int, text: str, bbox: tuple[float, float, float, float]) -> dict:
    return {"index": idx, "text": text, "bbox": list(bbox)}


def _ctx(words_by_page: dict[int, list[dict]]):
    return build_validation_context([
        {"page_number": pn, "ocr_words": ws}
        for pn, ws in words_by_page.items()
    ])


# A single-page sample with a borrower name spread across two tokens.
PAGE_WITH_NAME = [
    _word(0, "Borrower:", (0.05, 0.10, 0.15, 0.12)),
    _word(1, "Marcus", (0.20, 0.10, 0.30, 0.12)),
    _word(2, "Webb", (0.32, 0.10, 0.40, 0.12)),
    _word(3, "Loan", (0.05, 0.20, 0.10, 0.22)),
    _word(4, "Amount:", (0.12, 0.20, 0.20, 0.22)),
    _word(5, "$84,500.00", (0.22, 0.20, 0.32, 0.22)),
]


# ── Check 1: empty value → missing ────────────────────────────────────


def test_empty_value_returns_missing():
    raw = GroundedFieldRaw(name="borrower_name", value="", evidence=None, confidence=0.0)
    out = validate_field(raw, ctx=_ctx({1: PAGE_WITH_NAME}))
    assert out.field.status == "missing"
    assert out.field.location is None
    assert out.rejected_reason is None


# ── Check 2: missing evidence → ungrounded ────────────────────────────


def test_no_evidence_marks_ungrounded():
    raw = GroundedFieldRaw(
        name="borrower_name", value="Marcus Webb", evidence=None, confidence=0.95,
    )
    out = validate_field(raw, ctx=_ctx({1: PAGE_WITH_NAME}))
    assert out.field.status == "ungrounded"
    assert out.field.value == "Marcus Webb"
    assert out.field.location is None
    assert out.rejected_reason == "no_evidence_cite"


# ── Check 3: cited page not in stack ──────────────────────────────────


def test_unknown_page_marks_ungrounded():
    raw = GroundedFieldRaw(
        name="borrower_name",
        value="Marcus Webb",
        evidence=EvidenceCitation(page=99, token_indices=[1, 2]),
        confidence=0.95,
    )
    out = validate_field(raw, ctx=_ctx({1: PAGE_WITH_NAME}))
    assert out.field.status == "ungrounded"
    assert out.rejected_reason == "page_not_in_stack"


# ── Check 4: token index off the page ─────────────────────────────────


def test_offpage_token_index_marks_ungrounded():
    raw = GroundedFieldRaw(
        name="borrower_name",
        value="Marcus Webb",
        evidence=EvidenceCitation(page=1, token_indices=[1, 99]),
        confidence=0.95,
    )
    out = validate_field(raw, ctx=_ctx({1: PAGE_WITH_NAME}))
    assert out.field.status == "ungrounded"
    assert "off_page" in (out.rejected_reason or "")


# ── Check 5: substring overlap < 80% ──────────────────────────────────


def test_low_overlap_marks_ungrounded():
    # Cited tokens are "Loan Amount:" but the value claims to be "ABC".
    raw = GroundedFieldRaw(
        name="loan_amount",
        value="ABC",
        evidence=EvidenceCitation(page=1, token_indices=[3, 4]),
        confidence=0.95,
    )
    out = validate_field(raw, ctx=_ctx({1: PAGE_WITH_NAME}))
    assert out.field.status == "ungrounded"
    assert "overlap" in (out.rejected_reason or "")


def test_high_overlap_passes():
    raw = GroundedFieldRaw(
        name="borrower_name",
        value="Marcus Webb",
        evidence=EvidenceCitation(page=1, token_indices=[1, 2]),
        confidence=0.95,
    )
    out = validate_field(raw, ctx=_ctx({1: PAGE_WITH_NAME}))
    assert out.field.status == "located"
    assert out.field.location is not None
    assert out.field.location.page == 1
    assert out.field.location.evidence_token_indices == [1, 2]
    # Bbox is union of tokens 1 and 2: (0.20, 0.10) → (0.40, 0.12)
    assert out.field.location.bbox[0] == 0.20
    assert out.field.location.bbox[2] == 0.40


# ── Check 6: plausibility caps ────────────────────────────────────────


def test_too_tall_bbox_marks_ungrounded():
    # One sliver token spanning 30% of page height — implausible.
    sliver_page = [
        _word(0, "Marcus", (0.1, 0.1, 0.2, 0.45)),  # height 35%
    ]
    raw = GroundedFieldRaw(
        name="borrower_name",
        value="Marcus",
        evidence=EvidenceCitation(page=1, token_indices=[0]),
        confidence=0.95,
    )
    out = validate_field(raw, ctx=_ctx({1: sliver_page}))
    assert out.field.status == "ungrounded"
    assert "too_tall" in (out.rejected_reason or "")


def test_too_narrow_bbox_marks_ungrounded():
    narrow_page = [
        _word(0, "X", (0.10, 0.10, 0.105, 0.12)),  # width 0.5%
    ]
    raw = GroundedFieldRaw(
        name="initials",
        value="X",
        evidence=EvidenceCitation(page=1, token_indices=[0]),
        confidence=0.95,
    )
    out = validate_field(raw, ctx=_ctx({1: narrow_page}))
    assert out.field.status == "ungrounded"
    assert "too_narrow" in (out.rejected_reason or "")


# ── Check 7: type-format regex ────────────────────────────────────────


def test_currency_format_mismatch_marks_ungrounded():
    raw = GroundedFieldRaw(
        name="loan_amount",
        value="not-a-currency",
        evidence=EvidenceCitation(page=1, token_indices=[5]),
        confidence=0.95,
    )
    # value extracted overlaps cited token? — "$84,500.00" contains nothing
    # of "not-a-currency" so check 5 fires first. To isolate check 7, point
    # the cite at a text token whose normalized form happens to contain
    # the value… we'll instead use a bare numeric overlap then check the
    # regex by feeding a value that overlaps the cited token text but
    # fails the currency regex.
    page = [_word(0, "abc-def-not", (0.1, 0.1, 0.3, 0.12))]
    raw2 = GroundedFieldRaw(
        name="loan_amount",
        value="abc-def-not",
        evidence=EvidenceCitation(page=1, token_indices=[0]),
        confidence=0.95,
    )
    out = validate_field(raw2, ctx=_ctx({1: page}), data_type="currency")
    assert out.field.status == "ungrounded"
    assert "format" in (out.rejected_reason or "")


def test_currency_format_match_passes():
    raw = GroundedFieldRaw(
        name="loan_amount",
        value="$84,500.00",
        evidence=EvidenceCitation(page=1, token_indices=[5]),
        confidence=0.95,
    )
    out = validate_field(raw, ctx=_ctx({1: PAGE_WITH_NAME}), data_type="currency")
    assert out.field.status == "located"


# ── Check 8: confidence band ──────────────────────────────────────────


def test_confidence_band_located():
    raw = GroundedFieldRaw(
        name="borrower_name",
        value="Marcus Webb",
        evidence=EvidenceCitation(page=1, token_indices=[1, 2]),
        confidence=LOCATED_MIN_CONFIDENCE,
    )
    out = validate_field(raw, ctx=_ctx({1: PAGE_WITH_NAME}))
    assert out.field.status == "located"


def test_confidence_band_tentative():
    raw = GroundedFieldRaw(
        name="borrower_name",
        value="Marcus Webb",
        evidence=EvidenceCitation(page=1, token_indices=[1, 2]),
        confidence=(LOCATED_MIN_CONFIDENCE + TENTATIVE_MIN_CONFIDENCE) / 2,
    )
    out = validate_field(raw, ctx=_ctx({1: PAGE_WITH_NAME}))
    assert out.field.status == "tentative"


def test_confidence_band_below_floor_marks_ungrounded():
    raw = GroundedFieldRaw(
        name="borrower_name",
        value="Marcus Webb",
        evidence=EvidenceCitation(page=1, token_indices=[1, 2]),
        confidence=TENTATIVE_MIN_CONFIDENCE - 0.01,
    )
    out = validate_field(raw, ctx=_ctx({1: PAGE_WITH_NAME}))
    assert out.field.status == "ungrounded"
    assert "confidence" in (out.rejected_reason or "")


# ── Helpers ───────────────────────────────────────────────────────────


def test_normalize_collapses_whitespace_and_punct():
    # Periods are preserved (so "$84,500.00" → "84500.00" aligns), commas
    # are dropped, runs of spaces collapse to single spaces, casing folds.
    assert _normalize("  Marcus  T.  Webb,  ") == "marcus t. webb"
    assert _normalize("$84,500.00") == "84500.00"


def test_value_token_overlap_full_containment_returns_one():
    assert _value_token_overlap("Marcus Webb", "Borrower: Marcus Webb") == 1.0


def test_value_token_overlap_below_threshold():
    # value is much longer than cited
    overlap = _value_token_overlap("Marcus Theodore Webb III", "Marcus")
    assert overlap < MIN_VALUE_TOKEN_OVERLAP


def test_union_bbox_computes_envelope():
    bboxes = [(0.10, 0.20, 0.15, 0.25), (0.30, 0.18, 0.35, 0.22)]
    assert _union_bbox(bboxes) == (0.10, 0.18, 0.35, 0.25)


# ── Integration: same input → identical output ────────────────────────


def test_determinism_same_input_same_output():
    raw = GroundedFieldRaw(
        name="borrower_name",
        value="Marcus Webb",
        evidence=EvidenceCitation(page=1, token_indices=[1, 2]),
        confidence=0.95,
    )
    ctx = _ctx({1: PAGE_WITH_NAME})
    a = validate_field(raw, ctx=ctx)
    b = validate_field(raw, ctx=ctx)
    assert a == b
