import uuid
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.micro_apps.title_search.models.order import TAOrder
from app.micro_apps.title_search.models.document import TADocument
from app.micro_apps.title_search.models.chain_link import TAChainLink
from app.micro_apps.title_search.models.flag import TAFlag
from app.micro_apps.title_search.models.package import TAPackage
from app.core.exceptions import NotFoundError, ConflictError


async def get_package_or_raise(
    db: AsyncSession, org_id: uuid.UUID, order_id: uuid.UUID
) -> TAPackage:
    result = await db.execute(
        select(TAPackage).where(
            TAPackage.order_id == order_id,
            TAPackage.org_id == org_id,
        )
    )
    pkg = result.scalar_one_or_none()
    if not pkg:
        raise NotFoundError("Package", order_id)
    return pkg


async def issue_package(
    db: AsyncSession,
    org_id: uuid.UUID,
    order_id: uuid.UUID,
    issuer_id: uuid.UUID,
) -> TAPackage:
    """Manually issue a package. Blocks if unresolved critical flags exist."""
    pkg = await get_package_or_raise(db, org_id, order_id)

    if pkg.status == "issued":
        raise ConflictError("Package is already issued")

    flags = (await db.execute(
        select(TAFlag).where(
            TAFlag.order_id == order_id,
            TAFlag.org_id == org_id,
            TAFlag.status == "open",
            TAFlag.severity == "critical",
        )
    )).scalars().all()

    if flags:
        raise ConflictError(
            f"Cannot issue package: {len(flags)} unresolved critical flag(s)"
        )

    pkg.status = "issued"
    pkg.issued_by = "manual"
    pkg.issued_at = datetime.now(timezone.utc)
    pkg.issuer_id = issuer_id
    await db.commit()
    await db.refresh(pkg)
    return pkg


# ---------------------------------------------------------------------------
# PDF helper utilities
# ---------------------------------------------------------------------------

_HEADER_BG = (230, 126, 34)  # Logikality brand amber
_HEADER_FG = (255, 255, 255)  # White text on amber
_SUBHEADER_BG = (45, 55, 72)  # Charcoal for sub-headers
_ACCENT = (230, 126, 34)      # Amber accent lines
_ALT_ROW = (253, 246, 237)    # Warm off-white alternating rows
_SEV_COLORS = {
    "critical": (220, 53, 69),   # Red
    "high": (230, 126, 34),      # Amber
    "medium": (255, 193, 7),     # Yellow
    "low": (13, 110, 253),       # Blue
}
_ROW_H = 7
_FONT = "Helvetica"

# ---------------------------------------------------------------------------
# Research report colors — Logikality brand palette
# ---------------------------------------------------------------------------
_R_BRAND = (230, 126, 34)         # Logikality amber — section headers
_R_BRAND_DARK = (180, 95, 20)     # Darker amber for Section 8 header
_R_NAVY = (45, 55, 72)            # Charcoal — body accents, metadata labels
_R_WHITE = (255, 255, 255)
_R_BODY = (40, 40, 40)
_R_MUTED = (100, 100, 100)
_R_GREEN = (46, 125, 50)
_R_WARN = (200, 130, 0)
_R_TABLE_HDR = (220, 225, 230)
_R_TABLE_ALT = (245, 247, 249)
_R_FONT = "Helvetica"
_R_ROW_H = 7

# ---------------------------------------------------------------------------
# Research report narrative templates
# ---------------------------------------------------------------------------
_NOTE_SEC2_OWNERSHIP = (
    "Under {state} law, current owner information is public record. "
    "The {county} County Property Appraiser maintains real-time ownership data "
    "updated daily. Vesting (how title is held -- e.g., Joint Tenants, Tenants in "
    "Common, Trust) appears on the recorded deed at the {county} County Clerk of Courts."
)

_NOTE_SEC3_CHAIN = (
    "To obtain the full certified chain of title, search the {county} County Clerk's "
    "Official Records at {clerk_url} by grantor/grantee name or by parcel address. "
    "Records are available from 1988 forward; pre-1988 records require an in-person "
    "or mail request to the Clerk's Office."
)

_NOTE_SEC4_LIENS = (
    "The following categories of encumbrances must be verified through official "
    "{county} County public records searches. Status below is based on publicly "
    "available online data as of the date of this report:"
)

_NOTE_SEC5_TAX = (
    "{state} property taxes are paid in arrears. Bills are mailed in November; "
    "discounts apply for early payment (4% in November through 1% in February). "
    "Taxes become delinquent April 1 following the tax year."
)

_NOTE_SEC8_DISCLAIMER = (
    "Based on publicly available records researched as of the date of this report, "
    "the following preliminary observations are noted. This section is for "
    "informational purposes only and does NOT constitute a certified legal title "
    "opinion or title insurance commitment."
)


# Section 4 lien categories
_LIEN_CATEGORIES = [
    "Purchase Money Mortgage / First Lien",
    "Second Mortgage / HELOC",
    "Federal Tax Liens (IRS)",
    "State Tax Liens",
    "Judgment Liens",
    "HOA/COA Liens",
    "Mechanic's Liens",
    "Utility Liens / Special Assessments",
    "Code Enforcement Liens",
    "Child Support Liens",
]

# Section 7 court categories
_COURT_CATEGORIES = [
    "Active Foreclosure",
    "Pending Foreclosure Sale",
    "Lis Pendens",
    "Bankruptcy",
    "Probate / Estate",
    "Divorce Proceedings",
]


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return text.encode("latin-1", errors="replace").decode("latin-1")


def _party_names(party: dict | None) -> str:
    if not party:
        return "N/A"
    names = party.get("names", [])
    return ", ".join(names) if names else "N/A"


def _fmt_money(amount) -> str:
    if amount is None:
        return "N/A"
    try:
        return f"${float(amount):,.2f}"
    except (ValueError, TypeError):
        return "N/A"


def _fmt_doc_type(doc_type: str | None) -> str:
    if not doc_type:
        return "N/A"
    mapping = {
        "deed": "Warranty Deed",
        "mortgage": "Mortgage",
        "lien": "Lien",
        "satisfaction": "Satisfaction",
        "easement": "Easement",
        "hoa": "HOA Document",
        "judgment": "Judgment",
        "court_order": "Court Order",
        "plat": "Plat Map",
        "other": "Other",
    }
    return mapping.get(doc_type, doc_type.replace("_", " ").title())


def _deed_type_label(doc) -> str:
    """Get the best deed type label for a document."""
    # Check deed_type_detail in metadata first (e.g. "SW - Special Warranty")
    dtd = _doc_meta(doc, "deed_type_detail", "")
    if dtd and dtd != "N/A":
        # Clean up codes like "SW - Special Warranty" to just the name
        if " - " in dtd:
            return dtd.split(" - ", 1)[1]
        return dtd
    return _fmt_doc_type(doc.doc_type)


def _section_header(pdf, title: str, w: float) -> None:
    _ensure_space(pdf, _ROW_H + 8)
    pdf.set_fill_color(*_HEADER_BG)
    pdf.set_text_color(*_HEADER_FG)
    pdf.set_font(_FONT, "B", 10)
    pdf.cell(
        w, _ROW_H + 1, _clean(title), border=0, align="C",
        new_x="LMARGIN", new_y="NEXT", fill=True,
    )
    # Amber accent line below header
    pdf.set_draw_color(*_ACCENT)
    pdf.set_line_width(0.5)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + w, pdf.get_y())
    pdf.set_text_color(0, 0, 0)
    pdf.set_font(_FONT, "", 8)
    pdf.ln(1.5)


def _sub_header(pdf, title: str, w: float) -> None:
    """Charcoal sub-header for subsections."""
    _ensure_space(pdf, _ROW_H + 4)
    pdf.set_fill_color(*_SUBHEADER_BG)
    pdf.set_text_color(*_HEADER_FG)
    pdf.set_font(_FONT, "B", 8)
    pdf.cell(
        w, _ROW_H, _clean(title), border=0, align="L",
        new_x="LMARGIN", new_y="NEXT", fill=True,
    )
    pdf.set_text_color(0, 0, 0)
    pdf.set_font(_FONT, "", 8)
    pdf.ln(1)


def _ensure_space(pdf, needed: float) -> None:
    """Add a new page if there's not enough vertical space remaining."""
    remaining = pdf.h - pdf.get_y() - pdf.b_margin
    if remaining < needed:
        pdf.add_page()


def _label_value_row(pdf, label: str, value: str, w: float) -> None:
    lw = w * 0.35
    vw = w * 0.65
    val_clean = _clean(value)
    label_clean = _clean(label)

    pdf.set_font(_FONT, "", 8)
    val_lines = pdf.multi_cell(vw, _ROW_H, val_clean, dry_run=True, output="LINES")
    num_lines = len(val_lines) if val_lines else 1
    row_h = max(_ROW_H, _ROW_H * num_lines)

    _ensure_space(pdf, row_h + 2)

    x, y = pdf.get_x(), pdf.get_y()
    pdf.set_font(_FONT, "B", 8)
    pdf.cell(lw, row_h, label_clean, border=0, new_x="END", new_y="TOP")
    pdf.set_font(_FONT, "", 8)
    pdf.set_xy(x + lw, y)
    pdf.multi_cell(vw, _ROW_H, val_clean, border=0, new_x="LMARGIN", new_y="NEXT")

    expected_y = y + row_h
    if pdf.get_y() < expected_y:
        pdf.set_y(expected_y)


def _split_row(pdf, l1, v1, l2, v2, w) -> None:
    _ensure_space(pdf, _ROW_H + 2)
    col = w / 4
    pdf.set_font(_FONT, "B", 8)
    pdf.cell(col, _ROW_H, _clean(l1), border=0, new_x="END", new_y="TOP")
    pdf.set_font(_FONT, "", 8)
    pdf.cell(col, _ROW_H, _clean(v1), border=0, new_x="END", new_y="TOP")
    pdf.set_font(_FONT, "B", 8)
    pdf.cell(col, _ROW_H, _clean(l2), border=0, new_x="END", new_y="TOP")
    pdf.set_font(_FONT, "", 8)
    pdf.cell(col, _ROW_H, _clean(v2), border=0, new_x="LMARGIN", new_y="NEXT")


def _text_block_row(pdf, text: str, w: float) -> None:
    pdf.set_font(_FONT, "", 8)
    pdf.multi_cell(w, _ROW_H, _clean(text), border=0, new_x="LMARGIN", new_y="NEXT")


# ---------------------------------------------------------------------------
# Research-mode PDF subclass + helpers
# ---------------------------------------------------------------------------

class _ResearchReportPDF:
    """Mixin-free wrapper: we subclass FPDF at runtime to avoid import at module level."""
    pass


def _make_research_pdf(logo_path: str | None = None):
    """Create an FPDF subclass with branded footer."""
    from fpdf import FPDF

    class ResearchPDF(FPDF):
        _logo_path = logo_path

        def footer(self):
            self.set_y(-14)
            self.set_draw_color(200, 200, 200)
            self.set_line_width(0.3)
            self.line(self.l_margin, self.get_y(), self.w - self.r_margin,
                      self.get_y())
            self.ln(2)
            self.set_font(_R_FONT, "I", 6.5)
            self.set_text_color(130, 130, 130)
            self.cell(0, 4,
                      f"Logikality Title Intelligence Platform  |  Page {self.page_no()}",
                      align="C")

    return ResearchPDF()


