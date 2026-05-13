import { API_URL, apiFetch, apiFetchBlob } from "@/lib/api";
import { getToken } from "@/lib/auth";
import type {
  LoanContextInput,
  LoanDocTypeSpec,
  LoanExtractionOverride,
  LoanExtractionOverrideDelete,
  LoanExtractionOverrideUpsert,
  LoanExtractionsResponse,
  LoanPackage,
  LoanPackageListItem,
  LoanPackageRule,
  LoanPage,
  LoanPageOverride,
  LoanPageOverrideBatchRequest,
  LoanPageOverrideBatchResult,
  LoanPageOverrideRequest,
  LoanPageOverrideResult,
  LoanPipelineStatus,
  LoanRulePreset,
  LoanStack,
  LoanValidationResult,
} from "./types";

const BASE = "/api/v1/apps/loan-onboarding";

export interface CreateLoanPackageInput {
  name: string;
  borrower_name?: string;
  loan_reference?: string;
  hitl_threshold: number;
  doc_types: LoanDocTypeSpec[];
  validation_rules: Array<{
    rule_source: "preset" | "custom";
    rule_id: string;
    description?: string | null;
    config: Record<string, unknown>;
  }>;
  /** Master toggle for field extraction (Section D). */
  extraction_enabled?: boolean;
  /** Field labels to extract, keyed by doc-type key. */
  extraction_fields_by_doc?: Record<string, string[]>;
  /**
   * Optional loan context — drives the persona-aware compliance engine.
   * Omit if the loan officer skipped the compliance section.
   */
  loan_context?: LoanContextInput;
}

// Phase 6 cutover (2026-05-10): backend dropped the legacy `/packages/*`
// public router; the canonical create/get/list/delete/process/upload
// endpoints now live under `/loans/*`. Sub-routers that still serve
// `/packages/{id}/...` reads (stacks, validation-results, pages, extractions,
// etc.) stay on those paths and are untouched here.

export function createPackage(orgId: string, data: CreateLoanPackageInput) {
  return apiFetch<LoanPackage>(`${BASE}/loans`, {
    method: "POST",
    body: JSON.stringify(data),
    orgId,
  });
}

export function deletePackage(orgId: string, packageId: string) {
  return apiFetch<void>(`${BASE}/loans/${packageId}`, {
    method: "DELETE",
    orgId,
  });
}

export function listPackages(orgId: string) {
  return apiFetch<LoanPackageListItem[]>(`${BASE}/loans`, { orgId });
}

/**
 * Multipart upload for newly-created loan packages.
 *
 * Mirrors the auth shape (Bearer + X-Org-Id) used by `apiFetch`. The backend
 * accepts a multipart `files` field (repeating) at `/loans/{id}/files` and
 * returns the persisted `LOPackageFile` rows. We hand-roll the fetch because
 * `apiFetch` only handles JSON bodies and `uploadFiles` in `lib/api.ts` would
 * work but we want a dedicated wrapper that mirrors the rest of this file.
 */
export async function uploadPackageFiles(
  orgId: string,
  packageId: string,
  files: File[]
) {
  const form = new FormData();
  files.forEach((file) => form.append("files", file));
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (orgId) headers["X-Org-Id"] = orgId;
  const url = `${API_URL}${BASE}/loans/${packageId}/files`;
  const res = await fetch(url, { method: "POST", body: form, headers });
  if (!res.ok) {
    const errBody = await res
      .json()
      .catch(() => ({ detail: `Upload failed (${res.status})` }));
    throw new Error(errBody.detail || `Upload failed (${res.status})`);
  }
  return res.json();
}

/**
 * Phase 5.2 — list loan files via the LogikIntake `/loans` alias.
 *
 * Same response shape as `listPackages` (the backend route delegates to
 * `_packages.list_packages`); we use a distinct function so the queue page
 * is not coupled to the legacy `/packages` URL once the redirect cuts in.
 * Newer screens should call this — `listPackages` stays around only for
 * unported screens during the Phase 5 migration.
 */
export function listLoans(orgId: string) {
  return apiFetch<LoanPackageListItem[]>(`${BASE}/loans`, { orgId });
}

