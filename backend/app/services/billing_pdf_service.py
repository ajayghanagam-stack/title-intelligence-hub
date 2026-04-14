"""Billing PDF report generation using fpdf2 with Logikality branding."""

from __future__ import annotations

from pathlib import Path
from fpdf import FPDF


# ── Brand Colors (shared with TI pdf_service.py) ─────────────────────────────

_BRAND_AMBER = (197, 155, 0)
_BRAND_CHARCOAL = (45, 41, 36)
_BRAND_MAGENTA = (196, 46, 124)
_WHITE = (255, 255, 255)
_BODY = (30, 30, 30)
_MUTED = (100, 100, 100)
_TABLE_HDR = (240, 242, 245)
_TABLE_ALT = (248, 249, 251)

class _BillingPDF(FPDF):
    """FPDF subclass with brand footer."""

    def footer(self):
        self.set_y(-14)
        self.set_draw_color(*_BRAND_MAGENTA)
        self.set_line_width(0.3)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 5, f"Page {self.page_no()}", align="C")


def _find_logo() -> str | None:
    """Return path to Logikality logo."""
    assets_dir = Path(__file__).resolve().parent.parent / "micro_apps" / "title_intelligence" / "assets"
    bundled = assets_dir / "logikality_with_tagline.png"
    if bundled.is_file():
        return str(bundled)
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


def _clean(text: str) -> str:
    """Replace Unicode chars that fpdf2 (latin-1) cannot encode."""
    replacements = {
        "\u2013": "-", "\u2014": "--", "\u2018": "'", "\u2019": "'",
        "\u201c": '"', "\u201d": '"', "\u2026": "...", "\u2022": "-",
        "\u00a0": " ",
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _format_date_display(iso_date: str) -> str:
    """Convert YYYY-MM-DD to a readable format like 'Apr 14, 2026'."""
    try:
        from datetime import datetime
        dt = datetime.strptime(iso_date, "%Y-%m-%d")
        return dt.strftime("%b %d, %Y")
    except (ValueError, TypeError):
        return iso_date


def _section_header(pdf: _BillingPDF, title: str, w: float) -> None:
    """Render a brand amber full-width section header bar."""
    pdf.ln(6)
    # Page-break check: need at least 40mm for header + a few rows
    if pdf.get_y() > pdf.h - 40:
        pdf.add_page()
    pdf.set_fill_color(*_BRAND_AMBER)
    pdf.set_text_color(*_WHITE)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(w, 9, f"  {title}", new_x="LMARGIN", new_y="NEXT", fill=True)
    pdf.set_text_color(*_BODY)
    pdf.ln(3)


def generate_billing_report_pdf(
    org_name: str,
    start_date: str,
    end_date: str,
    apps_usage: list[dict],
) -> bytes:
    """Generate a branded usage report PDF for a single org.

    Args:
        org_name: Customer organization name.
        start_date: ISO date string (YYYY-MM-DD).
        end_date: ISO date string (YYYY-MM-DD).
        apps_usage: List of dicts with keys: app_slug, app_name,
            completed_count, total_count, items (list of item dicts).

    Returns:
        PDF file bytes.
    """
    pdf = _BillingPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    w = pdf.w - pdf.l_margin - pdf.r_margin
    start_display = _format_date_display(start_date)
    end_display = _format_date_display(end_date)

    # ── Logo ──
    logo_path = _find_logo()
    if logo_path:
        pdf.image(logo_path, x=pdf.l_margin, y=10, w=50)
        pdf.ln(20)
    else:
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_text_color(*_BRAND_AMBER)
        pdf.cell(0, 10, "Logikality", new_x="LMARGIN", new_y="NEXT")

    # ── Title with dates ──
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(*_BRAND_CHARCOAL)
    pdf.cell(0, 12, "Usage Report", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(*_BODY)
    pdf.cell(0, 7, org_name, new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*_BRAND_CHARCOAL)
    pdf.cell(0, 7, f"{start_display}  -  {end_display}", new_x="LMARGIN", new_y="NEXT")

    # ── Divider ──
    pdf.ln(4)
    pdf.set_draw_color(*_BRAND_AMBER)
    pdf.set_line_width(0.5)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + w, pdf.get_y())
    pdf.ln(6)

    # ══════════════════════════════════════════════════════════════
    # SUMMARY TABLE
    # ══════════════════════════════════════════════════════════════
    col_widths = [w * 0.65, w * 0.35]
    columns = ["Application", "Completed"]

    pdf.set_fill_color(*_BRAND_AMBER)
    pdf.set_text_color(*_WHITE)
    pdf.set_font("Helvetica", "B", 9)
    for i, col in enumerate(columns):
        align = "L" if i == 0 else "C"
        pdf.cell(col_widths[i], 8, col, border=0, fill=True, align=align)
    pdf.ln()

    pdf.set_text_color(*_BODY)
    pdf.set_font("Helvetica", "", 9)

    if not apps_usage:
        pdf.set_fill_color(*_TABLE_ALT)
        pdf.cell(sum(col_widths), 8, "No applications subscribed", border=0, fill=True, align="C")
        pdf.ln()
    else:
        for idx, app in enumerate(apps_usage):
            bg = _TABLE_ALT if idx % 2 == 1 else _WHITE
            pdf.set_fill_color(*bg)

            completed = app.get("completed_count", 0)

            pdf.cell(col_widths[0], 8, _clean(app.get("app_name", "")), border=0, fill=True, align="L")
            pdf.cell(col_widths[1], 8, str(completed), border=0, fill=True, align="C")
            pdf.ln()

    # Bottom border for summary
    pdf.set_draw_color(200, 205, 210)
    pdf.set_line_width(0.2)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + sum(col_widths), pdf.get_y())

    # ══════════════════════════════════════════════════════════════
    # DETAIL SECTIONS PER APP
    # ══════════════════════════════════════════════════════════════
    for app in (apps_usage or []):
        items = app.get("items", [])
        if not items:
            continue

        slug = app.get("app_slug", "")

        if slug == "title-intelligence":
            _render_ti_detail(pdf, w, items)
        elif slug == "title-search":
            _render_tsa_detail(pdf, w, items)

    # ── Footer note ──
    pdf.ln(10)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(130, 130, 130)
    pdf.cell(0, 5, "Generated by Logikality Title Intelligence Hub", new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())