def _r_section_header(pdf, num: int, title: str, w: float,
                      color: tuple = _R_BRAND) -> None:
    """Logikality-branded section header bar."""
    _ensure_space(pdf, _R_ROW_H + 14)
    pdf.ln(5)
    pdf.set_fill_color(*color)
    pdf.set_text_color(*_R_WHITE)
    pdf.set_font(_R_FONT, "B", 9.5)
    label = f"   SECTION {num}  --  {title}"
    pdf.cell(w, 9, _clean(label), border=0, align="L",
             new_x="LMARGIN", new_y="NEXT", fill=True)
    pdf.set_text_color(*_R_BODY)
    pdf.set_font(_R_FONT, "", 8)
    pdf.ln(3)


def _r_kv_row(pdf, label: str, value: str, w: float,
              row_idx: int = 0) -> None:
    """Bold label (30%) + value (70%) in a bordered row with proper alignment."""
    lw = w * 0.30
    vw = w * 0.70
    val_clean = _clean(value)
    label_clean = _clean(label)

    # Measure value height
    pdf.set_font(_R_FONT, "", 8)
    val_lines = pdf.multi_cell(vw - 2, _R_ROW_H, val_clean,
                               dry_run=True, output="LINES")
    num_lines = max(len(val_lines) if val_lines else 1, 1)
    row_h = max(_R_ROW_H * num_lines, _R_ROW_H)

    _ensure_space(pdf, row_h + 1)

    x, y = pdf.get_x(), pdf.get_y()

    # Alternating background
    if row_idx % 2 == 1:
        pdf.set_fill_color(*_R_TABLE_ALT)
        pdf.rect(x, y, w, row_h, style="F")

    # Draw cell borders
    pdf.set_draw_color(200, 200, 200)
    pdf.rect(x, y, lw, row_h)
    pdf.rect(x + lw, y, vw, row_h)

    # Label (bold, vertically centred)
    pdf.set_xy(x + 2, y + (row_h - _R_ROW_H) / 2)
    pdf.set_font(_R_FONT, "B", 7.5)
    pdf.set_text_color(*_R_BODY)
    pdf.cell(lw - 4, _R_ROW_H, label_clean, new_x="END", new_y="TOP")

    # Value (multi-line, padded)
    pdf.set_font(_R_FONT, "", 7.5)
    pdf.set_xy(x + lw + 2, y + 1)
    pdf.multi_cell(vw - 4, _R_ROW_H, val_clean,
                   new_x="LMARGIN", new_y="NEXT")

    # Advance to bottom of row
    pdf.set_y(y + row_h)


def _r_narrative(pdf, text: str, w: float) -> None:
    """Italic footnote / narrative paragraph in muted color."""
    pdf.set_font(_R_FONT, "I", 7)
    pdf.set_text_color(*_R_MUTED)
    pdf.multi_cell(w, 5.5, _clean(text),
                   new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*_R_BODY)
    pdf.set_font(_R_FONT, "", 8)
    pdf.ln(2)


def _r_table_header(pdf, columns: list[tuple[str, float]], w: float) -> None:
    """Gray-background column header row with rect-based rendering."""
    hdr_h = 8
    _ensure_space(pdf, hdr_h + 4)
    pdf.set_fill_color(*_R_TABLE_HDR)
    pdf.set_draw_color(180, 180, 180)
    pdf.set_font(_R_FONT, "B", 7)
    pdf.set_text_color(50, 50, 50)

    x0 = pdf.get_x()
    y0 = pdf.get_y()
    for i, (label, pct) in enumerate(columns):
        col_w = w * pct
        cx = x0 + sum(w * c[1] for c in columns[:i])
        pdf.rect(cx, y0, col_w, hdr_h, style="FD")
        pdf.set_xy(cx + 2, y0 + 1)
        pdf.cell(col_w - 4, hdr_h - 2, _clean(label), new_x="END", new_y="TOP")
    pdf.set_xy(x0, y0 + hdr_h)


def _r_table_row(pdf, cells: list[str], col_pcts: list[float],
                 w: float, row_idx: int = 0) -> None:
    """Table data row with proper multi-line cell height alignment."""
    fill = row_idx % 2 == 1
    if fill:
        pdf.set_fill_color(*_R_TABLE_ALT)

    pdf.set_font(_R_FONT, "", 6.5)
    pdf.set_draw_color(200, 200, 200)

    lh = 5.5  # tighter line height for table cells

    # Compute row height from tallest cell
    max_lines = 1
    for i, cell_text in enumerate(cells):
        col_w = w * col_pcts[i]
        lines = pdf.multi_cell(col_w - 2, lh, _clean(cell_text),
                               dry_run=True, output="LINES")
        max_lines = max(max_lines, len(lines) if lines else 1)
    row_h = max(lh * max_lines + 2, _R_ROW_H)  # +2 padding

    _ensure_space(pdf, row_h + 2)

    x0 = pdf.get_x()
    y0 = pdf.get_y()

    # Draw background + borders for each cell, then render text
    for i, cell_text in enumerate(cells):
        col_w = w * col_pcts[i]
        cx = x0 + sum(w * p for p in col_pcts[:i])
        # Background
        if fill:
            pdf.rect(cx, y0, col_w, row_h, style="F")
        # Border
        pdf.rect(cx, y0, col_w, row_h)
        # Text (vertically padded)
        pdf.set_xy(cx + 1, y0 + 1)
        pdf.multi_cell(col_w - 2, lh, _clean(cell_text),
                       new_x="END", new_y="TOP")

    pdf.set_xy(x0, y0 + row_h)


def _find_logo_path(org_id: uuid.UUID | None = None) -> str | None:
    """Return the filesystem path for the Logikality logo used on all reports."""
    # Always use the same logo as the sidebar footer (Logo_withTagline rendered to PNG)
    candidates = [
        "logikality_with_tagline.png",
        "logikality_logo.png",  # fallback if tagline version hasn't been built yet
    ]
    public_dirs = [
        Path(__file__).resolve().parents[5] / "frontend" / "public",
        Path(__file__).resolve().parents[4] / "frontend" / "public",
    ]
    for filename in candidates:
        for pub in public_dirs:
            p = pub / filename
            if p.is_file():
                return str(p)
    return None


def _doc_meta(doc, key: str, default: str = "N/A") -> str:
    if doc and doc.doc_metadata and isinstance(doc.doc_metadata, dict):
        val = doc.doc_metadata.get(key)
        if val:
            return str(val)
    return default


def _get_tax_info(documents: list) -> dict | None:
    """Find tax_info from documents metadata."""
    for d in documents:
        if d.doc_metadata and isinstance(d.doc_metadata, dict):
            ti = d.doc_metadata.get("tax_info")
            if ti:
                return ti
    return None


# ---------------------------------------------------------------------------
# Tax installment table (matches sample format)
# ---------------------------------------------------------------------------

def _render_tax_table(pdf, ti: dict, w: float) -> None:
    """Render the tax installment table from the sample PDF."""
    headers = ["Installments:", "Tax Amount:", "Status:", "Due/Paid Date:",
               "Total Amount (P&I):", "Good through Date:"]
    col_w = w / len(headers)

    # Header row — horizontal borders only (top+bottom), no vertical
    pdf.set_font(_FONT, "B", 7)
    for h in headers:
        pdf.cell(col_w, _ROW_H, _clean(h), border="TB", new_x="END", new_y="TOP")
    pdf.ln(_ROW_H)

    # Data row
    pdf.set_font(_FONT, "", 7)
    tax_amt = _fmt_money(ti.get("tax_amount"))
    status = str(ti.get("tax_status", "N/A") or "N/A")
    # Try to get paid date from payment history
    paid_date = ""
    history = ti.get("payment_history", [])
    if history and isinstance(history, list) and len(history) > 0:
        first = history[0]
        if isinstance(first, dict):
            paid_date = first.get("payment_date", "")

    values = ["Annual", tax_amt, status, paid_date, "", ""]
    for v in values:
        pdf.cell(col_w, _ROW_H, _clean(v), border="B", new_x="END", new_y="TOP")
    pdf.ln(_ROW_H)


def _render_kv_list(pdf, items: list[tuple[str, str]], w: float) -> None:
    """Render a list of key-value pairs with warm alternating rows."""
    for i, (label, value) in enumerate(items):
        if i % 2 == 1:
            pdf.set_fill_color(*_ALT_ROW)
            fill = True
        else:
            fill = False
        _ensure_space(pdf, _ROW_H + 2)
        lw = w * 0.35
        vw = w * 0.65
        x, y = pdf.get_x(), pdf.get_y()
        pdf.set_font(_FONT, "B", 8)
        if fill:
            pdf.cell(lw, _ROW_H, _clean(label), border=0, new_x="END", new_y="TOP", fill=True)
        else:
            pdf.cell(lw, _ROW_H, _clean(label), border=0, new_x="END", new_y="TOP")
        pdf.set_font(_FONT, "", 8)
        pdf.set_xy(x + lw, y)
        if fill:
            pdf.cell(vw, _ROW_H, _clean(value), border=0, new_x="LMARGIN", new_y="NEXT", fill=True)
        else:
            pdf.cell(vw, _ROW_H, _clean(value), border=0, new_x="LMARGIN", new_y="NEXT")


def _render_items_list(pdf, items: list[str], w: float) -> None:
    """Render a bulleted list of strings."""
    for item in items:
        _ensure_space(pdf, _ROW_H + 2)
        pdf.set_font(_FONT, "", 8)
        pdf.cell(5, _ROW_H, _clean("\u2022"), border=0, new_x="END", new_y="TOP")
        pdf.multi_cell(w - 5, _ROW_H, _clean(item), border=0, new_x="LMARGIN", new_y="NEXT")


def _render_severity_badge(pdf, severity: str, x: float, y: float) -> None:
    """Render a colored severity indicator dot."""
    color = _SEV_COLORS.get(severity, (128, 128, 128))
    pdf.set_fill_color(*color)
    pdf.ellipse(x, y + 2, 3, 3, style="F")
    pdf.set_fill_color(255, 255, 255)


def _ps(summary: dict | None, key: str, default=None):
    """Safely get a value from property_summary."""
    if not summary or not isinstance(summary, dict):
        return default
    return summary.get(key, default)


