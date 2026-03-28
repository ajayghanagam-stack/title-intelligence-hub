"""Synthetic PDF generator for benchmark tests.

Creates multi-page PDFs with realistic title commitment text so that
benchmark runs exercise the pipeline with representative token density
(~300 words per page).
"""

from __future__ import annotations

import io

from fpdf import FPDF

# ---------------------------------------------------------------------------
# Realistic legal text blocks (~300 words each)
# ---------------------------------------------------------------------------

SCHEDULE_A_TEXT = (
    "SCHEDULE A\n\n"
    "1. Effective Date: January 15, 2025\n\n"
    "2. Policy or Policies to be issued:\n"
    "(a) ALTA Owner's Policy (06-17-06) in the amount of $450,000.00\n"
    "Proposed Insured: John A. Smith and Jane B. Smith, as joint tenants\n\n"
    "(b) ALTA Loan Policy (06-17-06) in the amount of $360,000.00\n"
    "Proposed Insured: First National Mortgage Corporation, its successors and/or assigns\n\n"
    "3. The estate or interest in the land described or referred to in this Commitment "
    "is Fee Simple.\n\n"
    "4. Title to the Fee Simple estate or interest in the land is at the Effective Date "
    "vested in: Robert C. Johnson and Mary D. Johnson, husband and wife, as tenants by "
    "the entirety.\n\n"
    "5. The land referred to in this Commitment is described as follows:\n"
    "Lot 42, Block 7, OAKRIDGE ESTATES SUBDIVISION, Phase 3, according to the plat "
    "thereof recorded in Plat Book 156, Page 23, of the Public Records of Springfield "
    "County, State of Illinois.\n\n"
    "Property Address: 1234 Oakridge Drive, Springfield, IL 62704\n\n"
    "Tax Parcel ID: 14-25-300-042-0000\n\n"
    "The Company hereby commits to issue the Policy or Policies of Title Insurance "
    "described above, subject to the terms and conditions of this Commitment, the "
    "Conditions and Stipulations, and the Exclusions from Coverage."
)

SCHEDULE_B1_TEXT = (
    "SCHEDULE B -- PART I\n"
    "Requirements\n\n"
    "The following are the requirements to be complied with prior to the issuance of "
    "the Policy or Policies referred to herein:\n\n"
    "1. Payment of the full consideration to, or for the account of, the grantors or "
    "mortgagors.\n\n"
    "2. Instruments sufficient to create the estate or interest to be insured must be "
    "properly executed, delivered, and duly filed for record.\n\n"
    "3. Payment of all taxes, charges, assessments, and encumbrances due and payable "
    "against the subject premises.\n\n"
    "4. Satisfactory evidence that improvements and/or repairs are completed and the "
    "costs thereof have been paid.\n\n"
    "5. Release or reconveyance of Deed of Trust executed by Robert C. Johnson and "
    "Mary D. Johnson in favor of Second Federal Savings Bank dated March 12, 2019, "
    "and recorded April 1, 2019, as Document No. 2019-034567 in the Official Records "
    "of Springfield County, Illinois, securing an original indebtedness of $280,000.00.\n\n"
    "6. Execution and delivery of an Affidavit of Identity by the proposed insured "
    "parties sufficient to distinguish them from persons having similar names who may "
    "have judgments or liens against them.\n\n"
    "7. Proof of payment of real estate taxes for the current fiscal year."
)

SCHEDULE_B2_TEXT = (
    "SCHEDULE B -- PART II\n"
    "Exceptions\n\n"
    "The Policy or Policies to be issued will contain exceptions to the following "
    "matters unless the same are disposed of to the satisfaction of the Company:\n\n"
    "1. Rights or claims of parties in possession not shown by the public records.\n\n"
    "2. Encroachments, overlaps, boundary line disputes, or other matters which would "
    "be disclosed by an accurate survey and inspection of the premises.\n\n"
    "3. Easements or claims of easements not shown by the public records.\n\n"
    "4. Any lien, or right to a lien, for services, labor, or material heretofore or "
    "hereafter furnished, imposed by law and not shown by the public records.\n\n"
    "5. Taxes or assessments which are not shown as existing liens by the records of "
    "any taxing authority that levies taxes or assessments on real property.\n\n"
    "6. Real estate taxes for the year 2025 and subsequent years, which are not yet "
    "due and payable. First installment of 2024 taxes in the amount of $3,456.78, "
    "due March 1, 2025.\n\n"
    "7. Covenants, conditions, and restrictions as set forth in the Declaration of "
    "Covenants for Oakridge Estates Subdivision recorded in Book 892, Page 145.\n\n"
    "8. Easement for public utilities recorded in Book 734, Page 89, of the Official "
    "Records of Springfield County, Illinois."
)

ENDORSEMENT_TEXT = (
    "ENDORSEMENTS\n\n"
    "The following endorsements are available and may be issued with the Policy upon "
    "compliance with the applicable requirements:\n\n"
    "ALTA 8.1-06 -- Environmental Protection Lien Endorsement\n"
    "Insures against loss or damage sustained by the insured by reason of the existence "
    "of any environmental protection lien.\n\n"
    "ALTA 9-06 -- Restrictions, Encroachments, Minerals Endorsement\n"
    "Provides coverage against loss or damage resulting from violations of covenants, "
    "conditions, or restrictions, encroachments of improvements, and damage from mineral "
    "extraction.\n\n"
    "ALTA 5-06 -- Planned Unit Development Endorsement\n"
    "Provides coverage for planned unit developments including common elements and "
    "assessment liens.\n\n"
    "Each endorsement is subject to the applicable premium and any additional "
    "underwriting requirements. The availability of endorsements may vary by "
    "jurisdiction and is subject to change without notice."
)


def _page_text_for(page_number: int, total_pages: int) -> str:
    """Return representative text for a given page position in the document."""
    # First ~15% = Schedule A, next ~25% = Schedule B1, next ~35% = Schedule B2, rest = endorsements
    ratio = page_number / max(total_pages, 1)
    if ratio < 0.15:
        return SCHEDULE_A_TEXT
    elif ratio < 0.40:
        return SCHEDULE_B1_TEXT
    elif ratio < 0.75:
        return SCHEDULE_B2_TEXT
    else:
        return ENDORSEMENT_TEXT


def generate_synthetic_pdf(page_count: int) -> bytes:
    """Generate a synthetic title commitment PDF with *page_count* pages.

    Each page has ~300 words of legal text, matching realistic token density.
    Returns raw PDF bytes.
    """
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    for i in range(1, page_count + 1):
        pdf.add_page()
        pdf.set_font("Helvetica", size=10)
        text = _page_text_for(i, page_count)
        # Add page number and slight variation
        header = f"Page {i} of {page_count}\n\n"
        pdf.multi_cell(0, 5, header + text, new_x="LMARGIN", new_y="NEXT")

    buf = io.BytesIO()
    pdf.output(buf)
    return buf.getvalue()
