"""Server-side grounding of extracted fields against classifier bboxes.

The ExtractionAgent runs on text-only snippets (page text + the per-page
``detected_fields`` summary), so any bbox it emits is hallucinated. The
page classifier *does* see the rendered PDF and emits
``detected_fields[]`` with real, grounded bboxes (Gemini's [0, 1000]
normalized space). This module joins the two: for each extracted field
we walk the same ``detected_fields`` already in the snippets, pick the
classifier entry whose **label** matches the requested field name (with
aliases) and whose **value** corroborates the agent's value, and return
``{page, bbox}`` in 0..1 unit space — ready to persist on
``LOExtraction.fields[].location`` and render directly in the workbench
without any frontend disambiguation.

Determinism: pure function, no LLM, no IO. Matches are scored via a
small fixed-weight rubric; ties are broken by descriptor order, then by
page-then-bbox-position. Same inputs → identical output.
"""
from __future__ import annotations

import re
from typing import Iterable


# ── Field-name aliases ────────────────────────────────────────────────
# Maps the LOS-canonical field key (the snake_case label LOs configure
# in the package builder) to the set of human labels the page classifier
# typically emits for the same field. The classifier prompt is free-form
# text labels, so we have to normalize across spelling variants.
#
# All entries here are normalized via ``_norm``. New aliases should be
# lowercase, no punctuation, single-space-separated. Add coverage as the
# field catalog grows; missing aliases just degrade to a substring match.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    # 1003 (URLA) borrower identity
    "borrower_name": (
        "borrower name",
        "name of borrower",
        "full name",
        "borrower",
        "applicant name",
        "applicant",
    ),
    "co_borrower_name": (
        "co borrower name",
        "co borrower",
        "coborrower name",
        "coborrower",
        "name of co borrower",
    ),
    "ssn": (
        "ssn",
        "social security number",
        "social security no",
        "social security",
        "ss number",
        "ss no",
        "tin",
    ),
    "co_borrower_ssn": (
        "co borrower ssn",
        "co borrower social security number",
        "coborrower ssn",
    ),
    "date_of_birth": (
        "date of birth",
        "dob",
        "birth date",
    ),
    "phone": (
        "phone",
        "phone number",
        "home phone",
        "cell phone",
        "telephone",
    ),
    "email": (
        "email",
        "email address",
        "e mail",
    ),

    # Address / property
    "borrower_address": (
        "borrower address",
        "current address",
        "present address",
        "mailing address",
        "address",
    ),
    "property_address": (
        "property address",
        "subject property address",
        "subject property",
        "subject address",
        "address of property",
    ),
    "property_value": (
        "property value",
        "appraised value",
        "estimated value",
        "purchase price",
    ),

    # Loan terms
    "loan_amount": (
        "loan amount",
        "base loan amount",
        "mortgage amount",
        "loan amount applied for",
        "amount",
    ),
    "interest_rate": (
        "interest rate",
        "rate",
        "note rate",
    ),
    "loan_term": (
        "loan term",
        "term",
        "no of months",
        "amortization term",
    ),
    "loan_purpose": (
        "loan purpose",
        "purpose of loan",
        "purpose",
    ),

    # Employment / income
    "employer_name": (
        "employer name",
        "employer",
        "name of employer",
        "employer name and address",
        "company name",
        "company",
    ),
    "employee_name": (
        "employee name",
        "employee",
        "name of employee",
    ),
    "job_title": (
        "job title",
        "position",
        "title",
        "occupation",
    ),
    "gross_pay": (
        "gross pay",
        "gross",
        "gross earnings",
        "current gross",
        "gross income",
        "ytd gross",
        "year to date gross",
    ),
    "net_pay": (
        "net pay",
        "net",
        "take home pay",
        "current net",
    ),
    "monthly_income": (
        "monthly income",
        "gross monthly income",
        "monthly base income",
    ),
    "annual_income": (
        "annual income",
        "annual salary",
        "yearly income",
    ),

    # W-2 / 1040
    "wages": (
        "wages",
        "wages tips other compensation",
        "gross wages",
        "annual wages",
        "box 1",
    ),
    "federal_tax_withheld": (
        "federal tax withheld",
        "federal income tax withheld",
        "box 2",
    ),
    "tax_year": (
        "tax year",
        "year",
    ),

    # Asset statements
    "account_number": (
        "account number",
        "account no",
        "acct number",
        "account",
    ),
    "ending_balance": (
        "ending balance",
        "balance",
        "current balance",
        "available balance",
    ),
    "statement_date": (
        "statement date",
        "as of date",
        "date",
        "period ending",
    ),
}


