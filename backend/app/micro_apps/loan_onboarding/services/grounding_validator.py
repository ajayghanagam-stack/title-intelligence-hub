"""Server-side validation gate for vision-grounded extraction (Phase 1).

The new extractor returns ``{value, evidence: {page, token_indices},
confidence}`` per field. This module is the deterministic gate that
turns the model's citation into a bbox or rejects it as ``ungrounded``.
The model never returns coordinates — bboxes computed here are the only
ones that ever land on ``LOExtraction.fields[].location``.

See docs/phase0/grounding-contract.md §4 for the full spec. Eight checks
in a fixed order, fail-fast:

  1. Empty value           → ``missing``
  2. Missing evidence      → ``ungrounded``
  3. Cited page not in stack
  4. Cited token index off the page
  5. Substring overlap < 80% (case-fold + whitespace-collapse)
  6. Plausibility: union bbox height ≥ 20% page or width < 1.5%
  7. Type-format regex (currency/date/ssn/phone/email)
  8. Confidence band → ``located`` ≥ 0.85, ``tentative`` 0.65..0.85,
     else ``ungrounded``

Pure CPU. No I/O. Same inputs → identical output.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.micro_apps.loan_onboarding.schemas.extraction import (
    ExtractedField,
    FieldLocation,
)
from app.micro_apps.loan_onboarding.schemas.grounding import (
    EvidenceCitation,
    GroundedFieldRaw,
)

logger = logging.getLogger(__name__)


# ── Tunable thresholds (Phase 1) ─────────────────────────────────────


# Minimum character overlap between the model's value and the joined
# text of cited tokens (after case-fold + whitespace collapse). 80% is
# the contract default (see grounding-contract.md §4.1) — catches OCR
# whitespace artifacts and case drift without admitting hallucinations.
MIN_VALUE_TOKEN_OVERLAP: float = 0.80


# Plausibility caps on the union bbox.
MAX_UNION_HEIGHT_FRACTION: float = 0.20  # < 20% page height
MIN_UNION_WIDTH_FRACTION: float = 0.015  # > 1.5% page width


# Confidence-band cutoffs.
LOCATED_MIN_CONFIDENCE: float = 0.85
TENTATIVE_MIN_CONFIDENCE: float = 0.65


# Format regexes per data type. Keep deliberately permissive — the goal
# is to catch obvious type mismatches (a name in a currency slot), not
# to enforce canonical formatting (the LOS feed does that downstream).
_TYPE_REGEXES: dict[str, re.Pattern[str]] = {
    "currency": re.compile(r"^\$?\s*[\d,]+(?:\.\d{1,2})?$"),
    "date": re.compile(
        r"^\s*(?:\d{1,2}[\/\-]\d{1,2}[\/\-]\d{2,4}|"
        r"\d{4}[\/\-]\d{1,2}[\/\-]\d{1,2}|"
        r"[A-Za-z]+\.?\s+\d{1,2},?\s+\d{2,4})\s*$"
    ),
    "ssn": re.compile(r"^\s*\d{3}-?\d{2}-?\d{4}\s*$"),
    "phone": re.compile(
        r"^\s*\+?1?[\s\-\.]?\(?\d{3}\)?[\s\-\.]?\d{3}[\s\-\.]?\d{4}\s*$"
    ),
    "email": re.compile(r"^\s*[^@\s]+@[^@\s]+\.[^@\s]+\s*$"),
}


# ── Inputs ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class StackPage:
    """One page's OCR words, indexed for O(1) token lookup."""

    page_number: int  # 1-indexed within the stack
    word_count: int
    # bbox is (x1, y1, x2, y2) in 0..1
    words_by_index: dict[int, tuple[str, tuple[float, float, float, float]]]


@dataclass(frozen=True)
class ValidationContext:
    """Per-stack context shared across all field validations."""

    pages: dict[int, StackPage]  # keyed by 1-indexed page number


