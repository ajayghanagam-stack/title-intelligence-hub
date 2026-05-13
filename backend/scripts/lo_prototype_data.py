"""Loan Onboarding — prototype admin fixtures (extraction schemas,
validation rules, program profiles, doc-type catalog).

Mirrors ``prototype/src/mocks/logik-intake-admin.ts`` so a seeded org sees
the same starter configuration as the LogikIntake prototype. Fields are
authored per-doc-type (not paystub filler) so they're useful in real
extraction runs — the prototype's reuse of paystub fields across schemas
is a UI-counting trick, not a semantic contract.

All data is plain Python — no behavior. Imported by ``scripts/seed.py``.
"""
from __future__ import annotations

# ── 1. Doc-type catalog (22 entries) ──────────────────────────────
# (key, name, category, auto_classify_enabled, active)
DOC_TYPES: list[tuple[str, str, str, bool, bool]] = [
    ("w2", "W-2 Wage & Tax Statement", "Income", True, True),
    ("f1040", "IRS Form 1040 Tax Return", "Income", True, True),
    ("sch_c", "IRS Schedule C — Self-Employment", "Income", True, True),
    ("paystub", "Pay Stub / Paycheck", "Income", True, True),
    ("bank_stmt", "Bank Statement", "Assets", True, True),
    ("gov_id", "Government-issued Photo ID", "Identity", True, True),
    ("voe", "Verification of Employment (VOE)", "Employment", True, True),
    ("purchase_agmt", "Purchase Agreement / Sales Contract", "Property", True, True),
    ("appraisal", "Appraisal Report (1004 / URAR)", "Property", True, True),
    ("hoi", "Homeowners Insurance Declaration", "Insurance", True, True),
    ("title_commit", "Title Commitment", "Title", True, True),
    ("credit_report", "Credit Report — Tri-merge", "Credit", True, True),
    ("dd214", "DD-214 Military Discharge", "VA/Military", True, True),
    ("gift_letter", "Gift Letter", "Assets", True, True),
    ("flood_cert", "Flood Certificate", "Insurance", True, True),
    ("f4506c", "IRS 4506-C Tax Transcript Request", "Income", True, True),
    ("ss_award", "Social Security Award Letter", "Income", True, True),
    ("lease", "Lease Agreement", "Assets", False, False),
    ("urla_1003", "URLA 1003 (Loan Application)", "Application", True, True),
    ("closing_disclosure", "Closing Disclosure", "Closing", True, True),
    ("mi_certificate", "Mortgage Insurance Certificate", "Insurance", True, True),
    ("va_coe", "VA Certificate of Eligibility", "VA/Military", True, True),
]


# ── 2. Extraction schema field templates ──────────────────────────
# Field shape (matches backend `lo_extraction_schemas.fields` JSONB):
#   { "key": str, "type": str, "required": bool, "min_confidence": float }
#
# Type values follow the convention documented in
# ``backend/app/micro_apps/loan_onboarding/models/extraction_schema.py``:
#   "string" | "currency" | "date" | "ssn" | "phone" | "email"
#   | "address" | "boolean" | "number" | "year"
#
# Required/optional split chosen by underwriting relevance.
# min_confidence picks: identifiers 0.95, names/currency/dates 0.85–0.90,
# free-text 0.70.


def _f(key: str, ftype: str, required: bool, min_conf: float) -> dict:
    return {"key": key, "type": ftype, "required": required, "min_confidence": min_conf}


W2_FIELDS = [
    _f("employer_name", "string", True, 0.80),
    _f("employer_ein", "string", True, 0.90),
    _f("employee_name", "string", True, 0.85),
    _f("employee_ssn_last4", "ssn", True, 0.95),
    _f("employee_address", "address", False, 0.70),
    _f("tax_year", "year", True, 0.95),
    _f("box1_wages_tips", "currency", True, 0.90),
    _f("box2_federal_tax_withheld", "currency", True, 0.90),
    _f("box3_social_security_wages", "currency", True, 0.85),
    _f("box4_social_security_tax_withheld", "currency", True, 0.85),
    _f("box5_medicare_wages", "currency", True, 0.85),
    _f("box12_code_amount", "string", False, 0.70),
]

F1040_FIELDS = [
    _f("tax_year", "year", True, 0.95),
    _f("filing_status", "string", True, 0.90),
    _f("taxpayer_name", "string", True, 0.85),
    _f("taxpayer_ssn_last4", "ssn", True, 0.95),
    _f("spouse_name", "string", False, 0.80),
    _f("spouse_ssn_last4", "ssn", False, 0.95),
    _f("total_income", "currency", True, 0.90),
    _f("adjusted_gross_income", "currency", True, 0.90),
    _f("taxable_income", "currency", True, 0.88),
]

