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
        "employer_name",
        "gross_pay",
        "wages",
    }
    missing = must_have - FIELD_ALIASES.keys()
    assert not missing, f"Canonical keys without aliases: {missing}"
