import type { LoanDocTypeSpec } from "./types";

export const LOAN_STATUS_COLORS: Record<string, string> = {
  pending: "bg-stone-100 text-stone-600 ring-1 ring-stone-200",
  uploading: "bg-stone-100 text-stone-600 ring-1 ring-stone-200",
  processing: "bg-blue-50 text-blue-700 ring-1 ring-blue-200",
  awaiting_review: "bg-orange-50 text-orange-700 ring-1 ring-orange-200",
  completed: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200",
  failed: "bg-red-50 text-red-700 ring-1 ring-red-200",
};

export const LOAN_STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  uploading: "Uploading",
  processing: "Processing",
  awaiting_review: "Review Required",
  completed: "Completed",
  failed: "Failed",
};

export const LOAN_STAGE_LABELS: Record<string, string> = {
  ingest: "Ingest",
  classify: "Classify",
  stack: "Stack",
  validate: "Validate",
  review: "Review",
};

// Reserved bucket for pages that don't match any configured doc type.
// Mirrors backend `OTHERS_KEY = "Others"` in
// app/micro_apps/loan_onboarding/ai/page_classifier_agent.py.
export const OTHERS_DOC_TYPE_KEY = "Others";

/**
 * Canonical document-type catalog — the full 63-item superset covering a U.S.
 * residential mortgage loan package. Flat list (no categories) so the UI can
 * render it as a paginated checklist and default-select every type.
 *
 * Keys are stable (UPPER_SNAKE_CASE) and sent to the classifier as the
 * doc_type enum for each package. Default-required types cover the backbone
 * of a typical purchase package (URLA, paystubs, W-2, bank statements, credit
 * report). Everything else defaults to optional and can be toggled on per
 * order.
 */