SCH_C_FIELDS = [
    _f("business_name", "string", True, 0.85),
    _f("ein_or_ssn", "string", True, 0.95),
    _f("principal_business_activity", "string", True, 0.75),
    _f("accounting_method", "string", False, 0.70),
    _f("gross_receipts", "currency", True, 0.90),
    _f("total_expenses", "currency", True, 0.88),
    _f("net_profit_or_loss", "currency", True, 0.90),
    _f("line_31_net_profit", "currency", False, 0.85),
]

PAYSTUB_FIELDS = [
    _f("employer_name", "string", True, 0.85),
    _f("employee_name", "string", True, 0.85),
    _f("pay_period_start", "date", True, 0.90),
    _f("pay_period_end", "date", True, 0.90),
    _f("gross_pay", "currency", True, 0.90),
    _f("net_pay", "currency", True, 0.88),
    _f("ytd_gross", "currency", True, 0.88),
]

BANK_STMT_FIELDS = [
    _f("bank_name", "string", True, 0.85),
    _f("account_holder_name", "string", True, 0.85),
    _f("account_number_last4", "string", True, 0.90),
    _f("statement_period_start", "date", True, 0.90),
    _f("statement_period_end", "date", True, 0.90),
    _f("beginning_balance", "currency", True, 0.88),
    _f("ending_balance", "currency", True, 0.90),
    _f("average_daily_balance", "currency", False, 0.80),
    _f("total_deposits", "currency", False, 0.80),
    _f("total_withdrawals", "currency", False, 0.80),
]

GOV_ID_FIELDS = [
    _f("id_type", "string", True, 0.90),
    _f("id_number_last4", "string", True, 0.90),
    _f("full_name", "string", True, 0.90),
    _f("date_of_birth", "date", True, 0.90),
    _f("expiration_date", "date", True, 0.95),
    _f("issuing_state", "string", True, 0.85),
]

VOE_FIELDS = [
    _f("employer_name", "string", True, 0.90),
    _f("employee_name", "string", True, 0.90),
    _f("position_title", "string", True, 0.80),
    _f("hire_date", "date", True, 0.90),
    _f("employment_status", "string", True, 0.85),
    _f("current_salary", "currency", False, 0.85),
]

PURCHASE_AGMT_FIELDS = [
    _f("buyer_name", "string", True, 0.90),
    _f("seller_name", "string", True, 0.90),
    _f("property_address", "address", True, 0.85),
    _f("purchase_price", "currency", True, 0.95),
    _f("earnest_money", "currency", True, 0.85),
    _f("closing_date", "date", True, 0.90),
    _f("contingencies", "string", False, 0.70),
    _f("signature_buyer", "boolean", True, 0.85),
    _f("signature_seller", "boolean", True, 0.85),
]

APPRAISAL_FIELDS = [
    _f("subject_property_address", "address", True, 0.90),
    _f("appraiser_name", "string", True, 0.85),
    _f("appraiser_license_number", "string", True, 0.90),
    _f("effective_date", "date", True, 0.90),
    _f("appraised_value", "currency", True, 0.95),
    _f("gross_living_area_sqft", "number", True, 0.85),
    _f("year_built", "year", True, 0.85),
    _f("bedroom_count", "number", True, 0.85),
    _f("bathroom_count", "number", True, 0.85),
    _f("comparable_count", "number", False, 0.75),
    _f("appraiser_signed", "boolean", False, 0.75),
]

HOI_FIELDS = [
    _f("insurance_carrier", "string", True, 0.85),
    _f("policy_number", "string", True, 0.90),
    _f("named_insured", "string", True, 0.85),
    _f("property_address", "address", True, 0.85),
    _f("effective_date", "date", True, 0.90),
    _f("expiration_date", "date", False, 0.90),
    _f("dwelling_coverage_amount", "currency", False, 0.85),
]

CREDIT_REPORT_FIELDS = [
    _f("borrower_name", "string", True, 0.90),
    _f("borrower_ssn_last4", "ssn", True, 0.95),
    _f("report_date", "date", True, 0.90),
    _f("equifax_score", "number", True, 0.95),
    _f("experian_score", "number", True, 0.95),
    _f("transunion_score", "number", True, 0.95),
    _f("derogatory_count", "number", False, 0.85),
    _f("inquiries_count", "number", False, 0.85),
]

