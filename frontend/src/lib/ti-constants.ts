export const SEVERITY_COLORS: Record<string, string> = {
  critical: "bg-red-50 text-red-700 border border-red-200",
  high: "bg-amber-50 text-amber-700 border border-amber-200",
  medium: "bg-orange-50 text-orange-600 border border-orange-200",
  low: "bg-indigo-50 text-indigo-600 border border-indigo-200",
};

export const SEVERITY_BG_COLORS: Record<string, string> = {
  critical: "bg-red-50 border border-red-200",
  high: "bg-amber-50 border border-amber-200",
  medium: "bg-orange-50 border border-orange-200",
  low: "bg-indigo-50 border border-indigo-200",
};

export const SEVERITY_TEXT_COLORS: Record<string, string> = {
  critical: "text-red-700",
  high: "text-amber-700",
  medium: "text-orange-600",
  low: "text-indigo-600",
};

export const SEVERITY_DISPLAY_NAMES: Record<string, string> = {
  critical: "CRITICAL",
  high: "HIGH",
  medium: "MODERATE",
  low: "STANDARD",
};

export const PRIORITY_COLORS: Record<string, string> = {
  "MUST CLEAR": "bg-red-50 text-red-700 border border-red-200",
  "REQUIRED": "bg-amber-50 text-amber-700 border border-amber-200",
  "INFORMATIONAL": "bg-sky-50 text-sky-700 border border-sky-200",
};

export const STATUS_COLORS: Record<string, string> = {
  open: "bg-muted text-muted-foreground",
  approved: "bg-green-100 text-green-800 border-green-200",
  rejected: "bg-red-100 text-red-800 border-red-200",
  escalated: "bg-purple-100 text-purple-800 border-purple-200",
};

export const CATEGORY_LABELS: Record<string, string> = {
  extraction_completeness: "Extraction Completeness",
  risk_assessment: "Risk Assessment",
  flag_resolution: "Flag Resolution",
  extraction_confidence: "Extraction Confidence",
};

export const SECTION_TYPE_LABELS: Record<string, string> = {
  schedule_a: "Schedule A",
  schedule_b: "Schedule B",
  schedule_b1: "Schedule B-I",
  schedule_b2: "Schedule B-II",
  schedule_c: "Schedule C",
  schedule_d: "Schedule D",
  cover: "Cover Page",
  endorsements: "Endorsements",
  legal_description: "Legal Description",
  other: "Other",
};

export const REASON_CODES = [
  { value: "acceptable_risk", label: "Acceptable Risk" },
  { value: "standard_exception", label: "Standard Exception" },
  { value: "resolved_prior", label: "Resolved Prior to Closing" },
  { value: "insured_over", label: "Insured Over" },
  { value: "needs_endorsement", label: "Needs Endorsement" },
  { value: "title_defect", label: "Title Defect" },
  { value: "requires_curative", label: "Requires Curative Action" },
  { value: "other", label: "Other" },
];

export const SUGGESTED_QUESTIONS = [
  "What are the key parties involved in this transaction?",
  "Are there any liens or encumbrances on the property?",
  "What exceptions are listed in Schedule B?",
  "What is the legal description of the property?",
  "Are there any requirements that need to be met before closing?",
  "What is the effective date of this commitment?",
];

export const STAGE_LABELS: Record<string, string> = {
  ingest: "File Validation",
  render: "PDF Rendering",
  examine: "Title Examination",
  complete: "Finalization",
};
