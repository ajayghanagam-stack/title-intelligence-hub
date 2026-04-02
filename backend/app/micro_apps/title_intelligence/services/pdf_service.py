"""Professional Title Examination Report PDF generation using fpdf2."""

from __future__ import annotations

import re
from pathlib import Path
from fpdf import FPDF


# ── Logikality Brand Colors ──────────────────────────────────────────────────

_BRAND_AMBER = (197, 155, 0)
_BRAND_CHARCOAL = (45, 41, 36)
_BRAND_MAGENTA = (196, 46, 124)
_WHITE = (255, 255, 255)
_BODY = (30, 30, 30)
_MUTED = (100, 100, 100)
_TABLE_HDR = (240, 242, 245)
_TABLE_ALT = (248, 249, 251)
_BORDER = (200, 205, 210)

_SEVERITY_COLORS = {
    "critical": (185, 28, 28),
    "high": (180, 120, 0),
    "medium": (140, 105, 20),
    "low": (100, 100, 100),
}

_PRIORITY_COLORS = {
    "MUST CLEAR": (185, 28, 28),
    "REQUIRED": (180, 120, 0),
    "INFORMATIONAL": (70, 130, 180),
}

_SEVERITY_DISPLAY = {
    "critical": "CRITICAL",
    "high": "HIGH",
    "medium": "MODERATE",
    "low": "STANDARD",
}


# ── FPDF subclass ────────────────────────────────────────────────────────────

class _TIReportPDF(FPDF):
    """FPDF subclass with brand footer."""

    def footer(self):
        self.set_y(-14)
        # Thin magenta accent line
        self.set_draw_color(*_BRAND_MAGENTA)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5, f"Page {self.page_no()}", align="C")


# ── Logo finder ───────────────────────────────────────────────────────────────

def _find_logikality_logo() -> str | None:
    """Return path to the Logikality logo (bundled in backend assets)."""
    # Primary: bundled asset (works in Docker and local dev)
    assets_dir = Path(__file__).resolve().parent.parent / "assets"
    bundled = assets_dir / "logikality_with_tagline.png"
    if bundled.is_file():
        return str(bundled)
    # Fallback: frontend/public (local dev only)
    current = Path(__file__).resolve().parent
    while current != current.parent:
        pub = current / "frontend" / "public"
        if pub.is_dir():
            for name in ("logikality_with_tagline.png", "logikality_logo.png"):
                p = pub / name
                if p.is_file():
                    return str(p)
        current = current.parent
    return None


# ── Text utilities ────────────────────────────────────────────────────────────

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


# ── Reusable PDF building blocks ─────────────────────────────────────────────

def _section_header(pdf: _TIReportPDF, title: str, w: float) -> None:
    """Render a brand amber full-width section header bar with white text."""
    pdf.ln(6)
    _page_break_check(pdf, 14)
    pdf.set_fill_color(*_BRAND_AMBER)
    pdf.set_text_color(*_WHITE)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(w, 10, f"  {title}", new_x="LMARGIN", new_y="NEXT", fill=True)
    pdf.set_text_color(*_BODY)
    pdf.ln(3)


def _kv_row(pdf: _TIReportPDF, label: str, value: str, w: float, label_pct: float = 0.35) -> None:
    """Render a bold-label + value key-value row."""
    if not value:
        return
    _page_break_check(pdf, 7)
    label_w = w * label_pct
    value_w = w * (1.0 - label_pct)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*_BODY)
    pdf.cell(label_w, 6, _clean(label), new_x="RIGHT", new_y="TOP")
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(value_w, 6, _clean(value), new_x="LMARGIN", new_y="NEXT")


def _table_header(pdf: _TIReportPDF, columns: list[str], widths: list[float]) -> None:
    """Render a gray background column header row."""
    pdf.set_fill_color(*_TABLE_HDR)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*_BODY)
    for i, col in enumerate(columns):
        pdf.cell(widths[i], 7, col, border=0, fill=True)
    pdf.ln()


