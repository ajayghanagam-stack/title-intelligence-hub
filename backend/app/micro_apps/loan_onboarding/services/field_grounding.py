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

    # Asset / bank statements
    "account_number": (
        "account number",
        "account no",
        "account #",
        "acct number",
        "account",
    ),
    "account_holder_name": (
        "account holder name",
        "account holder",
        "account name",
        "name on account",
        "accountholder name",
    ),
    "ending_balance": (
        "ending balance",
        "balance",
        "current balance",
        "available balance",
        "ending account value",
        "ending market value",
        "ending portfolio value",
    ),
    "beginning_balance": (
        "beginning balance",
        "starting balance",
        "opening balance",
    ),
    "statement_date": (
        "statement date",
        "as of date",
    ),
    "statement_period": (
        "statement period",
        "report period",
        "report date range",
        "report date",
        "statement period start date",
        "statement period end date",
        "period ending",
        "period beginning",
    ),
    "institution_name": (
        "institution name",
        "bank name",
        "financial institution",
    ),

    # Paystub
    "pay_period": (
        "pay period",
        "pay date",
        "period beginning",
        "period ending",
        "period start date",
        "period end date",
        "period start",
        "period end",
        "pay period beginning",
        "pay period ending",
    ),

    # Loan-form metadata that LOs commonly extract
    "loan_number": (
        "loan number",
        "loan no",
        "loan id",
        "loan identifier",
        "lender loan no universal loan identifier",
        "lender loan no",
        "universal loan identifier",
        "universal loan id",
        "rsmc loan number",
    ),
    "lender_name": (
        "lender name",
        "lender",
        "name of lender",
        "lender broker",
        "lender client",
    ),
    "loan_originator_name": (
        "loan originator name",
        "loan officer name",
        "mlo name",
        "mortgage loan originator",
    ),
    "nmls_id": (
        "nmls id",
        "nmlsr id",
        "loan originator nmlsr id",
        "mlo nmls",
        "loan originator nmls id",
    ),
    "signature_date": (
        "signature date",
        "date signed",
        "signed date",
    ),

    # Identity / IDs
    "dl_number": (
        "dl number",
        "dl no",
        "driver license number",
        "drivers license number",
        "license number",
    ),

    # Insurance / flood
    "policy_number": (
        "policy number",
        "policy no",
    ),
    "policy_period": (
        "policy period",
        "effective period",
    ),
    "named_insured": (
        "named insured",
        "insured",
        "insured name",
    ),
    "flood_zone": (
        "flood zone",
        "flood zone designation",
    ),

    # Title / deed parties
    "grantor": (
        "grantor",
        "grantor name",
        "name of grantor",
    ),
    "grantee": (
        "grantee",
        "grantee name",
        "name of grantee",
    ),
    "seller_name": (
        "seller",
        "seller name",
        "name of seller",
    ),
    "buyer_name": (
        "buyer",
        "buyer name",
        "name of buyer",
    ),

    # Notary / affidavit
    "notary_name": (
        "notary name",
        "notary public name",
        "notary public",
    ),
    "affiant_name": (
        "affiant name",
        "affiant",
        "declarant name",
        "declarant",
    ),
    "donor_name": (
        "donor name",
        "name of donor",
        "donor",
    ),
    "signer_name": (
        "signer name",
        "signed by",
        "signer",
    ),

    # Tax forms
    "taxpayer_name": (
        "taxpayer name",
        "name of taxpayer",
    ),

    # File / reference numbers
    "file_number": (
        "file number",
        "file no",
        "file id",
        "file",
    ),

    # Closing Disclosure (CD) — by far the highest-volume uncovered
    # bucket on real loan packages. The 5-page CD form repeats fee
    # rows on pages 2–3 with a single label and many values, so
    # ``fee_description`` is intentionally generic; consumers
    # disambiguate by value.
    "fee_description": (
        "fee description",
        "fee name",
        "description of fee",
        "loan cost description",
        "other cost description",
        "service",
        "service description",
    ),
    "cash_to_close": (
        "cash to close",
        "estimated cash to close",
        "total cash to close",
        "cash from to borrower",
        "from borrower",
        "from to borrower",
    ),
    "total_closing_costs": (
        "total closing costs",
        "total loan costs",
        "total other costs",
        "closing costs",
        "j total closing costs",
        "d total loan costs",
        "i total other costs",
    ),

    # Appraisal / sales contract
    "appraiser_name": (
        "appraiser name",
        "appraiser",
        "name of appraiser",
        "appraiser signature",
    ),
    "effective_date_of_appraisal": (
        "effective date of appraisal",
        "effective date",
        "date of appraisal",
        "appraisal effective date",
        "date of value",
    ),
    "sale_price": (
        "sale price",
        "sales price",
        "contract sales price",
        "purchase price",
        "appraised value",
    ),
    "sales_contract_price": (
        "sales contract price",
        "contract price",
        "contract sales price",
        "purchase contract price",
    ),

    # Credit report
    "credit_score": (
        "credit score",
        "fico score",
        "fico",
        "score",
        "representative score",
        "middle score",
    ),

    # Title commitment / policy
    "commitment_number": (
        "commitment number",
        "commitment no",
        "title commitment number",
        "commitment id",
    ),

    # Notary / affidavit dates
    "commission_expiration_date": (
        "commission expiration date",
        "commission expires",
        "my commission expires",
        "notary commission expiration",
        "commission expiration",
    ),
    "execution_date": (
        "execution date",
        "executed on",
        "date of execution",
        "executed this date",
    ),
}


