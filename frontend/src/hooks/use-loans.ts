"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useOrg } from "@/hooks/use-org";
import { deletePackage, listLoans } from "@/lib/loan-onboarding/api";
import type { LoanPackageListItem } from "@/lib/loan-onboarding/types";

// Phase 5.2 — LogikIntake queue page data source.
//
// This hook is intentionally separate from `useLoanPackages` (which still
// powers the legacy `/packages` UI). It targets the new `/loans` alias so
// the queue page is decoupled from the legacy URL ahead of the Phase 4.9
// redirect cutover. Within an org, the queue is short-lived data so we
// keep a small staleTime and let the user pull-to-refresh via refetch.
const LOANS_STALE_TIME = 15_000;
const LOANS_GC_TIME = 5 * 60_000;
// Active poll cadence while at least one loan is still moving through
// the pipeline. 3s matches the pipeline status poll used by the loan
// overview page — fast enough that "Processing" → "Decision Ready" /
// "Needs Review" flips visibly without manual refresh, slow enough not
// to hammer the list endpoint on large queues.
const LOANS_ACTIVE_POLL_MS = 3_000;

// Statuses that mean "the pipeline is still doing work in the
// background". Anything else is a terminal state (decision_ready,
// completed, awaiting_review, failed, …) and doesn't need polling.
const IN_FLIGHT_STATUSES = new Set(["uploading", "processing"]);

function hasInFlightLoan(loans: LoanPackageListItem[] | undefined): boolean {
  if (!loans || loans.length === 0) return false;
  return loans.some((l) => IN_FLIGHT_STATUSES.has(l.status));
}

export function useLoans() {
  const { currentOrgId } = useOrg();
  const enabled = Boolean(currentOrgId);

  const query = useQuery<LoanPackageListItem[]>({
    queryKey: ["lo-loans", currentOrgId] as const,
    queryFn: () => listLoans(currentOrgId!),
    enabled,
    staleTime: LOANS_STALE_TIME,
    gcTime: LOANS_GC_TIME,
    // Auto-refresh while anything is still in flight. The function form
    // is re-evaluated after every fetch, so the moment the last loan
    // settles to a terminal status, polling stops on its own without us
    // having to wire an explicit "done" signal. When the user returns
    // to the tab, `refetchOnWindowFocus` (react-query default) picks up
    // anything we missed during the idle window.
    refetchInterval: (q) =>
      hasInFlightLoan(q.state.data) ? LOANS_ACTIVE_POLL_MS : false,
    refetchIntervalInBackground: false,
  });

  return {
    loans: query.data ?? [],
    loading: query.isPending && enabled,
    error: query.error
      ? query.error instanceof Error
        ? query.error.message
        : "Failed to load loans"
      : null,
    refetch: query.refetch,
  };
}

/**
 * Delete a loan package end-to-end: storage prefix + DB row + every
 * FK-cascaded child table (files, pages, classifications, stacks,
 * validations, HITL reviews, overrides, pipeline runs, audit rows).
 *
 * Optimistic update strips the row from the queue cache immediately so
 * the table doesn't flicker while the DELETE round-trips. Rolled back on
 * failure; the queue query is invalidated on settle either way so any
 * server-side fan-out (e.g. another tab adding a file) reconverges.
 */
export function useDeleteLoan() {
  const { currentOrgId } = useOrg();
  const queryClient = useQueryClient();

  return useMutation<void, Error, string, { previous?: LoanPackageListItem[] }>({
    mutationFn: (loanId: string) => {
      if (!currentOrgId) {
        return Promise.reject(new Error("No active organization"));
      }
      return deletePackage(currentOrgId, loanId);
    },
    onMutate: async (loanId) => {
      const key = ["lo-loans", currentOrgId] as const;
      await queryClient.cancelQueries({ queryKey: key });
      const previous =
        queryClient.getQueryData<LoanPackageListItem[]>(key);
      if (previous) {
        queryClient.setQueryData<LoanPackageListItem[]>(
          key,
          previous.filter((l) => l.id !== loanId),
        );
      }
      return { previous };
    },
    onError: (_err, _loanId, ctx) => {
      if (ctx?.previous) {
        queryClient.setQueryData(
          ["lo-loans", currentOrgId],
          ctx.previous,
        );
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({
        queryKey: ["lo-loans", currentOrgId],
      });
    },
  });
}