def _table_row(
    pdf: _TIReportPDF,
    cells: list[str],
    widths: list[float],
    row_idx: int,
) -> None:
    """Render a data row with alternating background."""
    # Compute row height
    pdf.set_font("Helvetica", "", 8)
    max_h = 5.0
    for text, w in zip(cells, widths):
        n_lines = max(1, len(pdf.multi_cell(w, 4, _clean(text), border=0, dry_run=True, output="LINES")))
        h = n_lines * 4
        if h > max_h:
            max_h = h

    _page_break_check(pdf, max_h + 2)

    bg = _TABLE_ALT if row_idx % 2 == 1 else _WHITE
    pdf.set_fill_color(*bg)
    pdf.set_font("Helvetica", "", 8)

    x_start = pdf.get_x()
    y_start = pdf.get_y()

    # Background rect
    total_w = sum(widths)
    pdf.rect(x_start, y_start, total_w, max_h, style="F")

    # Draw cells
    x = x_start
    for i, text in enumerate(cells):
        pdf.set_xy(x, y_start)
        pdf.multi_cell(widths[i], 4, _clean(text), border=0, new_x="RIGHT", new_y="TOP")
        x += widths[i]

    pdf.set_xy(x_start, y_start + max_h)


def _severity_label(severity: str) -> str:
    """Return display name for severity."""
    return _SEVERITY_DISPLAY.get(severity, severity.upper())


def _severity_badge(pdf: _TIReportPDF, severity: str, x: float, y: float) -> float:
    """Draw a colored severity pill badge. Returns badge width."""
    label = _severity_label(severity)
    color = _SEVERITY_COLORS.get(severity, _MUTED)
    pdf.set_font("Helvetica", "B", 7)
    text_w = pdf.get_string_width(label) + 4
    badge_h = 5
    # Draw pill background
    pdf.set_fill_color(*color)
    pdf.rect(x, y + 0.5, text_w, badge_h, style="F")
    # Draw text
    pdf.set_text_color(*_WHITE)
    pdf.set_xy(x, y + 0.5)
    pdf.cell(text_w, badge_h, label, align="C")
    pdf.set_text_color(*_BODY)
    return text_w


def _priority_badge(pdf: _TIReportPDF, priority: str, x: float, y: float) -> float:
    """Draw a colored priority pill badge. Returns badge width."""
    color = _PRIORITY_COLORS.get(priority, _MUTED)
    pdf.set_font("Helvetica", "B", 7)
    text_w = pdf.get_string_width(priority) + 4
    badge_h = 5
    pdf.set_fill_color(*color)
    pdf.rect(x, y + 0.5, text_w, badge_h, style="F")
    pdf.set_text_color(*_WHITE)
    pdf.set_xy(x, y + 0.5)
    pdf.cell(text_w, badge_h, priority, align="C")
    pdf.set_text_color(*_BODY)
    return text_w


def _narrative(pdf: _TIReportPDF, text: str, w: float) -> None:
    """Render a wrapped paragraph in regular body font."""
    if not text:
        return
    _page_break_check(pdf, 10)
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_BODY)
    pdf.multi_cell(w, 5, _clean(text), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)



def _page_break_check(pdf: _TIReportPDF, needed_h: float) -> None:
    """Add a new page if there isn't enough vertical space."""
    if pdf.get_y() + needed_h > pdf.h - pdf.b_margin:
        pdf.add_page()


# ── Section renderers ─────────────────────────────────────────────────────────

