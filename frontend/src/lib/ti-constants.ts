export const SEVERITY_COLORS: Record<string, string> = {
  critical: "bg-red-100 text-red-800 border-red-200",
  high: "bg-orange-100 text-orange-800 border-orange-200",
  medium: "bg-yellow-100 text-yellow-800 border-yellow-200",
  low: "bg-blue-100 text-blue-800 border-blue-200",
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
  requirements: "Requirements",
  endorsements: "Endorsements",
  liens: "Liens",
  exceptions: "Exceptions",
  consistency: "Consistency",
};

export const SECTION_TYPE_LABELS: Record<string, string> = {
  schedule_a: "Schedule A",
  schedule_b1: "Schedule B-1",
  schedule_b2: "Schedule B-2",
  schedule_c: "Schedule C",
  cover: "Cover Page",
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
  ocr: "Text Extraction (OCR)",
  index: "Text Indexing",
  ingestion_agent: "AI Data Extraction",
  risk_agent: "AI Risk Analysis",
  complete: "Finalization",
};
