"""Tests for professional Title Examination Report PDF generation."""

import pytest

from app.micro_apps.title_intelligence.services.pdf_service import generate_pack_report_pdf, _clean


def _minimal_report_data(**overrides) -> dict:
    """Return a minimal valid report_data dict with optional overrides."""
    data = {
        "property_address": "13110 Memorial Drive, Houston, TX 77079",
        "county": "El Paso",
        "state": "TX",
        "legal_description": "Lot 35, Block 1, Boulder Canyon Replat B",
        "interest_type": "Fee Simple",
        "commitment_number": "TX-26-1410",
        "faf_file_number": "111157928",
        "effective_date": "2026-03-02",
        "issued_date": "2026-03-13",
        "owners_policy": "$310,000.00 (T-1R)",
        "lenders_policy": "$299,150.00 (T-2)",
        "policy_amount": "$310,000.00",
        "buyer_borrower": "Marisela Acedo",
        "seller": "Shelley Lynn La Judice, Steven V. Callan",
        "lender": "Blue Spot Home Loans",
        "title_company": "Society Title, Inc.",
        "underwriter": "First American Title Insurance Company",
        "generated_at": "March 25, 2026 at 10:00 AM UTC",
        "flags_by_severity": {"critical": [], "high": [], "medium": [], "low": []},
        "total_open": 0,
        "risk_assessment": "",
        "standard_exceptions": [],
        "specific_exceptions": [],
        "requirements": [],
        "warnings": [],
        "checklist_items": [],
    }
    data.update(overrides)
    return data


def _sample_flags_by_severity():
    return {
        "critical": [
            {
                "flag_type": "unreleased_mortgage",
                "severity": "critical",
                "title": "Unreleased mortgage from 2018",
                "description": "Mortgage from 2018 with no recorded satisfaction",
                "ai_explanation": "The mortgage recorded in 2018 has no corresponding satisfaction or release document.",
                "evidence_refs": [{"page_number": 12}, {"page_number": 15}],
                "status": "open",
            }
        ],
        "high": [
            {
                "flag_type": "unresolved_lien",
                "severity": "high",
                "title": "Outstanding federal tax lien",
                "description": "Federal tax lien filed against property",
                "ai_explanation": "A federal tax lien was filed and has not been released.",
                "evidence_refs": [{"page_number": 23}],
                "status": "open",
            }
        ],
        "medium": [
            {
                "flag_type": "missing_endorsement",
                "severity": "medium",
                "title": "Missing survey endorsement",
                "description": "Survey endorsement not included",
                "ai_explanation": "No survey endorsement was found in the commitment.",
                "evidence_refs": [{"page_number": 8}],
                "status": "open",
            }
        ],
        "low": [],
    }


def _sample_specific_exceptions():
    return [
        {
            "number": 1,
            "description": "Deed of Trust from John Smith to First National Bank dated 01/15/2020",
            "severity": "critical",
            "status": "open",
            "page_ref": "p. 12",
        },
        {
            "number": 2,
            "description": "Easement for utility lines along the north boundary",
            "severity": "medium",
            "status": "open",
            "page_ref": "p. 8",
        },
    ]


def _sample_standard_exceptions():
    return [
        {"number": 1, "description": "Rights of parties in possession not shown by public records.", "page_ref": ""},
        {"number": 2, "description": "Encroachments, overlaps, boundary line disputes, or other matters which would be disclosed by an accurate survey.", "page_ref": ""},
        {"number": 3, "description": "Easements or claims of easements not shown by the public records.", "page_ref": ""},
        {"number": 4, "description": "Any lien for services, labor or material heretofore or hereafter furnished.", "page_ref": ""},
        {"number": 5, "description": "Taxes or assessments which are not shown as existing liens by the public records.", "page_ref": ""},
    ]


def _sample_requirements():
    return [
        {"number": 1, "description": "Payment of all taxes and assessments due and payable.", "status": "Satisfied", "page_ref": "p. 3"},
        {"number": 2, "description": "Execution and delivery of deed from Jane Doe to John Smith.", "status": "Open", "page_ref": "p. 4"},
        {"number": 3, "description": "Satisfaction of existing mortgage held by ABC Bank.", "status": "Pending", "page_ref": "p. 5"},
    ]


def _sample_checklist():
    return [
        {"label": "All Schedule C requirements satisfied", "checked": False},
        {"label": "Outstanding liens and mortgages resolved", "checked": False},
        {"label": "Endorsements confirmed", "checked": False},
        {"label": "Name discrepancies cleared", "checked": True},
        {"label": "Tax status verified", "checked": True},
        {"label": "Chain of title complete", "checked": True},
        {"label": "Survey / legal description verified", "checked": True},
    ]


def test_generate_report_basic():
    """Basic call with full data generates valid PDF bytes."""
    data = _minimal_report_data(
        flags_by_severity=_sample_flags_by_severity(),
        total_open=3,
        risk_assessment="- Title commitment has 3 open issues, including 1 critical.",
        standard_exceptions=_sample_standard_exceptions(),
        specific_exceptions=_sample_specific_exceptions(),
        requirements=_sample_requirements(),
        warnings=[
            {
                "title": "Unreleased mortgage from 2018",
                "explanation": "The mortgage recorded in 2018 has no corresponding satisfaction.",
                "flag_type": "unreleased_mortgage",
            }
        ],
        checklist_items=_sample_checklist(),
    )
    pdf_bytes = generate_pack_report_pdf(data)
    assert isinstance(pdf_bytes, (bytes, bytearray))
    assert len(pdf_bytes) > 0
    assert pdf_bytes[:5] == b"%PDF-"