export function getPackage(orgId: string, packageId: string) {
  return apiFetch<LoanPackage>(`${BASE}/loans/${packageId}`, { orgId });
}

export function processPackage(orgId: string, packageId: string) {
  return apiFetch<{ message: string; package_id: string }>(
    `${BASE}/loans/${packageId}/process`,
    { method: "POST", orgId }
  );
}

export function getPipelineStatus(orgId: string, packageId: string) {
  return apiFetch<LoanPipelineStatus>(
    `${BASE}/loans/${packageId}/pipeline`,
    { orgId }
  );
}

export function getPages(orgId: string, packageId: string) {
  return apiFetch<LoanPage[]>(`${BASE}/packages/${packageId}/pages`, { orgId });
}

export function getStacks(orgId: string, packageId: string) {
  return apiFetch<LoanStack[]>(`${BASE}/packages/${packageId}/stacks`, {
    orgId,
  });
}

export function getPackageRules(orgId: string, packageId: string) {
  return apiFetch<LoanPackageRule[]>(`${BASE}/packages/${packageId}/rules`, {
    orgId,
  });
}

export function getRulePresets(orgId: string) {
  return apiFetch<LoanRulePreset[]>(`${BASE}/rules/presets`, { orgId });
}

export function getValidationResults(orgId: string, packageId: string) {
  return apiFetch<LoanValidationResult[]>(
    `${BASE}/packages/${packageId}/validation-results`,
    { orgId }
  );
}

// ── Page overrides (Phase 1/2 "Move to…" flow) ───────────────────────────

export function applyPageOverride(
  orgId: string,
  packageId: string,
  pageId: string,
  body: LoanPageOverrideRequest
) {
  return apiFetch<LoanPageOverrideResult>(
    `${BASE}/packages/${packageId}/pages/${pageId}/override`,
    {
      method: "POST",
      body: JSON.stringify(body),
      orgId,
    }
  );
}

export function removePageOverride(
  orgId: string,
  packageId: string,
  pageId: string
) {
  return apiFetch<LoanPageOverrideResult>(
    `${BASE}/packages/${packageId}/pages/${pageId}/override`,
    { method: "DELETE", orgId }
  );
}

export function listPageOverrides(orgId: string, packageId: string) {
  return apiFetch<LoanPageOverride[]>(
    `${BASE}/packages/${packageId}/overrides`,
    { orgId }
  );
}

/**
 * Apply many page overrides in one request. The backend runs re-stack and
 * re-validate ONCE at the end (vs. once per page for the single endpoint),
 * so this is what drag-and-drop multi-move flows should call. No-op moves
 * (page already in the target doc type) are silently skipped server-side.
 */
export function applyPageOverridesBatch(
  orgId: string,
  packageId: string,
  body: LoanPageOverrideBatchRequest
) {
  return apiFetch<LoanPageOverrideBatchResult>(
    `${BASE}/packages/${packageId}/pages/overrides:batch`,
    {
      method: "POST",
      body: JSON.stringify(body),
      orgId,
    }
  );
}

// ── Field extraction (Section D output) ──────────────────────────────────

export function getExtractions(orgId: string, packageId: string) {
  return apiFetch<LoanExtractionsResponse>(
    `${BASE}/packages/${packageId}/extractions`,
    { orgId }
  );
}

// ── Reviewer-edited extraction overrides (per-field "Save" + "Reset") ────

export function listExtractionOverrides(orgId: string, packageId: string) {
  return apiFetch<LoanExtractionOverride[]>(
    `${BASE}/packages/${packageId}/extractions/overrides`,
    { orgId }
  );
}

export function upsertExtractionOverride(
  orgId: string,
  packageId: string,
  body: LoanExtractionOverrideUpsert
) {
  return apiFetch<LoanExtractionOverride>(
    `${BASE}/packages/${packageId}/extractions/overrides`,
    { method: "PUT", body: JSON.stringify(body), orgId }
  );
}