export const SUGGESTED_DOC_TYPES: LoanDocTypeSpec[] = [
  // ── Borrower financial ─────────────────────────────────────────────────
  {
    key: "URLA_1003",
    label: "URLA (1003)",
    description: "Uniform Residential Loan Application",
    required: true,
  },
  {
    key: "PAYSTUB",
    label: "Paystub",
    description: "Recent pay statements (30 days)",
    required: true,
  },
  {
    key: "W2",
    label: "W-2",
    description: "Wage and Tax Statement",
    required: true,
  },
  {
    key: "TAX_RETURN_1040",
    label: "Tax Return (1040)",
    description: "IRS Individual Tax Return",
    required: false,
  },
  {
    key: "BANK_STATEMENT",
    label: "Bank Statement",
    description: "Checking / savings statements (last 2 months)",
    required: true,
  },
  {
    key: "CREDIT_REPORT",
    label: "Credit Report",
    description: "Tri-merge credit report",
    required: true,
  },

  // ── Property & transaction ─────────────────────────────────────────────
  {
    key: "APPRAISAL",
    label: "Appraisal",
    description: "Form 1004 — Uniform Residential Appraisal Report",
    required: false,
  },
  {
    key: "PURCHASE_CONTRACT",
    label: "Purchase Contract",
    description: "Executed sales contract",
    required: false,
  },
  {
    key: "HOMEOWNERS_INS",
    label: "Homeowners Insurance",
    description: "Insurance declaration page",
    required: false,
  },

  // ── Title insurance ────────────────────────────────────────────────────
  {
    key: "TITLE_COMMITMENT",
    label: "Title Commitment",
    description: "Title insurance commitment",
    required: false,
  },
  {
    key: "TITLE_POLICY",
    label: "Title Policy",
    description: "Final title insurance policy",
    required: false,
  },

  // ── Recorded deeds ─────────────────────────────────────────────────────
  {
    key: "WARRANTY_DEED",
    label: "Warranty Deed",
    description: "Warranty deed conveying title",
    required: false,
  },
  {
    key: "QUITCLAIM_DEED",
    label: "Quitclaim Deed",
    description: "Quitclaim deed",
    required: false,
  },
  {
    key: "DEED_OTHER",
    label: "Deed (Other)",
    description: "Bargain & sale, trustee, special warranty, etc.",
    required: false,
  },
  {
    key: "ASSIGNMENT_OF_MORTGAGE",
    label: "Assignment of Mortgage",
    description: "Mortgage assignment to new holder",
    required: false,
  },

  // ── Other recorded instruments ─────────────────────────────────────────
  {
    key: "MORTGAGE_DEED_OF_TRUST",
    label: "Mortgage / Deed of Trust",
    description: "Recorded lien instrument",
    required: false,
  },
  {
    key: "SATISFACTION_RELEASE",
    label: "Satisfaction / Release",
    description: "Lien satisfaction or release",
    required: false,
  },
  {
    key: "SUBORDINATION_AGREEMENT",
    label: "Subordination Agreement",
    description: "Lien subordination",
    required: false,
  },
  {
    key: "LIEN_JUDGMENT",
    label: "Lien / Judgment",
    description: "Mechanic's lien, tax lien, judgment",
    required: false,
  },
  {
    key: "EASEMENT_ENCROACHMENT",
    label: "Easement / Encroachment",
    description: "Easement or encroachment filing",
    required: false,
  },
  {
    key: "POWER_OF_ATTORNEY",
    label: "Power of Attorney",
    description: "Signing authority document",
    required: false,
  },

  // ── Property records ───────────────────────────────────────────────────
  {
    key: "TAX_CERTIFICATE",
    label: "Tax Certificate / Tax Statement",
    description: "County tax certificate",
    required: false,
  },
  {
    key: "TAX_BILL",
    label: "Tax Bill",
    description: "Property tax bill",
    required: false,
  },
  {
    key: "SURVEY_PLAT",
    label: "Survey / Plat",
    description: "Survey or plat map",
    required: false,
  },
  {
    key: "CCR_HOA",
    label: "CC&Rs / HOA",
    description: "Covenants, conditions & restrictions, HOA docs",
    required: false,
  },

  // ── Closing documents ──────────────────────────────────────────────────
  {
    key: "LOAN_ESTIMATE",
    label: "Loan Estimate (LE)",
    description: "TRID initial disclosure",
    required: false,
  },
  {
    key: "CLOSING_DISCLOSURE",
    label: "Closing Disclosure (CD)",
    description: "TRID final disclosure",
    required: false,
  },
  {
    key: "HUD1_SETTLEMENT",
    label: "HUD-1 / Settlement Statement",
    description: "Settlement statement",
    required: false,
  },
  {
    key: "PROMISSORY_NOTE",
    label: "Promissory Note",
    description: "Borrower's note",
    required: false,
  },
  {
    key: "FIRST_PAYMENT_LETTER",
    label: "First Payment Letter",
    description: "First payment notice",
    required: false,
  },

  // ── Loan disclosures ───────────────────────────────────────────────────
  {
    key: "INITIAL_RESPA_DISCLOSURES",
    label: "Initial / RESPA Disclosures",
    description: "RESPA initial disclosures",
    required: false,
  },
  {
    key: "MI_PMI_DISCLOSURE",
    label: "MI / PMI Disclosure",
    description: "Mortgage insurance disclosure",
    required: false,
  },
  {
    key: "FLOOD_CERTIFICATION",
    label: "Flood Certification",
    description: "Flood zone determination",
    required: false,
  },
  {
    key: "RIGHT_OF_RESCISSION_TIL",
    label: "Right of Rescission / TIL",
    description: "Truth in Lending, right of rescission",
    required: false,
  },
  {
    key: "ANTI_COERCION",
    label: "Anti-Coercion / Insurance Choice",
    description: "Insurance choice disclosure",
    required: false,
  },
  {
    key: "HAZARD_INSURANCE_NOTIF",
    label: "Hazard Insurance Notification",
    description: "Hazard insurance notice",
    required: false,
  },
  {
    key: "HOMEOWNER_COUNSELING",
    label: "Homeowner Counseling",
    description: "Counseling disclosure",
    required: false,
  },
  {
    key: "ADVERSE_ACTION",
    label: "Adverse Action",
    description: "Adverse action notice",
    required: false,
  },
  {
    key: "SERVICING_TRANSFER_NOTICE",
    label: "Servicing Transfer Notice",
    description: "Notice of servicing transfer",
    required: false,
  },

  // ── Verifications & tax auth ───────────────────────────────────────────
  {
    key: "VOE",
    label: "Verification of Employment (VOE)",
    description: "VOE form",
    required: false,
  },
  {
    key: "VOD",
    label: "Verification of Deposit (VOD)",
    description: "VOD form",
    required: false,
  },
  {
    key: "FORM_4506T",
    label: "4506-T / Tax Transcript Request",
    description: "IRS 4506-T authorization",
    required: false,
  },
  {
    key: "FORM_1099",
    label: "1099",
    description: "Miscellaneous income statement",
    required: false,
  },

  // ── Identity & compliance ──────────────────────────────────────────────
  {
    key: "ID_DOCUMENT",
    label: "ID Document",
    description: "Government-issued ID",
    required: false,
  },
  {
    key: "PATRIOT_CIP",
    label: "Patriot Act / CIP",
    description: "Customer identification program",
    required: false,
  },
  {
    key: "PRIVACY_POLICY",
    label: "Privacy Policy",
    description: "Privacy policy disclosure",
    required: false,
  },
  {
    key: "FRAUD_NOTICE",
    label: "Fraud / Misrepresentation Notice",
    description: "Fraud notice",
    required: false,
  },

  // ── Affidavits ─────────────────────────────────────────────────────────
  {
    key: "AFFIDAVIT_GENERIC",
    label: "Affidavit (generic)",
    description: "Generic affidavit",
    required: false,
  },
  {
    key: "NAME_AFFIDAVIT_AKA",
    label: "Name Affidavit / AKA",
    description: "Name / AKA affidavit",
    required: false,
  },
  {
    key: "NOTARY_ACKNOWLEDGMENT",
    label: "Notary Acknowledgment / Jurat",
    description: "Notary acknowledgment page",
    required: false,
  },

  // ── Closing instructions & escrow ──────────────────────────────────────
  {
    key: "WIRE_INSTRUCTIONS",
    label: "Wire Instructions / Funding Authorization",
    description: "Funding wire instructions",
    required: false,
  },
  {
    key: "ESCROW_WAIVER_AGREEMENT",
    label: "Escrow Waiver / Agreement",
    description: "Escrow account waiver or agreement",
    required: false,
  },
  {
    key: "EO_COMPLIANCE",
    label: "Errors & Omissions / Compliance Agreement",
    description: "E&O / compliance agreement",
    required: false,
  },

  // ── Property-type riders ───────────────────────────────────────────────
  {
    key: "CONDO_PUD_CERT",
    label: "Condo / PUD Certification",
    description: "Condominium or PUD certification",
    required: false,
  },
  {
    key: "FHA_VA_SPECIFIC",
    label: "FHA / VA Specific",
    description: "FHA / VA program-specific attachments",
    required: false,
  },

  // ── Misc / catch-all ───────────────────────────────────────────────────
  {
    key: "GIFT_LETTER",
    label: "Gift Letter",
    description: "Gift funds letter",
    required: false,
  },
  {
    key: "UNDERWRITING_AUS",
    label: "Underwriting / AUS Findings",
    description: "DU / LP findings",
    required: false,
  },
  {
    key: "INSURANCE_BINDER",
    label: "Insurance Binder",
    description: "Temporary insurance binder",
    required: false,
  },
  {
    key: "LEGAL_DESCRIPTION_EXHIBIT_A",
    label: "Legal Description / Exhibit A",
    description: "Legal description exhibit",
    required: false,
  },
  {
    key: "RECORDING_COVER_SHEET",
    label: "Recording Cover Sheet",
    description: "County recording cover sheet",
    required: false,
  },
  {
    key: "COVER_LETTER_TRANSMITTAL",
    label: "Cover Letter / Transmittal",
    description: "Cover letter or transmittal",
    required: false,
  },
  {
    key: "ESIGN_ECONSENT",
    label: "eSign / eConsent",
    description: "Electronic signature consent",
    required: false,
  },
  {
    key: "BORROWER_CERT_AUTHORIZATION",
    label: "Borrower Certification / Authorization",
    description: "Borrower certification and authorization",
    required: false,
  },
];

