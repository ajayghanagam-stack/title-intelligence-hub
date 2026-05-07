"""Tests for the server-side field grounding service.

These verify the join between the page classifier's grounded bboxes
(emitted in Gemini's [0, 1000] space alongside doc-type detection) and
the ExtractionAgent's text-only output (which has no real coordinate
signal). The service must:
  - Match through known aliases (ssn ↔ "Social Security Number", etc.)
  - Disambiguate by value when the same label appears on multiple pages
  - Disambiguate by label when the same value appears under multiple labels
    (borrower SSN vs co-borrower SSN with the same digit suffix)
  - Convert classifier bboxes from [0, 1000] to 0..1 unit space
  - Return None when nothing matches
"""
from app.micro_apps.loan_onboarding.services.field_grounding import (
    FIELD_ALIASES,
    _normalize_bbox_to_unit,
    ground_field_location,
    is_extraction_worthy_label,
)


def _snippet(page_number: int, fields: list[dict]) -> dict:
    """Helper to build a snippet dict with detected_fields."""
    return {"page_number": page_number, "text": "", "detected_fields": fields}


# ── bbox normalization ────────────────────────────────────────────────


def test_normalize_bbox_gemini_thousand():
    # Gemini's standard [0, 1000] space → divide by 1000
    out = _normalize_bbox_to_unit([186, 249, 300, 262])
    assert out is not None
    assert out == [0.186, 0.249, 0.300, 0.262]


def test_normalize_bbox_already_unit():
    # Pre-normalized 0..1 passes through
    out = _normalize_bbox_to_unit([0.1, 0.2, 0.3, 0.4])
    assert out == [0.1, 0.2, 0.3, 0.4]


def test_normalize_bbox_zero_rejected():
    assert _normalize_bbox_to_unit([0, 0, 0, 0]) is None


def test_normalize_bbox_degenerate_rejected():
    # Zero-width box
    assert _normalize_bbox_to_unit([100, 100, 100, 200]) is None


def test_normalize_bbox_garbage_rejected():
    assert _normalize_bbox_to_unit([10000, 10000, 20000, 20000]) is None
    assert _normalize_bbox_to_unit("not a list") is None
    assert _normalize_bbox_to_unit([1, 2, 3]) is None


def test_normalize_bbox_vertical_sliver_rejected():
    # Real Benavides URLA_1003 case: classifier emitted a 2%×21% vertical
    # strip (likely the column position of a label, not the value's
    # actual line). Such slivers always overlap many lines on a page,
    # which makes them "match" anything — they were winning grounding
    # ties on continuation pages and highlighting nothing useful.
    # In Gemini's [0, 1000] space: width=20, height=211.
    assert _normalize_bbox_to_unit([95, 233, 115, 444]) is None
    # Already-unit version of the same sliver
    assert _normalize_bbox_to_unit([0.095, 0.233, 0.115, 0.444]) is None


def test_normalize_bbox_too_tall_rejected():
    # Classifier sometimes returns whole-region bboxes (e.g. boxing an
    # entire section). >20% page height means we're not looking at a
    # value's bbox.
    # 0..1000 space: height = 250
    assert _normalize_bbox_to_unit([100, 100, 500, 350]) is None


def test_normalize_bbox_horizontal_text_line_passes():
    # A normal text-value bbox — wide but short — must NOT be rejected.
    # 50% width × 2% height is the canonical shape of a name/address line.
    out = _normalize_bbox_to_unit([100, 250, 600, 270])
    assert out is not None
    assert out == [0.1, 0.25, 0.6, 0.27]


# ── alias matching ────────────────────────────────────────────────────


def test_ground_ssn_via_alias():
    # The classifier emits "Social Security Number"; the LOS-canonical
    # field key is "ssn" — the alias map must bridge them.
    snippets = [
        _snippet(3, [
            {
                "field_name": "Social Security Number",
                "value": "635-30-9229",
                "bbox": [550, 249, 630, 262],
            },
        ]),
    ]
    result = ground_field_location("ssn", "635-30-9229", snippets)
    assert result is not None
    page, bbox = result
    assert page == 3
    assert bbox == [0.550, 0.249, 0.630, 0.262]