# ── Output ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GateOutcome:
    """Result of running the validation gate on one field."""

    field: ExtractedField
    rejected_reason: str | None  # None when status is located/tentative


# ── Gate ──────────────────────────────────────────────────────────────


def build_validation_context(
    pages: list[dict],
) -> ValidationContext:
    """Build a ``ValidationContext`` from a list of page dicts.

    Each ``page`` dict shape:
      ``{"page_number": int (1-indexed), "ocr_words": [OcrWordDict], ...}``
    """
    by_page: dict[int, StackPage] = {}
    for p in pages:
        try:
            page_num = int(p.get("page_number"))
        except (TypeError, ValueError):
            continue
        ocr_words = p.get("ocr_words") or []
        words_by_index: dict[
            int, tuple[str, tuple[float, float, float, float]]
        ] = {}
        for w in ocr_words:
            if not isinstance(w, dict):
                continue
            try:
                idx = int(w["index"])
                txt = str(w["text"])
                bbox = w["bbox"]
                if not (isinstance(bbox, (list, tuple)) and len(bbox) == 4):
                    continue
                bbox_t = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
            except (KeyError, TypeError, ValueError):
                continue
            words_by_index[idx] = (txt, bbox_t)
        by_page[page_num] = StackPage(
            page_number=page_num,
            word_count=len(words_by_index),
            words_by_index=words_by_index,
        )
    return ValidationContext(pages=by_page)


def validate_field(
    raw: GroundedFieldRaw,
    *,
    ctx: ValidationContext,
    data_type: str | None = None,
) -> GateOutcome:
    """Run the 8-step gate on one model-returned field.

    Returns an ``ExtractedField`` shaped for direct persistence on
    ``LOExtraction.fields[]`` plus a ``rejected_reason`` for logging
    when the field is downgraded to ``ungrounded``.
    """
    name = raw.name
    value = (raw.value or "").strip()
    confidence = max(0.0, min(1.0, float(raw.confidence)))

    # Check 1 — empty value → missing.
    if not value:
        return GateOutcome(
            field=ExtractedField(
                name=name, value="", confidence=0.0, status="missing", location=None,
            ),
            rejected_reason=None,
        )

    # Check 2 — evidence must be present.
    if raw.evidence is None:
        return _ungrounded(name, value, confidence, "no_evidence_cite")

    # Check 3 — cited page exists in stack.
    page = ctx.pages.get(raw.evidence.page)
    if page is None:
        return _ungrounded(name, value, confidence, "page_not_in_stack")

    # Check 4 — every cited token index exists on the cited page.
    cited_words: list[tuple[str, tuple[float, float, float, float]]] = []
    for idx in raw.evidence.token_indices:
        word = page.words_by_index.get(idx)
        if word is None:
            return _ungrounded(
                name, value, confidence,
                f"token_index_{idx}_off_page_{raw.evidence.page}",
            )
        cited_words.append(word)

    if not cited_words:
        return _ungrounded(name, value, confidence, "empty_token_citation")

    # Check 5 — substring overlap.
    cited_text = " ".join(w[0] for w in cited_words)
    overlap = _value_token_overlap(value, cited_text)
    if overlap < MIN_VALUE_TOKEN_OVERLAP:
        return _ungrounded(
            name, value, confidence,
            f"value_token_overlap_{overlap:.2f}_below_{MIN_VALUE_TOKEN_OVERLAP:.2f}",
        )

    # Check 6 — plausibility on union bbox.
    union = _union_bbox([w[1] for w in cited_words])
    height = union[3] - union[1]
    width = union[2] - union[0]
    if height >= MAX_UNION_HEIGHT_FRACTION:
        return _ungrounded(name, value, confidence, f"bbox_height_{height:.3f}_too_tall")
    if width < MIN_UNION_WIDTH_FRACTION:
        return _ungrounded(name, value, confidence, f"bbox_width_{width:.3f}_too_narrow")

    # Check 7 — type-format regex (only if data_type names a known regex).
    if data_type and data_type in _TYPE_REGEXES:
        if not _TYPE_REGEXES[data_type].match(value):
            return _ungrounded(
                name, value, confidence,
                f"value_format_mismatch_{data_type}",
            )

    # Check 8 — confidence band.
    if confidence >= LOCATED_MIN_CONFIDENCE:
        status = "located"
    elif confidence >= TENTATIVE_MIN_CONFIDENCE:
        status = "tentative"
    else:
        return _ungrounded(name, value, confidence, f"confidence_{confidence:.2f}_below_band")

    location = FieldLocation(
        page=raw.evidence.page,
        bbox=[round(float(c), 6) for c in union],
        evidence_token_indices=list(raw.evidence.token_indices),
        ocr_word_count=page.word_count,
    )
    return GateOutcome(
        field=ExtractedField(
            name=name,
            value=value,
            confidence=confidence,
            status=status,  # type: ignore[arg-type]
            location=location,
        ),
        rejected_reason=None,
    )


