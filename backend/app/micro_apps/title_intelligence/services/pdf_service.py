"""PDF report generation using fpdf2, matching V2's pdf-lib approach."""

import re

from fpdf import FPDF


def markdown_to_pdf(content: str, title: str = "Title Intelligence Report") -> bytes:
    """Convert markdown-formatted report content to PDF bytes.

    Handles:
    - # and ## headers
    - Bullet points (- and *)
    - Bold (**text**)
    - Paragraphs
    - Auto-wrap and auto-paginate
    """
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 12, _clean_markdown(title), new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(6)

    lines = content.split("\n")

    for line in lines:
        stripped = line.strip()

        if not stripped:
            pdf.ln(4)
            continue

        # H1 header
        if stripped.startswith("# "):
            text = stripped[2:].strip()
            pdf.ln(4)
            pdf.set_font("Helvetica", "B", 14)
            pdf.multi_cell(0, 8, _clean_markdown(text), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
            continue

        # H2 header
        if stripped.startswith("## "):
            text = stripped[3:].strip()
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 12)
            pdf.multi_cell(0, 7, _clean_markdown(text), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
            continue

        # H3 header
        if stripped.startswith("### "):
            text = stripped[4:].strip()
            pdf.ln(2)
            pdf.set_font("Helvetica", "BI", 11)
            pdf.multi_cell(0, 7, _clean_markdown(text), new_x="LMARGIN", new_y="NEXT")
            pdf.ln(1)
            continue

        # Bullet point
        if stripped.startswith("- ") or stripped.startswith("* "):
            text = stripped[2:].strip()
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 6, f"  - {_clean_markdown(text)}", new_x="LMARGIN", new_y="NEXT")
            continue

        # Numbered list
        if re.match(r"^\d+\.\s", stripped):
            pdf.set_font("Helvetica", "", 10)
            pdf.multi_cell(0, 6, f"  {_clean_markdown(stripped)}", new_x="LMARGIN", new_y="NEXT")
            continue

        # Regular paragraph
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 6, _clean_markdown(stripped), new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())


def _clean_markdown(text: str) -> str:
    """Remove markdown formatting and replace Unicode chars for PDF compatibility."""
    # Remove bold markers
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
    # Remove italic markers
    text = re.sub(r"\*(.*?)\*", r"\1", text)
    # Remove code markers
    text = re.sub(r"`(.*?)`", r"\1", text)
    # Replace Unicode characters that Helvetica (latin-1) can't encode
    replacements = {
        "\u2013": "-",   # en-dash
        "\u2014": "--",  # em-dash
        "\u2018": "'",   # left single quote
        "\u2019": "'",   # right single quote
        "\u201c": '"',   # left double quote
        "\u201d": '"',   # right double quote
        "\u2026": "...", # ellipsis
        "\u2022": "-",   # bullet
        "\u00a0": " ",   # non-breaking space
        "\u2010": "-",   # hyphen
        "\u2011": "-",   # non-breaking hyphen
        "\u2012": "-",   # figure dash
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    # Fallback: encode to latin-1, replacing any remaining unsupported chars
    text = text.encode("latin-1", errors="replace").decode("latin-1")
    return text