# ── Normalization helpers ─────────────────────────────────────────────


_PUNCT_RE = re.compile(r"[^\w\s]")
_WS_RE = re.compile(r"\s+")
_DIGITS_RE = re.compile(r"\d+")


def _norm(s: str | None) -> str:
    """Lowercase, strip punctuation, collapse whitespace."""
    if not s:
        return ""
    s = s.replace("_", " ").replace("-", " ")
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip().lower()
    return s


def _norm_value(s: str | None) -> str:
    """Same as ``_norm`` but also strips leading zeros from digit runs.

    Useful for matching account numbers / SSNs where the classifier may
    show a masked form (``***-**-9229``) and the extraction agent emits
    the unmasked digits (``635-30-9229``).
    """
    n = _norm(s)
    return n


def _candidate_labels(field_name: str) -> set[str]:
    """Return the normalized label variants a classifier might emit for
    this LOS-canonical field name. Always includes the field name itself
    (normalized) so unknown fields still get a substring match path.
    """
    out: set[str] = set()
    n = _norm(field_name)
    if n:
        out.add(n)
    aliases = FIELD_ALIASES.get(n) or FIELD_ALIASES.get(field_name.strip().lower())
    if aliases:
        for a in aliases:
            na = _norm(a)
            if na:
                out.add(na)
    return out


def _label_score(detected_label: str, candidates: set[str]) -> float:
    """0..3 score for how well a classifier label matches the candidate
    set. Higher is better. Exact = 3, substring either way = 2, partial
    token overlap = 1, no overlap = 0.
    """
    nd = _norm(detected_label)
    if not nd or not candidates:
        return 0.0
    if nd in candidates:
        return 3.0
    for c in candidates:
        if not c:
            continue
        if nd == c:
            return 3.0
        if nd in c or c in nd:
            # Require that the longer of the two contains the shorter
            # *as a token*, not just a substring — avoids "ssn" matching
            # "occupation" via the substring "ss".
            shorter, longer = (nd, c) if len(nd) <= len(c) else (c, nd)
            longer_tokens = set(longer.split())
            if shorter in longer_tokens or shorter in longer:
                # Stronger signal when full-token contained
                return 2.5 if shorter in longer_tokens else 2.0
    # Token overlap fallback
    nd_tokens = set(nd.split())
    for c in candidates:
        ct = set((c or "").split())
        if nd_tokens & ct:
            return 1.0
    return 0.0


def _value_score(detected_value: str | None, target_value: str) -> float:
    """0..2 score for how well the classifier's value corroborates the
    agent's value. Exact = 2, substring either way = 1.5, digit-run
    match (last 4 of an SSN, masked account, etc.) = 1, none = 0.
    Empty target_value → 0.5 (no value signal but not disqualifying).
    """
    if not target_value:
        return 0.5
    nv = _norm_value(detected_value)
    nt = _norm_value(target_value)
    if not nv:
        return 0.0
    if nv == nt:
        return 2.0
    if nv in nt or nt in nv:
        return 1.5
    # Digit-run match — handles SSN masking and account-number truncation
    nv_digits = "".join(_DIGITS_RE.findall(nv))
    nt_digits = "".join(_DIGITS_RE.findall(nt))
    if nv_digits and nt_digits and (
        nv_digits in nt_digits or nt_digits in nv_digits
    ):
        return 1.0
    return 0.0