GIFT_LETTER_FIELDS = [
    _f("donor_name", "string", True, 0.85),
    _f("donor_relationship", "string", True, 0.80),
    _f("gift_amount", "currency", True, 0.95),
    _f("gift_date", "date", True, 0.90),
    _f("donor_signature_present", "boolean", False, 0.80),
]

SS_AWARD_FIELDS = [
    _f("recipient_name", "string", True, 0.85),
    _f("recipient_ssn_last4", "ssn", True, 0.95),
    _f("monthly_benefit_amount", "currency", True, 0.90),
    _f("effective_date", "date", False, 0.85),
]

LEASE_FIELDS = [
    _f("lessor_name", "string", True, 0.85),
    _f("lessee_name", "string", True, 0.85),
    _f("lease_start_date", "date", True, 0.90),
    _f("lease_end_date", "date", True, 0.90),
    _f("monthly_rent", "currency", False, 0.85),
]

DD214_FIELDS = [
    _f("service_member_name", "string", True, 0.90),
    _f("service_member_ssn_last4", "ssn", True, 0.95),
    _f("date_of_birth", "date", True, 0.90),
    _f("branch_of_service", "string", True, 0.90),
    _f("entry_date", "date", True, 0.90),
    _f("separation_date", "date", True, 0.90),
    _f("character_of_service", "string", True, 0.85),
    _f("rank_at_separation", "string", False, 0.80),
    _f("total_active_service_years", "number", False, 0.85),
]

FLOOD_CERT_FIELDS = [
    _f("borrower_name", "string", True, 0.85),
    _f("property_address", "address", True, 0.90),
    _f("certificate_number", "string", True, 0.95),
    _f("determination_date", "date", True, 0.90),
    _f("flood_zone", "string", True, 0.95),
    _f("in_special_flood_hazard_area", "boolean", True, 0.95),
    _f("nfip_community_number", "string", False, 0.85),
    _f("nfip_community_name", "string", False, 0.80),
]

TITLE_COMMIT_FIELDS = [
    _f("title_company_name", "string", True, 0.85),
    _f("file_number", "string", True, 0.95),
    _f("effective_date", "date", True, 0.90),
    _f("proposed_insured", "string", True, 0.85),
    _f("property_address", "address", True, 0.90),
    _f("legal_description", "string", True, 0.75),
    _f("estate_or_interest", "string", True, 0.80),
    _f("purchase_price", "currency", False, 0.90),
    _f("loan_amount", "currency", False, 0.90),
    _f("current_vesting", "string", False, 0.80),
]

F4506C_FIELDS = [
    _f("taxpayer_name", "string", True, 0.90),
    _f("taxpayer_ssn_last4", "ssn", True, 0.95),
    _f("spouse_name", "string", False, 0.85),
    _f("spouse_ssn_last4", "ssn", False, 0.95),
    _f("current_address", "address", True, 0.85),
    _f("previous_address", "address", False, 0.80),
    _f("transcript_type", "string", True, 0.90),
    _f("tax_years_requested", "string", True, 0.90),
    _f("signature_date", "date", True, 0.90),
]

URLA_1003_FIELDS = [
    _f("borrower_name", "string", False, 0.90),
    _f("borrower_ssn_last4", "ssn", False, 0.95),
    _f("borrower_date_of_birth", "date", False, 0.90),
    _f("co_borrower_name", "string", False, 0.85),
    _f("co_borrower_ssn_last4", "ssn", False, 0.95),
    _f("subject_property_address", "address", False, 0.90),
    _f("loan_purpose", "string", False, 0.90),
    _f("loan_amount", "currency", False, 0.95),
    _f("loan_term_months", "number", False, 0.90),
    _f("interest_rate", "number", False, 0.90),
    _f("occupancy_type", "string", False, 0.85),
    _f("monthly_income_total", "currency", False, 0.85),
    _f("monthly_housing_expense", "currency", False, 0.85),
    _f("borrower_signature_present", "boolean", False, 0.85),
    _f("borrower_signature_date", "date", False, 0.90),
]

CLOSING_DISCLOSURE_FIELDS = [
    _f("borrower_name", "string", False, 0.90),
    _f("co_borrower_name", "string", False, 0.85),
    _f("seller_name", "string", False, 0.85),
    _f("lender_name", "string", False, 0.90),
    _f("loan_term_months", "number", False, 0.90),
    _f("loan_purpose", "string", False, 0.90),
    _f("loan_product", "string", False, 0.85),
    _f("loan_type", "string", False, 0.85),
    _f("loan_amount", "currency", False, 0.95),
    _f("interest_rate", "number", False, 0.95),
    _f("monthly_principal_and_interest", "currency", False, 0.90),
    _f("prepayment_penalty", "boolean", False, 0.85),
    _f("balloon_payment", "boolean", False, 0.85),
    _f("closing_date", "date", False, 0.90),
    _f("disbursement_date", "date", False, 0.90),
    _f("cash_to_close", "currency", False, 0.90),
    _f("subject_property_address", "address", False, 0.90),
    _f("sale_price", "currency", False, 0.90),
]