def _render_header(pdf: _TIReportPDF, data: dict, w: float) -> None:
    """Render report title block matching reference document format."""
    # Logo (right-aligned on its own row)
    logo_path = _find_logikality_logo()
    if logo_path:
        pdf.image(logo_path, x=pdf.w - pdf.r_margin - 50, y=pdf.get_y(), h=12)
        pdf.ln(16)

    # Title (centered, below logo)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(*_BRAND_CHARCOAL)
    pdf.cell(0, 10, "TITLE EXAMINATION REPORT", new_x="LMARGIN", new_y="NEXT", align="C")

    # Subtitle
    subtitle = data.get("subtitle", "Exceptions from Coverage & Schedule C Warnings")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*_MUTED)
    pdf.cell(0, 6, _clean(subtitle), new_x="LMARGIN", new_y="NEXT", align="C")

    # Commitment / file number line
    commit = data.get("commitment_number", "")
    faf = data.get("faf_file_number", "")
    if commit or faf:
        parts = []
        if commit:
            parts.append(f"Commitment No. {commit}")
        if faf:
            parts.append(f"FAF File No. {faf}")
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 5, _clean("  |  ".join(parts)), new_x="LMARGIN", new_y="NEXT", align="C")

    # Effective date / issued date line
    eff = data.get("effective_date", "")
    issued = data.get("issued_date", "")
    if eff or issued:
        parts = []
        if eff:
            parts.append(f"Effective Date: {eff}")
        if issued:
            parts.append(f"Issued: {issued}")
        pdf.cell(0, 5, _clean("  |  ".join(parts)), new_x="LMARGIN", new_y="NEXT", align="C")

    # Thin brand amber horizontal rule
    pdf.ln(3)
    pdf.set_draw_color(*_BRAND_AMBER)
    pdf.set_line_width(0.8)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(3)

    pdf.set_text_color(*_BODY)


def _render_transaction_summary(pdf: _TIReportPDF, data: dict, w: float) -> None:
    """Section I: Transaction Summary — full key-value grid."""
    _section_header(pdf, "I.  TRANSACTION SUMMARY", w)

    fields = [
        ("GF / Commitment No:", data.get("commitment_number", "")),
        ("FAF File Number:", data.get("faf_file_number", "")),
        ("Effective Date:", data.get("effective_date", "")),
        ("Issued Date:", data.get("issued_date", "")),
        ("County:", data.get("county", "")),
        ("State:", data.get("state", "")),
        ("Property Address:", data.get("property_address", "")),
        ("Legal Description:", data.get("legal_description", "")),
        ("Interest Type:", data.get("interest_type", "")),
        ("Proposed Buyer / Borrower:", data.get("buyer_borrower", "")),
        ("Current Owner / Seller:", data.get("seller", "")),
        ("Lender:", data.get("lender", "")),
        ("Issuing Agent:", data.get("title_company", "")),
        ("Underwriter:", data.get("underwriter", "")),
        ("Owner's Policy:", data.get("owners_policy", "") or data.get("policy_amount", "")),
        ("Lender's Policy:", data.get("lenders_policy", "")),
        ("Report Generated:", data.get("generated_at", "")),
    ]

    for label, value in fields:
        if value:  # skip empty fields instead of showing N/A
            _kv_row(pdf, label, value, w)

    pdf.ln(2)


def _render_risk_summary(pdf: _TIReportPDF, data: dict, w: float) -> None:
    """Section II: Examiner's Risk Summary — severity count boxes + narrative."""
    _section_header(pdf, "II.  EXAMINER'S RISK SUMMARY", w)

    flags_by_severity = data.get("flags_by_severity", {})

    # 4 colored severity count boxes in a row
    box_w = w / 4 - 2
    box_h = 14
    x_start = pdf.get_x()
    y_start = pdf.get_y()

    for i, sev in enumerate(("critical", "high", "medium", "low")):
        n = len(flags_by_severity.get(sev, []))
        color = _SEVERITY_COLORS.get(sev, _MUTED)
        label = _SEVERITY_DISPLAY.get(sev, sev.upper())
        x = x_start + i * (box_w + 2.5)

        # Colored box
        pdf.set_fill_color(*color)
        pdf.rect(x, y_start, box_w, box_h, style="F")

        # Label text (white, bold)
        pdf.set_text_color(*_WHITE)
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_xy(x, y_start + 1)
        pdf.cell(box_w, 5, label, align="C")

        # Count text
        pdf.set_font("Helvetica", "", 8)
        pdf.set_xy(x, y_start + 6.5)
        item_text = f"{n} item{'s' if n != 1 else ''}"
        pdf.cell(box_w, 5, item_text, align="C")

    pdf.set_xy(x_start, y_start + box_h + 4)
    pdf.set_text_color(*_BODY)

    # Risk narrative
    risk_text = data.get("risk_assessment", "")
    if risk_text:
        for line in risk_text.split("\n"):
            line = line.strip()
            if line.startswith("- "):
                line = line[2:]
            if line:
                _narrative(pdf, line, w)

    pdf.ln(2)