def test_ground_borrower_name_via_alias():
    snippets = [
        _snippet(3, [
            {
                "field_name": "Borrower Name",
                "value": "Julio Benavides",
                "bbox": [186, 249, 300, 262],
            },
        ]),
    ]
    result = ground_field_location("borrower_name", "Julio Benavides", snippets)
    assert result is not None
    page, bbox = result
    assert page == 3
    assert bbox == [0.186, 0.249, 0.300, 0.262]


def test_ground_property_address_via_subject_property_alias():
    # 1003 forms emit "Subject Property Address" — that should still
    # resolve to the canonical "property_address" field key.
    snippets = [
        _snippet(5, [
            {
                "field_name": "Subject Property Address",
                "value": "1937A Norfolk St Houston TX 77098",
                "bbox": [120, 400, 700, 420],
            },
        ]),
    ]
    result = ground_field_location(
        "property_address",
        "1937A Norfolk St Houston TX 77098",
        snippets,
    )
    assert result is not None
    page, bbox = result
    assert page == 5
    assert bbox == [0.120, 0.400, 0.700, 0.420]


# ── disambiguation ────────────────────────────────────────────────────


def test_disambiguate_by_value_when_same_label_on_multiple_pages():
    # Borrower Name appears in headers across multiple 1003 pages with
    # different values (continuation pages vs original). Picking the
    # right page requires the value to corroborate.
    snippets = [
        _snippet(3, [
            {
                "field_name": "Borrower Name",
                "value": "Julio Benavides",
                "bbox": [186, 249, 300, 262],
            },
        ]),
        _snippet(58, [
            {
                "field_name": "Borrower Name",
                "value": "Different Person",
                "bbox": [186, 100, 300, 115],
            },
        ]),
    ]
    result = ground_field_location("borrower_name", "Julio Benavides", snippets)
    assert result is not None
    page, _ = result
    assert page == 3, "value should win the page selection"


def test_disambiguate_borrower_ssn_vs_co_borrower_ssn_by_label():
    # Both SSNs share the same 4-digit suffix; only the label
    # disambiguates which is which.
    snippets = [
        _snippet(3, [
            {
                "field_name": "Social Security Number",
                "value": "635-30-9229",
                "bbox": [550, 249, 630, 262],
            },
            {
                "field_name": "Co-Borrower Social Security Number",
                "value": "111-22-9229",
                "bbox": [550, 320, 630, 333],
            },
        ]),
    ]
    co_result = ground_field_location("co_borrower_ssn", "111-22-9229", snippets)
    assert co_result is not None
    _, co_bbox = co_result
    assert co_bbox == [0.550, 0.320, 0.630, 0.333]

    primary_result = ground_field_location("ssn", "635-30-9229", snippets)
    assert primary_result is not None
    _, primary_bbox = primary_result
    assert primary_bbox == [0.550, 0.249, 0.630, 0.262]


# ── empty / missing inputs ────────────────────────────────────────────


def test_ground_returns_none_when_no_matches():
    snippets = [
        _snippet(1, [
            {
                "field_name": "Some Unrelated Field",
                "value": "irrelevant",
                "bbox": [100, 100, 200, 200],
            },
        ]),
    ]
    result = ground_field_location("ssn", "635-30-9229", snippets)
    assert result is None


def test_ground_returns_none_when_no_snippets():
    assert ground_field_location("ssn", "635-30-9229", []) is None


def test_ground_label_only_when_value_empty():
    # Even when the agent reported the field as missing (empty value),
    # we can still highlight WHERE the field should be from the label
    # alone — useful for review/HITL.
    snippets = [
        _snippet(3, [
            {
                "field_name": "Social Security Number",
                "value": "",
                "bbox": [550, 249, 630, 262],
            },
        ]),
    ]
    result = ground_field_location("ssn", "", snippets)
    assert result is not None
    page, _ = result
    assert page == 3