MI_CERTIFICATE_FIELDS = [
    _f("mi_company_name", "string", False, 0.90),
    _f("certificate_number", "string", False, 0.95),
    _f("borrower_name", "string", False, 0.90),
    _f("lender_name", "string", False, 0.85),
    _f("loan_number", "string", False, 0.90),
    _f("property_address", "address", False, 0.90),
    _f("loan_amount", "currency", False, 0.95),
    _f("coverage_percent", "number", False, 0.90),
    _f("premium_amount", "currency", False, 0.85),
    _f("premium_plan", "string", False, 0.80),
    _f("effective_date", "date", False, 0.90),
    _f("expiration_date", "date", False, 0.90),
]

VA_COE_FIELDS = [
    _f("veteran_name", "string", False, 0.90),
    _f("veteran_ssn_last4", "ssn", False, 0.95),
    _f("veteran_date_of_birth", "date", False, 0.90),
    _f("service_number", "string", False, 0.90),
    _f("branch_of_service", "string", False, 0.90),
    _f("entitlement_code", "string", False, 0.90),
    _f("entitlement_amount", "currency", False, 0.95),
    _f("entitlement_used", "currency", False, 0.85),
    _f("entitlement_available", "currency", False, 0.90),
    _f("funding_fee_status", "string", False, 0.85),
    _f("certificate_date", "date", False, 0.90),
    _f("certificate_number", "string", False, 0.95),
]


# (doc_type_key, fields)
# Every one of the prototype doc types gets a populated schema so the
# admin UI's per-doc-type sidebar has fields to display for each.
EXTRACTION_SCHEMAS: list[tuple[str, list[dict]]] = [
    ("w2", W2_FIELDS),
    ("f1040", F1040_FIELDS),
    ("sch_c", SCH_C_FIELDS),
    ("paystub", PAYSTUB_FIELDS),
    ("bank_stmt", BANK_STMT_FIELDS),
    ("gov_id", GOV_ID_FIELDS),
    ("voe", VOE_FIELDS),
    ("purchase_agmt", PURCHASE_AGMT_FIELDS),
    ("appraisal", APPRAISAL_FIELDS),
    ("hoi", HOI_FIELDS),
    ("title_commit", TITLE_COMMIT_FIELDS),
    ("credit_report", CREDIT_REPORT_FIELDS),
    ("dd214", DD214_FIELDS),
    ("gift_letter", GIFT_LETTER_FIELDS),
    ("flood_cert", FLOOD_CERT_FIELDS),
    ("f4506c", F4506C_FIELDS),
    ("ss_award", SS_AWARD_FIELDS),
    ("lease", LEASE_FIELDS),
    ("urla_1003", URLA_1003_FIELDS),
    ("closing_disclosure", CLOSING_DISCLOSURE_FIELDS),
    ("mi_certificate", MI_CERTIFICATE_FIELDS),
    ("va_coe", VA_COE_FIELDS),
]


