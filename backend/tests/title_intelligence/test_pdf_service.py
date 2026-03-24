"""Tests for PDF report generation."""

import pytest

from app.micro_apps.title_intelligence.services.pdf_service import markdown_to_pdf


def test_markdown_to_pdf_basic():
    """Basic markdown generates valid PDF bytes."""
    content = "# Title Report\n\nThis is a test report.\n\n## Summary\n\n- Item 1\n- Item 2"
    pdf_bytes = markdown_to_pdf(content, title="Test Report")
    assert isinstance(pdf_bytes, (bytes, bytearray))
    assert len(pdf_bytes) > 0
    assert pdf_bytes[:5] == b"%PDF-"


def test_markdown_to_pdf_with_headers():
    """PDF handles multiple header levels."""
    content = "# H1 Header\n## H2 Header\n### H3 Header\n\nParagraph text."
    pdf_bytes = markdown_to_pdf(content)
    assert pdf_bytes[:5] == b"%PDF-"


def test_markdown_to_pdf_with_bullets():
    """PDF handles bullet points."""
    content = "- First item\n- Second item\n* Third item\n\n1. Numbered item"
    pdf_bytes = markdown_to_pdf(content)
    assert pdf_bytes[:5] == b"%PDF-"


def test_markdown_to_pdf_with_bold():
    """PDF strips markdown bold formatting."""
    content = "This has **bold text** in it."
    pdf_bytes = markdown_to_pdf(content)
    assert pdf_bytes[:5] == b"%PDF-"


def test_markdown_to_pdf_empty():
    """Empty content generates a valid PDF."""
    pdf_bytes = markdown_to_pdf("")
    assert pdf_bytes[:5] == b"%PDF-"


def test_markdown_to_pdf_long_content():
    """Long content generates multi-page PDF."""
    lines = [f"Line {i}: This is a test line with some content." for i in range(200)]
    content = "\n".join(lines)
    pdf_bytes = markdown_to_pdf(content, title="Long Report")
    assert pdf_bytes[:5] == b"%PDF-"
    # Multi-page PDF should be larger
    assert len(pdf_bytes) > 1000