# ── Admin / structural label filter ───────────────────────────────────
# Labels the page classifier sometimes emits for *form scaffolding*
# rather than *extractable data*: page navigation aids, form revision
# stamps, section headers, checkbox stems, signature-line markers, etc.
# These are real labels the classifier produces, but they don't
# correspond to any LOS field. We exclude them from coverage probes so
# the alias map's coverage % reflects real field gaps, not noise.
#
# All entries are matched against the *normalized* label (``_norm``):
# lowercase, punctuation-stripped, single-spaced. Add patterns
# conservatively — false-positives here turn a legitimate field into
# an unground-able one.
_ADMIN_LABELS: frozenset[str] = frozenset({
    # Page navigation / pagination
    "page",
    "page number",
    "page no",
    "pg",
    # Form metadata
    "form",
    "form number",
    "form no",
    "form name",
    "form version",
    "form revision",
    "form date",
    "revision",
    "revision date",
    "rev",
    "rev date",
    "version",
    # Section / structural headers
    "section",
    "subsection",
    "part",
    "header",
    "footer",
    "title",  # form title, not employment "title" — see _ADMIN_LABEL_GUARD
    # Boolean / checkbox stems
    "yes",
    "no",
    "yes no",
    "n a",
    "na",
    "not applicable",
    "checkbox",
    "check box",
    "check one",
    "select one",
    # Signature scaffolding (the *line*, not a real signer field)
    "signature",
    "signature line",
    "sign here",
    "initials",
    "x",
    # Catch-all instruction labels
    "instructions",
    "note",
    "notes",
    "see attached",
    "see below",
    "see above",
    "continued",
    "continuation",
})