# ── 3. Validation rules (14 entries, matches prototype) ───────────
# Frontend uses tabs keyed by `scope`: "doc" or "data".
# Backend: scope is a free-form string (max 50 chars); rule unique per
# (org, scope, rule). severity ∈ {"hard", "soft"}.
# preset_id=None → LLM-evaluated; set non-null to route through
# ``services/validation_presets.py``.
# Each row carries the prototype's clean separation of description /
# applies_to / condition so the admin UI can render them in dedicated
# columns (1:1 with prototype/src/mocks/logik-intake-admin.ts).
VALIDATION_RULES: list[dict] = [
    # Document Rules
    {"scope": "doc", "rule": "Document recency",
     "description": "Document must be dated within N days of loan application",
     "applies_to": "All Income Docs",
     "condition": "Max age: 60 days",
     "preset_id": None, "severity": "hard"},
    {"scope": "doc", "rule": "Minimum image resolution",
     "description": "Must meet DPI threshold for OCR legibility",
     "applies_to": "All Documents",
     "condition": "Min: 150 DPI",
     "preset_id": None, "severity": "hard"},
    {"scope": "doc", "rule": "Borrower name match",
     "description": "Name on document must match loan application",
     "applies_to": "All Documents",
     "condition": "Fuzzy match ≥ 90%",
     "preset_id": None, "severity": "hard"},
    {"scope": "doc", "rule": "Required signature present",
     "description": "Signature must be detected where required",
     "applies_to": "Purchase Agmt, VOE",
     "condition": "Signature: required",
     "preset_id": "missing_signatures", "severity": "hard"},
    {"scope": "doc", "rule": "Duplicate document check",
     "description": "Same document type and period already in file",
     "applies_to": "All Documents",
     "condition": "Exact match → flag",
     "preset_id": None, "severity": "soft"},
    {"scope": "doc", "rule": "Missing required document",
     "description": "Program checklist has required doc not uploaded",
     "applies_to": "Program Checklist",
     "condition": "All required present",
     "preset_id": None, "severity": "hard"},
    {"scope": "doc", "rule": "Document integrity — alteration",
     "description": "Metadata or pixel anomaly signals tampering",
     "applies_to": "All Documents",
     "condition": "Flag if detected",
     "preset_id": None, "severity": "hard"},
    {"scope": "doc", "rule": "Government ID expiry check",
     "description": "ID must not be expired at application date",
     "applies_to": "Government ID",
     "condition": "Expiry ≥ app date",
     "preset_id": None, "severity": "hard"},
    # Data Validation Rules
    {"scope": "data", "rule": "W-2 vs. Pay Stub income",
     "description": "Annualized Pay Stub YTD vs. W-2 Box 1 within tolerance",
     "applies_to": "W-2, Pay Stub",
     "condition": "Variance ≤ 5%",
     "preset_id": None, "severity": "hard"},
    {"scope": "data", "rule": "Employer name consistency",
     "description": "Name must match across W-2, Pay Stub, and VOE",
     "applies_to": "W-2, Pay Stub, VOE",
     "condition": "Fuzzy match ≥ 85%",
     "preset_id": None, "severity": "hard"},
    {"scope": "data", "rule": "Borrower SSN consistency",
     "description": "Last 4 of SSN consistent across income documents",
     "applies_to": "W-2, 1040, Credit",
     "condition": "Exact match",
     "preset_id": None, "severity": "hard"},
    {"scope": "data", "rule": "Bank deposits vs. income",
     "description": "Avg monthly deposits consistent with gross income",
     "applies_to": "Bank Stmt, W-2",
     "condition": "Variance ≤ 20%",
     "preset_id": None, "severity": "soft"},
    {"scope": "data", "rule": "Address consistency",
     "description": "Address on ID and bank statement match application",
     "applies_to": "ID, Bank Statement",
     "condition": "Fuzzy match ≥ 80%",
     "preset_id": None, "severity": "soft"},
    {"scope": "data", "rule": "1040 AGI vs. W-2 wages",
     "description": "1040 AGI consistent with W-2 reported wages",
     "applies_to": "1040, W-2",
     "condition": "Variance ≤ 10%",
     "preset_id": None, "severity": "hard"},
]


# ── 4. Program profiles ───────────────────────────────────────────
# Checklist entry shape: {"doc_type_key": str, "required": bool,
#                         "expected_min_pages": int|None,
#                         "expected_max_pages": int|None,
#                         "note": str|None}
#
# Backend's stacks_with is *investor_overlay → loan_program* (FK on
# overlay points at base program). The prototype renders the inverse
# (loan_program "stacks with" overlay), so we map by reversing the
# pointer where applicable.
CONV30_CHECKLIST: list[dict] = [
    {"doc_type_key": "w2", "required": True, "note": "2 years"},
    {"doc_type_key": "f1040", "required": True, "note": "2 years"},
    {"doc_type_key": "paystub", "required": True, "note": "Most recent 30 days"},
    {"doc_type_key": "bank_stmt", "required": True, "note": "2 months"},
    {"doc_type_key": "gov_id", "required": True, "note": None},
    {"doc_type_key": "purchase_agmt", "required": True, "note": None},
    {"doc_type_key": "appraisal", "required": True, "note": None},
    {"doc_type_key": "hoi", "required": True, "note": None},
    {"doc_type_key": "title_commit", "required": True, "note": None},
    {"doc_type_key": "credit_report", "required": True, "note": None},
    {"doc_type_key": "voe", "required": False, "note": "When not using DU findings"},
    {"doc_type_key": "gift_letter", "required": False, "note": "When gift funds used"},
    {"doc_type_key": "flood_cert", "required": False, "note": "When property in flood zone"},
]