def test_ground_skips_invalid_bbox():
    # Even with a strong label match, an unusable bbox means we can't
    # render anything — return None rather than fake coords.
    snippets = [
        _snippet(3, [
            {
                "field_name": "Social Security Number",
                "value": "635-30-9229",
                "bbox": [0, 0, 0, 0],
            },
        ]),
    ]
    result = ground_field_location("ssn", "635-30-9229", snippets)
    assert result is None


def test_ground_skips_degenerate_sliver_bbox():
    # The Benavides URLA_1003 case: a real classifier on a continuation
    # page emits "Property Address" with the right value but a vertical
    # sliver bbox (height >> width, height > 20% of page). The
    # plausibility check rejects the bbox so this entry can't win
    # grounding even though label+value both score perfectly.
    snippets = [
        # Page 3 — the legitimate first-page entry, normal text-line bbox
        _snippet(3, [
            {
                "field_name": "Subject Property Address",
                "value": "123 Main St, Austin, TX 78701",
                "bbox": [120, 250, 600, 270],
            },
        ]),
        # Page 60 — the sloppy continuation page entry with a sliver
        _snippet(60, [
            {
                "field_name": "Property Address",
                "value": "123 Main St, Austin, TX 78701",
                "bbox": [95, 233, 115, 444],  # width=20, height=211 → garbage
            },
        ]),
    ]
    result = ground_field_location(
        "property_address", "123 Main St, Austin, TX 78701", snippets
    )
    assert result is not None
    page, _ = result
    # Page 60's sliver must be rejected; legitimate page 3 entry wins.
    assert page == 3


def test_ground_prefers_earlier_page_in_stack_when_scores_equal():
    # The deterministic stacker collapses ALL same-doc-type pages into
    # one stack regardless of contiguity, so a URLA_1003 stack can span
    # pages [3..361]. When the same labelled field appears on multiple
    # stack pages with identical bboxes/values, the earliest page in
    # the stack must win — that's the canonical instance.
    snippets = []
    for pn in (3, 5, 9, 13, 17, 21, 25, 29, 33, 60):
        snippets.append(_snippet(pn, [
            {
                "field_name": "Borrower Name",
                "value": "Jane Doe",
                "bbox": [120, 250, 400, 270],
            },
        ]))
    result = ground_field_location("borrower_name", "Jane Doe", snippets)
    assert result is not None
    page, _ = result
    assert page == 3


def test_ground_position_penalty_caps_far_page_lift():
    # With 10 stack pages, the position penalty (0.10 × position) caps
    # how much a far page can outscore an early page. A page-9 entry
    # that has only a label match (no value confirmation) cannot beat
    # a page-3 entry with the same label, even though the existing
    # -page tiebreaker would normally pick page 9 if combined scores
    # tied. Here the penalty makes page 3 strictly higher-scored.
    snippets = []
    for pn in (3, 5, 7, 11, 15, 19, 23, 27, 31, 60):
        # All ten pages are in this URLA_1003 stack
        snippets.append(_snippet(pn, []))
    # Only pages 3 and 60 have the field
    snippets[0]["detected_fields"] = [
        {
            "field_name": "Borrower Name",
            "value": "Jane Doe",
            "bbox": [120, 250, 400, 270],
        },
    ]
    snippets[-1]["detected_fields"] = [
        {
            "field_name": "Borrower Name",
            "value": "Jane Doe",
            "bbox": [120, 250, 400, 270],
        },
    ]
    result = ground_field_location("borrower_name", "Jane Doe", snippets)
    assert result is not None
    page, _ = result
    assert page == 3


