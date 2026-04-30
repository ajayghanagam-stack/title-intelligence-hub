export interface LoanDocTypeSpec {
  key: string;
  label: string;
  required: boolean;
  /**
   * Short human-readable hint shown under the label in the doc-type picker.
   * Optional — custom user-added types omit it.
   */
  description?: string;
  /**
   * Locked entries are always-selected, always-required catch-all buckets
   * (e.g. "Others"). The UI must not allow deselecting, deleting, or toggling
   * `required` off for these. They are also filtered out before submit — the
   * backend reserves "Others" as an implicit bucket.
   */
  locked?: boolean;
}

/**
 * Per-doc-type validation toggles selected on the new-package form. Lives in
 * UI state only; on submit the form derives a backend `validation_rules`
 * payload by emitting one rule per preset with `applies_to_doc_keys` listing
 * the doc types that have it enabled. `date_consistency` has no backend
 * evaluator yet and is stripped at submit (kept in the UI for parity with
 * the prototype).
 */
export interface DocValidations {
  missing_pages: boolean;
  missing_signatures: boolean;
  date_consistency: boolean;
  missing_fields: boolean;
  /** Required field labels for the missing_fields rule on this doc type. */
  required_fields: string[];
}

export const EMPTY_DOC_VALIDATIONS: DocValidations = {
  missing_pages: false,
  missing_signatures: false,
  date_consistency: false,
  missing_fields: false,
  required_fields: [],
};

export interface LoanPresetConfigField {
  name: string;
  type: "number" | "integer" | "string" | "boolean" | "string_list";
  label?: string;
  default?: number | string | boolean | string[];
  min?: number;
  max?: number;
}

export interface LoanRulePreset {
  rule_id: string;
  label: string;
  description: string;
  config_schema: LoanPresetConfigField[];
}

export interface LoanPackageRule {
  id?: string;
  package_id?: string;
  rule_source: "preset" | "custom";
  rule_id: string;
  description: string | null;
  config: Record<string, unknown>;
  created_at?: string;
}

/**
 * Loan-context snapshot captured on the new-package form and editable from the
 * compliance page. Drives the compliance engine's rule applicability and the
 * generated PDF report header. Wire format mirrors backend `LoanContextIn`
 * (camelCase keys: `scenarioFlags`, `ausEngine`, etc.).
 */
export interface LoanContextInput {
  program: string;
  purpose: string;
  occupancy: string;
  state: string;
  scenarioFlags: string[];
  ausEngine: string;
  ausWaivers: string[];
  loanAmount: number | null;
  propertyValue: number | null;
}

export interface LoanPackage {
  id: string;
  org_id: string;
  name: string;
  borrower_name: string | null;
  loan_reference: string | null;
  doc_types: LoanDocTypeSpec[];
  status: string;
  pipeline_stage: string | null;
  pipeline_error: string | null;
  /**
   * Field-extraction config mirroring section "D · Field Extraction" on the
   * new-package form. `extraction_enabled` is the master toggle; the map
   * stores `{ [doc_type_key]: string[] }` of field labels to pull per type.
   */
  extraction_enabled: boolean;
  extraction_fields_by_doc: Record<string, string[]>;
  /** Persisted loan context, null if the loan officer skipped the section. */
  loan_context: LoanContextInput | null;
  created_at: string;
  updated_at: string;
}

export interface LoanPackageListItem {
  id: string;
  name: string;
  borrower_name: string | null;
  loan_reference: string | null;
  status: string;
  pipeline_stage: string | null;
  updated_at: string;
  created_at: string;
}