/**
 * Reserved catch-all bucket for pages that do not match any configured type.
 * Always selected, always required, and stripped from the API payload (the
 * backend implicitly reserves "Others" on every package).
 */
export const OTHERS_CATCH_ALL_SPEC: LoanDocTypeSpec = {
  key: OTHERS_DOC_TYPE_KEY,
  label: "Others (catch-all)",
  required: true,
  locked: true,
};

export const LOAN_DOC_TYPE_LABELS: Record<string, string> = Object.fromEntries(
  [...SUGGESTED_DOC_TYPES, OTHERS_CATCH_ALL_SPEC].map((d) => [d.key, d.label])
);

/**
 * Total number of selectable doc types (excludes the locked Others bucket)
 * — surfaced in the UI as "X / N selected".
 */
export const TOTAL_DOC_TYPE_COUNT: number = SUGGESTED_DOC_TYPES.length;

export const DEFAULT_HITL_THRESHOLD = 0.96;

/**
 * Suggested required-field names per doc type — used by the Missing Fields
 * editor to show clickable chips that pre-populate common fields. The names
 * mirror what the page classifier surfaces in `detected_fields`, so a hint
 * picked here will actually match against extracted page content.
 *
 * Keep each list to ~4-6 high-signal fields. Doc types without an explicit
 * entry fall back to `GENERIC_FIELD_HINTS` (signature + date + party name),
 * which are nearly universal across mortgage paperwork.
 */