# (key, name, type, active, stacks_with_name, checklist_slice_length,
#  extraction_overrides, rule_overrides)
# `stacks_with_name` is the name of another seeded profile this row's
# FK should point to. Only investor_overlay rows resolve it (loan
# programs leave stacks_with NULL per the backend model contract).
PROGRAM_PROFILES: list[dict] = [
    {
        "key": "conv30",
        "name": "Conventional 30yr",
        "type": "loan_program",
        "active": True,
        "stacks_with_name": None,
        "checklist": CONV30_CHECKLIST,
        "extraction_overrides": {
            "w2": {"box12_code_amount": {"required": True, "min_confidence": 0.88}},
            "bank_stmt": {"account_number_last4": {"min_confidence": 0.90}},
            "appraisal": {"appraised_value": {"required": True, "min_confidence": 0.95}},
        },
        "rule_overrides": [
            {"scope": "data", "rule": "Bank deposits vs. income",
             "condition": "Tightened for Conventional: variance ≤ 15% (was 20%).",
             "preset_id": None, "severity": "hard"},
        ],
    },
    {
        "key": "fha",
        "name": "FHA Purchase",
        "type": "loan_program",
        "active": True,
        "stacks_with_name": None,
        "checklist": CONV30_CHECKLIST[:11],
        "extraction_overrides": {
            "gov_id": {
                "expiration_date": {"required": True, "min_confidence": 0.97},
                "id_number_last4": {"min_confidence": 0.95},
            },
            "credit_report": {
                "equifax_score": {"min_confidence": 0.97},
                "experian_score": {"min_confidence": 0.97},
                "transunion_score": {"min_confidence": 0.97},
            },
            "appraisal": {
                "appraised_value": {"required": True, "min_confidence": 0.97},
            },
        },
        "rule_overrides": [
            {"scope": "doc", "rule": "Government ID expiry check",
             "condition": "FHA: ID expiration date must be ≥ 90 days past application date.",
             "preset_id": None, "severity": "hard"},
        ],
    },
    {
        "key": "va30",
        "name": "VA 30yr",
        "type": "loan_program",
        "active": True,
        "stacks_with_name": None,
        "checklist": CONV30_CHECKLIST,
        "extraction_overrides": {
            "dd214": {
                "branch_of_service": {"required": True, "min_confidence": 0.92},
                "character_of_service": {"required": True, "min_confidence": 0.90},
                "separation_date": {"required": True, "min_confidence": 0.92},
            },
            "credit_report": {
                "equifax_score": {"min_confidence": 0.95},
            },
        },
        "rule_overrides": [
            {"scope": "doc", "rule": "DD-214 character of service",
             "condition": "VA: Service member must provide DD-214 showing honorable or general (under honorable) discharge.",
             "preset_id": None, "severity": "hard"},
        ],
    },
    {
        "key": "usda",
        "name": "USDA Rural Development",
        "type": "loan_program",
        "active": True,
        "stacks_with_name": None,
        "checklist": CONV30_CHECKLIST[:10],
        "extraction_overrides": {
            "appraisal": {
                "subject_property_address": {"required": True, "min_confidence": 0.92},
                "appraised_value": {"required": True, "min_confidence": 0.95},
            },
            "flood_cert": {
                "flood_zone": {"required": True, "min_confidence": 0.97},
                "in_special_flood_hazard_area": {"required": True, "min_confidence": 0.97},
            },
        },
        "rule_overrides": [
            {"scope": "doc", "rule": "USDA rural eligibility",
             "condition": "Subject property must be in a USDA-designated rural area per the USDA eligibility map.",
             "preset_id": None, "severity": "hard"},
        ],
    },
    {
        "key": "portfolio",
        "name": "Portfolio — Internal",
        "type": "loan_program",
        "active": False,
        "stacks_with_name": None,
        "checklist": CONV30_CHECKLIST[:9],
        "extraction_overrides": {
            "purchase_agmt": {
                "purchase_price": {"min_confidence": 0.96},
            },
        },
        "rule_overrides": [
            {"scope": "data", "rule": "Portfolio compensating factors",
             "condition": "Portfolio: DTI > 43% allowed when 6+ months reserves verified.",
             "preset_id": None, "severity": "soft"},
        ],
    },
    # Investor overlays — stacks_with resolves to the matching loan program.
    {
        "key": "fnma_du",
        "name": "Fannie Mae DU",
        "type": "investor_overlay",
        "active": True,
        "stacks_with_name": "Conventional 30yr",
        "checklist": CONV30_CHECKLIST[:8],
        "extraction_overrides": {
            "f1040": {
                "adjusted_gross_income": {"required": True, "min_confidence": 0.92},
                "total_income": {"required": True, "min_confidence": 0.92},
            },
            "w2": {
                "box1_wages_tips": {"required": True, "min_confidence": 0.92},
            },
        },
        "rule_overrides": [
            {"scope": "data", "rule": "DU findings alignment",
             "condition": "FNMA DU: Extracted income must reconcile with the DU findings income figure.",
             "preset_id": None, "severity": "hard"},
        ],
    },
    {
        "key": "fhlmc_lpa",
        "name": "Freddie Mac LPA",
        "type": "investor_overlay",
        "active": True,
        "stacks_with_name": "Conventional 30yr",
        "checklist": CONV30_CHECKLIST[:7],
        "extraction_overrides": {
            "bank_stmt": {
                "ending_balance": {"required": True, "min_confidence": 0.92},
                "average_daily_balance": {"required": True, "min_confidence": 0.85},
            },
            "f1040": {
                "adjusted_gross_income": {"required": True, "min_confidence": 0.92},
            },
        },
        "rule_overrides": [
            {"scope": "data", "rule": "LPA reserves verification",
             "condition": "Freddie LPA: 2+ months PITI reserves required for primary residence purchase.",
             "preset_id": None, "severity": "hard"},
        ],
    },
    {
        "key": "gnma_i",
        "name": "Ginnie Mae I",
        "type": "investor_overlay",
        "active": True,
        "stacks_with_name": "FHA Purchase",
        "checklist": CONV30_CHECKLIST[:6],
        "extraction_overrides": {
            "title_commit": {
                "file_number": {"min_confidence": 0.97},
                "property_address": {"required": True, "min_confidence": 0.92},
            },
            "flood_cert": {
                "certificate_number": {"min_confidence": 0.97},
            },
        },
        "rule_overrides": [
            {"scope": "doc", "rule": "GNMA-eligible servicing",
             "condition": "Ginnie Mae I: Loan must meet FHA/VA servicing requirements; servicing transfer prohibited within 90 days of pooling.",
             "preset_id": None, "severity": "hard"},
        ],
    },
]


