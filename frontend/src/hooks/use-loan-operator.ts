"use client";

// Phase 5.2 — react-query hooks for the LogikIntake operator surface.
//
// These hit the new `/loans/*` alias endpoints (Phase 4) and expose
// per-screen data sources for the classify / doc-validation / extract /
// validation / loan-overview pages. Mutations invalidate the queries
// they affect so the screens stay live without manual refetch wiring.
//
// Cache keys are namespaced under `lo-` and include the loan/doc id so
// concurrent screens don't collide. 15s staleTime is the same as the
// queue page — short enough to feel live, long enough to skip the
// network round-trip on tab switches.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { QueryClient } from "@tanstack/react-query";

import { useOrg } from "@/hooks/use-org";
import {
  acknowledgeLoanValidation,
  advanceLoan,
  confirmLoanClassification,
  getLoanAuditEvents,
  getLoanChecklist,
  getLoanDocExtraction,
  getLoanDocuments,
  getLoanValidations,
  getPipelineStatus,
  patchLoanExtractionField,
  rejectLoanDocument,
  rerunLoanDocExtraction,
  reuploadLoanDocument,
} from "@/lib/loan-onboarding/api";
import type {
  LoanAdvanceResponse,
  LoanAuditEvent,
  LoanChecklistItem,
  LoanDocExtractionResponse,
  RerunExtractionResult,
  ReuploadLoanDocumentResult,
} from "@/lib/loan-onboarding/api";
import type {
  LoanPackage,
  LoanPipelineStatus,
  LoanStack,
  LoanValidationResult,
} from "@/lib/loan-onboarding/types";

const STALE = 15_000;
const GC = 5 * 60_000;

// Auto-refresh cadence while the loan's pipeline is still in flight. Matches
// `useLoanPackage`'s 3s status poll so the doc grid, checklist and validation
// rollups stay in lock-step with the pipeline rail. The function form of
// `refetchInterval` is re-evaluated after every fetch, so the moment the
// package flips to a terminal status the interval turns itself off without
// any explicit "done" signal from the page.
const IN_FLIGHT_POLL_MS = 3_000;
const IN_FLIGHT_STATUSES = new Set([
  "uploading",
  "processing",
  // `awaiting_review` is a terminal state from the operator's POV (humans
  // act on it; the pipeline isn't doing more work), so it is NOT included
  // here — we want polling to stop once the loan parks in review.
]);

/**
 * Returns true when the loan package (looked up from the shared
 * `useLoanPackage` cache) is still actively moving through the pipeline.
 *
 * Falls back to `true` when the package row isn't cached yet — we don't
 * want a brand-new loan to skip polling before the first status fetch
 * lands, otherwise the doc list would sit empty until the user navigates
 * away and back.
 */
function isLoanInFlight(
  qc: QueryClient,
  orgId: string | null | undefined,
  loanId: string | null | undefined,
): boolean {
  if (!orgId || !loanId) return false;
  const pkg = qc.getQueryData<LoanPackage>(["lo-package", orgId, loanId]);
  if (!pkg) return true;
  return IN_FLIGHT_STATUSES.has(pkg.status);
}

export function useLoanDocuments(loanId: string | null | undefined) {
  const { currentOrgId } = useOrg();
  const qc = useQueryClient();
  const enabled = Boolean(currentOrgId && loanId);
  return useQuery<LoanStack[]>({
    queryKey: ["lo-loan-documents", currentOrgId, loanId] as const,
    queryFn: () => getLoanDocuments(currentOrgId!, loanId!),
    enabled,
    staleTime: STALE,
    gcTime: GC,
    refetchInterval: () =>
      isLoanInFlight(qc, currentOrgId, loanId) ? IN_FLIGHT_POLL_MS : false,
    refetchIntervalInBackground: false,
  });
}

/**
 * Polls /pipeline so the rail can display per-stage timings (and the
 * stage status enum the loan overview page surfaces under each pip).
 * Stops polling on terminal status, matching `useLoanDocuments`.
 *
 * The package poll already exposes `status` and `pipeline_stage` for the
 * rail's overall step indicator — this hook only adds the *timings*
 * payload, which is the part operators were missing ("how long did each
 * stage take?"). Kept on its own cache key so other consumers can hit
 * the same data without duplicating the fetch.
 */
