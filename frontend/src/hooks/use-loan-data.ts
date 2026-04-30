"use client";

/**
 * Shared TanStack Query hooks for loan-onboarding aux data.
 *
 * The Documents (Results), Dashboard, and Compliance tabs each need overlapping
 * subsets of the same six endpoints (stacks, validation results, page
 * overrides, extractions, extraction overrides, compliance run). Without a
 * shared cache, every tab switch re-issues the full Promise.all — for India →
 * us-east-1 round-trips that adds up to ~30-60s of waiting on a *completed*
 * package whose data hasn't actually changed.
 *
 * These hooks share one cache so:
 *   - First tab visit fetches once and warms the cache.
 *   - Subsequent tab navigation paints instantly (data is already there).
 *   - Mutations (Move-to / extraction edits) invalidate explicit keys.
 *
 * Terminal packages (`completed` / `failed` / `awaiting_review`) get
 * `staleTime: Infinity` because their backend state is immutable except via
 * the mutations we already invalidate from. Non-terminal packages get the
 * default 30s staleTime so processing-time UIs still see fresh data.
 */

import { useCallback } from "react";
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryKey,
} from "@tanstack/react-query";
import { useOrg } from "@/hooks/use-org";
import {
  applyPageOverride,
  deleteExtractionOverride,
  evaluateComplianceApi,
  getComplianceRun,
  getExtractions,
  getStacks,
  getValidationResults,
  listExtractionOverrides,
  listPageOverrides,
  removePageOverride,
  upsertExtractionOverride,
  type ComplianceRunPayload,
} from "@/lib/loan-onboarding/api";
import type {
  LoanContextInput,
  LoanExtractionOverride,
  LoanExtractionOverrideDelete,
  LoanExtractionOverrideUpsert,
  LoanPageOverride,
  LoanPageOverrideRequest,
  LoanPageOverrideResult,
  LoanStack,
  LoanStackExtraction,
  LoanValidationResult,
} from "@/lib/loan-onboarding/types";

const TERMINAL_STATUSES = new Set([
  "completed",
  "failed",
  "awaiting_review",
]);

export const loanDataKeys = {
  all: (orgId: string | null, packageId: string | null | undefined) =>
    ["loan-data", orgId, packageId] as const,
  stacks: (orgId: string | null, packageId: string | null | undefined) =>
    ["loan-data", orgId, packageId, "stacks"] as const,
  validation: (orgId: string | null, packageId: string | null | undefined) =>
    ["loan-data", orgId, packageId, "validation"] as const,
  pageOverrides: (
    orgId: string | null,
    packageId: string | null | undefined
  ) => ["loan-data", orgId, packageId, "page-overrides"] as const,
  extractions: (orgId: string | null, packageId: string | null | undefined) =>
    ["loan-data", orgId, packageId, "extractions"] as const,
  extractionOverrides: (
    orgId: string | null,
    packageId: string | null | undefined
  ) => ["loan-data", orgId, packageId, "extraction-overrides"] as const,
  compliance: (orgId: string | null, packageId: string | null | undefined) =>
    ["loan-data", orgId, packageId, "compliance"] as const,
};

/**
 * Pick a staleTime tuned to the package status. Terminal packages don't
 * change server-side except through mutations we already invalidate, so we
 * can hold their data forever (until gcTime evicts it). Non-terminal packages
 * fall back to the QueryClient default (30s).
 */
function staleTimeFor(status: string | null | undefined): number | undefined {
  if (status && TERMINAL_STATUSES.has(status)) return Infinity;
  return undefined; // use QueryClient default
}

interface LoanDataHookArgs {
  packageId: string | null | undefined;
  /** Current package status — drives staleTime so terminal packages cache forever. */
  packageStatus?: string | null;
}

export function useLoanStacks({ packageId, packageStatus }: LoanDataHookArgs) {
  const { currentOrgId } = useOrg();
  return useQuery<LoanStack[]>({
    queryKey: loanDataKeys.stacks(currentOrgId, packageId),
    queryFn: () => getStacks(currentOrgId as string, packageId as string),
    enabled: !!currentOrgId && !!packageId,
    staleTime: staleTimeFor(packageStatus),
  });
}