def test_ground_value_match_can_still_overcome_small_position_gap():
    # Defensive: a strong label-only match on the first page should NOT
    # beat a label+value match on the very next page. The penalty is
    # deliberately small enough that real value matches remain dominant.
    snippets = [
        _snippet(3, [
            # Label match only — value differs (extraction picked a
            # later page's value)
            {
                "field_name": "Borrower Name",
                "value": "Some Other Person",
                "bbox": [120, 250, 400, 270],
            },
        ]),
        _snippet(5, [
            # Label + exact value match
            {
                "field_name": "Borrower Name",
                "value": "Jane Doe",
                "bbox": [120, 350, 400, 370],
            },
        ]),
    ]
    result = ground_field_location("borrower_name", "Jane Doe", snippets)
    assert result is not None
    page, _ = result
    # Page 5 has +2.0 from value match; page 3 only has 0.5 from value
    # signal absence. Even with -0.10 position penalty, page 5 wins.
    assert page == 5


def test_ground_handles_non_dict_entries_gracefully():
    snippets = [
        _snippet(3, [
            "not a dict",  # malformed entry
            None,
            {
                "field_name": "Social Security Number",
                "value": "635-30-9229",
                "bbox": [550, 249, 630, 262],
            },
        ]),
    ]
    result = ground_field_location("ssn", "635-30-9229", snippets)
    assert result is not None


# ── alias coverage sanity check ───────────────────────────────────────


def test_known_canonical_keys_have_aliases():
    """Lock in the canonical field-key set we promise to ground.

    Dropping a key here is allowed but should be deliberate — adding
    one without aliases means it falls through to substring match
    only, which is fine for unique labels but flaky for short or
    ambiguous ones.
    """
    must_have = {
        "borrower_name",
        "ssn",
        "property_address",
        "loan_amount",
        "loan_number",
        "employer_name",
        "employee_name",
        "gross_pay",
        "wages",
        "account_number",
        "pay_period",
    }
    missing = must_have - FIELD_ALIASES.keys()
    assert not missing, f"Canonical keys without aliases: {missing}"


# ── Negative tests — guard against false grounds ──────────────────────


def test_ssn_does_not_match_unrelated_short_substring():
    """The substring rule is gated by full containment in either
    direction — short tokens that share characters but aren't proper
    substrings (e.g. "ssn" vs "session id" vs "occupation") must not
    match. This is the regression that motivated removing the
    token-overlap fallback entirely.
    """
    snippets = [
        _snippet(1, [
            {"field_name": "Occupation", "value": "Engineer", "bbox": [100, 100, 200, 200]},
            {"field_name": "Session ID", "value": "abc123", "bbox": [300, 300, 400, 400]},
        ]),
    ]
    assert ground_field_location("ssn", "635-30-9229", snippets) is None


def test_loan_amount_does_not_match_loan_number_via_token_overlap():
    """`loan amount` and `loan number` share the bare token "loan" but
    represent different fields. With the token-overlap fallback gone,
    sharing one token is not enough to ground — even when a
    coincidental value substring is present.
    """
    snippets = [
        _snippet(2, [
            {"field_name": "Loan Number", "value": "750000123", "bbox": [100, 100, 200, 200]},
        ]),
    ]
    # The agent's loan_amount value happens to be a substring of the
    # classifier's loan_number value. Old behaviour: ls=1.0 (token
    # overlap) + vs=1.5 (substring) → combined=3.0 → false ground.
    # New behaviour: ls=0 → rejected.
    assert ground_field_location("loan_amount", "750000", snippets) is None


def test_borrower_name_does_not_match_lender_name():
    """Both labels share the bare token "name" but mean different things."""
    snippets = [
        _snippet(2, [
            {"field_name": "Lender Name", "value": "Wells Fargo", "bbox": [100, 100, 200, 200]},
        ]),
    ]
    assert ground_field_location("borrower_name", "Julio Benavides", snippets) is None


def test_account_number_does_not_match_loan_number():
    """`account number` and `loan number` share the bare token "number"
    but mean different things. A coincidental value match must not
    bridge them.
    """
    snippets = [
        _snippet(3, [
            {"field_name": "Loan Number", "value": "00123456", "bbox": [100, 100, 200, 200]},
        ]),
    ]
    assert ground_field_location("account_number", "00123456", snippets) is None