def _render_note(pdf: _TIReportPDF, note: str, w: float) -> None:
    """Render a user note block below item content."""
    if not note:
        return
    note_text = _clean(note)
    # Estimate height for page break check
    lines = pdf.multi_cell(w - 14, 4.5, note_text, dry_run=True, output="LINES")
    _page_break_check(pdf, len(lines) * 4.5 + 6)

    x_start = pdf.l_margin + 4
    pdf.set_xy(x_start, pdf.get_y())
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*_MUTED)
    pdf.cell(10, 4.5, "Note:")
    pdf.set_font("Helvetica", "I", 8)
    pdf.multi_cell(w - 14, 4.5, note_text, new_x="LMARGIN", new_y="NEXT")


def _render_exception_item(pdf: _TIReportPDF, item: dict, w: float, prefix: str = "B") -> None:
    """Render a single exception in card format with severity badge."""
    num = str(item.get("number", ""))
    title = item.get("title", "")
    desc = item.get("description", "")
    severity = item.get("severity", "")
    note = item.get("note") or ""

    # Estimate height needed
    pdf.set_font("Helvetica", "", 9)
    desc_text = _clean(desc) if desc else ""
    lines = pdf.multi_cell(w - 20, 5, desc_text, dry_run=True, output="LINES") if desc_text else []
    needed_h = 8 + max(len(lines) * 5, 0) + 4
    if note:
        note_lines = pdf.multi_cell(w - 14, 4.5, _clean(note), dry_run=True, output="LINES")
        needed_h += len(note_lines) * 4.5 + 6
    _page_break_check(pdf, needed_h)

    y_top = pdf.get_y()
    x_start = pdf.l_margin

    # Item number (bold)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*_BRAND_CHARCOAL)
    item_num = f"{prefix}-{num}" if prefix and num else str(num)
    num_w = pdf.get_string_width(item_num) + 3
    pdf.set_xy(x_start, y_top)
    pdf.cell(num_w, 6, item_num)

    # Severity badge
    badge_x = x_start + num_w + 1
    badge_w = 0
    if severity:
        badge_w = _severity_badge(pdf, severity, badge_x, y_top) + 2

    # Bold title on same line
    title_x = badge_x + badge_w + 1
    if title:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_BRAND_CHARCOAL)
        pdf.set_xy(title_x, y_top)
        pdf.cell(w - (title_x - x_start), 6, _clean(title))

    pdf.set_xy(x_start + 4, y_top + 7)

    # Description paragraph (indented)
    if desc_text:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_BODY)
        pdf.multi_cell(w - 8, 5, desc_text, new_x="LMARGIN", new_y="NEXT")

    # User note
    _render_note(pdf, note, w)

    pdf.ln(3)