def is_extraction_worthy_label(label: str | None) -> bool:
    """Return ``True`` if ``label`` looks like a real data field (and
    therefore worth scoring for alias coverage), ``False`` if it's
    form scaffolding the classifier sometimes emits.

    Used by coverage probes to compute "% of *extractable* labels
    aliased" rather than "% of *all* labels aliased" — the latter is
    permanently capped by structural noise that no alias would ever
    bridge to a real field.

    The check is intentionally conservative: an unknown label is
    treated as worthy. Only labels that exactly match an entry in
    ``_ADMIN_LABELS`` (after normalization) are filtered out.
    """
    n = _norm(label)
    if not n:
        return False
    if n in _ADMIN_LABELS:
        return False
    # Pure-digit labels (e.g. classifier emitting "1.", "23")
    if n.replace(" ", "").isdigit():
        return False
    return True


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
    set. Higher is better.
      3.0 — exact normalized match
      2.5 — shorter is contained in longer as a full token
      2.0 — shorter is a non-token substring of longer (covers "ssn"
            matching "ssn provided" once the substring rule fires —
            gated by the token-or-substring containment check, NOT by
            arbitrary character co-occurrence: "ssn" against "session"
            never reaches this path because neither substring contains
            the other)
      0   — no usable signal

    Note: a previous version returned 1.0 for any token co-occurrence
    (e.g. "loan amount" vs "loan number" sharing the bare token
    "number" or "loan"). That fallback proved too noisy — short
    common tokens ("name", "number", "date", "id") show up across
    unrelated fields and a coincidental value substring would then
    push the combined score over threshold and ground the wrong
    label. Removed: only exact-or-containment counts now.
    """
    nd = _norm(detected_label)
    if not nd or not candidates:
        return 0.0
    if nd in candidates:
        return 3.0
    for c in candidates:
        if not c or nd == c:
            continue
        if nd in c or c in nd:
            shorter, longer = (nd, c) if len(nd) <= len(c) else (c, nd)
            longer_tokens = set(longer.split())
            return 2.5 if shorter in longer_tokens else 2.0
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
    bail (likely garbage). After normalization, the box is also
    plausibility-checked (see ``_is_plausible_bbox``) so degenerate
    slivers from sloppy classifier output don't poison grounding.
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
        unit = nums
    elif max_c > 1500:
        return None
    else:
        unit = [x / 1000.0 for x in nums]
    if not _is_plausible_bbox(unit):
        return None
    return unit


# Minimum / maximum dimensions for a plausible text-field bbox in 0..1
# unit space. Empirically tuned against real Gemini classifier output:
#  - Real form values rarely render with width < ~1.5% of the page
#    (single character at ~2-3 pt font would be wider than that)
#  - Real text fields rarely span more than ~20% of page height; values
#    that do are almost always the classifier picking up a region/section
#    instead of the value's actual line
# Both checks are deliberately permissive — false positives here mean a
# legitimate field gets no highlight, which is strictly less bad than the
# alternative (a giant or sliver bbox highlighting the wrong area).
_MIN_BBOX_WIDTH = 0.015
_MAX_BBOX_HEIGHT = 0.20


def _is_plausible_bbox(unit_bbox: list[float]) -> bool:
    """Return ``False`` for bboxes that look like classifier garbage.

    Catches two pathologies seen on real packages:

    1. *Vertical slivers*: e.g. ``[0.095, 0.233, 0.115, 0.444]`` — width
       2% of page, height 21% of page. The classifier occasionally
       boxes the *column position* of a label rather than the line it
       lives on. These slivers always grade as "matches" against any
       value because they're tall enough to overlap dozens of lines, so
       they win grounding ties on continuation pages.
    2. *Whole-region boxes*: bboxes spanning >20% of the page height,
       which in practice means the classifier returned a section
       boundary, not a single value's coordinates.

    ``unit_bbox`` is already in 0..1 space.
    """
    x1, y1, x2, y2 = unit_bbox
    w = abs(x2 - x1)
    h = abs(y2 - y1)
    if w < _MIN_BBOX_WIDTH:
        return False
    if h > _MAX_BBOX_HEIGHT:
        return False
    return True


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

    snippet_list = [s for s in snippets if isinstance(s, dict)]
    # Position-in-stack: pages sorted ascending → position 0 is the
    # earliest page in this stack. The deterministic stacker collapses
    # all same-doc-type pages into one stack regardless of contiguity,
    # so a URLA_1003 stack can legitimately span pages [3..361]. Without
    # this penalty, a sloppy classifier label on a continuation page
    # whose value happens to match outranks the legitimate first-page
    # match (combined score ties broken by score, not by which page is
    # canonical for the field). The penalty is applied per-page, not
    # per-page-number, so a stack with pages [3, 7, 60] punishes page
    # 60 by the same amount as a stack with pages [3, 4, 5] punishes
    # page 5 — the third page is the third page either way.
    page_position: dict[int, int] = {}
    for pos, page in enumerate(
        sorted({s.get("page_number") for s in snippet_list
                if isinstance(s.get("page_number"), int)})
    ):
        page_position[page] = pos

    best: tuple[float, int, int, list[float]] | None = None
    # Tuple shape: (adjusted_score, -page, -entry_index, bbox)
    # Negation forces the *earliest* page+entry to win on remaining ties.

    for snippet in snippet_list:
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
            # Require exact or containment label match (>=2.0). Token
            # co-occurrence alone is filtered to avoid false grounds on
            # ambiguous short tokens shared across unrelated fields.
            if ls < 2.0:
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
            bbox = _normalize_bbox_to_unit(entry.get("bbox"))
            if bbox is None:
                continue

            # Position penalty — small enough that strong, exact value
            # matches on a later page can still win over weak label-only
            # matches on the first page, but large enough that a
            # weak/medium value match on a far page can't beat a
            # legitimate first-page match. With weights below:
            #   first page, label-only:        4.5 - 0.0 = 4.5
            #   third page,  label+exact val:  6.5 - 0.2 = 6.3 (wins)
            #   first page, label+exact val:   6.5 - 0.0 = 6.5 (wins all)
            #   tenth page, label-only:        4.5 - 1.0 = 3.5 (loses)
            penalty = _STACK_POSITION_PENALTY * page_position.get(page, 0)
            adjusted = combined - penalty

            key = (adjusted, -page, -idx, bbox)
            if best is None or key > best:
                best = key

    if best is None:
        return None
    _, neg_page, _, bbox = best
    return (-neg_page, bbox)


# Per-position penalty applied to grounding scores so earlier pages of
# a stack win ties (and small score deltas) against later pages. See
# ``ground_field_location`` for the calibration. Tuned so:
#   - A pure label match (2.0) → contributes 3.0 to combined
#   - A label match + exact value match → 6.5 max
#   - Per-position 0.10 means a 5-position gap erases a strong label-only
#     match (~0.5 of score) but doesn't erase a strong value-confirmed
#     match (~2.0 of score gap)
_STACK_POSITION_PENALTY = 0.10