def _ungrounded(
    name: str, value: str, confidence: float, reason: str
) -> GateOutcome:
    """Build an ungrounded outcome — value retained, no bbox."""
    return GateOutcome(
        field=ExtractedField(
            name=name,
            value=value,
            confidence=confidence,
            status="ungrounded",
            location=None,
        ),
        rejected_reason=reason,
    )


# ── Helpers ──────────────────────────────────────────────────────────


_NORM_RE = re.compile(r"\s+")


def _normalize(s: str) -> str:
    """Lowercase + collapse whitespace + drop most punctuation.

    Used by the substring-overlap check so OCR whitespace artifacts
    (``Marcus  T.  Webb`` vs. ``Marcus T. Webb``), case (``MARCUS WEBB``),
    and trailing punctuation (``Webb,``) don't sink an otherwise valid
    citation.
    """
    s = s.lower()
    # Drop ASCII punctuation but keep digits, letters, and ``.`` (so
    # ``$84,500.00`` ↔ ``84500.00`` aligns once we strip ``$,``).
    s = re.sub(r"[^\w\.\s]", "", s)
    s = re.sub(r",", "", s)  # commas inside numbers
    s = _NORM_RE.sub(" ", s).strip()
    return s


def _value_token_overlap(value: str, cited_text: str) -> float:
    """Fraction of ``value``'s normalized chars covered by ``cited_text``.

    Defined as: take the longest contiguous common substring after
    normalization; divide by the length of the normalized value. 1.0 if
    the cited text fully contains the value; smaller when only a portion
    matches. Returns 0.0 if either side normalizes to empty.
    """
    nv = _normalize(value)
    nc = _normalize(cited_text)
    if not nv or not nc:
        return 0.0
    if nv in nc:
        return 1.0
    # Longest common substring — short strings only, so O(n*m) is fine.
    best = 0
    n, m = len(nv), len(nc)
    # DP row to keep memory at O(min(n,m)).
    prev_row = [0] * (m + 1)
    for i in range(1, n + 1):
        cur_row = [0] * (m + 1)
        for j in range(1, m + 1):
            if nv[i - 1] == nc[j - 1]:
                cur_row[j] = prev_row[j - 1] + 1
                if cur_row[j] > best:
                    best = cur_row[j]
        prev_row = cur_row
    return best / max(1, len(nv))


def _union_bbox(
    bboxes: list[tuple[float, float, float, float]],
) -> tuple[float, float, float, float]:
    """Min/max corner over a list of 0..1 bboxes."""
    x1 = min(b[0] for b in bboxes)
    y1 = min(b[1] for b in bboxes)
    x2 = max(b[2] for b in bboxes)
    y2 = max(b[3] for b in bboxes)
    return (x1, y1, x2, y2)
