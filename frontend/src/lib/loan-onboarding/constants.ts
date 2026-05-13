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
 * Keys are stable lower-snake-case and sent to the classifier as the
 * doc_type enum for each package. They mirror the canonical
 * `lo_doc_type_catalog` vocabulary (paystub, w2, urla_1003, …) so the per-loan
 * overlay merges cleanly with global catalog rows. Default-required types
 * cover the backbone
 * of a typical purchase package (URLA, paystubs, W-2, bank statements, credit
 * report). Everything else defaults to optional and can be toggled on per
 * order.
 */
export const SUGGESTED_DOC_TYPES: LoanDocTypeSpec[] = [
  // ── Borrower financial ─────────────────────────────────────────────────
  {
    key: "urla_1003",
    label: "URLA (1003)",
    description: "Uniform Residential Loan Application",
    required: true,
  },
  {
    key: "paystub",
    label: "Paystub",
    description: "Recent pay statements (30 days)",
    required: true,
  },
  {
    key: "w2",
    label: "W-2",
    description: "Wage and Tax Statement",
    required: true,
  },
  {
    key: "f1040",
    label: "Tax Return (1040)",
    description: "IRS Individual Tax Return",
    required: false,
  },
  {
    key: "bank_stmt",
    label: "Bank Statement",
    description: "Checking / savings statements (last 2 months)",
    required: true,
  },
  {
    key: "credit_report",
    label: "Credit Report",
    description: "Tri-merge credit report",
    required: true,
  },

  // ── Property & transaction ─────────────────────────────────────────────
  {
    key: "appraisal",
    label: "Appraisal",
    description: "Form 1004 — Uniform Residential Appraisal Report",
    required: false,
  },
  {
    key: "purchase_agmt",
    label: "Purchase Contract",
    description: "Executed sales contract",
    required: false,
  },
  {
    key: "hoi",
    label: "Homeowners Insurance",
    description: "Insurance declaration page",
    required: false,
  },

  // ── Title insurance ────────────────────────────────────────────────────
  {
    key: "title_commit",
    label: "Title Commitment",
    description: "Title insurance commitment",
    required: false,
  },
  {
    key: "title_policy",
    label: "Title Policy",
    description: "Final title insurance policy",
    required: false,
  },

  // ── Recorded deeds ─────────────────────────────────────────────────────
  {
    key: "warranty_deed",
    label: "Warranty Deed",
    description: "Warranty deed conveying title",
    required: false,
  },
  {
    key: "quitclaim_deed",
    label: "Quitclaim Deed",
    description: "Quitclaim deed",
    required: false,
  },
  {
    key: "deed_other",
    label: "Deed (Other)",
    description: "Bargain & sale, trustee, special warranty, etc.",
    required: false,
  },
  {
    key: "assignment_of_mortgage",
    label: "Assignment of Mortgage",
    description: "Mortgage assignment to new holder",
    required: false,
  },

  // ── Other recorded instruments ─────────────────────────────────────────
  {
    key: "mortgage_deed_of_trust",
    label: "Mortgage / Deed of Trust",
    description: "Recorded lien instrument",
    required: false,
  },
  {
    key: "satisfaction_release",
    label: "Satisfaction / Release",
    description: "Lien satisfaction or release",
    required: false,
  },
  {
    key: "subordination_agreement",
    label: "Subordination Agreement",
    description: "Lien subordination",
    required: false,
  },
  {
    key: "lien_judgment",
    label: "Lien / Judgment",
    description: "Mechanic's lien, tax lien, judgment",
    required: false,
  },
  {
    key: "easement_encroachment",
    label: "Easement / Encroachment",
    description: "Easement or encroachment filing",
    required: false,
  },
  {
    key: "power_of_attorney",
    label: "Power of Attorney",
    description: "Signing authority document",
    required: false,
  },

  // ── Property records ───────────────────────────────────────────────────
  {
    key: "tax_certificate",
    label: "Tax Certificate / Tax Statement",
    description: "County tax certificate",
    required: false,
  },
  {
    key: "tax_bill",
    label: "Tax Bill",
    description: "Property tax bill",
    required: false,
  },
  {
    key: "survey_plat",
    label: "Survey / Plat",
    description: "Survey or plat map",
    required: false,
  },
  {
    key: "ccr_hoa",
    label: "CC&Rs / HOA",
    description: "Covenants, conditions & restrictions, HOA docs",
    required: false,
  },

  // ── Closing documents ──────────────────────────────────────────────────
  {
    key: "loan_estimate",
    label: "Loan Estimate (LE)",
    description: "TRID initial disclosure",
    required: false,
  },
  {
    key: "closing_disclosure",
    label: "Closing Disclosure (CD)",
    description: "TRID final disclosure",
    required: false,
  },
  {
    key: "hud1_settlement",
    label: "HUD-1 / Settlement Statement",
    description: "Settlement statement",
    required: false,
  },
  {
    key: "promissory_note",
    label: "Promissory Note",
    description: "Borrower's note",
    required: false,
  },
  {
    key: "first_payment_letter",
    label: "First Payment Letter",
    description: "First payment notice",
    required: false,
  },

  // ── Loan disclosures ───────────────────────────────────────────────────
  {
    key: "initial_respa_disclosures",
    label: "Initial / RESPA Disclosures",
    description: "RESPA initial disclosures",
    required: false,
  },
  {
    key: "mi_certificate",
    label: "MI / PMI Disclosure",
    description: "Mortgage insurance disclosure",
    required: false,
  },
  {
    key: "flood_cert",
    label: "Flood Certification",
    description: "Flood zone determination",
    required: false,
  },
  {
    key: "right_of_rescission_til",
    label: "Right of Rescission / TIL",
    description: "Truth in Lending, right of rescission",
    required: false,
  },
  {
    key: "anti_coercion",
    label: "Anti-Coercion / Insurance Choice",
    description: "Insurance choice disclosure",
    required: false,
  },
  {
    key: "hazard_insurance_notif",
    label: "Hazard Insurance Notification",
    description: "Hazard insurance notice",
    required: false,
  },
  {
    key: "homeowner_counseling",
    label: "Homeowner Counseling",
    description: "Counseling disclosure",
    required: false,
  },
  {
    key: "adverse_action",
    label: "Adverse Action",
    description: "Adverse action notice",
    required: false,
  },
  {
    key: "servicing_transfer_notice",
    label: "Servicing Transfer Notice",
    description: "Notice of servicing transfer",
    required: false,
  },

  // ── Verifications & tax auth ───────────────────────────────────────────
  {
    key: "voe",
    label: "Verification of Employment (voe)",
    description: "voe form",
    required: false,
  },
  {
    key: "vod",
    label: "Verification of Deposit (vod)",
    description: "vod form",
    required: false,
  },
  {
    key: "f4506c",
    label: "4506-T / Tax Transcript Request",
    description: "IRS 4506-T authorization",
    required: false,
  },
  {
    key: "form_1099",
    label: "1099",
    description: "Miscellaneous income statement",
    required: false,
  },

  // ── Identity & compliance ──────────────────────────────────────────────
  {
    key: "gov_id",
    label: "ID Document",
    description: "Government-issued ID",
    required: false,
  },
  {
    key: "patriot_cip",
    label: "Patriot Act / CIP",
    description: "Customer identification program",
    required: false,
  },
  {
    key: "privacy_policy",
    label: "Privacy Policy",
    description: "Privacy policy disclosure",
    required: false,
  },
  {
    key: "fraud_notice",
    label: "Fraud / Misrepresentation Notice",
    description: "Fraud notice",
    required: false,
  },

  // ── Affidavits ─────────────────────────────────────────────────────────
  {
    key: "affidavit_generic",
    label: "Affidavit (generic)",
    description: "Generic affidavit",
    required: false,
  },
  {
    key: "name_affidavit_aka",
    label: "Name Affidavit / AKA",
    description: "Name / AKA affidavit",
    required: false,
  },
  {
    key: "notary_acknowledgment",
    label: "Notary Acknowledgment / Jurat",
    description: "Notary acknowledgment page",
    required: false,
  },

  // ── Closing instructions & escrow ──────────────────────────────────────
  {
    key: "wire_instructions",
    label: "Wire Instructions / Funding Authorization",
    description: "Funding wire instructions",
    required: false,
  },
  {
    key: "escrow_waiver_agreement",
    label: "Escrow Waiver / Agreement",
    description: "Escrow account waiver or agreement",
    required: false,
  },
  {
    key: "eo_compliance",
    label: "Errors & Omissions / Compliance Agreement",
    description: "E&O / compliance agreement",
    required: false,
  },

  // ── Property-type riders ───────────────────────────────────────────────
  {
    key: "condo_pud_cert",
    label: "Condo / PUD Certification",
    description: "Condominium or PUD certification",
    required: false,
  },
  {
    key: "fha_va_specific",
    label: "FHA / VA Specific",
    description: "FHA / VA program-specific attachments",
    required: false,
  },

  // ── Misc / catch-all ───────────────────────────────────────────────────
  {
    key: "gift_letter",
    label: "Gift Letter",
    description: "Gift funds letter",
    required: false,
  },
  {
    key: "underwriting_aus",
    label: "Underwriting / AUS Findings",
    description: "DU / LP findings",
    required: false,
  },
  {
    key: "insurance_binder",
    label: "Insurance Binder",
    description: "Temporary insurance binder",
    required: false,
  },
  {
    key: "legal_description_exhibit_a",
    label: "Legal Description / Exhibit A",
    description: "Legal description exhibit",
    required: false,
  },
  {
    key: "recording_cover_sheet",
    label: "Recording Cover Sheet",
    description: "County recording cover sheet",
    required: false,
  },
  {
    key: "cover_letter_transmittal",
    label: "Cover Letter / Transmittal",
    description: "Cover letter or transmittal",
    required: false,
  },
  {
    key: "esign_econsent",
    label: "eSign / eConsent",
    description: "Electronic signature consent",
    required: false,
  },
  {
    key: "borrower_cert_authorization",
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
  urla_1003: [
    "borrower_name",
    "co_borrower_name",
    "ssn",
    "property_address",
    "loan_amount",
    "employer_name",
    "monthly_income",
    "signature_date",
  ],
  paystub: [
    "employee_name",
    "employer_name",
    "pay_period",
    "gross_pay",
    "net_pay",
    "ytd_gross",
    "pay_date",
  ],
  w2: [
    "employee_name",
    "employer_name",
    "employer_ein",
    "ssn",
    "wages",
    "federal_tax_withheld",
    "tax_year",
  ],
  f1040: [
    "filer_name",
    "ssn",
    "filing_status",
    "agi",
    "total_tax",
    "tax_year",
    "signature",
  ],
  bank_stmt: [
    "account_holder",
    "account_number",
    "statement_period",
    "beginning_balance",
    "ending_balance",
  ],
  credit_report: [
    "borrower_name",
    "ssn",
    "fico_score",
    "report_date",
    "tradelines",
  ],
  appraisal: [
    "property_address",
    "appraised_value",
    "appraiser_name",
    "appraisal_date",
    "effective_date",
    "sales_price",
  ],
  purchase_agmt: [
    "buyer_name",
    "seller_name",
    "property_address",
    "purchase_price",
    "closing_date",
    "earnest_money",
    "signatures",
  ],
  hoi: [
    "insured_name",
    "property_address",
    "policy_number",
    "coverage_amount",
    "effective_date",
    "expiration_date",
  ],
  title_commit: [
    "insured_name",
    "property_address",
    "policy_amount",
    "effective_date",
    "schedule_b_exceptions",
  ],
  title_policy: [
    "insured_name",
    "property_address",
    "policy_amount",
    "policy_date",
    "policy_number",
  ],
  warranty_deed: [
    "grantor",
    "grantee",
    "property_legal_description",
    "recording_date",
    "signatures",
    "notary_acknowledgment",
  ],
  quitclaim_deed: [
    "grantor",
    "grantee",
    "property_legal_description",
    "recording_date",
    "signatures",
  ],
  deed_other: [
    "grantor",
    "grantee",
    "property_legal_description",
    "recording_date",
    "signatures",
  ],
  assignment_of_mortgage: [
    "assignor",
    "assignee",
    "original_mortgagor",
    "recording_date",
    "signatures",
  ],
  mortgage_deed_of_trust: [
    "borrower",
    "lender",
    "property_legal_description",
    "loan_amount",
    "recording_date",
    "signatures",
  ],
  satisfaction_release: [
    "lender",
    "borrower",
    "original_mortgage_recording_info",
    "satisfaction_date",
    "signatures",
  ],
  subordination_agreement: [
    "subordinating_lender",
    "senior_lender",
    "property_address",
    "signatures",
  ],
  lien_judgment: [
    "claimant",
    "debtor",
    "amount",
    "recording_date",
    "property_description",
  ],
  power_of_attorney: [
    "principal_name",
    "agent_name",
    "signing_authority_scope",
    "effective_date",
    "notary_acknowledgment",
  ],
  tax_certificate: [
    "parcel_number",
    "owner_name",
    "tax_year",
    "amount_due",
    "certificate_date",
  ],
  tax_bill: ["parcel_number", "owner_name", "tax_year", "amount_due", "due_date"],
  survey_plat: [
    "surveyor_name",
    "property_legal_description",
    "survey_date",
    "plat_reference",
  ],
  loan_estimate: [
    "borrower_name",
    "loan_amount",
    "interest_rate",
    "monthly_payment",
    "closing_costs",
    "issue_date",
  ],
  closing_disclosure: [
    "borrower_name",
    "loan_amount",
    "interest_rate",
    "monthly_payment",
    "closing_costs",
    "closing_date",
    "signatures",
  ],
  hud1_settlement: [
    "borrower_name",
    "seller_name",
    "property_address",
    "settlement_date",
    "total_settlement_charges",
  ],
  promissory_note: [
    "borrower_name",
    "lender_name",
    "loan_amount",
    "interest_rate",
    "maturity_date",
    "signature",
  ],
  first_payment_letter: [
    "borrower_name",
    "loan_number",
    "first_payment_due_date",
    "payment_amount",
  ],
  flood_cert: [
    "property_address",
    "flood_zone",
    "certification_date",
    "determination_authority",
  ],
  right_of_rescission_til: [
    "borrower_name",
    "transaction_date",
    "rescission_deadline",
    "signature",
  ],
  voe: [
    "employee_name",
    "employer_name",
    "position",
    "start_date",
    "current_salary",
    "signature",
  ],
  vod: [
    "account_holder",
    "bank_name",
    "account_number",
    "current_balance",
    "average_balance",
    "signature",
  ],
  f4506c: ["taxpayer_name", "ssn", "tax_year", "signature", "signature_date"],
  form_1099: [
    "recipient_name",
    "payer_name",
    "recipient_tin",
    "total_payments",
    "tax_year",
  ],
  gov_id: [
    "full_name",
    "date_of_birth",
    "id_number",
    "expiration_date",
  ],
  name_affidavit_aka: [
    "affiant_name",
    "aka_names",
    "signature",
    "notary_acknowledgment",
  ],
  notary_acknowledgment: [
    "notary_name",
    "notary_commission_expiry",
    "county",
    "signature_date",
    "principal_name",
  ],
  wire_instructions: [
    "bank_name",
    "routing_number",
    "account_number",
    "beneficiary_name",
    "wire_amount",
  ],
  gift_letter: [
    "donor_name",
    "recipient_name",
    "gift_amount",
    "relationship",
    "signature",
  ],
  underwriting_aus: ["borrower_name", "loan_number", "decision", "run_date"],
  legal_description_exhibit_a: ["property_legal_description", "parcel_id"],
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
 * doc-type *labels* as keys). We re-key by our stable lower-snake-case
 * catalog keys so the data round-trips through the backend cleanly. The user can
 * add / remove fields per doc type in the new-package form before submit.
 */
export const DEFAULT_EXTRACTION_FIELDS_BY_DOC: Record<string, string[]> = {
  urla_1003: [
    "Borrower Name",
    "Co-Borrower Name",
    "Loan Amount",
    "Property Address",
    "Loan Purpose",
    "Loan Term",
    "Interest Rate",
  ],
  paystub: [
    "Employee Name",
    "Employer Name",
    "Pay Period",
    "Gross Pay",
    "Net Pay",
    "YTD Earnings",
  ],
  w2: [
    "Employee Name",
    "Employer Name",
    "Wages",
    "Federal Tax Withheld",
    "Tax Year",
  ],
  f1040: [
    "Taxpayer Name",
    "Filing Status",
    "Adjusted Gross Income",
    "Total Tax",
    "Tax Year",
  ],
  bank_stmt: [
    "Account Holder",
    "Account Number",
    "Statement Period",
    "Beginning Balance",
    "Ending Balance",
  ],
  credit_report: ["Borrower Name", "Credit Score", "Report Date", "Bureau"],
  title_commit: [
    "Property Address",
    "Legal Description",
    "Title Holder",
    "Policy Amount",
    "Effective Date",
  ],
  hoi: [
    "Insured Name",
    "Policy Number",
    "Coverage Amount",
    "Effective Date",
    "Premium",
  ],
  purchase_agmt: [
    "Buyer Name",
    "Seller Name",
    "Purchase Price",
    "Earnest Money",
    "Closing Date",
  ],
  closing_disclosure: [
    "Borrower Name",
    "Loan Amount",
    "Closing Date",
    "Cash to Close",
    "APR",
  ],
  hud1_settlement: [
    "Borrower Name",
    "Loan Amount",
    "Closing Date",
    "Cash to Close",
    "APR",
  ],
  appraisal: [
    "Property Address",
    "Appraised Value",
    "Appraiser Name",
    "Appraiser License",
    "Effective Date",
  ],
  voe: [
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