# ── 5. Global settings defaults ───────────────────────────────────
# Backs the 8-tab Global Settings admin surface (Phase 5.3). Values
# mirror the prototype's hardcoded display strings so the first GET
# matches the prototype UI exactly. Used by ``scripts/seed.py`` and
# by the admin route's "auto-create on first GET" path.

def build_default_global_settings(
    tenant_slug: str = "society-title",
    organization_name: str = "LogikCore",
) -> dict:
    """Return the JSONB payload for the 8 columns on ``lo_global_settings``.

    Mirrors prototype/src/app/logik-intake/admin/global-settings/page.tsx
    1:1 — section titles, labels, descriptions, defaults, options, and
    ordering are copied verbatim from the prototype so the operator
    (and AI prompts that surface these settings) sees the exact same
    explanation text. Pure function — no side effects."""
    return {
        # ── AI Thresholds ────────────────────────────────────────────
        "ai_thresholds": {
            "sections": [
                {
                    "title": "Auto-Classification Thresholds",
                    "settings": [
                        {
                            "key": "auto_classify_threshold",
                            "label": "Auto-Classify Threshold",
                            "description": "Documents at or above this confidence are classified automatically without human review",
                            "type": "percent",
                            "value": 85,
                        },
                        {
                            "key": "review_band_lower_bound",
                            "label": "Review Band Lower Bound",
                            "description": "Documents between this and the auto-classify threshold are routed to operator review",
                            "type": "percent",
                            "value": 60,
                        },
                        {
                            "key": "below_review_band",
                            "label": "Below Review Band",
                            "description": "Documents below this threshold are flagged for manual entry — AI result not trusted",
                            "type": "percent",
                            "value": 60,
                            "suffix": "% (fixed = Review Band lower bound)",
                        },
                    ],
                },
            ],
        },
        # ── STP Targets ─────────────────────────────────────────────
        "stp_targets": {
            "title": "STP Targets",
            "settings": [
                {
                    "key": "day1_stp_target",
                    "label": "Day 1 STP Target",
                    "description": "% of files that should complete all stages automatically without human intervention on Day 1",
                    "type": "percent",
                    "value": 80,
                },
                {
                    "key": "day60_stp_target",
                    "label": "60-Day STP Target",
                    "description": "% of files that should reach Decision-Ready within 60 days",
                    "type": "percent",
                    "value": 90,
                },
            ],
        },
        # ── Exception Defaults ──────────────────────────────────────
        "exception_defaults": {
            "title": "Hard Stop & Advisory Flag Defaults",
            "settings": [
                {
                    "key": "eod_advisory_flag_behavior",
                    "label": "End-of-Day Advisory Flag Behavior",
                    "description": "What happens to files with unacknowledged Advisory Flags at day end",
                    "type": "select",
                    "options": [
                        "Hold — operator must acknowledge before advancing",
                        "Auto-advance — log and continue",
                    ],
                    "value": "Hold — operator must acknowledge before advancing",
                },
                {
                    "key": "hard_stop_escalation_hours",
                    "label": "Hard Stop Escalation Time",
                    "description": "If a Hard Stop is unresolved beyond this threshold, escalate to supervisor",
                    "type": "hours",
                    "value": 4,
                },
                {
                    "key": "override_note_required",
                    "label": "Override Note Requirement",
                    "description": "Require operators to provide written justification when overriding a Hard Stop",
                    "type": "toggle",
                    "value": True,
                },
            ],
        },
        # ── Audit & Compliance ──────────────────────────────────────
        "audit": {
            "title": "Audit Log Configuration",
            "settings": [
                {
                    "key": "retention_period",
                    "label": "Audit Log Retention Period",
                    "description": "Minimum 7 years for RESPA/QC compliance",
                    "type": "select",
                    "options": ["7 years", "10 years", "Indefinite"],
                    "value": "7 years",
                },
                {
                    "key": "events_logged",
                    "label": "Events Logged",
                    "description": "All classification decisions, extraction confirmations, overrides, and user actions are logged immutably.",
                    "type": "readonly_badge",
                    "value": "All events — cannot disable",
                },
            ],
        },
        # ── User Roles (display-only) ───────────────────────────────
        "roles": {
            "title": "Role Definitions",
            "items": [
                {
                    "role": "Operator",
                    "description": "Can review classification, extraction, and acknowledge Advisory Flags. Cannot override Hard Stops.",
                    "permissions": "Read · Confirm · Acknowledge",
                },
                {
                    "role": "Supervisor / QC Lead",
                    "description": "All Operator permissions plus Hard Stop override with written justification.",
                    "permissions": "Read · Confirm · Override · Advance",
                },
                {
                    "role": "Admin",
                    "description": "Full configuration access. Can modify document types, schemas, rules, profiles, and global settings.",
                    "permissions": "Full configuration access",
                },
                {
                    "role": "Read-Only",
                    "description": "View-only access to file status and reports. No action permissions.",
                    "permissions": "Read only",
                },
            ],
        },
        # ── Notifications ───────────────────────────────────────────
        "notifications": {
            "title": "Notification Rules",
            "items": [
                {
                    "event": "File stuck in stage",
                    "threshold": "4 hours",
                    "channel": "Email + In-app",
                },
                {
                    "event": "Hard Stop unresolved",
                    "threshold": "4 hours",
                    "channel": "Email + In-app",
                },
                {
                    "event": "STP rate below target",
                    "threshold": "< 70%",
                    "channel": "Email",
                },
                {
                    "event": "Classification failure",
                    "threshold": "3 attempts",
                    "channel": "In-app",
                },
            ],
        },
        # ── Integrations ────────────────────────────────────────────
        "integrations": {
            "title": "Connected Systems",
            "items": [
                {
                    "system": "LOS Connection",
                    "description": "Encompass / Byte / OpenClose — bi-directional file sync",
                    "status": "Connected",
                    "status_color": "emerald",
                },
                {
                    "system": "Document Storage",
                    "description": "Azure Blob Storage — encrypted document repository",
                    "status": "Connected",
                    "status_color": "emerald",
                },
                {
                    "system": "Webhook Endpoint",
                    "description": "Push validation results to downstream systems",
                    "status": "Not configured",
                    "status_color": "muted",
                },
                {
                    "system": "API Access",
                    "description": "REST API for LOS plugins and third-party integrations",
                    "status": "Enabled",
                    "status_color": "teal",
                },
            ],
        },
        # ── Tenant Settings ─────────────────────────────────────────
        "tenant": {
            "title": "Tenant Configuration",
            "tenant_slug": tenant_slug,
            "settings": [
                {
                    "key": "organization_name",
                    "label": "Organization Name",
                    "type": "text",
                    "value": organization_name,
                },
                {
                    "key": "timezone",
                    "label": "Timezone",
                    "type": "select",
                    "options": [
                        "US/Eastern (EST/EDT)",
                        "US/Central",
                        "US/Pacific",
                    ],
                    "value": "US/Eastern (EST/EDT)",
                },
                {
                    "key": "date_format",
                    "label": "Date Format",
                    "type": "select",
                    "options": ["MM/DD/YYYY", "YYYY-MM-DD"],
                    "value": "MM/DD/YYYY",
                },
            ],
        },
    }
