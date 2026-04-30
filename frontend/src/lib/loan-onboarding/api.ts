import { apiFetch, apiFetchBlob } from "@/lib/api";
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

export function createPackage(orgId: string, data: CreateLoanPackageInput) {
  return apiFetch<LoanPackage>(`${BASE}/packages`, {
    method: "POST",
    body: JSON.stringify(data),
    orgId,
  });
}

export function deletePackage(orgId: string, packageId: string) {
  return apiFetch<void>(`${BASE}/packages/${packageId}`, {
    method: "DELETE",
    orgId,
  });
}

export function listPackages(orgId: string) {
  return apiFetch<LoanPackageListItem[]>(`${BASE}/packages`, { orgId });
}

export function getPackage(orgId: string, packageId: string) {
  return apiFetch<LoanPackage>(`${BASE}/packages/${packageId}`, { orgId });
}

export function processPackage(orgId: string, packageId: string) {
  return apiFetch<{ message: string; package_id: string }>(
    `${BASE}/packages/${packageId}/process`,
    { method: "POST", orgId }
  );
}

export function getPipelineStatus(orgId: string, packageId: string) {
  return apiFetch<LoanPipelineStatus>(
    `${BASE}/packages/${packageId}/pipeline`,
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