# ── Detail renderers ──────────────────────────────────────────────────────────


def _render_ti_detail(pdf: _BillingPDF, w: float, items: list[dict]) -> None:
    """Render Title Intelligence detail: completed packs with uploaded filenames."""
    _section_header(pdf, "Title Intelligence - Completed Uploads", w)

    col_w = [w * 0.10, w * 0.65, w * 0.25]
    headers = ["#", "Filename(s)", "Date"]

    # Column header
    pdf.set_fill_color(*_TABLE_HDR)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*_BODY)
    for i, h in enumerate(headers):
        pdf.cell(col_w[i], 7, h, border=0, fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    for idx, item in enumerate(items):
        filenames = item.get("filenames", [])
        file_display = ", ".join(filenames) if filenames else item.get("name", "-")
        created = item.get("created_at", "")

        # Compute row height for multi-line filename cell
        n_lines = max(1, len(pdf.multi_cell(col_w[1], 4, _clean(file_display), border=0, dry_run=True, output="LINES")))
        row_h = max(6, n_lines * 4)

        # Page break check
        if pdf.get_y() + row_h > pdf.h - 20:
            pdf.add_page()

        bg = _TABLE_ALT if idx % 2 == 1 else _WHITE
        pdf.set_fill_color(*bg)

        y_start = pdf.get_y()
        x_start = pdf.get_x()

        # Background rect
        pdf.rect(x_start, y_start, sum(col_w), row_h, style="F")

        # # column
        pdf.set_xy(x_start, y_start)
        pdf.set_text_color(*_MUTED)
        pdf.cell(col_w[0], row_h, str(idx + 1), border=0)

        # Filename(s) column (multi-line)
        pdf.set_xy(x_start + col_w[0], y_start)
        pdf.set_text_color(*_BODY)
        pdf.multi_cell(col_w[1], 4, _clean(file_display), border=0, new_x="RIGHT", new_y="TOP")

        # Date column
        pdf.set_xy(x_start + col_w[0] + col_w[1], y_start)
        pdf.set_text_color(*_MUTED)
        pdf.cell(col_w[2], row_h, created, border=0)

        pdf.set_xy(x_start, y_start + row_h)
        pdf.set_text_color(*_BODY)

    # Bottom line
    pdf.set_draw_color(200, 205, 210)
    pdf.set_line_width(0.2)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + sum(col_w), pdf.get_y())


def _render_tsa_detail(pdf: _BillingPDF, w: float, items: list[dict]) -> None:
    """Render Title Search detail: completed orders with property address."""
    _section_header(pdf, "Title Search & Abstracting - Completed Orders", w)

    col_w = [w * 0.10, w * 0.65, w * 0.25]
    headers = ["#", "Order / Property Address", "Date"]

    pdf.set_fill_color(*_TABLE_HDR)
    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(*_BODY)
    for i, h in enumerate(headers):
        pdf.cell(col_w[i], 7, h, border=0, fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    for idx, item in enumerate(items):
        name = item.get("name", "-")
        created = item.get("created_at", "")

        n_lines = max(1, len(pdf.multi_cell(col_w[1], 4, _clean(name), border=0, dry_run=True, output="LINES")))
        row_h = max(6, n_lines * 4)

        if pdf.get_y() + row_h > pdf.h - 20:
            pdf.add_page()

        bg = _TABLE_ALT if idx % 2 == 1 else _WHITE
        pdf.set_fill_color(*bg)

        y_start = pdf.get_y()
        x_start = pdf.get_x()

        pdf.rect(x_start, y_start, sum(col_w), row_h, style="F")

        # #
        pdf.set_xy(x_start, y_start)
        pdf.set_text_color(*_MUTED)
        pdf.cell(col_w[0], row_h, str(idx + 1), border=0)

        # Order name
        pdf.set_xy(x_start + col_w[0], y_start)
        pdf.set_text_color(*_BODY)
        pdf.multi_cell(col_w[1], 4, _clean(name), border=0, new_x="RIGHT", new_y="TOP")

        # Date
        pdf.set_xy(x_start + col_w[0] + col_w[1], y_start)
        pdf.set_text_color(*_MUTED)
        pdf.cell(col_w[2], row_h, created, border=0)

        pdf.set_xy(x_start, y_start + row_h)
        pdf.set_text_color(*_BODY)

    pdf.set_draw_color(200, 205, 210)
    pdf.set_line_width(0.2)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + sum(col_w), pdf.get_y())