export const FIELD_HINTS_BY_DOC_TYPE: Record<string, string[]> = {
  URLA_1003: [
    "borrower_name",
    "co_borrower_name",
    "ssn",
    "property_address",
    "loan_amount",
    "employer_name",
    "monthly_income",
    "signature_date",
  ],
  PAYSTUB: [
    "employee_name",
    "employer_name",
    "pay_period",
    "gross_pay",
    "net_pay",
    "ytd_gross",
    "pay_date",
  ],
  W2: [
    "employee_name",
    "employer_name",
    "employer_ein",
    "ssn",
    "wages",
    "federal_tax_withheld",
    "tax_year",
  ],
  TAX_RETURN_1040: [
    "filer_name",
    "ssn",
    "filing_status",
    "agi",
    "total_tax",
    "tax_year",
    "signature",
  ],
  BANK_STATEMENT: [
    "account_holder",
    "account_number",
    "statement_period",
    "beginning_balance",
    "ending_balance",
  ],
  CREDIT_REPORT: [
    "borrower_name",
    "ssn",
    "fico_score",
    "report_date",
    "tradelines",
  ],
  APPRAISAL: [
    "property_address",
    "appraised_value",
    "appraiser_name",
    "appraisal_date",
    "effective_date",
    "sales_price",
  ],
  PURCHASE_CONTRACT: [
    "buyer_name",
    "seller_name",
    "property_address",
    "purchase_price",
    "closing_date",
    "earnest_money",
    "signatures",
  ],
  HOMEOWNERS_INS: [
    "insured_name",
    "property_address",
    "policy_number",
    "coverage_amount",
    "effective_date",
    "expiration_date",
  ],
  TITLE_COMMITMENT: [
    "insured_name",
    "property_address",
    "policy_amount",
    "effective_date",
    "schedule_b_exceptions",
  ],
  TITLE_POLICY: [
    "insured_name",
    "property_address",
    "policy_amount",
    "policy_date",
    "policy_number",
  ],
  WARRANTY_DEED: [
    "grantor",
    "grantee",
    "property_legal_description",
    "recording_date",
    "signatures",
    "notary_acknowledgment",
  ],
  QUITCLAIM_DEED: [
    "grantor",
    "grantee",
    "property_legal_description",
    "recording_date",
    "signatures",
  ],
  DEED_OTHER: [
    "grantor",
    "grantee",
    "property_legal_description",
    "recording_date",
    "signatures",
  ],
  ASSIGNMENT_OF_MORTGAGE: [
    "assignor",
    "assignee",
    "original_mortgagor",
    "recording_date",
    "signatures",
  ],
  MORTGAGE_DEED_OF_TRUST: [
    "borrower",
    "lender",
    "property_legal_description",
    "loan_amount",
    "recording_date",
    "signatures",
  ],
  SATISFACTION_RELEASE: [
    "lender",
    "borrower",
    "original_mortgage_recording_info",
    "satisfaction_date",
    "signatures",
  ],
  SUBORDINATION_AGREEMENT: [
    "subordinating_lender",
    "senior_lender",
    "property_address",
    "signatures",
  ],
  LIEN_JUDGMENT: [
    "claimant",
    "debtor",
    "amount",
    "recording_date",
    "property_description",
  ],
  POWER_OF_ATTORNEY: [
    "principal_name",
    "agent_name",
    "signing_authority_scope",
    "effective_date",
    "notary_acknowledgment",
  ],
  TAX_CERTIFICATE: [
    "parcel_number",
    "owner_name",
    "tax_year",
    "amount_due",
    "certificate_date",
  ],
  TAX_BILL: ["parcel_number", "owner_name", "tax_year", "amount_due", "due_date"],
  SURVEY_PLAT: [
    "surveyor_name",
    "property_legal_description",
    "survey_date",
    "plat_reference",
  ],
  LOAN_ESTIMATE: [
    "borrower_name",
    "loan_amount",
    "interest_rate",
    "monthly_payment",
    "closing_costs",
    "issue_date",
  ],
  CLOSING_DISCLOSURE: [
    "borrower_name",
    "loan_amount",
    "interest_rate",
    "monthly_payment",
    "closing_costs",
    "closing_date",
    "signatures",
  ],
  HUD1_SETTLEMENT: [
    "borrower_name",
    "seller_name",
    "property_address",
    "settlement_date",
    "total_settlement_charges",
  ],
  PROMISSORY_NOTE: [
    "borrower_name",
    "lender_name",
    "loan_amount",
    "interest_rate",
    "maturity_date",
    "signature",
  ],
  FIRST_PAYMENT_LETTER: [
    "borrower_name",
    "loan_number",
    "first_payment_due_date",
    "payment_amount",
  ],
  FLOOD_CERTIFICATION: [
    "property_address",
    "flood_zone",
    "certification_date",
    "determination_authority",
  ],
  RIGHT_OF_RESCISSION_TIL: [
    "borrower_name",
    "transaction_date",
    "rescission_deadline",
    "signature",
  ],
  VOE: [
    "employee_name",
    "employer_name",
    "position",
    "start_date",
    "current_salary",
    "signature",
  ],
  VOD: [
    "account_holder",
    "bank_name",
    "account_number",
    "current_balance",
    "average_balance",
    "signature",
  ],
  FORM_4506T: ["taxpayer_name", "ssn", "tax_year", "signature", "signature_date"],
  FORM_1099: [
    "recipient_name",
    "payer_name",
    "recipient_tin",
    "total_payments",
    "tax_year",
  ],
  ID_DOCUMENT: [
    "full_name",
    "date_of_birth",
    "id_number",
    "expiration_date",
  ],
  NAME_AFFIDAVIT_AKA: [
    "affiant_name",
    "aka_names",
    "signature",
    "notary_acknowledgment",
  ],
  NOTARY_ACKNOWLEDGMENT: [
    "notary_name",
    "notary_commission_expiry",
    "county",
    "signature_date",
    "principal_name",
  ],
  WIRE_INSTRUCTIONS: [
    "bank_name",
    "routing_number",
    "account_number",
    "beneficiary_name",
    "wire_amount",
  ],
  GIFT_LETTER: [
    "donor_name",
    "recipient_name",
    "gift_amount",
    "relationship",
    "signature",
  ],
  UNDERWRITING_AUS: ["borrower_name", "loan_number", "decision", "run_date"],
  LEGAL_DESCRIPTION_EXHIBIT_A: ["property_legal_description", "parcel_id"],
};