export function useLoanValidationResults({
  packageId,
  packageStatus,
}: LoanDataHookArgs) {
  const { currentOrgId } = useOrg();
  return useQuery<LoanValidationResult[]>({
    queryKey: loanDataKeys.validation(currentOrgId, packageId),
    queryFn: () =>
      getValidationResults(currentOrgId as string, packageId as string),
    enabled: !!currentOrgId && !!packageId,
    staleTime: staleTimeFor(packageStatus),
  });
}

export function useLoanPageOverrides({
  packageId,
  packageStatus,
}: LoanDataHookArgs) {
  const { currentOrgId } = useOrg();
  return useQuery<LoanPageOverride[]>({
    queryKey: loanDataKeys.pageOverrides(currentOrgId, packageId),
    queryFn: () =>
      listPageOverrides(currentOrgId as string, packageId as string),
    enabled: !!currentOrgId && !!packageId,
    staleTime: staleTimeFor(packageStatus),
  });
}

export function useLoanExtractions({
  packageId,
  packageStatus,
}: LoanDataHookArgs) {
  const { currentOrgId } = useOrg();
  return useQuery<LoanStackExtraction[]>({
    queryKey: loanDataKeys.extractions(currentOrgId, packageId),
    queryFn: () =>
      getExtractions(currentOrgId as string, packageId as string).then(
        (r) => r.stacks
      ),
    enabled: !!currentOrgId && !!packageId,
    staleTime: staleTimeFor(packageStatus),
  });
}

export function useLoanExtractionOverrides({
  packageId,
  packageStatus,
}: LoanDataHookArgs) {
  const { currentOrgId } = useOrg();
  return useQuery<LoanExtractionOverride[]>({
    queryKey: loanDataKeys.extractionOverrides(currentOrgId, packageId),
    queryFn: () =>
      listExtractionOverrides(currentOrgId as string, packageId as string),
    enabled: !!currentOrgId && !!packageId,
    staleTime: staleTimeFor(packageStatus),
  });
}

/**
 * GET /compliance — backend evaluates-if-missing-or-returns-cached. We use
 * GET (not POST /evaluate) because:
 *   - First-time visits hit the cached run on every tab switch back, instead
 *     of re-evaluating against the same inputs.
 *   - Compliance state only changes when (a) the LO edits loan_context (the
 *     PATCH endpoint already persists a fresh run, we just refetch) or
 *     (b) doc inventory changes (mutations invalidate this key).
 *
 * The previous implementation called POST /evaluate inside a useEffect with
 * `pkg` in the deps — every package refetch triggered a fresh evaluation,
 * which on a complex loan package is *not* free.
 */
export function useLoanCompliance({
  packageId,
  packageStatus,
}: LoanDataHookArgs) {
  const { currentOrgId } = useOrg();
  return useQuery<ComplianceRunPayload>({
    queryKey: loanDataKeys.compliance(currentOrgId, packageId),
    queryFn: () =>
      getComplianceRun(currentOrgId as string, packageId as string),
    enabled: !!currentOrgId && !!packageId,
    staleTime: staleTimeFor(packageStatus),
  });
}

// ─── Mutations ─────────────────────────────────────────────────────────────

/**
 * Page override (Move-to-stack) mutations. Invalidates everything downstream
 * because the rebuild can shift stacks, validation results, and extractions.
 */