def _render_schedule_b(pdf: _TIReportPDF, data: dict, w: float) -> None:
    """Section III: Schedule B — Exceptions with card-style items."""
    _section_header(pdf, "III.  SCHEDULE B -- EXCEPTIONS FROM COVERAGE", w)

    standard = data.get("standard_exceptions", [])
    specific = data.get("specific_exceptions", [])

    # Intro paragraph
    _narrative(
        pdf,
        "The following exceptions will appear in the final title policy and represent "
        "areas NOT covered against loss. Items marked CRITICAL or HIGH warrant immediate "
        "legal review or resolution.",
        w,
    )

    # 3.1 Standard / Boilerplate Exceptions
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*_BRAND_CHARCOAL)
    pdf.cell(0, 7, "3.1  Standard / Boilerplate Exceptions", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    if standard:
        for item in standard:
            _render_exception_item(pdf, item, w, prefix="B")
    else:
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(*_MUTED)
        pdf.cell(0, 6, "No standard exceptions identified.", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(3)

    # 3.2 Specific Property Exceptions
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*_BRAND_CHARCOAL)
    pdf.cell(0, 7, "3.2  Specific Property Exceptions", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    if specific:
        for item in specific:
            _render_exception_item(pdf, item, w, prefix="")
    else:
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(*_MUTED)
        pdf.cell(0, 6, "No specific exceptions identified.", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(2)


def _render_requirement_item(pdf: _TIReportPDF, item: dict, w: float) -> None:
    """Render a single requirement in card format with priority badge."""
    num = str(item.get("number", ""))
    title = item.get("title", "")
    desc = item.get("description", "")
    priority = item.get("priority", "REQUIRED")
    note = item.get("note") or ""

    pdf.set_font("Helvetica", "", 9)
    desc_text = _clean(desc) if desc else ""
    lines = pdf.multi_cell(w - 20, 5, desc_text, dry_run=True, output="LINES") if desc_text else []
    needed_h = 8 + max(len(lines) * 5, 0) + 4
    if note:
        note_lines = pdf.multi_cell(w - 14, 4.5, _clean(note), dry_run=True, output="LINES")
        needed_h += len(note_lines) * 4.5 + 6
    _page_break_check(pdf, needed_h)

    y_top = pdf.get_y()
    x_start = pdf.l_margin

    # Item number (bold)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*_BRAND_CHARCOAL)
    item_num = f"C-{num}" if num else ""
    num_w = pdf.get_string_width(item_num) + 3
    pdf.set_xy(x_start, y_top)
    pdf.cell(num_w, 6, item_num)

    # Priority badge
    badge_x = x_start + num_w + 1
    badge_w = _priority_badge(pdf, priority, badge_x, y_top) + 2

    # Bold title on same line
    title_x = badge_x + badge_w + 1
    if title:
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*_BRAND_CHARCOAL)
        pdf.set_xy(title_x, y_top)
        pdf.cell(w - (title_x - x_start), 6, _clean(title))

    pdf.set_xy(x_start + 4, y_top + 7)

    # Description paragraph (indented)
    if desc_text:
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_BODY)
        pdf.multi_cell(w - 8, 5, desc_text, new_x="LMARGIN", new_y="NEXT")

    # User note
    _render_note(pdf, note, w)

    pdf.ln(3)


def _render_schedule_c(pdf: _TIReportPDF, data: dict, w: float) -> None:
    """Section IV: Schedule C — Requirements with priority badges."""
    requirements = data.get("requirements", [])
    _section_header(pdf, "IV.  SCHEDULE C -- REQUIREMENTS & CONDITIONS", w)

    # Intro paragraph
    _narrative(
        pdf,
        "The following items MUST be satisfied before the title policy can be issued. "
        "Failure to clear these requirements will result in them appearing as exceptions "
        "or in refusal to insure.",
        w,
    )

    if not requirements:
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(*_MUTED)
        pdf.cell(0, 6, "No requirements identified.", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        return

    for req in requirements:
        _render_requirement_item(pdf, req, w)

    pdf.ln(2)


def _render_warnings(pdf: _TIReportPDF, data: dict, w: float) -> None:
    """Section V: Key Warnings & Examiner's Notes — with severity prefix."""
    warnings = data.get("warnings", [])
    _section_header(pdf, "V.  KEY WARNINGS & EXAMINER'S NOTES", w)

    if not warnings:
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(*_MUTED)
        pdf.cell(0, 6, "No warnings identified.", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        return

    for warning in warnings:
        _page_break_check(pdf, 18)
        severity = warning.get("severity", "high")
        sev_display = _SEVERITY_DISPLAY.get(severity, severity.upper())
        sev_color = _SEVERITY_COLORS.get(severity, _MUTED)
        title = warning.get("title", "")

        # Warning icon + severity prefix + bold title
        pdf.set_font("Helvetica", "B", 9)
        pdf.set_text_color(*sev_color)
        header = f"! {sev_display} -- {title}"
        pdf.cell(0, 6, _clean(header), new_x="LMARGIN", new_y="NEXT")

        # Explanation paragraph
        explanation = warning.get("explanation", "")
        if explanation:
            pdf.set_text_color(*_BODY)
            _narrative(pdf, explanation, w)
        pdf.ln(1)

    pdf.ln(1)


def _render_checklist(pdf: _TIReportPDF, data: dict, w: float) -> None:
    """Section VI: Pre-Closing Action Checklist as numbered table."""
    checklist = data.get("checklist_items", [])
    _section_header(pdf, "VI.  PRE-CLOSING ACTION CHECKLIST", w)

    if not checklist:
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(*_MUTED)
        pdf.cell(0, 6, "No checklist items.", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        return

    # Check if any checklist items have notes
    has_notes = any(item.get("note") for item in checklist)

    if has_notes:
        col_widths = [w * 0.05, w * 0.35, w * 0.14, w * 0.14, w * 0.32]
        _table_header(pdf, ["#", "Action Required", "Priority", "Status", "Notes"], col_widths)
    else:
        col_widths = [w * 0.06, w * 0.56, w * 0.20, w * 0.18]
        _table_header(pdf, ["#", "Action Required", "Priority", "Status"], col_widths)

    for i, item in enumerate(checklist):
        number = str(item.get("number", i + 1))
        action = item.get("action", item.get("label", ""))
        priority = item.get("priority", "")
        checked = item.get("checked", False)
        status = "[x]  Cleared" if checked else "[ ]  Pending"
        note = item.get("note") or ""

        if has_notes:
            cells = [number, action, priority, status, note]
        else:
            cells = [number, action, priority, status]
        _table_row(pdf, cells, col_widths, i)

    pdf.ln(2)


def _render_exceptions_and_actions(pdf: _TIReportPDF, data: dict, w: float) -> None:
    """Section VII: Combined Exceptions & Required Actions table with notes column.

    Shows only the root-level title per flag (no sub-descriptions), matching
    the Results page layout: item number, severity badge, title, page ref, notes.
    """
    all_flags = data.get("all_flags", [])
    _section_header(pdf, "VII.  EXCEPTIONS & REQUIRED ACTIONS", w)

    if not all_flags:
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(*_MUTED)
        pdf.cell(0, 6, "No exceptions or required actions identified.", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        return

    col_widths = [w * 0.07, w * 0.36, w * 0.12, w * 0.10, w * 0.35]
    _table_header(pdf, ["#", "Title", "Severity", "Page Ref", "Notes"], col_widths)

    for i, flag in enumerate(all_flags):
        number = f"EX-{str(i + 1).zfill(3)}"
        title = flag.get("title", "")
        severity = _SEVERITY_DISPLAY.get(flag.get("severity", ""), flag.get("severity", "").upper())
        page_ref = flag.get("page_ref", "")
        note = flag.get("note") or ""
        _table_row(pdf, [number, title, severity, page_ref, note], col_widths, i)

    pdf.ln(2)


def _render_disclaimer(pdf: _TIReportPDF, data: dict, w: float) -> None:
    """Section VII: Examiner's Disclaimer with signature section."""
    _section_header(pdf, "VII.  EXAMINER'S DISCLAIMER", w)

    disclaimer_p1 = (
        "This Title Examination Report is prepared solely on the basis of the "
        "Commitment for Title Insurance and the instruments referenced therein as of "
        "the effective date. This report does not constitute legal advice or a legal "
        "opinion and should not be relied upon as such. All findings are based on "
        "AI-assisted analysis and should be reviewed by a licensed title examiner "
        "before reliance."
    )
    disclaimer_p2 = (
        "The commitment expires ninety (90) days from its effective date unless the "
        "policy is issued sooner. All Schedule C requirements must be satisfied and "
        "all Schedule B exceptions must be resolved to the Company's satisfaction "
        "before a clean policy can be issued."
    )

    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*_BODY)
    pdf.multi_cell(w, 5, _clean(disclaimer_p1), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.multi_cell(w, 5, _clean(disclaimer_p2), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # Horizontal signature line
    _page_break_check(pdf, 40)
    pdf.set_draw_color(*_BRAND_CHARCOAL)
    pdf.set_line_width(0.3)

    # Two-column signature area
    col_w = w / 2 - 5
    y_sig = pdf.get_y()

    # Left: Prepared By
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*_BRAND_CHARCOAL)
    pdf.set_xy(pdf.l_margin, y_sig)
    pdf.cell(col_w, 5, "Prepared By:")
    pdf.set_xy(pdf.l_margin, y_sig + 8)
    pdf.line(pdf.l_margin, y_sig + 14, pdf.l_margin + col_w * 0.8, y_sig + 14)
    pdf.set_xy(pdf.l_margin, y_sig + 16)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(col_w, 5, "Logikality AI-Assisted Title Examination")

    # Right: Report Date + File Reference
    right_x = pdf.l_margin + col_w + 10
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_xy(right_x, y_sig)
    pdf.cell(col_w, 5, "Report Date:")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_xy(right_x, y_sig + 6)
    pdf.cell(col_w, 5, _clean(data.get("generated_at", "")))

    pdf.set_xy(right_x, y_sig + 14)
    pdf.set_font("Helvetica", "B", 9)
    commit = data.get("commitment_number", "")
    faf = data.get("faf_file_number", "")
    file_ref = commit
    if faf:
        file_ref += f" / FAF {faf}" if commit else faf
    pdf.cell(col_w, 5, "File Reference:")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_xy(right_x, y_sig + 20)
    pdf.cell(col_w, 5, _clean(file_ref))

    pdf.set_xy(pdf.l_margin, y_sig + 28)
    pdf.set_text_color(*_BODY)
    pdf.ln(2)


# ── Main entry point ──────────────────────────────────────────────────────────

def generate_pack_report_pdf(report_data: dict) -> bytes:
    """Build a professional Title Examination Report PDF.

    Args:
        report_data: Dictionary containing all report sections. Expected keys:
            - property_address, county, state, legal_description
            - commitment_number, effective_date, policy_amount
            - buyer_borrower, seller, lender, title_company, underwriter
            - generated_at
            - flags_by_severity: {critical: [...], high: [...], ...}
            - total_open: int
            - risk_assessment: str
            - standard_exceptions: [{number, description, page_ref}]
            - specific_exceptions: [{number, description, severity, status, page_ref}]
            - requirements: [{number, description, status, page_ref}]
            - warnings: [{title, explanation, flag_type}]
            - checklist_items: [{label, checked}]

    Returns:
        PDF bytes.
    """
    pdf = _TIReportPDF()
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.add_page()
    w = pdf.epw

    _render_header(pdf, report_data, w)
    _render_transaction_summary(pdf, report_data, w)
    _render_risk_summary(pdf, report_data, w)
    _render_schedule_b(pdf, report_data, w)
    _render_schedule_c(pdf, report_data, w)
    _render_warnings(pdf, report_data, w)
    _render_checklist(pdf, report_data, w)
    return bytes(pdf.output())