/**
 * Fallback hints for any doc type without an explicit entry above. These
 * fields are universal across mortgage paperwork.
 */
export const GENERIC_FIELD_HINTS: string[] = [
  "borrower_name",
  "property_address",
  "signature",
  "signature_date",
];

/**
 * Returns a list of suggested required field names for the given doc type
 * key, falling back to generic hints when the doc type isn't in the catalog
 * (e.g., a user-added custom doc type or the reserved Others bucket).
 */
export function getFieldHintsForDocType(docKey: string): string[] {
  return FIELD_HINTS_BY_DOC_TYPE[docKey] ?? GENERIC_FIELD_HINTS;
}

/**
 * Default fields the system extracts per doc type — independent of the
 * Missing-Fields validation rule. These are human-readable labels that
 * surface verbatim in the downstream LOS export (JSON / CSV / MISMO XML),
 * and they map by doc-type *key* (matching `LoanDocTypeSpec.key`) so the
 * config survives label edits.
 *
 * Sourced from the prototype's `DEFAULT_EXTRACTION_FIELDS` (which uses
 * doc-type *labels* as keys). We re-key by our stable UPPER_SNAKE_CASE
 * keys so the data round-trips through the backend cleanly. The user can
 * add / remove fields per doc type in the new-package form before submit.
 */
