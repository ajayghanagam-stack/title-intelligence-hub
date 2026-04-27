import { apiFetch } from "@/lib/api";
import type {
  LoanDocTypeSpec,
  LoanExtractionsResponse,
  LoanPackage,
  LoanPackageListItem,
  LoanPackageRule,
  LoanPage,
  LoanPageOverride,
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

// ── Field extraction (Section D output) ──────────────────────────────────

export function getExtractions(orgId: string, packageId: string) {
  return apiFetch<LoanExtractionsResponse>(
    `${BASE}/packages/${packageId}/extractions`,
    { orgId }
  );
}