export function deleteExtractionOverride(
  orgId: string,
  packageId: string,
  body: LoanExtractionOverrideDelete
) {
  return apiFetch<{ removed: boolean }>(
    `${BASE}/packages/${packageId}/extractions/overrides`,
    { method: "DELETE", body: JSON.stringify(body), orgId }
  );
}

// ── Page word coords (for extraction text highlighting) ──────────────

export interface LoanPageWord {
  text: string;
  /** Normalized 0..1 coords. */
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  block: number;
  line: number;
  word: number;
}

export interface LoanPageWordsResponse {
  page_width: number;
  page_height: number;
  words: LoanPageWord[];
}

export function fetchPageWords(
  orgId: string,
  packageId: string,
  pageId: string
) {
  return apiFetch<LoanPageWordsResponse>(
    `${BASE}/packages/${packageId}/pages/${pageId}/words`,
    { orgId }
  );
}

export function fetchCompliancePdfBlob(orgId: string, packageId: string) {
  return apiFetchBlob(`${BASE}/packages/${packageId}/compliance/report.pdf`, {
    orgId,
  });
}

export function fetchFinalPacketPdfBlob(orgId: string, packageId: string) {
  return apiFetchBlob(`${BASE}/packages/${packageId}/final-packet.pdf`, {
    orgId,
  });
}

export function fetchPerStackZipBlob(orgId: string, packageId: string) {
  return apiFetchBlob(`${BASE}/packages/${packageId}/per-stack.zip`, {
    orgId,
  });
}

/**
 * PATCH the persisted loan context for a package. Backend validates enum
 * membership server-side and returns the persisted snapshot.
 */
export function updateComplianceContext(
  orgId: string,
  packageId: string,
  body: LoanContextInput
) {
  return apiFetch<LoanContextInput>(
    `${BASE}/packages/${packageId}/compliance/context`,
    { method: "PATCH", body: JSON.stringify(body), orgId }
  );
}

/**
 * Raw compliance-engine response from the backend. Mirrors the Pydantic
 * `ComplianceRunOut` schema exactly (camelCase keys for findings, snake_case
 * for the wrapper). The frontend `compliance.ts` adapter projects this into
 * the legacy `ComplianceReport` shape consumed by the LO + QC views.
 */
export interface ComplianceFindingPayload {
  id: string;
  category: string;
  regulation: string;
  requirement: string;
  requires: string[];
  requiresMode: "all" | "any" | "process";
  severity: "critical" | "high" | "medium" | "low" | "info";
  status: "compliant" | "partial" | "missing" | "attestation_required";
  matched: string[];
  missingDocs: string[];
  details: string;
  remediation: string;
}

export interface ComplianceRunPayload {
  run_id?: string | null;
  package_id: string;
  package_name?: string | null;
  loan_reference?: string | null;
  borrower_name?: string | null;
  rules_version: string;
  rule_set_hash: string;
  loan_context_snapshot: LoanContextInput;
  doc_inventory_snapshot: string[];
  summary: {
    total: number;
    compliant: number;
    partial: number;
    missing: number;
    attestation_required: number;
    open_criticals: ComplianceFindingPayload[];
    open_criticals_count: number;
  };
  findings: ComplianceFindingPayload[];
  lo_view: {
    closeability: {
      tone: "green" | "yellow" | "red";
      label: string;
      message: string;
      open_critical_count: number;
      open_findings_count: number;
    };
    deal_killers: ComplianceFindingPayload[];
    borrower_asks: Array<{
      id: string;
      severity: ComplianceFindingPayload["severity"];
      docs: string[];
      reason: string;
      remediation: string;
    }>;
  };
  qc_view: {
    summary_tiles: {
      total: number;
      compliant: number;
      partial: number;
      missing: number;
      attestation_required: number;
      open_criticals_count: number;
    };
    open_criticals: ComplianceFindingPayload[];
    by_category: Record<string, ComplianceFindingPayload[]>;
  } | null;
  regulations:
    | Array<{
        id: string;
        name: string;
        citation: string;
        applicable: boolean;
        rationale: string;
      }>
    | null;
  doc_checks:
    | Array<{
        docKey: string;
        docLabel: string;
        required: boolean;
        submitted: boolean;
        pageCount: number;
        confidence: number | null;
        status: "ok" | "missing" | "low_confidence" | "needs_review";
        notes: string[];
      }>
    | null;
  created_at?: string | null;
}