export function usePageOverrideMutations(packageId: string) {
  const { currentOrgId } = useOrg();
  const queryClient = useQueryClient();

  const invalidateAll = useCallback(() => {
    if (!currentOrgId) return;
    const keys: QueryKey[] = [
      loanDataKeys.stacks(currentOrgId, packageId),
      loanDataKeys.validation(currentOrgId, packageId),
      loanDataKeys.pageOverrides(currentOrgId, packageId),
      loanDataKeys.extractions(currentOrgId, packageId),
      loanDataKeys.compliance(currentOrgId, packageId),
    ];
    keys.forEach((queryKey) =>
      queryClient.invalidateQueries({ queryKey })
    );
  }, [currentOrgId, packageId, queryClient]);

  const apply = useMutation<
    LoanPageOverrideResult,
    Error,
    { pageId: string; body: LoanPageOverrideRequest }
  >({
    mutationFn: ({ pageId, body }) => {
      if (!currentOrgId) throw new Error("No organization selected");
      return applyPageOverride(currentOrgId, packageId, pageId, body);
    },
    onSuccess: invalidateAll,
  });

  const remove = useMutation<LoanPageOverrideResult, Error, string>({
    mutationFn: (pageId) => {
      if (!currentOrgId) throw new Error("No organization selected");
      return removePageOverride(currentOrgId, packageId, pageId);
    },
    onSuccess: invalidateAll,
  });

  return { apply, remove };
}

/**
 * Reviewer-edited field overrides. Only invalidates the extraction-overrides
 * cache — saves don't shift stacks or compliance, just the persisted "Reviewed
 * value" we surface in the workbench.
 */
export function useExtractionOverrideMutations(packageId: string) {
  const { currentOrgId } = useOrg();
  const queryClient = useQueryClient();

  const upsert = useMutation<
    LoanExtractionOverride,
    Error,
    LoanExtractionOverrideUpsert
  >({
    mutationFn: (body) => {
      if (!currentOrgId) throw new Error("No organization selected");
      return upsertExtractionOverride(currentOrgId, packageId, body);
    },
    onSuccess: () => {
      if (!currentOrgId) return;
      queryClient.invalidateQueries({
        queryKey: loanDataKeys.extractionOverrides(currentOrgId, packageId),
      });
    },
  });

  const remove = useMutation<
    { removed: boolean },
    Error,
    LoanExtractionOverrideDelete
  >({
    mutationFn: (body) => {
      if (!currentOrgId) throw new Error("No organization selected");
      return deleteExtractionOverride(currentOrgId, packageId, body);
    },
    onSuccess: () => {
      if (!currentOrgId) return;
      queryClient.invalidateQueries({
        queryKey: loanDataKeys.extractionOverrides(currentOrgId, packageId),
      });
    },
  });

  return { upsert, remove };
}

/**
 * Force a fresh compliance evaluation (POST /evaluate). Use this only after
 * the loan context has been edited — normal page loads should call
 * `useLoanCompliance` (GET, cached). On success, replaces the cached run
 * so the UI re-renders against the new evaluation.
 */
export function useEvaluateCompliance(packageId: string) {
  const { currentOrgId } = useOrg();
  const queryClient = useQueryClient();

  return useMutation<ComplianceRunPayload, Error, void>({
    mutationFn: () => {
      if (!currentOrgId) throw new Error("No organization selected");
      return evaluateComplianceApi(currentOrgId, packageId);
    },
    onSuccess: (payload) => {
      if (!currentOrgId) return;
      queryClient.setQueryData<ComplianceRunPayload>(
        loanDataKeys.compliance(currentOrgId, packageId),
        payload
      );
    },
  });
}

/**
 * Compliance context PATCH already persists a fresh run server-side
 * (compliance_service.update_loan_context → evaluate(persist=True)). After
 * the PATCH resolves, callers should invalidate the compliance + package
 * keys so the next read pulls the persisted run + new context snapshot.
 */
export function useInvalidateCompliance(packageId: string) {
  const { currentOrgId } = useOrg();
  const queryClient = useQueryClient();

  return useCallback(
    async (newContext?: LoanContextInput) => {
      void newContext; // for callers that want to log the patched value
      if (!currentOrgId) return;
      await Promise.all([
        queryClient.invalidateQueries({
          queryKey: loanDataKeys.compliance(currentOrgId, packageId),
        }),
        // Package detail carries `loan_context`, which the compliance header
        // reads back from useLoanPackage. Invalidate it too.
        queryClient.invalidateQueries({
          queryKey: ["loan-packages", "detail", currentOrgId, packageId],
        }),
      ]);
    },
    [currentOrgId, packageId, queryClient]
  );
}