def test_ssn_picks_correct_entry_when_other_id_fields_share_digits():
    """A real-world hazard: 1003 forms render multiple `*_number`
    labels on the same page; one digit suffix can coincide. Only the
    label that aliases to "ssn" should match.
    """
    snippets = [
        _snippet(3, [
            {"field_name": "Employer Identification Number", "value": "12-3459229", "bbox": [100, 100, 200, 200]},
            {"field_name": "Loan Number", "value": "9229", "bbox": [200, 200, 300, 300]},
            {"field_name": "Social Security Number", "value": "635-30-9229", "bbox": [550, 249, 630, 262]},
        ]),
    ]
    result = ground_field_location("ssn", "635-30-9229", snippets)
    assert result is not None
    page, bbox = result
    assert page == 3
    assert bbox == [0.550, 0.249, 0.630, 0.262]


# ── Cross-doc-type golden cases ───────────────────────────────────────


def test_paystub_employer_name():
    snippets = [
        _snippet(12, [
            {"field_name": "Employer", "value": "Acme Corp", "bbox": [80, 60, 220, 75]},
            {"field_name": "Employee Name", "value": "Jane Doe", "bbox": [80, 100, 220, 115]},
        ]),
    ]
    result = ground_field_location("employer_name", "Acme Corp", snippets)
    assert result is not None
    page, bbox = result
    assert page == 12
    assert bbox == [0.080, 0.060, 0.220, 0.075]


def test_paystub_pay_period_via_period_ending_alias():
    """Stage data shows paystubs label this 'Pay Date' or
    'Period Ending'. Either should ground to `pay_period`.
    """
    snippets = [
        _snippet(15, [
            {"field_name": "Period Ending", "value": "2024-04-15", "bbox": [400, 80, 520, 95]},
        ]),
    ]
    result = ground_field_location("pay_period", "2024-04-15", snippets)
    assert result is not None
    page, _ = result
    assert page == 15


def test_paystub_gross_pay_via_ytd_alias():
    snippets = [
        _snippet(15, [
            {"field_name": "YTD Gross", "value": "$45,200.00", "bbox": [600, 200, 700, 215]},
        ]),
    ]
    result = ground_field_location("gross_pay", "$45,200.00", snippets)
    assert result is not None


def test_w2_wages_via_box1_label():
    """W-2s often label the wages field with the box number too."""
    snippets = [
        _snippet(20, [
            {"field_name": "Wages, Tips, Other Compensation", "value": "65000", "bbox": [400, 150, 480, 165]},
        ]),
    ]
    result = ground_field_location("wages", "65000", snippets)
    assert result is not None


def test_w2_federal_tax_withheld():
    snippets = [
        _snippet(20, [
            {"field_name": "Federal Income Tax Withheld", "value": "8500", "bbox": [400, 200, 480, 215]},
        ]),
    ]
    result = ground_field_location("federal_tax_withheld", "8500", snippets)
    assert result is not None


def test_bank_statement_account_number_via_hash_alias():
    """Bank statements sometimes label this 'Account #'."""
    snippets = [
        _snippet(30, [
            {"field_name": "Account #", "value": "****1234", "bbox": [80, 50, 200, 65]},
        ]),
    ]
    result = ground_field_location("account_number", "1234", snippets)
    assert result is not None


def test_bank_statement_account_holder_name():
    snippets = [
        _snippet(30, [
            {"field_name": "Account Holder Name", "value": "Julio Benavides", "bbox": [80, 80, 300, 95]},
        ]),
    ]
    result = ground_field_location("account_holder_name", "Julio Benavides", snippets)
    assert result is not None


def test_bank_statement_ending_balance_via_market_value_alias():
    snippets = [
        _snippet(35, [
            {"field_name": "Ending Market Value", "value": "$1,874,480.18", "bbox": [600, 400, 750, 415]},
        ]),
    ]
    result = ground_field_location("ending_balance", "$1,874,480.18", snippets)
    assert result is not None