export const DEFAULT_EXTRACTION_FIELDS_BY_DOC: Record<string, string[]> = {
  URLA_1003: [
    "Borrower Name",
    "Co-Borrower Name",
    "Loan Amount",
    "Property Address",
    "Loan Purpose",
    "Loan Term",
    "Interest Rate",
  ],
  PAYSTUB: [
    "Employee Name",
    "Employer Name",
    "Pay Period",
    "Gross Pay",
    "Net Pay",
    "YTD Earnings",
  ],
  W2: [
    "Employee Name",
    "Employer Name",
    "Wages",
    "Federal Tax Withheld",
    "Tax Year",
  ],
  TAX_RETURN_1040: [
    "Taxpayer Name",
    "Filing Status",
    "Adjusted Gross Income",
    "Total Tax",
    "Tax Year",
  ],
  BANK_STATEMENT: [
    "Account Holder",
    "Account Number",
    "Statement Period",
    "Beginning Balance",
    "Ending Balance",
  ],
  CREDIT_REPORT: ["Borrower Name", "Credit Score", "Report Date", "Bureau"],
  TITLE_COMMITMENT: [
    "Property Address",
    "Legal Description",
    "Title Holder",
    "Policy Amount",
    "Effective Date",
  ],
  HOMEOWNERS_INS: [
    "Insured Name",
    "Policy Number",
    "Coverage Amount",
    "Effective Date",
    "Premium",
  ],
  PURCHASE_CONTRACT: [
    "Buyer Name",
    "Seller Name",
    "Purchase Price",
    "Earnest Money",
    "Closing Date",
  ],
  CLOSING_DISCLOSURE: [
    "Borrower Name",
    "Loan Amount",
    "Closing Date",
    "Cash to Close",
    "APR",
  ],
  HUD1_SETTLEMENT: [
    "Borrower Name",
    "Loan Amount",
    "Closing Date",
    "Cash to Close",
    "APR",
  ],
  APPRAISAL: [
    "Property Address",
    "Appraised Value",
    "Appraiser Name",
    "Appraiser License",
    "Effective Date",
  ],
  VOE: [
    "Employee Name",
    "Employer Name",
    "Position",
    "Start Date",
    "Annual Salary",
  ],
};

/**
 * Build the initial extraction map for a fresh package — every selected
 * doc type that has a default field list seeds with those fields. Doc
 * types without defaults are left empty (the user can add fields manually).
 * Excludes the reserved Others bucket. The returned object is mutable.
 */
export function buildInitialExtractionFields(
  docTypes: LoanDocTypeSpec[]
): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const d of docTypes) {
    if (d.key === OTHERS_DOC_TYPE_KEY) continue;
    const seed = DEFAULT_EXTRACTION_FIELDS_BY_DOC[d.key];
    if (seed && seed.length > 0) {
      out[d.key] = [...seed];
    }
  }
  return out;
}
