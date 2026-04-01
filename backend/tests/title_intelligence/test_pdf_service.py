"""Tests for data-driven PDF report generation."""

import pytest

from app.micro_apps.title_intelligence.services.pdf_service import generate_pack_report_pdf, _clean


def _sample_exceptions():
    return [
        {
            "id": 1,
            "severity": "critical",
            "category": "Unreleased Mortgage",
            "description": "Mortgage from 2018 with no recorded satisfaction",
            "doc_ref": "p. 12, 15",
            "action": "Must resolve before closing",
        },
        {
            "id": 2,
            "severity": "high",
            "category": "Tax Lien",
            "description": "Outstanding federal tax lien",
            "doc_ref": "p. 23",
            "action": "Resolve before closing",
        },
        {
            "id": 3,
            "severity": "medium",
            "category": "Easement",
            "description": "Utility easement along north boundary",
            "doc_ref": "p. 8",
            "action": "Review and address",
        },
    ]


def test_generate_report_basic():
    """Basic call generates valid PDF bytes."""
    pdf_bytes = generate_pack_report_pdf(
        property_address="123 Main St, Springfield, IL 62701",
        order_number="TC-2026-0042",
        commitment_date="March 15, 2026",
        issued_by="First American Title",
        generated_at="March 25, 2026 at 10:00 AM UTC",
        critical_count=1,
        warning_count=2,
        review_count=3,

        exceptions=_sample_exceptions(),
    )
    assert isinstance(pdf_bytes, (bytes, bytearray))
    assert len(pdf_bytes) > 0
    assert pdf_bytes[:5] == b"%PDF-"


def test_generate_report_no_exceptions():
    """Report with no exceptions renders correctly."""
    pdf_bytes = generate_pack_report_pdf(
        property_address="456 Oak Ave",
        order_number="",
        commitment_date="",
        issued_by="",
        generated_at="March 25, 2026",
        critical_count=0,
        warning_count=0,
        review_count=0,

        exceptions=[],
    )
    assert pdf_bytes[:5] == b"%PDF-"


def test_generate_report_many_exceptions():
    """Many exceptions generate a multi-page PDF."""
    exceptions = [
        {
            "id": i,
            "severity": "medium",
            "category": f"Category {i}",
            "description": f"Description for exception {i} with enough text to wrap across multiple lines in the table cell",
            "doc_ref": f"p. {i}",
            "action": "Review and address",
        }
        for i in range(1, 51)
    ]
    pdf_bytes = generate_pack_report_pdf(
        property_address="789 Long Report Lane",
        order_number="LR-001",
        commitment_date="2026-01-01",
        issued_by="Test Title Co",
        generated_at="March 25, 2026",
        critical_count=0,
        warning_count=50,
        review_count=50,

        exceptions=exceptions,
    )
    assert pdf_bytes[:5] == b"%PDF-"
    assert len(pdf_bytes) > 2000  # multi-page


def test_generate_report_unicode_handling():
    """Unicode characters in data are sanitized for PDF."""
    pdf_bytes = generate_pack_report_pdf(
        property_address="123 Main St \u2014 Suite 200",
        order_number="TC\u20132026",
        commitment_date="March 15, 2026",
        issued_by="O\u2019Brien Title",
        generated_at="March 25, 2026",
        critical_count=1,
        warning_count=0,
        review_count=0,

        exceptions=[
            {
                "id": 1,
                "severity": "critical",
                "category": "Name Mismatch",
                "description": "Grantor\u2019s name doesn\u2019t match \u2014 check deed",
                "doc_ref": "p. 5",
                "action": "Must resolve",
            }
        ],
    )
    assert pdf_bytes[:5] == b"%PDF-"


def test_generate_report_empty_fields():
    """Empty/missing fields don't crash PDF generation."""
    pdf_bytes = generate_pack_report_pdf(
        property_address="",
        order_number="",
        commitment_date="",
        issued_by="",
        generated_at="",
        critical_count=0,
        warning_count=0,
        review_count=0,

        exceptions=[],
    )
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