def test_loan_number_via_universal_loan_identifier_alias():
    """1003 forms label this 'Lender Loan No./Universal Loan Identifier'."""
    snippets = [
        _snippet(3, [
            {"field_name": "Lender Loan No./Universal Loan Identifier", "value": "ABC123456", "bbox": [400, 100, 600, 115]},
        ]),
    ]
    result = ground_field_location("loan_number", "ABC123456", snippets)
    assert result is not None


def test_warranty_deed_grantor_grantee():
    snippets = [
        _snippet(50, [
            {"field_name": "Grantor", "value": "John Seller", "bbox": [80, 100, 250, 115]},
            {"field_name": "Grantee", "value": "Jane Buyer", "bbox": [80, 200, 250, 215]},
        ]),
    ]
    grantor = ground_field_location("grantor", "John Seller", snippets)
    grantee = ground_field_location("grantee", "Jane Buyer", snippets)
    assert grantor is not None
    assert grantee is not None
    # Distinct bboxes — must not collapse to the same one
    assert grantor[1] != grantee[1]


def test_id_document_dl_number():
    snippets = [
        _snippet(70, [
            {"field_name": "DL Number", "value": "X12345678", "bbox": [200, 100, 350, 115]},
        ]),
    ]
    result = ground_field_location("dl_number", "X12345678", snippets)
    assert result is not None


# ── Disambiguation in mixed-page-detected_fields scenarios ───────────


def test_ssn_label_score_beats_value_substring_on_wrong_label():
    """When SSN value happens to be a substring of an unrelated
    `*_number` field on the same page, the label score on the correct
    SSN entry must dominate. This is the borrower-page realism test:
    one 'Loan Number' = '7506350309229' (just for stress) and one
    'Social Security Number' = '635-30-9229'. We must pick the SSN.
    """
    snippets = [
        _snippet(3, [
            {"field_name": "Loan Number", "value": "7506350309229", "bbox": [100, 100, 200, 115]},
            {"field_name": "Social Security Number", "value": "635-30-9229", "bbox": [550, 249, 630, 262]},
        ]),
    ]
    result = ground_field_location("ssn", "635-30-9229", snippets)
    assert result is not None
    page, bbox = result
    assert page == 3
    # Must land on the SSN bbox, not the loan-number bbox
    assert bbox == [0.550, 0.249, 0.630, 0.262]


# ── New canonical fields (CD / appraisal / credit / title / notary) ───


def test_ground_cash_to_close_via_cd_alias():
    snippets = [
        _snippet(3, [
            {"field_name": "Estimated Cash to Close", "value": "$24,500.00", "bbox": [400, 200, 600, 215]},
        ]),
    ]
    result = ground_field_location("cash_to_close", "$24,500.00", snippets)
    assert result is not None


def test_ground_total_closing_costs_via_cd_alias():
    snippets = [
        _snippet(2, [
            {"field_name": "J. Total Closing Costs", "value": "$8,250.00", "bbox": [400, 600, 600, 615]},
        ]),
    ]
    result = ground_field_location("total_closing_costs", "$8,250.00", snippets)
    assert result is not None


def test_ground_appraiser_name():
    snippets = [
        _snippet(40, [
            {"field_name": "Appraiser", "value": "Pat Smith", "bbox": [80, 700, 300, 715]},
        ]),
    ]
    result = ground_field_location("appraiser_name", "Pat Smith", snippets)
    assert result is not None


def test_ground_effective_date_of_appraisal():
    snippets = [
        _snippet(40, [
            {"field_name": "Effective Date of Appraisal", "value": "2025-09-12", "bbox": [400, 80, 560, 95]},
        ]),
    ]
    result = ground_field_location("effective_date_of_appraisal", "2025-09-12", snippets)
    assert result is not None