// ── Phase 5.2 LogikIntake operator endpoints (/loans/* surface) ──────
//
// These hit the new alias router. Read shapes are 1:1 delegations to the
// /packages handlers; write endpoints are LogikIntake-specific (classify,
// acknowledge, advance, SSE stream).

export interface LoanChecklistItem {
  doc_type: string;
  label: string;
  requirement: "Required" | "Optional" | "Conditional";
  received: boolean;
  stack_count: number;
  needs_review: boolean;
}

export interface LoanDocExtractionField {
  name: string;
  value: string;
  confidence: number;
  status: string;
  page: number | null;
  bbox: number[] | null;
  grounded: boolean;
  edited: boolean;
  edited_at: string | null;
  // Schema-merged fields. Populated when the backend resolved an
  // extraction schema for this stack's doc_type (always, in practice).
  key?: string;
  label?: string;
  required?: boolean;
  data_type?: string;
}

export interface LoanDocExtractionResponse {
  stack_id: string;
  doc_type: string;
  fields: LoanDocExtractionField[];
  located_count: number;
  total_count: number;
  schema_version?: number | null;
  // True when an LOExtraction row exists for this stack. When false the
  // stack was never processed by the extract stage (skipped at run time
  // because the schema had no fields for this doc_type, or extraction
  // was disabled for the package).
  extraction_present?: boolean;
  // Number of fields currently configured in the resolved schema. The UI
  // compares this to the number of fields that have values to detect
  // "schema added fields after this loan ran" and prompt a re-run.
  schema_field_count?: number;
}

export interface RerunExtractionResult {
  stack_id: string;
  fields_extracted: number;
  status: string;
}

export interface LoanAdvanceResponse {
  advanced: boolean;
  from_status: string;
  to_status: string;
  blocked_reason: string | null;
  open_hard_stops: number;
  open_soft_flags: number;
}

export function getLoanDocuments(orgId: string, loanId: string) {
  return apiFetch<LoanStack[]>(
    `${BASE}/loans/${loanId}/documents`,
    { orgId }
  );
}

export function getLoanChecklist(orgId: string, loanId: string) {
  return apiFetch<LoanChecklistItem[]>(
    `${BASE}/loans/${loanId}/checklist`,
    { orgId }
  );
}

export function getLoanValidations(orgId: string, loanId: string) {
  return apiFetch<LoanValidationResult[]>(
    `${BASE}/loans/${loanId}/validations`,
    { orgId }
  );
}

export function getLoanDocExtraction(
  orgId: string,
  loanId: string,
  docId: string
) {
  return apiFetch<LoanDocExtractionResponse>(
    `${BASE}/loans/${loanId}/extractions/${docId}`,
    { orgId }
  );
}

export function rerunLoanDocExtraction(
  orgId: string,
  loanId: string,
  docId: string
) {
  return apiFetch<RerunExtractionResult>(
    `${BASE}/loans/${loanId}/extractions/${docId}/rerun`,
    { orgId, method: "POST" }
  );
}

export function patchLoanExtractionField(
  orgId: string,
  loanId: string,
  docId: string,
  fieldId: string,
  value: string
) {
  return apiFetch<{
    stack_id: string;
    field_name: string;
    value: string;
    edited_at: string;
  }>(
    `${BASE}/loans/${loanId}/extractions/${docId}/fields/${fieldId}`,
    {
      method: "PATCH",
      body: JSON.stringify({ value }),
      orgId,
    }
  );
}

export function confirmLoanClassification(
  orgId: string,
  loanId: string,
  docId: string,
  body: { doc_type?: string | null; notes?: string | null }
) {
  return apiFetch<{
    stack_id: string;
    decision: "accept" | "reclassify";
    doc_type: string;
    review_id: string;
  }>(
    `${BASE}/loans/${loanId}/documents/${docId}/classify`,
    { method: "POST", body: JSON.stringify(body), orgId }
  );
}