def _render_cover_page(pdf, order, pkg, logo_path: str | None, w: float) -> None:
    """Render a professional cover page."""
    # Background gradient effect (amber bar at top)
    pdf.set_fill_color(*_HEADER_BG)
    pdf.rect(0, 0, pdf.w, 45, style="F")

    # Logo centered on amber bar
    if logo_path:
        pdf.image(logo_path, x=(pdf.w - 50) / 2, y=8, h=18)

    # Title below amber bar
    pdf.set_y(55)
    pdf.set_text_color(*_SUBHEADER_BG)
    pdf.set_font(_FONT, "B", 22)
    pdf.cell(w, 12, "Title Search Report", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font(_FONT, "", 12)
    pdf.set_text_color(100, 100, 100)
    pdf.ln(5)
    pdf.cell(w, 8, _clean(order.property_address or ""), align="C", new_x="LMARGIN", new_y="NEXT")
    city_state = f"{order.city or ''}, {order.state_code or ''} {order.zip_code or ''}".strip(", ")
    pdf.cell(w, 8, _clean(city_state), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(5)
    pdf.cell(w, 8, _clean(f"{order.county or ''} County"), align="C", new_x="LMARGIN", new_y="NEXT")

    # Divider line
    pdf.ln(10)
    pdf.set_draw_color(*_ACCENT)
    pdf.set_line_width(0.8)
    center_x = pdf.w / 2
    pdf.line(center_x - 30, pdf.get_y(), center_x + 30, pdf.get_y())
    pdf.ln(10)

    # Package details
    pdf.set_text_color(0, 0, 0)
    pdf.set_font(_FONT, "", 10)
    now = datetime.now(timezone.utc)
    details = [
        ("Package Number:", pkg.package_number),
        ("Order Reference:", order.order_reference or "N/A"),
        ("Product Type:", "Full Search" if (order.search_scope or "full") == "full" else "Current Owner Search"),
        ("Report Date:", now.strftime("%B %d, %Y")),
    ]
    for label, value in details:
        pdf.set_font(_FONT, "B", 10)
        pdf.cell(w / 2, 8, _clean(label), align="R", new_x="END", new_y="TOP")
        pdf.set_font(_FONT, "", 10)
        pdf.cell(w / 2, 8, _clean(f"  {value}"), align="L", new_x="LMARGIN", new_y="NEXT")

    # Footer text
    pdf.set_y(pdf.h - 30)
    pdf.set_font(_FONT, "I", 8)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(w, 6, "Generated by Logikality Title Intelligence Platform", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)


def _add_footer(pdf) -> None:
    """Add page number footer to current page."""
    pdf.set_y(pdf.h - 10)
    pdf.set_font(_FONT, "I", 7)
    pdf.set_text_color(150, 150, 150)
    pdf.cell(0, 5, f"Page {pdf.page_no()}", align="L", new_x="END", new_y="TOP")
    now_str = datetime.now(timezone.utc).strftime("%m/%d/%Y %H:%M UTC")
    pdf.cell(0, 5, f"Generated by Logikality  |  {now_str}", align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)


# ---------------------------------------------------------------------------
# Research-mode section renderers
# ---------------------------------------------------------------------------


def _render_research_header(pdf, order, pkg, w: float,
                            logo_path: str | None = None) -> None:
    """Render branded header with logo, title, and metadata grid."""
    now = datetime.now(timezone.utc)
    county = order.county or "Unknown"
    state = order.state_code or "FL"
    address = order.property_address or "N/A"
    city = order.city or ""
    zip_code = order.zip_code or ""
    state_full = _state_full_name(state)

    # Brand amber accent bar across top
    pdf.set_fill_color(*_R_BRAND)
    pdf.rect(0, 0, pdf.w, 4, style="F")

    # Logo (right-aligned) + Title (left-aligned)
    y_title = 8
    if logo_path:
        try:
            pdf.image(logo_path, x=pdf.w - 55, y=y_title, h=12)
        except Exception:
            pass

    pdf.set_xy(pdf.l_margin, y_title)
    pdf.set_font(_R_FONT, "B", 17)
    pdf.set_text_color(*_R_NAVY)  # charcoal for title
    pdf.cell(w * 0.65, 12, "TITLE SEARCH REPORT", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font(_R_FONT, "", 9)
    pdf.set_text_color(*_R_MUTED)
    pdf.cell(w * 0.65, 5,
             _clean(f"{county} County, {state_full} -- Public Record Research"),
             new_x="LMARGIN", new_y="NEXT")

    # Brand accent rule
    pdf.ln(3)
    pdf.set_draw_color(*_R_BRAND)
    pdf.set_line_width(0.5)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.l_margin + w, pdf.get_y())
    pdf.ln(4)

    # Metadata grid (2x3) — draw rect + text manually for clean borders
    pdf.set_draw_color(190, 190, 190)
    pdf.set_text_color(*_R_BODY)

    meta_rows = [
        ("Report Date:", now.strftime("%B %d, %Y"),
         "Prepared By:", "Logikality Title Research"),
        ("Subject Property:", f"{address}, {city}, {state} {zip_code}",
         "County:", f"{county} County, {state}"),
        ("Report Type:", "Preliminary Title Search /\nChain-of-Title Analysis",
         "Search Period:", f"Through {now.strftime('%B %d, %Y')}"),
    ]

    cw = [w * 0.16, w * 0.34, w * 0.14, w * 0.36]
    lh = 5  # line height inside grid

    for l1, v1, l2, v2 in meta_rows:
        x0, y0 = pdf.get_x(), pdf.get_y()

        # Measure tallest value cell to compute row height
        pdf.set_font(_R_FONT, "", 7.5)
        h1 = len(pdf.multi_cell(cw[1] - 4, lh, _clean(v1), dry_run=True, output="LINES") or [""])
        h2 = len(pdf.multi_cell(cw[3] - 4, lh, _clean(v2), dry_run=True, output="LINES") or [""])
        rh = max(h1, h2, 1) * lh + 3  # +3 for padding

        # Draw 4 bordered cells
        for ci, cwidth in enumerate(cw):
            cx = x0 + sum(cw[:ci])
            if ci % 2 == 0:  # label cell — light gray bg
                pdf.set_fill_color(240, 242, 245)
                pdf.rect(cx, y0, cwidth, rh, style="FD")
            else:
                pdf.rect(cx, y0, cwidth, rh)

        # Text for each cell
        pad_y = y0 + 1.5

        pdf.set_font(_R_FONT, "B", 7.5)
        pdf.set_xy(x0 + 2, pad_y)
        pdf.cell(cw[0] - 4, lh, _clean(l1))

        pdf.set_font(_R_FONT, "", 7.5)
        pdf.set_xy(x0 + cw[0] + 2, pad_y)
        pdf.multi_cell(cw[1] - 4, lh, _clean(v1), new_x="END", new_y="TOP")

        pdf.set_font(_R_FONT, "B", 7.5)
        pdf.set_xy(x0 + cw[0] + cw[1] + 2, pad_y)
        pdf.cell(cw[2] - 4, lh, _clean(l2))

        pdf.set_font(_R_FONT, "", 7.5)
        pdf.set_xy(x0 + cw[0] + cw[1] + cw[2] + 2, pad_y)
        pdf.multi_cell(cw[3] - 4, lh, _clean(v2), new_x="END", new_y="TOP")

        pdf.set_y(y0 + rh)

    pdf.ln(4)


def _render_sec1_property_id(pdf, ps: dict, order, w: float) -> None:
    """SECTION 1 -- PROPERTY IDENTIFICATION."""
    _r_section_header(pdf, 1, "PROPERTY IDENTIFICATION", w)

    prop_id = ps.get("property_identification", {})
    if not isinstance(prop_id, dict):
        prop_id = {}
    phys = ps.get("physical_attributes", {})
    if not isinstance(phys, dict):
        phys = {}
    lot = ps.get("lot_and_land", {})
    if not isinstance(lot, dict):
        lot = {}

    county = order.county or "N/A"
    state = order.state_code or "N/A"
    _v = "To be confirmed via county property appraiser"

    # Build bed/bath string
    bed_bath_parts = []
    if phys.get("bedrooms"):
        bed_bath_parts.append(f"{phys['bedrooms']} Bedrooms")
    if phys.get("bathrooms"):
        bed_bath_parts.append(f"{phys['bathrooms']} Bathrooms")
    bed_bath = " / ".join(bed_bath_parts) if bed_bath_parts else _v

    # Living area
    if phys.get("living_area_sqft"):
        living_area = f"{phys['living_area_sqft']:,.0f} sq. ft. (per public records)"
    else:
        living_area = _v

    # Zoning
    if lot.get("zoning"):
        zd = lot.get("zoning_description", "")
        zoning = f"{lot['zoning']} -- {zd}".strip(" -") if zd else lot["zoning"]
    else:
        zoning = f"Verify via {county} County zoning department"

    # Flood zone
    if lot.get("flood_zone"):
        fzd = lot.get("flood_zone_description", "")
        flood = f"{lot['flood_zone']} -- {fzd}".strip(" -") if fzd else lot["flood_zone"]
    else:
        flood = "Recommend FEMA FIRM map verification -- Zone TBD"

    rows = [
        ("Property Address:", prop_id.get("address") or prop_id.get("property_address") or order.property_address or "N/A"),
        ("County / State:", f"{county} County, {state}"),
        ("Subdivision / Community:", prop_id.get("subdivision") or _v),
        ("Property Type:", phys.get("property_type") or _v),
        ("Year Built:", str(phys["year_built"]) if phys.get("year_built") else _v),
        ("Bedrooms / Bathrooms:", bed_bath),
        ("Living Area (approx.):", living_area),
        ("Lot Configuration:", lot.get("lot_configuration") or "Single-family residential lot"),
        ("Zoning District:", zoning),
        ("Parcel ID (RE#):", prop_id.get("parcel_id") or prop_id.get("parcel_number") or order.parcel_number or _v),
        ("Tax District:", ps.get("tax_status", {}).get("tax_district") or f"Verify via {county} County Tax Collector"),
        ("Flood Zone:", flood),
    ]

    for i, (label, value) in enumerate(rows):
        _r_kv_row(pdf, label, value, w, i)

    # Note about parcel RE
    pdf.ln(1)
    _r_narrative(
        pdf,
        f"NOTE: Parcel RE number and legal description require direct confirmation "
        f"from the {order.county or ''} County Property Appraiser or Clerk's "
        f"Official Records portal.",
        w,
    )


def _render_sec2_ownership(pdf, ps: dict, order, w: float) -> None:
    """SECTION 2 -- CURRENT OWNERSHIP & VESTING."""
    _r_section_header(pdf, 2, "CURRENT OWNERSHIP & VESTING", w)

    co = ps.get("current_ownership", {})
    rows = []
    owner_names = co.get("owner_names", [])
    rows.append(("Current Owner(s):",
                 ", ".join(owner_names) if owner_names else
                 "To be confirmed -- search property appraiser by address"))
    rows.append(("Vesting Type:",
                 co.get("ownership_type") or
                 "Fee Simple (presumed -- standard for residential SFR)"))
    he = co.get("homestead_exemption")
    if isinstance(he, str) and he:
        rows.append(("Homestead Exemption:", he))
    elif isinstance(he, bool):
        rows.append(("Homestead Exemption:",
                     "Yes" if he else
                     f"Status unknown -- verify via {order.county or ''} County PAO exemptions search"))
    else:
        rows.append(("Homestead Exemption:",
                     f"Status unknown -- verify via {order.county or ''} County PAO exemptions search"))
    rows.append(("Owner Mailing Address:",
                 co.get("mailing_address") or
                 f"As recorded with {order.county or ''} County Property Appraiser"))
    rows.append(("Occupancy Status:",
                 co.get("occupancy_status") or
                 "Verify via public directory data"))

    for i, (label, value) in enumerate(rows):
        _r_kv_row(pdf, label, value, w, i)

    # Narrative
    county = order.county or "Unknown"
    state = order.state_code or "FL"
    state_full = _state_full_name(state)
    pdf.ln(1)
    _r_narrative(
        pdf,
        _NOTE_SEC2_OWNERSHIP.format(county=county, state=state_full),
        w,
    )


def _render_sec3_chain(pdf, ps: dict, order, w: float) -> None:
    """SECTION 3 -- CHAIN OF TITLE SUMMARY."""
    _r_section_header(pdf, 3, "CHAIN OF TITLE SUMMARY", w)

    chain = ps.get("chain_of_title", [])

    # Intro narrative
    county = order.county or "Unknown"
    pdf.set_font(_R_FONT, "", 8)
    pdf.set_text_color(*_R_BODY)
    intro = ps.get("chain_narrative", "")
    if intro:
        pdf.multi_cell(w, _R_ROW_H, _clean(intro),
                       new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    if chain:
        # Multi-column table — handle both agent schema and manual format
        col_pcts = [0.04, 0.22, 0.10, 0.24, 0.12, 0.28]
        _r_table_header(pdf, [
            ("#", 0.04), ("Event / Instrument", 0.22),
            ("Est. Date", 0.10), ("Parties", 0.24),
            ("Book/Page", 0.12), ("Notes", 0.28),
        ], w)
        for i, link in enumerate(chain):
            if isinstance(link, dict):
                # Agent schema: {deed_type, grantor, grantee, recording_date, recording_ref, ...}
                event = (link.get("event")
                         or link.get("deed_type")
                         or link.get("description")
                         or "N/A")
                date = (link.get("date")
                        or link.get("recording_date")
                        or link.get("est_date")
                        or "N/A")
                # Build parties from grantor/grantee if no explicit parties field
                parties = link.get("parties", "")
                if not parties:
                    grantor = link.get("grantor", "")
                    grantee = link.get("grantee", "")
                    if grantor and grantee:
                        parties = f"{grantor} to {grantee}"
                    elif grantor or grantee:
                        parties = grantor or grantee
                    else:
                        parties = "N/A"
                book_page = (link.get("book_page")
                             or link.get("recording_ref")
                             or "N/A")
                cells = [
                    str(link.get("link_number", i + 1)),
                    event,
                    date,
                    parties,
                    book_page,
                    link.get("notes", ""),
                ]
            else:
                cells = [str(i + 1), str(link), "", "", "", ""]
            _r_table_row(pdf, cells, col_pcts, w, i)
    else:
        pdf.multi_cell(w, _R_ROW_H,
                       _clean("No chain of title data available."),
                       new_x="LMARGIN", new_y="NEXT")

    # Footnote
    clerk_url = ps.get("clerk_url", "oncore.duvalclerk.com")
    pdf.ln(1)
    _r_narrative(
        pdf,
        _NOTE_SEC3_CHAIN.format(county=county, clerk_url=clerk_url),
        w,
    )


def _render_sec4_liens(pdf, ps: dict, w: float) -> None:
    """SECTION 4 -- MORTGAGES, ENCUMBRANCES & LIEN STATUS."""
    _r_section_header(pdf, 4, "MORTGAGES, ENCUMBRANCES & LIEN STATUS", w)

    county = ps.get("_county", "")
    _r_narrative(pdf, _NOTE_SEC4_LIENS.format(county=county), w)
    pdf.ln(1)

    mortgages = ps.get("mortgages", [])
    liens = ps.get("liens", [])

    # Build a category map from whatever shape the data arrives in.
    # Agent schema: mortgages=[{lender, amount, status,...}], liens=[{lien_type,...}]
    # Manual/override: dict keyed by category name -> description string
    cat_map: dict[str, str] = {}

    if isinstance(mortgages, list):
        for m in mortgages:
            if not isinstance(m, dict):
                continue
            lender = m.get("lender", "Unknown lender")
            amount = m.get("amount", "TBD")
            status = m.get("status", "")
            ref = m.get("recording_ref", "")
            desc = f"{lender} -- {amount}"
            if status:
                desc += f" ({status})"
            if ref:
                desc += f" Ref: {ref}"
            if m.get("notes"):
                desc += f". {m['notes']}"
            # Classify: first mortgage vs second/HELOC
            if not cat_map.get("Purchase Money Mortgage / First Lien"):
                cat_map["Purchase Money Mortgage / First Lien"] = desc
            else:
                cat_map.setdefault("Second Mortgage / HELOC", desc)
    elif isinstance(mortgages, dict):
        for key, val in mortgages.items():
            cat_map[key] = val if isinstance(val, str) else str(val)

    if isinstance(liens, list):
        for li in liens:
            if not isinstance(li, dict):
                continue
            lien_type = (li.get("lien_type") or "other").lower()
            desc_parts = []
            if li.get("creditor"):
                desc_parts.append(f"Creditor: {li['creditor']}")
            if li.get("amount"):
                desc_parts.append(f"Amount: {li['amount']}")
            if li.get("status"):
                desc_parts.append(f"Status: {li['status']}")
            if li.get("recording_ref"):
                desc_parts.append(f"Ref: {li['recording_ref']}")
            if li.get("notes"):
                desc_parts.append(li["notes"])
            desc = ". ".join(desc_parts) if desc_parts else "See records."
            # Map lien_type to closest category
            if "tax" in lien_type and "federal" in lien_type:
                cat_map.setdefault("Federal Tax Liens (IRS)", desc)
            elif "tax" in lien_type:
                cat_map.setdefault("State Tax Liens", desc)
            elif "judgment" in lien_type:
                cat_map.setdefault("Judgment Liens", desc)
            elif "hoa" in lien_type or "coa" in lien_type:
                cat_map.setdefault("HOA/COA Liens", desc)
            elif "mechanic" in lien_type:
                cat_map.setdefault("Mechanic's Liens", desc)
            elif "utility" in lien_type or "assessment" in lien_type:
                cat_map.setdefault("Utility Liens / Special Assessments", desc)
            elif "code" in lien_type or "enforcement" in lien_type:
                cat_map.setdefault("Code Enforcement Liens", desc)
            elif "child" in lien_type or "support" in lien_type:
                cat_map.setdefault("Child Support Liens", desc)
            else:
                cat_map.setdefault("Judgment Liens", desc)
    elif isinstance(liens, dict):
        for key, val in liens.items():
            cat_map[key] = val if isinstance(val, str) else str(val)

    for i, category in enumerate(_LIEN_CATEGORIES):
        # Try exact key match, then normalized key
        norm_key = category.lower().replace("/", "_").replace(" ", "_")
        value = cat_map.get(category, "")
        if not value:
            for k, v in cat_map.items():
                if norm_key[:15] in k.lower().replace(" ", "_"):
                    value = v
                    break
        if not value:
            value = "Not identified in available data."
        _r_kv_row(pdf, f"{category}:", value, w, i)


def _render_sec5_tax(pdf, ps: dict, w: float) -> None:
    """SECTION 5 -- PROPERTY TAX STATUS."""
    _r_section_header(pdf, 5, "PROPERTY TAX STATUS", w)

    tax = ps.get("tax_status", {})
    if not isinstance(tax, dict):
        tax = {}
    comps = ps.get("comparable_sales", [])

    county = ps.get("_county", "Unknown")
    tc_url = tax.get("tax_collector_url", "")
    _tv = f"Searchable via {county} County Tax Collector" + (f": {tc_url}" if tc_url else "")

    def _fmt_val(val):
        """Format a value that may be numeric, string, or None."""
        if val is None:
            return _tv
        if isinstance(val, (int, float)):
            return f"${val:,.0f}"
        return str(val) if val else _tv

    # Assessed value
    av = _fmt_val(tax.get("assessed_value"))
    # Market value — include comps if available
    mv = tax.get("market_value")
    if mv:
        market_val = str(mv)
    elif comps:
        comp_note = "; ".join(
            f"{c.get('address', 'N/A')} sold {c.get('sale_price', 'N/A')} {c.get('sale_date', '')}"
            for c in comps[:3]
        )
        market_val = f"Comparable sales: {comp_note}"
    else:
        market_val = f"Verify current assessed value at {county} County property appraiser"
    # Annual tax
    ta = tax.get("total_tax_amount")
    annual = _fmt_val(ta)
    if annual == _tv and tax.get("annual_tax_estimate"):
        annual = str(tax["annual_tax_estimate"])
    # Exemptions
    exemptions = tax.get("exemptions", [])
    if exemptions and isinstance(exemptions, list):
        exempt_str = ", ".join(exemptions)
    elif tax.get("homestead_exemption_note"):
        exempt_str = tax["homestead_exemption_note"]
    elif tax.get("homestead_exemption") is not None:
        exempt_str = "Yes" if tax["homestead_exemption"] else "N/A"
    else:
        exempt_str = f"If applicable: reduces taxable value (verify via {county} County PAO)"

    rows = [
        ("Tax Account:", str(tax.get("tax_account") or _tv)),
        ("Tax Year (Current):", str(tax.get("tax_year") or "Current tax year")),
        ("Assessed Value (est.):", av),
        ("Market Value (est.):", market_val),
        ("Annual Tax Estimate:", annual),
        ("Tax Payment Status:", str(tax.get("tax_status") or f"VERIFY -- confirm no delinquent taxes via {county} County Tax Collector")),
        ("Homestead Exemption:", exempt_str),
        ("Tax Certificate / Tax Deed:", str(tax.get("tax_certificate") or f"Verify no outstanding tax certificates via {county} County Tax Collector")),
        ("Millage Rate:", str(tax.get("millage_rate") or f"Verify exact rate per {county} County Tax Collector")),
    ]

    for i, (label, value) in enumerate(rows):
        _r_kv_row(pdf, label, str(value), w, i)

    state = ps.get("_state_full", "Florida")
    pdf.ln(1)
    _r_narrative(pdf, _NOTE_SEC5_TAX.format(state=state), w)


def _render_sec6_easements(pdf, ps: dict, w: float) -> None:
    """SECTION 6 -- EASEMENTS, RESTRICTIONS & PLAT MATTERS."""
    _r_section_header(pdf, 6, "EASEMENTS, RESTRICTIONS & PLAT MATTERS", w)

    easements = ps.get("easements", [])
    ccrs = ps.get("ccrs_restrictions", {})
    if not isinstance(ccrs, dict):
        ccrs = {}
    survey = ps.get("survey_plat", {})
    if not isinstance(survey, dict):
        survey = {}
    county = ps.get("_county", "Unknown")

    rows = []

    # Easement rows from data (dict or list)
    if isinstance(easements, dict) and easements:
        for key, val in easements.items():
            label = key.replace("_", " ").title()
            rows.append((f"{label}:", val if isinstance(val, str) else str(val)))
    elif isinstance(easements, list) and easements:
        for e in easements:
            if isinstance(e, dict):
                etype = (e.get("easement_type") or e.get("type") or "Easement")
                desc = e.get("description", "N/A")
                if e.get("recording_ref"):
                    desc += f" (Ref: {e['recording_ref']})"
                rows.append((f"{etype}:", desc))
            else:
                rows.append(("Easement:", str(e)))

    # Always show these standard categories with fallback text
    _has = lambda label: any(label.lower() in r[0].lower() for r in rows)
    if not _has("subdivision") and not _has("plat"):
        rows.insert(0, ("Subdivision Plat:",
                         f"Obtain certified plat copy from {county} County Clerk (plat book and page TBD)."))
    if not _has("utility"):
        rows.append(("Utility Easements:",
                      "Standard utility easements typically run along rear and side lot lines -- verify exact dimensions on recorded plat."))
    if not _has("drainage"):
        rows.append(("Drainage Easements:",
                      "Verify on plat and survey."))

    # HOA / CC&Rs
    rows.append(("HOA / CC&Rs:",
                  ccrs.get("description") or ccrs.get("notes") or
                  f"Verify whether property is subject to HOA/CC&Rs. Obtain from {county} County Clerk or HOA directly."))

    # Access
    if ccrs.get("access_ingress_egress"):
        rows.append(("Access / Ingress-Egress:", ccrs["access_ingress_egress"]))
    # Private restrictions
    rows.append(("Private Restrictions:",
                  ccrs.get("private_restrictions") or
                  "Review original deed and CC&Rs for any deed restrictions on use, structures, or transfers."))
    # Survey
    rows.append(("Survey Recommendation:",
                  survey.get("recommendation") or survey.get("notes") or
                  "A current boundary survey (ALTA/NSPS) is strongly recommended prior to any purchase or financing transaction."))

    for i, (label, value) in enumerate(rows):
        _r_kv_row(pdf, label, value, w, i)


def _render_sec7_court(pdf, ps: dict, w: float) -> None:
    """SECTION 7 -- FORECLOSURE & COURT PROCEEDING SEARCH."""
    _r_section_header(pdf, 7, "FORECLOSURE & COURT PROCEEDING SEARCH", w)

    court = ps.get("court_proceedings", [])
    # court may be list of cases (agent schema) or dict keyed by category (manual)
    cat_map: dict[str, str] = {}
    if isinstance(court, dict):
        cat_map = {k: v if isinstance(v, str) else str(v) for k, v in court.items()}
    elif isinstance(court, list):
        # Agent schema: [{case_type, case_number, parties, filing_date, status, notes}]
        # Map case_type to our category names
        _CASE_TYPE_MAP = {
            "foreclosure": "Active Foreclosure",
            "foreclosure_sale": "Pending Foreclosure Sale",
            "lis_pendens": "Lis Pendens",
            "bankruptcy": "Bankruptcy",
            "probate": "Probate / Estate",
            "estate": "Probate / Estate",
            "divorce": "Divorce Proceedings",
        }
        for case in court:
            if not isinstance(case, dict):
                continue
            ct = (case.get("case_type") or "unknown").lower().replace(" ", "_")
            category_name = _CASE_TYPE_MAP.get(ct, "")
            if not category_name:
                # Fuzzy match
                for key, cat_name in _CASE_TYPE_MAP.items():
                    if key in ct:
                        category_name = cat_name
                        break
            desc_parts = []
            if case.get("case_number"):
                desc_parts.append(f"Case #{case['case_number']}")
            if case.get("parties"):
                desc_parts.append(case["parties"])
            if case.get("status"):
                desc_parts.append(f"Status: {case['status']}")
            if case.get("filing_date"):
                desc_parts.append(f"Filed: {case['filing_date']}")
            if case.get("notes"):
                desc_parts.append(case["notes"])
            desc = ". ".join(desc_parts) if desc_parts else "See records."
            if category_name:
                cat_map.setdefault(category_name, desc)

    for i, category in enumerate(_COURT_CATEGORIES):
        value = cat_map.get(category, "")
        if not value:
            norm = category.lower().replace("/", "_").replace(" ", "_")
            for k, v in cat_map.items():
                if norm[:12] in k.lower().replace(" ", "_"):
                    value = v
                    break
        if not value:
            value = "Not identified in publicly available data."
        _r_kv_row(pdf, f"{category}:", value, w, i)


def _render_sec8_opinion(pdf, ps: dict, w: float) -> None:
    """SECTION 8 -- PRELIMINARY TITLE OPINION & EXCEPTIONS."""
    _r_section_header(pdf, 8, "PRELIMINARY TITLE OPINION & EXCEPTIONS", w,
                      color=_R_BRAND_DARK)

    # Intro disclaimer
    _r_narrative(pdf, _NOTE_SEC8_DISCLAIMER, w)
    pdf.ln(1)

    items = ps.get("title_opinion_items", [])
    if not items:
        pdf.set_font(_R_FONT, "", 8)
        pdf.multi_cell(w, _R_ROW_H,
                       _clean("No title opinion items available."),
                       new_x="LMARGIN", new_y="NEXT")
        return

    # Three-column table: colored-status dot | Item name | Recommendation
    c1p, c2p, c3p = 0.05, 0.20, 0.75  # percentages
    lh = 5

    # Table header
    _r_table_header(pdf, [("", c1p), ("Item", c2p),
                          ("Finding / Recommendation", c3p)], w)

    for i, item in enumerate(items):
        status = (item.get("status") or "open").lower()
        is_clear = status in ("clear", "resolved", "confirmed", "ok")
        title_text = _clean(item.get("item", item.get("title", "N/A")))
        desc = _clean(item.get("recommendation", item.get("description", "")))

        dot_color = _R_GREEN if is_clear else _R_WARN
        fill = i % 2 == 1

        c1w = w * c1p
        c2w = w * c2p
        c3w = w * c3p

        # Measure row height from longest column
        pdf.set_font(_R_FONT, "", 7)
        desc_lines = pdf.multi_cell(c3w - 4, lh, desc,
                                    dry_run=True, output="LINES")
        pdf.set_font(_R_FONT, "B", 7)
        title_lines = pdf.multi_cell(c2w - 4, lh, title_text,
                                     dry_run=True, output="LINES")
        n_lines = max(len(desc_lines) if desc_lines else 1,
                      len(title_lines) if title_lines else 1, 1)
        row_h = max(n_lines * lh + 2, 8)

        _ensure_space(pdf, row_h + 2)
        x0 = pdf.get_x()
        y0 = pdf.get_y()

        # Backgrounds + borders
        pdf.set_draw_color(200, 200, 200)
        if fill:
            pdf.set_fill_color(*_R_TABLE_ALT)
            pdf.rect(x0, y0, w, row_h, style="F")
        pdf.rect(x0, y0, c1w, row_h)
        pdf.rect(x0 + c1w, y0, c2w, row_h)
        pdf.rect(x0 + c1w + c2w, y0, c3w, row_h)

        # Status dot — large enough to see colour clearly
        dot_sz = 3
        pdf.set_fill_color(*dot_color)
        pdf.ellipse(x0 + (c1w - dot_sz) / 2,
                    y0 + (row_h - dot_sz) / 2,
                    dot_sz, dot_sz, style="F")

        # Item name (bold)
        pdf.set_font(_R_FONT, "B", 7)
        pdf.set_text_color(*_R_BODY)
        pdf.set_xy(x0 + c1w + 2, y0 + 1)
        pdf.multi_cell(c2w - 4, lh, title_text,
                       new_x="END", new_y="TOP")

        # Description
        pdf.set_font(_R_FONT, "", 7)
        pdf.set_xy(x0 + c1w + c2w + 2, y0 + 1)
        pdf.multi_cell(c3w - 4, lh, desc,
                       new_x="LMARGIN", new_y="NEXT")

        pdf.set_xy(x0, y0 + row_h)

    # Legend below table
    pdf.ln(2)
    pdf.set_font(_R_FONT, "", 6)
    pdf.set_text_color(*_R_MUTED)
    ly = pdf.get_y()
    pdf.set_fill_color(*_R_GREEN)
    pdf.ellipse(pdf.get_x(), ly + 0.5, 2.5, 2.5, style="F")
    pdf.set_xy(pdf.get_x() + 4, ly)
    pdf.cell(25, 4, "Clear / Confirmed", new_x="END", new_y="TOP")
    pdf.set_fill_color(*_R_WARN)
    pdf.ellipse(pdf.get_x() + 2, ly + 0.5, 2.5, 2.5, style="F")
    pdf.set_xy(pdf.get_x() + 6, ly)
    pdf.cell(30, 4, "Attention Required", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*_R_BODY)


def _render_sec9_next_steps(pdf, ps: dict, w: float) -> None:
    """SECTION 9 -- RECOMMENDED NEXT STEPS."""
    _r_section_header(pdf, 9, "RECOMMENDED NEXT STEPS", w)

    steps = ps.get("next_steps", [])
    if not steps:
        pdf.set_font(_R_FONT, "", 8)
        pdf.multi_cell(w, _R_ROW_H,
                       _clean("No next steps specified."),
                       new_x="LMARGIN", new_y="NEXT")
        return

    num_w = 10
    lh = 5.5
    for i, step in enumerate(steps, 1):
        action = step.get("action", step) if isinstance(step, dict) else str(step)

        # Measure height
        pdf.set_font(_R_FONT, "", 7.5)
        lines = pdf.multi_cell(w - num_w - 1, lh, _clean(action),
                               dry_run=True, output="LINES")
        row_h = max(len(lines) if lines else 1, 1) * lh
        _ensure_space(pdf, row_h + 2)

        x0, y0 = pdf.get_x(), pdf.get_y()

        # Number (bold)
        pdf.set_font(_R_FONT, "B", 8)
        pdf.set_text_color(*_R_NAVY)
        pdf.set_xy(x0, y0)
        pdf.cell(num_w, lh, f"{i}.", align="R", new_x="END", new_y="TOP")

        # Action text
        pdf.set_font(_R_FONT, "", 7.5)
        pdf.set_text_color(*_R_BODY)
        pdf.set_xy(x0 + num_w + 1, y0)
        pdf.multi_cell(w - num_w - 1, lh, _clean(action),
                       new_x="LMARGIN", new_y="NEXT")

        bottom = max(pdf.get_y(), y0 + lh)
        pdf.set_y(bottom + 0.5)


def _render_sec10_contacts(pdf, ps: dict, w: float) -> None:
    """SECTION 10 -- KEY CONTACTS & OFFICIAL RESOURCES."""
    _r_section_header(pdf, 10, "KEY CONTACTS & OFFICIAL RESOURCES", w)

    contacts = ps.get("key_contacts", [])
    if not contacts:
        pdf.set_font(_R_FONT, "", 8)
        pdf.multi_cell(w, _R_ROW_H,
                       _clean("No contact information available."),
                       new_x="LMARGIN", new_y="NEXT")
        return

    # 3-column table
    col_pcts = [0.30, 0.40, 0.30]
    _r_table_header(pdf, [
        ("Office / Entity", 0.30), ("Address", 0.40), ("Contact", 0.30),
    ], w)
    for i, c in enumerate(contacts):
        name = c.get("name", c.get("office", "N/A")) if isinstance(c, dict) else str(c)
        address = c.get("address", "") if isinstance(c, dict) else ""
        contact_info = ""
        if isinstance(c, dict):
            parts = []
            if c.get("phone"):
                parts.append(c["phone"])
            if c.get("website"):
                parts.append(c["website"])
            contact_info = " | ".join(parts)
        _r_table_row(pdf, [name, address, contact_info], col_pcts, w, i)


def _state_full_name(code: str) -> str:
    """Convert 2-letter state code to full name (common states)."""
    names = {
        "FL": "Florida", "CA": "California", "TX": "Texas", "NY": "New York",
        "PA": "Pennsylvania", "OH": "Ohio", "GA": "Georgia", "NC": "North Carolina",
        "NJ": "New Jersey", "VA": "Virginia", "IL": "Illinois", "AZ": "Arizona",
        "MI": "Michigan", "WA": "Washington", "TN": "Tennessee", "CO": "Colorado",
        "SC": "South Carolina", "MA": "Massachusetts", "MD": "Maryland",
        "IN": "Indiana", "MN": "Minnesota", "MO": "Missouri",
    }
    return names.get(code.upper(), code)


# ---------------------------------------------------------------------------
# Research-mode orchestrator
# ---------------------------------------------------------------------------


def _generate_research_report_pdf(order, pkg, ps: dict) -> bytes:
    """Generate the 10-section research-mode PDF matching reference format."""
    logo_path = _find_logo_path()
    pdf = _make_research_pdf(logo_path)
    pdf.set_auto_page_break(auto=True, margin=18)
    pdf.set_margins(15, 10, 15)
    pdf.add_page()
    w = pdf.epw

    # Inject helper values into ps for templates
    ps["_county"] = order.county or "Unknown"
    ps["_state_full"] = _state_full_name(order.state_code or "FL")

    _render_research_header(pdf, order, pkg, w, logo_path)
    _render_sec1_property_id(pdf, ps, order, w)
    _render_sec2_ownership(pdf, ps, order, w)
    _render_sec3_chain(pdf, ps, order, w)
    _render_sec4_liens(pdf, ps, w)
    _render_sec5_tax(pdf, ps, w)
    _render_sec6_easements(pdf, ps, w)
    _render_sec7_court(pdf, ps, w)
    _render_sec8_opinion(pdf, ps, w)
    _render_sec9_next_steps(pdf, ps, w)
    _render_sec10_contacts(pdf, ps, w)

    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# Main PDF generation
# ---------------------------------------------------------------------------

async def generate_package_pdf(
    db: AsyncSession, org_id: uuid.UUID, order_id: uuid.UUID
) -> bytes:
    """Generate a professional PDF report matching the Logikality sample format."""
    pkg = await get_package_or_raise(db, org_id, order_id)

    order = (await db.execute(
        select(TAOrder).where(TAOrder.id == order_id, TAOrder.org_id == org_id)
    )).scalar_one()

    # Dispatch to research-mode renderer if applicable
    ps = pkg.property_summary or {}
    if isinstance(ps, dict) and ps.get("research_mode") == "grounded":
        return _generate_research_report_pdf(order, pkg, ps)

    documents = (await db.execute(
        select(TADocument).where(TADocument.order_id == order_id, TADocument.org_id == org_id)
    )).scalars().all()

    chain_links = (await db.execute(
        select(TAChainLink).where(TAChainLink.order_id == order_id, TAChainLink.org_id == org_id)
        .order_by(TAChainLink.position)
    )).scalars().all()

    flags = (await db.execute(
        select(TAFlag).where(TAFlag.order_id == order_id, TAFlag.org_id == org_id)
    )).scalars().all()

    try:
        from fpdf import FPDF
    except ImportError:
        raise RuntimeError("fpdf2 is required for PDF generation")

    doc_map = {str(doc.id): doc for doc in documents}

    # Classify documents
    deed_docs = [d for d in documents if d.doc_type == "deed"]
    mortgage_docs = [d for d in documents if d.doc_type == "mortgage"]
    lien_docs = [d for d in documents if d.doc_type in ("lien", "judgment")]
    easement_docs = [d for d in documents if d.doc_type == "easement"]
    misc_docs = [d for d in documents if d.doc_type in ("other", "hoa", "plat", "court_order")]
    # Exclude tax assessment records from misc
    misc_docs = [d for d in misc_docs if not (d.summary and "Tax Assessment" in d.summary)]

    # Vesting deed = most recent deed by recording_date
    vesting_deed = None
    if deed_docs:
        def _date_sort_key(d):
            """Parse various date formats for sorting."""
            rd = d.recording_date or ""
            for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
                try:
                    from datetime import datetime as dt
                    return dt.strptime(rd, fmt)
                except ValueError:
                    continue
            return datetime.min
        vesting_deed = max(deed_docs, key=_date_sort_key)

    # Chain deeds (all except the vesting deed)
    chain_conveyance_links = [
        link for link in chain_links
        if link.link_type == "conveyance"
        and (not vesting_deed or str(link.document_id) != str(vesting_deed.id))
    ]

    # Borrower name
    borrower_name = order.borrower_name or "N/A"
    if borrower_name == "N/A" and vesting_deed:
        borrower_name = _party_names(vesting_deed.grantee)

    is_full_search = (order.search_scope or "full") == "full"

    # Tax info — prefer research data, fall back to document metadata
    ti = _get_tax_info(documents)
    _ps_data = pkg.property_summary if pkg.property_summary and isinstance(pkg.property_summary, dict) else {}
    tax_research = _ps_data.get("tax_status", {})
    if tax_research and not ti:
        # Convert research tax_status to legacy ti format for rendering
        ti = {
            "parcel_id": tax_research.get("parcel_number", order.parcel_number),
            "tax_year": tax_research.get("tax_year"),
            "land_value": tax_research.get("land_value"),
            "improvement_value": tax_research.get("improvement_value"),
            "assessed_value": tax_research.get("assessed_value"),
            "tax_amount": tax_research.get("total_tax_amount"),
            "tax_status": tax_research.get("tax_status"),
            "homestead_exemption": any("homestead" in e.lower() for e in tax_research.get("exemptions", [])),
        }

    # Subdivision from tax_info or package summary
    subdivision = "N/A"
    if ti and ti.get("subdivision"):
        subdivision = ti["subdivision"]
    elif pkg.property_summary and isinstance(pkg.property_summary, dict):
        subdivision = pkg.property_summary.get("subdivision", "N/A") or "N/A"
    if subdivision == "N/A" and vesting_deed:
        subdivision = _doc_meta(vesting_deed, "subdivision")

    # Build PDF
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    w = pdf.epw
    now = datetime.now(timezone.utc)
    order_date = now.strftime("%m/%d/%Y")
    if hasattr(order, "created_at") and order.created_at:
        order_date = order.created_at.strftime("%m/%d/%Y")

    # ---- Header: Logo + Order info ----
    # Logo anchored at top-right; text anchored at top-left at same baseline.
    # After both, cursor is forced below the taller of the two before sections begin.
    LOGO_Y = 10        # mm from top of page
    LOGO_H = 15        # mm tall
    HEADER_GAP = 6     # mm gap between header block and first section

    logo_path = _find_logo_path(org_id)
    if logo_path:
        pdf.image(logo_path, x=pdf.w - 65, y=LOGO_Y, h=LOGO_H)

    # Place caption text at same top-left baseline as the logo
    pdf.set_xy(pdf.l_margin, LOGO_Y)
    pdf.set_font(_FONT, "", 10)
    scope_label = "Full Search" if is_full_search else "Current Owner Search"
    pdf.cell(0, 6, _clean(f"Product Type: {scope_label}"), new_x="LMARGIN", new_y="NEXT")
    order_ref = order.order_reference or pkg.package_number
    pdf.cell(0, 6, _clean(f"Order/Loan#: {order_ref}"), new_x="LMARGIN", new_y="NEXT")

    # Push cursor below both the logo and the text before the first section
    cursor_after_text = pdf.get_y()
    logo_bottom = LOGO_Y + LOGO_H
    pdf.set_y(max(cursor_after_text, logo_bottom) + HEADER_GAP)

    # ---- 1. PROPERTY INFORMATION ----
    _section_header(pdf, "PROPERTY INFORMATION", w)
    _label_value_row(pdf, "Borrower's Name:", borrower_name, w)
    _label_value_row(pdf, "Property Address:", order.property_address or "N/A", w)

    municipality = order.city or "N/A"
    zip_code = order.zip_code or "N/A"
    _split_row(pdf, "Municipality:", municipality, "Zip:", zip_code, w)
    _split_row(pdf, "State:", order.state_code or "N/A", "County:", order.county or "N/A", w)

    parcel = order.parcel_number or "N/A"
    _split_row(pdf, "Parcel Number:", parcel, "Subdivision:", subdivision, w)

    # Dates
    eff_date = order.effective_date
    if not eff_date and hasattr(order, "created_at") and order.created_at:
        eff_date = order.created_at.date() if hasattr(order.created_at, "date") else order.created_at
    if eff_date:
        effective_date_str = eff_date.strftime("%m/%d/%Y")
        years = order.search_years or 60
        try:
            search_from_dt = eff_date.replace(year=eff_date.year - years)
            search_from = search_from_dt.strftime("%m/%d/%Y")
        except ValueError:
            search_from = "N/A"
    else:
        effective_date_str = order_date
        search_from = "N/A"
    _split_row(pdf, "Searched From Date:", search_from, "Effective Date:", effective_date_str, w)

    short_legal = order.legal_description or "N/A"
    if len(short_legal) > 80:
        short_legal = short_legal[:80] + "..."
    _label_value_row(pdf, "Short Legal:", short_legal, w)
    pdf.ln(3)

    # ---- 2. VESTING DEED INFORMATION ----
    _section_header(pdf, "VESTING DEED INFORMATION", w)
    if vesting_deed:
        deed_label = _deed_type_label(vesting_deed)
        _split_row(
            pdf, "Deed Type:", deed_label,
            "Consideration Amount:", _fmt_money(vesting_deed.consideration), w,
        )
        _label_value_row(pdf, "Grantor Name:", _party_names(vesting_deed.grantor), w)
        _label_value_row(pdf, "Grantee Name:", _party_names(vesting_deed.grantee), w)
        _label_value_row(pdf, "Fee Simple/leasehold:", "Fee Simple", w)

        rec_date = vesting_deed.recording_date or "N/A"
        _split_row(pdf, "Dated Date:", rec_date, "Recorded Date:", rec_date, w)

        book_page = _doc_meta(vesting_deed, "book_page")
        inst_no = _doc_meta(vesting_deed, "instrument_number", vesting_deed.recording_ref or "N/A")
        _split_row(pdf, " Book/Page No:", book_page, "Instrument No:", inst_no, w)
        _label_value_row(pdf, "Comments:", "", w)
    else:
        _text_block_row(pdf, "No vesting deed found.", w)
    pdf.ln(3)

    # ---- 3. REFERENCE OF LEGAL DESCRIPTION ----
    _section_header(pdf, "REFERENCE OF LEGAL DESCRIPTION", w)
    if vesting_deed:
        rec_date = vesting_deed.recording_date or "N/A"
        _split_row(pdf, "Dated Date:", rec_date, "Recorded Date:", rec_date, w)
        book_page = _doc_meta(vesting_deed, "book_page")
        inst_no = _doc_meta(vesting_deed, "instrument_number", vesting_deed.recording_ref or "N/A")
        _split_row(pdf, " Book/Page No:", book_page, "Instrument No:", inst_no, w)
    else:
        _text_block_row(pdf, "N/A", w)
    pdf.ln(3)

    # ---- 4. CHAIN OF TITLE (Full Search only) ----
    if is_full_search:
        if chain_conveyance_links:
            for link in chain_conveyance_links:
                doc = doc_map.get(str(link.document_id)) if link.document_id else None
                _section_header(pdf, "CHAIN OF TITLE", w)
                doc_type = _fmt_doc_type(doc.doc_type) if doc else "N/A"
                if doc:
                    doc_type = _deed_type_label(doc)
                consideration = _fmt_money(doc.consideration) if doc else "N/A"
                _split_row(pdf, "Deed Type:", doc_type, "Consideration Amount:", consideration, w)

                # Grantor: chain link from_party → fall back to document grantor
                from_names = _party_names(link.from_party) if isinstance(link.from_party, dict) else (link.from_party or "")
                if (not from_names or from_names == "N/A") and doc and doc.grantor:
                    from_names = _party_names(doc.grantor)
                _label_value_row(pdf, "Grantor Name:", from_names or "N/A", w)

                # Grantee: chain link to_party → fall back to document grantee
                to_names = _party_names(link.to_party) if isinstance(link.to_party, dict) else (link.to_party or "")
                if (not to_names or to_names == "N/A") and doc and doc.grantee:
                    to_names = _party_names(doc.grantee)
                _label_value_row(pdf, "Grantee Name:", to_names or "N/A", w)

                _label_value_row(pdf, "Fee Simple/leasehold:", "Fee Simple", w)
                rec_date = link.effective_date or (doc.recording_date if doc else None) or "N/A"
                _split_row(pdf, "Dated Date:", rec_date, "Recorded Date:", rec_date, w)

                # Book/Page and Instrument: doc_metadata → recording_ref
                chain_book_page = "N/A"
                chain_instrument = "N/A"
                if doc:
                    chain_book_page = _doc_meta(doc, "book_page", doc.recording_ref or "N/A")
                    chain_instrument = _doc_meta(doc, "instrument_number", doc.recording_ref or "N/A")
                _split_row(pdf, " Book/Page No:", chain_book_page, "Instrument No:", chain_instrument, w)

                comments = ""
                if link.is_gap:
                    comments = f"GAP: {link.gap_description or 'Gap detected in chain'}"
                _label_value_row(pdf, "Comments:", comments, w)
                pdf.ln(3)
        else:
            _section_header(pdf, "CHAIN OF TITLE", w)
            _text_block_row(pdf, "No additional chain of title entries.", w)
            pdf.ln(3)

    # ---- 5. DEED OF TRUST/MORTGAGE INFORMATION ----
    _section_header(pdf, "DEED OF TRUST/MORTGAGE INFORMATION", w)
    if mortgage_docs:
        for mdoc in mortgage_docs:
            # In mortgages: grantor = borrower, grantee = lender
            borrower = _party_names(mdoc.grantee) if mdoc.grantee else "N/A"
            lender = _party_names(mdoc.grantor) if mdoc.grantor else "N/A"
            # Swap if the source is clerk (clerk: "From" = borrower, "To" = lender)
            source = _doc_meta(mdoc, "source")
            if source == "clerk_of_court":
                borrower = _party_names(mdoc.grantor) if mdoc.grantor else "N/A"
                lender = _party_names(mdoc.grantee) if mdoc.grantee else "N/A"
            _label_value_row(pdf, "Borrower's Name:", borrower, w)
            _label_value_row(pdf, "Lender Name:", lender, w)
            _label_value_row(pdf, "Trustee Name:", _doc_meta(mdoc, "trustee"), w)
            rec_date = mdoc.recording_date or "N/A"
            _split_row(pdf, "Dated Date:", rec_date, "Recorded Date:", rec_date, w)
            inst_no = _doc_meta(mdoc, "instrument_number", mdoc.recording_ref or "N/A")
            book_page = _doc_meta(mdoc, "book_page")
            _split_row(pdf, "Instrument No:", inst_no, "Book/Page No:", book_page, w)
            maturity = _doc_meta(mdoc, "maturity_date")
            _split_row(pdf, "Loan Amount:", _fmt_money(mdoc.consideration), "Maturity Date:", maturity, w)
            open_closed = _doc_meta(mdoc, "open_closed_end")
            min_num = _doc_meta(mdoc, "min_number")
            _split_row(pdf, "Open End/Closed End:", open_closed, "MIN Number:", min_num, w)
            riders = _doc_meta(mdoc, "riders")
            _label_value_row(pdf, "PUD/Family/Home/FHA Rider:", riders, w)
            assoc_docs = _doc_meta(mdoc, "associated_docs", "")
            _label_value_row(pdf, "Associated Documents:", assoc_docs, w)
            comments = _doc_meta(mdoc, "comments", "")
            _label_value_row(pdf, "Comments:", comments, w)
            pdf.ln(2)
    else:
        has_captcha = any(
            sf.get("captcha_blocked") for sf in (pkg.property_summary or {}).get("sources_failed", [])
            if isinstance(sf, dict)
        )
        if has_captcha:
            _text_block_row(
                pdf,
                "Mortgage records not available - clerk portal access was blocked. "
                "Manual retrieval required.", w,
            )
        else:
            _text_block_row(pdf, "N/A", w)
    pdf.ln(3)

    # ---- 6. JUDGMENT & LIEN'S INFORMATION ----
    _section_header(pdf, "JUDGMENT & LIEN'S INFORMATION", w)
    judgment_flags = [f for f in flags if f.flag_type in ("unreleased_mortgage", "lien")]
    if lien_docs or judgment_flags:
        for ldoc in lien_docs:
            _text_block_row(
                pdf,
                f"{_fmt_doc_type(ldoc.doc_type)}: {ldoc.recording_ref or 'N/A'} "
                f"({ldoc.recording_date or 'N/A'}) - {_party_names(ldoc.grantor)} "
                f"vs {_party_names(ldoc.grantee)} "
                f"Amount: {_fmt_money(ldoc.consideration)}",
                w,
            )
        for jf in judgment_flags:
            if not lien_docs:
                _text_block_row(pdf, f"[{jf.severity.upper()}] {jf.title}: {jf.description}", w)
    else:
        _text_block_row(pdf, "NA", w)
    pdf.ln(3)

    # ---- 7. TAX INFORMATION ----
    _section_header(pdf, "TAX INFORMATION", w)
    if ti:
        parcel_id = str(ti.get("parcel_id", "N/A") or "N/A")
        tax_year = str(ti.get("tax_year", "N/A") or "N/A")
        # Assessment year defaults to tax year
        assessment_year = str(ti.get("assessment_year", tax_year) or tax_year)

        _split_row(pdf, "Parcel ID:", parcel_id, "Assessment Year:", assessment_year, w)
        _split_row(pdf, "Tax Year:", tax_year, "", "", w)
        _split_row(
            pdf, "Land Value:", _fmt_money(ti.get("land_value")),
            "Improvement Value:", _fmt_money(ti.get("improvement_value")), w,
        )
        total_value = ti.get("total_value") or ti.get("assessed_value")
        _split_row(
            pdf, "Total Value:", _fmt_money(total_value),
            "Homestead Exemption:", "Yes" if ti.get("homestead_exemption") else "NA", w,
        )

        # Blank lines for other exemption as in sample
        _split_row(pdf, "Other Exemption:", "NA", "", "", w)
        pdf.ln(1)

        # Tax installment table
        _render_tax_table(pdf, ti, w)

        _label_value_row(pdf, "Comments:", "", w)
    else:
        _text_block_row(pdf, "Tax information not available in current data.", w)
    pdf.ln(3)

    # ---- 8. EXCEPTIONS/EASEMENTS DOCUMENTS ----
    _section_header(pdf, "EXCEPTIONS/EASEMENTS DOCUMENTS", w)
    if easement_docs:
        for edoc in easement_docs:
            _text_block_row(
                pdf,
                f"{_fmt_doc_type(edoc.doc_type)}: {edoc.recording_ref or 'N/A'} "
                f"({edoc.recording_date or 'N/A'}) - {edoc.summary or ''}",
                w,
            )
    else:
        _text_block_row(pdf, "N/A", w)
    pdf.ln(3)

    # ---- 9. MISCELLANEOUS DOCUMENTS ----
    _section_header(pdf, "MISCELLANEOUS DOCUMENTS", w)
    # Include plat docs in misc section as "Plat Map recorded in B/P X/Y"
    plat_docs = [d for d in documents if d.doc_type == "plat" or (
        d.doc_metadata and isinstance(d.doc_metadata, dict)
        and d.doc_metadata.get("deed_type_detail", "").startswith("PB")
    )]
    all_misc = list(misc_docs)
    # Add plat docs that aren't already in misc
    misc_ids = {str(d.id) for d in all_misc}
    for pd in plat_docs:
        if str(pd.id) not in misc_ids:
            all_misc.append(pd)

    if all_misc:
        for i, mdoc in enumerate(all_misc, 1):
            if mdoc.doc_type == "plat" or (
                mdoc.doc_metadata and isinstance(mdoc.doc_metadata, dict)
                and mdoc.doc_metadata.get("deed_type_detail", "").startswith("PB")
            ):
                bp = _doc_meta(mdoc, "book_page", mdoc.recording_ref or "N/A")
                desc = f"Plat Map is Recorded in B/P {bp}"
            else:
                desc = mdoc.summary or f"{_fmt_doc_type(mdoc.doc_type)}: {mdoc.recording_ref or 'N/A'}"
            _text_block_row(pdf, f"{i}. {desc}", w)
    else:
        _text_block_row(pdf, "N/A", w)
    pdf.ln(3)

    # ---- 10. LEGAL DESCRIPTION ----
    _section_header(pdf, "LEGAL DESCRIPTION", w)
    _text_block_row(pdf, order.legal_description or "N/A", w)
    pdf.ln(3)

    # ---- 11. NAMES SEARCH ----
    _section_header(pdf, "NAMES SEARCH", w)
    all_names: set[str] = set()
    # Collect from documents
    for doc in documents:
        if doc.grantor:
            for name in doc.grantor.get("names", []):
                if name:
                    all_names.add(name)
        if doc.grantee:
            for name in doc.grantee.get("names", []):
                if name:
                    all_names.add(name)
    # Collect from chain links
    for link in chain_links:
        if isinstance(link.from_party, dict):
            for name in link.from_party.get("names", []):
                if name:
                    all_names.add(name)
        if isinstance(link.to_party, dict):
            for name in link.to_party.get("names", []):
                if name:
                    all_names.add(name)
    # Add subdivision name if meaningful
    if subdivision and subdivision != "N/A":
        all_names.add(subdivision)
    if all_names:
        names_text = "\n".join(sorted(all_names))
        _text_block_row(pdf, names_text, w)
    else:
        _text_block_row(pdf, "N/A", w)
    pdf.ln(3)

    # ---- Research-enhanced sections (from property_summary) ----
    ps = pkg.property_summary if pkg.property_summary and isinstance(pkg.property_summary, dict) else {}

    # ---- 12. PHYSICAL ATTRIBUTES (new) ----
    phys = _ps(ps, "physical_attributes", {})
    if phys:
        _section_header(pdf, "PHYSICAL ATTRIBUTES", w)
        rows = []
        if phys.get("property_type"):
            rows.append(("Property Type:", phys["property_type"]))
        if phys.get("year_built"):
            rows.append(("Year Built:", str(phys["year_built"])))
        if phys.get("living_area_sqft"):
            rows.append(("Living Area:", f"{phys['living_area_sqft']:,.0f} sq ft"))
        if phys.get("bedrooms"):
            rows.append(("Bedrooms:", str(phys["bedrooms"])))
        if phys.get("bathrooms"):
            rows.append(("Bathrooms:", str(phys["bathrooms"])))
        if phys.get("construction_type"):
            rows.append(("Construction:", phys["construction_type"]))
        if phys.get("roof_type"):
            rows.append(("Roof:", phys["roof_type"]))
        if phys.get("pool") is not None:
            rows.append(("Pool:", "Yes" if phys["pool"] else "No"))
        if rows:
            _render_kv_list(pdf, rows, w)
        else:
            _text_block_row(pdf, "N/A", w)
        pdf.ln(3)

    # ---- 13. LOT & LAND / ZONING (new) ----
    lot = _ps(ps, "lot_and_land", {})
    if lot:
        _section_header(pdf, "LOT & LAND / ZONING", w)
        rows = []
        if lot.get("lot_size_acres"):
            rows.append(("Lot Size:", f"{lot['lot_size_acres']} acres"))
        elif lot.get("lot_size_sqft"):
            rows.append(("Lot Size:", f"{lot['lot_size_sqft']:,.0f} sq ft"))
        if lot.get("zoning"):
            rows.append(("Zoning:", f"{lot['zoning']} — {lot.get('zoning_description', '')}".strip(" —")))
        if lot.get("flood_zone"):
            rows.append(("Flood Zone:", f"{lot['flood_zone']} — {lot.get('flood_zone_description', '')}".strip(" —")))
        if lot.get("land_use_code"):
            rows.append(("Land Use Code:", lot["land_use_code"]))
        if rows:
            _render_kv_list(pdf, rows, w)
        else:
            _text_block_row(pdf, "N/A", w)
        pdf.ln(3)

    # ---- 14. CURRENT OWNERSHIP (expanded) ----
    co = _ps(ps, "current_ownership", {})
    if co:
        _section_header(pdf, "CURRENT OWNERSHIP", w)
        if co.get("owner_names"):
            _label_value_row(pdf, "Owner(s):", ", ".join(co["owner_names"]), w)
        if co.get("ownership_type"):
            _label_value_row(pdf, "Ownership Type:", co["ownership_type"], w)
        if co.get("vesting_deed_ref"):
            _split_row(pdf, "Vesting Deed:", co["vesting_deed_ref"],
                       "Date:", co.get("vesting_deed_date", "N/A"), w)
        if co.get("homestead_exemption") is not None:
            _label_value_row(pdf, "Homestead:", "Yes" if co["homestead_exemption"] else "No", w)
        pdf.ln(3)

    # ---- 15. HOA / SUBDIVISION (new) ----
    hoa = _ps(ps, "hoa", {})
    if hoa and hoa.get("has_hoa"):
        _section_header(pdf, "HOA / SUBDIVISION", w)
        if hoa.get("hoa_name"):
            _label_value_row(pdf, "HOA Name:", hoa["hoa_name"], w)
        if hoa.get("hoa_contact"):
            _label_value_row(pdf, "Contact:", hoa["hoa_contact"], w)
        if hoa.get("hoa_fees"):
            _label_value_row(pdf, "Fees:", hoa["hoa_fees"], w)
        violations = hoa.get("hoa_violations", [])
        if violations:
            _sub_header(pdf, "Open Violations", w)
            _render_items_list(pdf, violations, w)
        pdf.ln(3)

    # ---- 16. CC&Rs / RESTRICTIONS (new) ----
    ccrs = _ps(ps, "ccrs_restrictions", {})
    if ccrs and ccrs.get("has_ccrs"):
        _section_header(pdf, "CC&Rs / RESTRICTIONS", w)
        if ccrs.get("recording_ref"):
            _label_value_row(pdf, "Recording Ref:", ccrs["recording_ref"], w)
        restrictions = ccrs.get("key_restrictions", [])
        if restrictions:
            _render_items_list(pdf, restrictions, w)
        if ccrs.get("notes"):
            _text_block_row(pdf, ccrs["notes"], w)
        pdf.ln(3)

    # ---- 17. NOTICE OF COMMENCEMENT (new) ----
    noc = _ps(ps, "notice_of_commencement", {})
    if noc and noc.get("has_noc"):
        _section_header(pdf, "NOTICE OF COMMENCEMENT", w)
        _split_row(pdf, "Recording Ref:", noc.get("recording_ref", "N/A"),
                   "Date:", noc.get("recording_date", "N/A"), w)
        if noc.get("contractor"):
            _label_value_row(pdf, "Contractor:", noc["contractor"], w)
        if noc.get("description"):
            _label_value_row(pdf, "Description:", noc["description"], w)
        fpa = noc.get("final_payment_affidavit")
        _label_value_row(pdf, "Final Payment Affidavit:", "Yes" if fpa else "No / Not Filed", w)
        pdf.ln(3)

    # ---- 18. FORECLOSURE / COURT (new) ----
    court = _ps(ps, "court_proceedings", [])
    if court:
        _section_header(pdf, "FORECLOSURE / COURT PROCEEDINGS", w)
        for case in court:
            _sub_header(pdf, f"{case.get('case_type', 'Case')} — #{case.get('case_number', 'N/A')}", w)
            _split_row(pdf, "Filed:", case.get("filing_date", "N/A"),
                       "Status:", case.get("status", "N/A"), w)
            if case.get("parties"):
                _label_value_row(pdf, "Parties:", case["parties"], w)
            if case.get("notes"):
                _text_block_row(pdf, case["notes"], w)
        pdf.ln(3)

    # ---- 19. PERMITS / CODE ENFORCEMENT (new) ----
    permits = _ps(ps, "permits", [])
    if permits:
        _section_header(pdf, "PERMITS / CODE ENFORCEMENT", w)
        for p in permits:
            status = p.get("status", "N/A")
            desc = p.get("description", p.get("permit_type", "Permit"))
            _split_row(pdf, f"#{p.get('permit_number', 'N/A')}:", desc,
                       "Status:", status, w)
            if p.get("violation_details"):
                _text_block_row(pdf, f"  Violation: {p['violation_details']}", w)
        pdf.ln(3)

    # ---- 20. SURVEY & PLAT (new) ----
    survey = _ps(ps, "survey_plat", {})
    if survey and survey.get("has_survey"):
        _section_header(pdf, "SURVEY & PLAT", w)
        if survey.get("plat_book_page"):
            _label_value_row(pdf, "Plat Book/Page:", survey["plat_book_page"], w)
        if survey.get("survey_date"):
            _label_value_row(pdf, "Survey Date:", survey["survey_date"], w)
        if survey.get("surveyor"):
            _label_value_row(pdf, "Surveyor:", survey["surveyor"], w)
        if survey.get("notes"):
            _text_block_row(pdf, survey["notes"], w)
        pdf.ln(3)

    # ---- 21. MISCELLANEOUS DOCUMENTS (existing, renumbered) ----
    # Already rendered above as section 9

    # ---- 22. LEGAL DESCRIPTION (existing, renumbered) ----
    # Already rendered above as section 10

    # ---- 23. NAMES SEARCH (existing, renumbered) ----
    # Already rendered above as section 11

    # ---- 24. TITLE OPINION SUMMARY (new) ----
    opinion_items = _ps(ps, "title_opinion_items", [])
    if opinion_items:
        _section_header(pdf, "TITLE OPINION SUMMARY", w)
        for item in opinion_items:
            _ensure_space(pdf, _ROW_H * 2 + 4)
            sev = item.get("severity", "low")
            x_start = pdf.get_x()
            y_start = pdf.get_y()
            _render_severity_badge(pdf, sev, x_start, y_start)
            pdf.set_x(x_start + 5)
            pdf.set_font(_FONT, "B", 8)
            status_label = item.get("status", "open").upper()
            pdf.cell(0, _ROW_H, _clean(f"[{status_label}] {item.get('item', '')}"),
                     new_x="LMARGIN", new_y="NEXT")
            if item.get("recommendation"):
                pdf.set_font(_FONT, "I", 7)
                pdf.cell(5, _ROW_H, "", new_x="END", new_y="TOP")
                pdf.multi_cell(w - 5, _ROW_H, _clean(f"Recommendation: {item['recommendation']}"),
                               new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    # ---- 25. NEXT STEPS / ACTION ITEMS (new) ----
    next_steps = _ps(ps, "next_steps", [])
    if next_steps:
        _section_header(pdf, "NEXT STEPS / ACTION ITEMS", w)
        for ns in next_steps:
            priority = ns.get("priority", "medium").upper()
            action = ns.get("action", "")
            _ensure_space(pdf, _ROW_H + 2)
            pdf.set_font(_FONT, "B", 8)
            pdf.cell(20, _ROW_H, _clean(f"[{priority}]"), new_x="END", new_y="TOP")
            pdf.set_font(_FONT, "", 8)
            pdf.multi_cell(w - 20, _ROW_H, _clean(action), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(3)

    # ---- 26. KEY CONTACTS (new) ----
    contacts = _ps(ps, "key_contacts", [])
    if contacts:
        _section_header(pdf, "KEY CONTACTS", w)
        for c in contacts:
            parts = [c.get("name", "")]
            if c.get("role"):
                parts[0] += f" ({c['role']})"
            if c.get("phone"):
                parts.append(f"Phone: {c['phone']}")
            if c.get("website"):
                parts.append(c["website"])
            _text_block_row(pdf, " | ".join(parts), w)
        pdf.ln(3)

    # ---- 27. COMPARABLE SALES (new) ----
    comps = _ps(ps, "comparable_sales", [])
    if comps:
        _section_header(pdf, "COMPARABLE SALES", w)
        for comp in comps:
            line = f"{comp.get('address', 'N/A')} — {comp.get('sale_date', 'N/A')} — {comp.get('sale_price', 'N/A')}"
            if comp.get("sqft"):
                line += f" ({comp['sqft']:,.0f} sq ft)"
            _text_block_row(pdf, line, w)
        pdf.ln(3)

    # ---- 28. ADDITIONAL COMMENTS + SOURCES ----
    _section_header(pdf, "ADDITIONAL COMMENTS", w)
    narrative = ""
    if ps:
        narrative = ps.get("narrative", "")
    if not is_full_search:
        _text_block_row(pdf, narrative or "N/A", w)
    else:
        comment = narrative or "Please note: Search Starts from Developer Deed."
        _text_block_row(pdf, comment, w)

    # Source citations (from web search)
    search_summary = _ps(ps, "search_summary", {})
    sources_searched = search_summary.get("sources_searched", []) if search_summary else []
    if sources_searched:
        pdf.ln(2)
        _sub_header(pdf, "Sources Searched", w)
        _render_items_list(pdf, sources_searched, w)

    return bytes(pdf.output())
