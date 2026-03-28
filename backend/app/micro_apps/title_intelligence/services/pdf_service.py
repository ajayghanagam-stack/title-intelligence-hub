"""Data-driven PDF report generation using fpdf2."""

from __future__ import annotations

import re
from fpdf import FPDF


# Severity sort order for table rows
_SEVERITY_ORDER = {"critical": 0, "warning": 1, "high": 1, "medium": 2, "review": 3, "low": 3}

# Column layout: (header_label, width_pct)
_COLUMNS = [
    ("ID", 0.06),
    ("Severity", 0.10),
    ("Category", 0.14),
    ("Description", 0.36),
    ("Doc Ref", 0.14),
    ("Action", 0.20),
]

# Colors
_HEADER_BG = (45, 55, 72)
_HEADER_FG = (255, 255, 255)
_ROW_ALT = (245, 247, 250)
_ROW_NORMAL = (255, 255, 255)


def generate_pack_report_pdf(
    property_address: str,
    order_number: str,
    commitment_date: str,
    issued_by: str,
    generated_at: str,
    critical_count: int,
    warning_count: int,
    review_count: int,
    validation_score: int,
    exceptions: list[dict],
) -> bytes:
    """Build a data-driven Title Intelligence Report PDF.

    Args:
        property_address: Property address string.
        order_number: Commitment / order number.
        commitment_date: Effective / commitment date.
        issued_by: Title company or underwriter name.
        generated_at: Human-readable generation timestamp.
        critical_count: Number of critical-severity flags.
        warning_count: Number of high+medium-severity flags.
        review_count: Number of open/escalated flags.
        validation_score: Readiness score 0-10.
        exceptions: List of dicts with keys:
            id, severity, category, description, doc_ref, action
    """
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    usable = pdf.w - pdf.l_margin - pdf.r_margin

    # ── Title ──
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 12, "Title Intelligence Report", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(4)

    # ── Property Info Block ──
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, _clean(property_address or "N/A"), new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 10)
    info_lines = [
        ("Order No:", order_number),
        ("Commitment Date:", commitment_date),
        ("Issued By:", issued_by),
        ("Generated:", generated_at),
    ]
    for label, value in info_lines:
        pdf.cell(35, 6, label)
        pdf.cell(0, 6, _clean(value or "N/A"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # ── Executive Summary ──
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Executive Summary", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    summary = (
        f"Critical: {critical_count}  |  "
        f"Warnings: {warning_count}  |  "
        f"Review: {review_count}  |  "
        f"Validation: {validation_score}/10"
    )
    pdf.cell(0, 7, summary, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # ── Exceptions & Required Actions ──
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "Exceptions & Required Actions", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    if not exceptions:
        pdf.set_font("Helvetica", "I", 10)
        pdf.cell(0, 7, "No exceptions found.", new_x="LMARGIN", new_y="NEXT")
        return bytes(pdf.output())

    # Compute column widths
    col_widths = [usable * pct for _, pct in _COLUMNS]

    # Table header
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_fill_color(*_HEADER_BG)
    pdf.set_text_color(*_HEADER_FG)
    for i, (label, _) in enumerate(_COLUMNS):
        pdf.cell(col_widths[i], 8, label, border=0, fill=True)
    pdf.ln()
    pdf.set_text_color(0, 0, 0)

    # Table rows
    sorted_exceptions = sorted(
        exceptions,
        key=lambda e: (_SEVERITY_ORDER.get(e.get("severity", "low"), 9), e.get("category", "")),
    )

    for row_idx, exc in enumerate(sorted_exceptions):
        row_data = [
            str(exc.get("id", "")),
            str(exc.get("severity", "")).title(),
            _clean(str(exc.get("category", ""))),
            _clean(str(exc.get("description", ""))),
            _clean(str(exc.get("doc_ref", ""))),
            _clean(str(exc.get("action", ""))),
        ]

        # Determine row height by measuring the tallest cell
        row_height = _compute_row_height(pdf, row_data, col_widths, font_size=8)

        # Check if row fits on current page
        if pdf.get_y() + row_height > pdf.h - pdf.b_margin:
            pdf.add_page()
            # Re-draw header on new page
            pdf.set_font("Helvetica", "B", 8)
            pdf.set_fill_color(*_HEADER_BG)
            pdf.set_text_color(*_HEADER_FG)
            for i, (label, _) in enumerate(_COLUMNS):
                pdf.cell(col_widths[i], 8, label, border=0, fill=True)
            pdf.ln()
            pdf.set_text_color(0, 0, 0)

        # Alternating row background
        bg = _ROW_ALT if row_idx % 2 == 1 else _ROW_NORMAL
        pdf.set_fill_color(*bg)
        pdf.set_font("Helvetica", "", 8)

        x_start = pdf.get_x()
        y_start = pdf.get_y()

        # Draw background rect for the full row
        pdf.rect(x_start, y_start, usable, row_height, style="F")

        # Draw each cell
        x = x_start
        for i, text in enumerate(row_data):
            pdf.set_xy(x, y_start)
            pdf.multi_cell(col_widths[i], 4, text, border=0, new_x="RIGHT", new_y="TOP")
            x += col_widths[i]

        pdf.set_xy(x_start, y_start + row_height)

    return bytes(pdf.output())


def _compute_row_height(pdf: FPDF, cells: list[str], widths: list[float], font_size: int = 8) -> float:
    """Compute the height needed for the tallest cell in a row."""
    pdf.set_font("Helvetica", "", font_size)
    max_h = 4.0  # minimum one line
    for text, w in zip(cells, widths):
        # Count how many lines this text needs
        n_lines = max(1, len(pdf.multi_cell(w, 4, text, border=0, dry_run=True, output="LINES")))
        h = n_lines * 4
        if h > max_h:
            max_h = h
    return max_h


def _clean(text: str) -> str:
    """Remove markdown formatting and replace Unicode chars for PDF compatibility."""
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    text = re.sub(r"`(.*?)`", r"\1", text)
    replacements = {
        "\u2013": "-",
        "\u2014": "--",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2026": "...",
        "\u2022": "-",
        "\u00a0": " ",
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    text = text.encode("latin-1", errors="replace").decode("latin-1")
    return text