export function acknowledgeLoanValidation(
  orgId: string,
  loanId: string,
  checkId: string,
  override_note?: string
) {
  return apiFetch<{
    stack_id: string;
    rule_source: string;
    rule_id: string;
    acknowledged: boolean;
    override_note: string | null;
  }>(
    `${BASE}/loans/${loanId}/validations/${checkId}/acknowledge`,
    {
      method: "POST",
      body: JSON.stringify({ override_note: override_note ?? null }),
      orgId,
    }
  );
}

export function advanceLoan(orgId: string, loanId: string) {
  return apiFetch<LoanAdvanceResponse>(
    `${BASE}/loans/${loanId}/advance`,
    { method: "POST", orgId }
  );
}

// ── Reject + re-upload (remediation modal — Phase 5 closing) ──────────

export function rejectLoanDocument(
  orgId: string,
  loanId: string,
  docId: string,
  notes?: string | null
) {
  return apiFetch<{
    stack_id: string;
    decision: "reject";
    review_id: string;
    package_status: string;
  }>(
    `${BASE}/loans/${loanId}/documents/${docId}/reject`,
    {
      method: "POST",
      body: JSON.stringify({ notes: notes ?? null }),
      orgId,
    }
  );
}

export interface ReuploadLoanDocumentResult {
  stack_id: string;
  review_id: string;
  file_id: string;
  pages_added: number;
  first_page_number: number;
  last_page_number: number;
  workflow_id: string | null;
  backend: "temporal" | "background_tasks";
}

/**
 * Multipart re-upload — replaces a flagged stack with a fresh PDF.
 * Backend rejects the old stack, ingests the new file, and dispatches the
 * Variant-A remediation workflow (classify → validate → extract).
 */
export async function reuploadLoanDocument(
  orgId: string,
  loanId: string,
  docId: string,
  file: File,
  notes?: string | null
): Promise<ReuploadLoanDocumentResult> {
  // Hand-rolled fetch — apiFetch only handles JSON bodies and uploadFiles
  // posts an array under the "files" key, but the backend expects a single
  // "file" multipart field plus an optional "notes" query param. Mirrors
  // the auth shape (Bearer + X-Org-Id) of apiFetch / uploadFiles.
  const form = new FormData();
  form.append("file", file);
  const trimmedNotes = notes && notes.trim() ? notes.trim() : "";
  const qs = trimmedNotes ? `?notes=${encodeURIComponent(trimmedNotes)}` : "";
  const token = getToken();
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (orgId) headers["X-Org-Id"] = orgId;
  const url = `${API_URL}${BASE}/loans/${loanId}/documents/${docId}/reupload${qs}`;
  const res = await fetch(url, { method: "POST", body: form, headers });
  if (!res.ok) {
    const errBody = await res
      .json()
      .catch(() => ({ detail: `Upload failed (${res.status})` }));
    throw new Error(errBody.detail || `Upload failed (${res.status})`);
  }
  return (await res.json()) as ReuploadLoanDocumentResult;
}

// ── Audit events (replaces the synthesized timeline in audit-drawer.tsx) ─

export interface LoanAuditEvent {
  id: string;
  action: string;
  target_type: string;
  target_id: string | null;
  actor_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export function getLoanAuditEvents(orgId: string, loanId: string) {
  return apiFetch<LoanAuditEvent[]>(
    `${BASE}/loans/${loanId}/audit-events`,
    { orgId }
  );
}

/**
 * GET the most recent compliance run for a package; backend evaluates fresh
 * if no prior run exists.
 */
export function getComplianceRun(orgId: string, packageId: string) {
  return apiFetch<ComplianceRunPayload>(
    `${BASE}/packages/${packageId}/compliance`,
    { orgId }
  );
}

/**
 * POST a fresh compliance evaluation. Used after the LO edits the loan context
 * (so the persisted run reflects the new context immediately) and on first
 * load when the page wants to re-derive against current package state.
 */
export function evaluateComplianceApi(orgId: string, packageId: string) {
  return apiFetch<ComplianceRunPayload>(
    `${BASE}/packages/${packageId}/compliance/evaluate`,
    { method: "POST", orgId }
  );
}