export interface LoanPipelineStageTiming {
  stage: string;
  elapsed_seconds: number | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface LoanPipelineStageStatus {
  stage: string;
  status: string;
}

export interface LoanPipelineStatus {
  package_id: string;
  status: string;
  pipeline_stage: string | null;
  pipeline_error: string | null;
  stages: LoanPipelineStageStatus[];
  processed: number;
  total: number;
  stage_timings: LoanPipelineStageTiming[];
}

export interface LoanPage {
  id: string;
  package_id: string;
  file_id: string;
  page_number: number;
  predicted_doc_type: string | null;
  confidence: number | null;
  page_role: string | null;
  detected_fields: Record<string, unknown> | null;
}

export interface LoanStackPage {
  page_id: string;
  page_number: number;
  predicted_doc_type: string | null;
  confidence: number | null;
  page_role: string | null;
  detected_fields: Record<string, unknown> | null;
}

export interface LoanStack {
  id: string;
  stack_index: number;
  doc_type: string;
  first_page: number;
  last_page: number;
  page_count: number;
  classification_confidence: number | null;
  overall_confidence: number | null;
  status: string;
  pages: LoanStackPage[];
}

export interface LoanConfidenceBreakdown {
  classification: number | null;
  /**
   * Stack split-accuracy heuristic from the backend (key matches the JSONB
   * field exactly: see `confidence_scorer.split_accuracy_from_roles`).
   */
  split_accuracy: number | null;
  validation: number | null;
}

export interface LoanRuleEvaluation {
  rule_id: string;
  rule_source: string;
  label: string;
  description: string | null;
  passed: boolean;
  detail: string | null;
  config: Record<string, unknown>;
}

export interface LoanValidationResult {
  id: string;
  stack_id: string;
  doc_type: string;
  rules_evaluated: LoanRuleEvaluation[];
  confidence_breakdown: LoanConfidenceBreakdown;
  overall_confidence: number | null;
}

export type LoanPageRole =
  | "first_page"
  | "continuation"
  | "last_page"
  | "signature_page";

export interface LoanPageOverrideRequest {
  assigned_doc_type: string;
  page_role_override?: LoanPageRole | null;
  note?: string | null;
}

export interface LoanPageOverride {
  id: string;
  package_id: string;
  page_id: string;
  assigned_doc_type: string;
  previous_doc_type: string;
  page_role_override: LoanPageRole | null;
  reviewer_id: string | null;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface LoanOverrideRebuildSummary {
  stacks: number;
  pages: number;
  preset_rules: number;
  custom_rules: number;
}

export interface LoanPageOverrideResult {
  override: LoanPageOverride | null;
  rebuild: LoanOverrideRebuildSummary;
}

export interface LoanPageOverrideBatchItem {
  page_id: string;
  assigned_doc_type: string;
  page_role_override?: LoanPageRole | null;
  note?: string | null;
}

export interface LoanPageOverrideBatchRequest {
  overrides: LoanPageOverrideBatchItem[];
}

export interface LoanPageOverrideBatchResult {
  overrides: LoanPageOverride[];
  rebuild: LoanOverrideRebuildSummary;
}

// ── Field extraction (Section D output) ──────────────────────────────────

export type LoanExtractionFieldStatus =
  | "located"
  | "low_confidence"
  | "missing";

export interface LoanExtractionField {
  name: string;
  value: string;
  confidence: number;
  status: LoanExtractionFieldStatus;
  /** Optional citation — present when the agent tied the value to a page. */
  page: number | null;
  bbox: number[] | null;
}

export interface LoanStackExtraction {
  stack_id: string;
  stack_index: number;
  doc_type: string;
  fields: LoanExtractionField[];
  located_count: number;
  total_count: number;
}

export interface LoanExtractionsResponse {
  package_id: string;
  extraction_enabled: boolean;
  stacks: LoanStackExtraction[];
}

export interface LoanExtractionOverride {
  id: string;
  package_id: string;
  doc_type: string;
  field_name: string;
  /** Opaque key — UUID for real stacks, `placeholder-{doc_type}` for unmatched. */
  stack_id: string;
  value: string;
  edited_by: string | null;
  edited_at: string;
}

export interface LoanExtractionOverrideUpsert {
  doc_type: string;
  field_name: string;
  stack_id: string;
  value: string;
}

export interface LoanExtractionOverrideDelete {
  doc_type: string;
  field_name: string;
  stack_id: string;
}