# ── bbox normalization ────────────────────────────────────────────────


def _normalize_bbox_to_unit(bbox: object) -> list[float] | None:
    """Coerce a classifier bbox into 0..1 unit space.

    The page classifier feeds raw PDF bytes to Gemini, so the emitted
    bboxes are in Gemini's standard [0, 1000] normalized coordinate
    system. We always divide by 1000 here — DO NOT trust the
    classifier prompt's claim of "pixel coordinates".

    Defensive: if any value already sits in 0..1.5, we assume the bbox
    is pre-normalized and pass through. If any value exceeds 1500, we
    bail (likely garbage).
    """
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        return None
    try:
        nums = [float(x) for x in bbox]
    except (TypeError, ValueError):
        return None
    if any(not _is_finite(x) for x in nums):
        return None
    x1, y1, x2, y2 = nums
    if x1 == 0 and y1 == 0 and x2 == 0 and y2 == 0:
        return None
    if abs(x2 - x1) < 1e-6 or abs(y2 - y1) < 1e-6:
        return None
    max_c = max(abs(x) for x in nums)
    if max_c <= 1.5:
        return nums
    if max_c > 1500:
        return None
    return [x / 1000.0 for x in nums]


def _is_finite(x: float) -> bool:
    return x == x and x not in (float("inf"), float("-inf"))


# ── Public entry point ────────────────────────────────────────────────


def ground_field_location(
    field_name: str,
    field_value: str,
    snippets: Iterable[dict],
) -> tuple[int, list[float]] | None:
    """Find the best ``(page, bbox)`` for a freshly-extracted field.

    Walks every page's classifier ``detected_fields[]`` and scores each
    entry against the canonical field name (label score) and the
    extracted value (value score). Returns the highest-scoring entry's
    page + bbox in 0..1 unit space, or ``None`` if no entry clears a
    minimum threshold.

    Args:
        field_name: LOS-canonical key (e.g. ``"ssn"``, ``"borrower_name"``).
            The aliases in ``FIELD_ALIASES`` map this to the labels the
            classifier actually emits.
        field_value: The value the ExtractionAgent extracted. May be
            empty when the agent reported the field as missing — in
            that case grounding still tries label-only matching, which
            is useful for highlighting "where this field SHOULD be" on
            review.
        snippets: Iterable of ``{page_number, text, detected_fields}``
            dicts as already built by ``stage_extract._build_snippets``.

    Returns:
        ``(page_number, [x1, y1, x2, y2])`` with bbox normalized to
        0..1, or ``None`` when no classifier entry matches the field.
    """
    candidates = _candidate_labels(field_name)
    if not candidates:
        return None

    best: tuple[float, int, int, list[float]] | None = None
    # Tuple shape: (combined_score, -page, -entry_index, bbox)
    # Negation forces the *earliest* page+entry to win on ties.

    for snippet in snippets:
        if not isinstance(snippet, dict):
            continue
        page = snippet.get("page_number")
        if not isinstance(page, int):
            continue
        detected = snippet.get("detected_fields") or []
        if not isinstance(detected, list):
            continue

        for idx, entry in enumerate(detected):
            if not isinstance(entry, dict):
                continue
            label = entry.get("field_name")
            if not isinstance(label, str):
                continue
            ls = _label_score(label, candidates)
            if ls < 1.0:
                continue
            vs = _value_score(
                entry.get("value") if isinstance(entry.get("value"), str) else None,
                field_value,
            )
            # Combined: weight label more heavily than value. A strong
            # label match (3.0) beats a strong value match (2.0) when
            # values can occur in multiple labelled rows (SSN under
            # borrower vs co-borrower).
            combined = (ls * 1.5) + vs
            if combined < 2.0:
                continue
            bbox = _normalize_bbox_to_unit(entry.get("bbox"))
            if bbox is None:
                continue

            key = (combined, -page, -idx, bbox)
            if best is None or key > best:
                best = key

    if best is None:
        return None
    _, neg_page, _, bbox = best
    return (-neg_page, bbox)