export function useLoanPipeline(loanId: string | null | undefined) {
  const { currentOrgId } = useOrg();
  const qc = useQueryClient();
  const enabled = Boolean(currentOrgId && loanId);
  return useQuery<LoanPipelineStatus>({
    queryKey: ["lo-loan-pipeline", currentOrgId, loanId] as const,
    queryFn: () => getPipelineStatus(currentOrgId!, loanId!),
    enabled,
    staleTime: STALE,
    gcTime: GC,
    refetchInterval: () =>
      isLoanInFlight(qc, currentOrgId, loanId) ? IN_FLIGHT_POLL_MS : false,
    refetchIntervalInBackground: false,
  });
}

export function useLoanChecklist(loanId: string | null | undefined) {
  const { currentOrgId } = useOrg();
  const qc = useQueryClient();
  const enabled = Boolean(currentOrgId && loanId);
  return useQuery<LoanChecklistItem[]>({
    queryKey: ["lo-loan-checklist", currentOrgId, loanId] as const,
    queryFn: () => getLoanChecklist(currentOrgId!, loanId!),
    enabled,
    staleTime: STALE,
    gcTime: GC,
    refetchInterval: () =>
      isLoanInFlight(qc, currentOrgId, loanId) ? IN_FLIGHT_POLL_MS : false,
    refetchIntervalInBackground: false,
  });
}

export function useLoanValidations(loanId: string | null | undefined) {
  const { currentOrgId } = useOrg();
  const qc = useQueryClient();
  const enabled = Boolean(currentOrgId && loanId);
  return useQuery<LoanValidationResult[]>({
    queryKey: ["lo-loan-validations", currentOrgId, loanId] as const,
    queryFn: () => getLoanValidations(currentOrgId!, loanId!),
    enabled,
    staleTime: STALE,
    gcTime: GC,
    refetchInterval: () =>
      isLoanInFlight(qc, currentOrgId, loanId) ? IN_FLIGHT_POLL_MS : false,
    refetchIntervalInBackground: false,
  });
}

export function useLoanDocExtraction(
  loanId: string | null | undefined,
  docId: string | null | undefined
) {
  const { currentOrgId } = useOrg();
  const qc = useQueryClient();
  const enabled = Boolean(currentOrgId && loanId && docId);
  return useQuery<LoanDocExtractionResponse>({
    queryKey: ["lo-loan-doc-extraction", currentOrgId, loanId, docId] as const,
    queryFn: () => getLoanDocExtraction(currentOrgId!, loanId!, docId!),
    enabled,
    staleTime: STALE,
    gcTime: GC,
    refetchInterval: () =>
      isLoanInFlight(qc, currentOrgId, loanId) ? IN_FLIGHT_POLL_MS : false,
    refetchIntervalInBackground: false,
  });
}

// ── Mutations ─────────────────────────────────────────────────────────

export function useConfirmClassification(loanId: string) {
  const { currentOrgId } = useOrg();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      docId,
      doc_type,
      notes,
    }: {
      docId: string;
      doc_type?: string | null;
      notes?: string | null;
    }) =>
      confirmLoanClassification(currentOrgId!, loanId, docId, {
        doc_type,
        notes,
      }),
    onSuccess: () => {
      // Confirmation may flip stack.requires_hitl + status, drain the
      // awaiting_review queue, and unlock advance — invalidate everything
      // the loan overview / doc-validation / queue pages render.
      qc.invalidateQueries({
        queryKey: ["lo-loan-documents", currentOrgId, loanId],
      });
      qc.invalidateQueries({
        queryKey: ["lo-loan-checklist", currentOrgId, loanId],
      });
      qc.invalidateQueries({ queryKey: ["lo-loans", currentOrgId] });
    },
  });
}

export function usePatchExtractionField(loanId: string, docId: string) {
  const { currentOrgId } = useOrg();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ fieldId, value }: { fieldId: string; value: string }) =>
      patchLoanExtractionField(currentOrgId!, loanId, docId, fieldId, value),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ["lo-loan-doc-extraction", currentOrgId, loanId, docId],
      });
    },
  });
}