def test_ground_credit_score_via_fico_alias():
    snippets = [
        _snippet(60, [
            {"field_name": "FICO Score", "value": "742", "bbox": [200, 100, 280, 115]},
        ]),
    ]
    result = ground_field_location("credit_score", "742", snippets)
    assert result is not None


def test_ground_commitment_number():
    snippets = [
        _snippet(45, [
            {"field_name": "Commitment Number", "value": "CMT-12345", "bbox": [400, 80, 560, 95]},
        ]),
    ]
    result = ground_field_location("commitment_number", "CMT-12345", snippets)
    assert result is not None


def test_ground_commission_expiration_date():
    snippets = [
        _snippet(72, [
            {"field_name": "My Commission Expires", "value": "2027-06-30", "bbox": [400, 600, 560, 615]},
        ]),
    ]
    result = ground_field_location("commission_expiration_date", "2027-06-30", snippets)
    assert result is not None


def test_ground_execution_date():
    snippets = [
        _snippet(50, [
            {"field_name": "Execution Date", "value": "2025-10-15", "bbox": [400, 700, 560, 715]},
        ]),
    ]
    result = ground_field_location("execution_date", "2025-10-15", snippets)
    assert result is not None


def test_new_canonical_keys_have_aliases():
    """Lock in the new canonical keys added for the CD / appraisal /
    credit / title / notary buckets — the highest-volume uncovered
    label families on real loan packages.
    """
    must_have = {
        "fee_description",
        "cash_to_close",
        "total_closing_costs",
        "appraiser_name",
        "effective_date_of_appraisal",
        "sale_price",
        "sales_contract_price",
        "credit_score",
        "commitment_number",
        "commission_expiration_date",
        "execution_date",
    }
    missing = must_have - FIELD_ALIASES.keys()
    assert not missing, f"New canonical keys without aliases: {missing}"


# ── Admin / structural label filter ───────────────────────────────────


def test_admin_label_filter_strips_pagination():
    assert is_extraction_worthy_label("Page") is False
    assert is_extraction_worthy_label("Page Number") is False
    assert is_extraction_worthy_label("page no.") is False


def test_admin_label_filter_strips_form_metadata():
    assert is_extraction_worthy_label("Form Number") is False
    assert is_extraction_worthy_label("Revision Date") is False
    assert is_extraction_worthy_label("Version") is False


def test_admin_label_filter_strips_checkbox_stems():
    assert is_extraction_worthy_label("Yes") is False
    assert is_extraction_worthy_label("No") is False
    assert is_extraction_worthy_label("N/A") is False
    assert is_extraction_worthy_label("Check One") is False


def test_admin_label_filter_strips_signature_scaffolding():
    assert is_extraction_worthy_label("Signature") is False
    assert is_extraction_worthy_label("Signature Line") is False
    assert is_extraction_worthy_label("Initials") is False


def test_admin_label_filter_strips_pure_numeric():
    assert is_extraction_worthy_label("1.") is False
    assert is_extraction_worthy_label("23") is False


def test_admin_label_filter_strips_empty():
    assert is_extraction_worthy_label("") is False
    assert is_extraction_worthy_label(None) is False
    assert is_extraction_worthy_label("   ") is False


def test_admin_label_filter_keeps_real_field_labels():
    # Sanity: actual extractable fields must NOT be filtered.
    assert is_extraction_worthy_label("Borrower Name") is True
    assert is_extraction_worthy_label("Social Security Number") is True
    assert is_extraction_worthy_label("Loan Amount") is True
    assert is_extraction_worthy_label("FICO Score") is True
    assert is_extraction_worthy_label("My Commission Expires") is True
    # 'Title' is borderline (form title vs job title) — currently
    # filtered. If this changes, employment 'job_title' aliasing
    # already covers the real-field case via the 'job title' / 'position'
    # / 'occupation' aliases, so a bare 'Title' label is more often
    # form scaffolding than a real field.
    assert is_extraction_worthy_label("Title") is False