def test_generate_report_no_flags():
    """Report with no flags renders all sections without error."""
    data = _minimal_report_data(
        checklist_items=[
            {"label": "All Schedule C requirements satisfied", "checked": True},
            {"label": "Chain of title complete", "checked": True},
        ],
    )
    pdf_bytes = generate_pack_report_pdf(data)
    assert pdf_bytes[:5] == b"%PDF-"


def test_generate_report_no_exceptions():
    """Report with no exceptions renders empty schedule B."""
    data = _minimal_report_data()
    pdf_bytes = generate_pack_report_pdf(data)
    assert pdf_bytes[:5] == b"%PDF-"


def test_generate_report_many_exceptions():
    """Many specific exceptions generate a multi-page PDF."""
    specific = [
        {
            "number": i,
            "description": f"Exception {i} with enough text to wrap across multiple lines in the table cell for testing purposes",
            "severity": "medium",
            "status": "open",
            "page_ref": f"p. {i}",
        }
        for i in range(1, 51)
    ]
    data = _minimal_report_data(specific_exceptions=specific)
    pdf_bytes = generate_pack_report_pdf(data)
    assert pdf_bytes[:5] == b"%PDF-"
    assert len(pdf_bytes) > 2000  # multi-page


def test_generate_report_unicode_handling():
    """Unicode characters in data are sanitized for PDF."""
    data = _minimal_report_data(
        property_address="123 Main St \u2014 Suite 200",
        commitment_number="TC\u20132026",
        title_company="O\u2019Brien Title",
        specific_exceptions=[
            {
                "number": 1,
                "description": "Grantor\u2019s name doesn\u2019t match \u2014 check deed",
                "severity": "critical",
                "status": "open",
                "page_ref": "p. 5",
            }
        ],
        warnings=[
            {
                "title": "Name mismatch \u2014 Grantor",
                "explanation": "The grantor\u2019s name doesn\u2019t match the vesting deed.",
                "flag_type": "name_discrepancy",
            }
        ],
    )
    pdf_bytes = generate_pack_report_pdf(data)
    assert pdf_bytes[:5] == b"%PDF-"


def test_generate_report_empty_fields():
    """Empty/missing fields don't crash PDF generation."""
    data = {
        "property_address": "",
        "county": "",
        "state": "",
        "legal_description": "",
        "interest_type": "",
        "commitment_number": "",
        "faf_file_number": "",
        "effective_date": "",
        "issued_date": "",
        "owners_policy": "",
        "lenders_policy": "",
        "policy_amount": "",
        "buyer_borrower": "",
        "seller": "",
        "lender": "",
        "title_company": "",
        "underwriter": "",
        "generated_at": "",
        "flags_by_severity": {"critical": [], "high": [], "medium": [], "low": []},
        "total_open": 0,
        "risk_assessment": "",
        "standard_exceptions": [],
        "specific_exceptions": [],
        "requirements": [],
        "warnings": [],
        "checklist_items": [],
    }
    pdf_bytes = generate_pack_report_pdf(data)
    assert pdf_bytes[:5] == b"%PDF-"


def test_generate_report_only_standard_exceptions():
    """Report with only standard exceptions (no specific) renders correctly."""
    data = _minimal_report_data(standard_exceptions=_sample_standard_exceptions())
    pdf_bytes = generate_pack_report_pdf(data)
    assert pdf_bytes[:5] == b"%PDF-"


def test_generate_report_only_requirements():
    """Report with only requirements (no exceptions) renders correctly."""
    data = _minimal_report_data(requirements=_sample_requirements())
    pdf_bytes = generate_pack_report_pdf(data)
    assert pdf_bytes[:5] == b"%PDF-"


def test_generate_report_checklist_all_checked():
    """Checklist with all items checked renders correctly."""
    checklist = [
        {"label": "All Schedule C requirements satisfied", "checked": True},
        {"label": "Outstanding liens and mortgages resolved", "checked": True},
        {"label": "Endorsements confirmed", "checked": True},
        {"label": "Name discrepancies cleared", "checked": True},
        {"label": "Tax status verified", "checked": True},
        {"label": "Chain of title complete", "checked": True},
        {"label": "Survey / legal description verified", "checked": True},
    ]
    data = _minimal_report_data(checklist_items=checklist)
    pdf_bytes = generate_pack_report_pdf(data)
    assert pdf_bytes[:5] == b"%PDF-"


def test_clean_strips_markdown():
    """_clean removes markdown bold and italic markers."""
    assert _clean("**bold**") == "bold"
    assert _clean("*italic*") == "italic"
    assert _clean("`code`") == "code"


def test_clean_replaces_unicode():
    """_clean replaces common Unicode with ASCII equivalents."""
    assert _clean("\u2019") == "'"
    assert _clean("\u2014") == "--"
    assert _clean("\u2026") == "..."