/**
 * Re-run the extract stage on a single stack against the *current*
 * resolver schema. Use when admin schema edits land after the loan was
 * processed and the review screen is showing schema-driven placeholders
 * with empty values.
 */
export function useRerunExtraction(loanId: string, docId: string) {
  const { currentOrgId } = useOrg();
  const qc = useQueryClient();
  return useMutation<RerunExtractionResult, Error, void>({
    mutationFn: () => rerunLoanDocExtraction(currentOrgId!, loanId, docId),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ["lo-loan-doc-extraction", currentOrgId, loanId, docId],
      });
      // Doc grid surfaces extraction_status — refresh so the stack pill
      // moves out of "Extracting…" if it was still there.
      qc.invalidateQueries({
        queryKey: ["lo-loan-documents", currentOrgId, loanId],
      });
    },
  });
}

export function useAcknowledgeValidation(loanId: string) {
  const { currentOrgId } = useOrg();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      checkId,
      override_note,
    }: {
      checkId: string;
      override_note?: string;
    }) =>
      acknowledgeLoanValidation(currentOrgId!, loanId, checkId, override_note),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: ["lo-loan-validations", currentOrgId, loanId],
      });
    },
  });
}

export function useAdvanceLoan(loanId: string) {
  const { currentOrgId } = useOrg();
  const qc = useQueryClient();
  return useMutation<LoanAdvanceResponse, Error, void>({
    mutationFn: () => advanceLoan(currentOrgId!, loanId),
    onSuccess: () => {
      // Advance is the last step before decision_ready — refresh the
      // queue + every per-loan tab so the new status propagates.
      qc.invalidateQueries({ queryKey: ["lo-loans", currentOrgId] });
      qc.invalidateQueries({
        queryKey: ["lo-loan-documents", currentOrgId, loanId],
      });
      qc.invalidateQueries({
        queryKey: ["lo-loan-validations", currentOrgId, loanId],
      });
    },
  });
}

// ── Reject + re-upload (remediation modal) ────────────────────────────

function _invalidateLoanState(
  qc: ReturnType<typeof useQueryClient>,
  orgId: string,
  loanId: string
) {
  qc.invalidateQueries({ queryKey: ["lo-loan-documents", orgId, loanId] });
  qc.invalidateQueries({ queryKey: ["lo-loan-checklist", orgId, loanId] });
  qc.invalidateQueries({ queryKey: ["lo-loan-validations", orgId, loanId] });
  qc.invalidateQueries({ queryKey: ["lo-loan-audit-events", orgId, loanId] });
  qc.invalidateQueries({ queryKey: ["lo-loans", orgId] });
}

export function useRejectStack(loanId: string) {
  const { currentOrgId } = useOrg();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      docId,
      notes,
    }: {
      docId: string;
      notes?: string | null;
    }) => rejectLoanDocument(currentOrgId!, loanId, docId, notes),
    onSuccess: () => _invalidateLoanState(qc, currentOrgId!, loanId),
  });
}

export function useReuploadStack(loanId: string) {
  const { currentOrgId } = useOrg();
  const qc = useQueryClient();
  return useMutation<
    ReuploadLoanDocumentResult,
    Error,
    { docId: string; file: File; notes?: string | null }
  >({
    mutationFn: ({ docId, file, notes }) =>
      reuploadLoanDocument(currentOrgId!, loanId, docId, file, notes),
    onSuccess: () => _invalidateLoanState(qc, currentOrgId!, loanId),
  });
}

// ── Audit events (real timeline, replaces synthesis) ──────────────────

export function useLoanAuditEvents(loanId: string | null | undefined) {
  const { currentOrgId } = useOrg();
  const qc = useQueryClient();
  const enabled = Boolean(currentOrgId && loanId);
  return useQuery<LoanAuditEvent[]>({
    queryKey: ["lo-loan-audit-events", currentOrgId, loanId] as const,
    queryFn: () => getLoanAuditEvents(currentOrgId!, loanId!),
    enabled,
    staleTime: STALE,
    gcTime: GC,
    refetchInterval: () =>
      isLoanInFlight(qc, currentOrgId, loanId) ? IN_FLIGHT_POLL_MS : false,
    refetchIntervalInBackground: false,
  });
}
