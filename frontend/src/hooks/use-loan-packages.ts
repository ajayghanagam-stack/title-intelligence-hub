"use client";

import { useCallback, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
// useQueryClient is used by `remove` below to evict the per-package cache
// entry on delete so other mounted consumers don't briefly render a 404.
import { useOrg } from "@/hooks/use-org";
import {
  createPackage,
  deletePackage,
  getPackage,
  listPackages,
} from "@/lib/loan-onboarding/api";
import type {
  CreateLoanPackageInput,
} from "@/lib/loan-onboarding/api";
import type {
  LoanPackage,
  LoanPackageListItem,
} from "@/lib/loan-onboarding/types";

const TERMINAL_STATUSES = new Set([
  "completed",
  "failed",
  "awaiting_review",
]);

// 30s of fresh-cache behaviour for the per-package fetch. Within this window,
// re-mounting `useLoanPackage` (e.g., navigating between Results/Dashboard
// tabs, or revisiting a package from the Recent sidebar) returns the cached
// row immediately — no network round-trip, no spinner. React Query still
// background-revalidates after the window expires so live status pips stay
// truthful. We keep `gcTime` longer than `staleTime` so cache survives a brief
// unmount when the user clicks away and comes back.
const PACKAGE_STALE_TIME = 30_000;
const PACKAGE_GC_TIME = 5 * 60_000;
const PACKAGE_POLL_MS = 3000;

export function useLoanPackages() {
  const { currentOrgId } = useOrg();
  const queryClient = useQueryClient();
  const [packages, setPackages] = useState<LoanPackageListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchPackages = useCallback(async () => {
    if (!currentOrgId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await listPackages(currentOrgId);
      setPackages(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load packages");
      setPackages([]);
    } finally {
      setLoading(false);
    }
  }, [currentOrgId]);

  useEffect(() => {
    fetchPackages();
  }, [fetchPackages]);

  const create = useCallback(
    async (data: CreateLoanPackageInput) => {
      if (!currentOrgId) throw new Error("No organization selected");
      return createPackage(currentOrgId, data);
    },
    [currentOrgId]
  );

  const remove = useCallback(
    async (packageId: string) => {
      if (!currentOrgId) throw new Error("No organization selected");
      await deletePackage(currentOrgId, packageId);
      // Optimistic local update so the row disappears immediately.
      setPackages((prev) => prev.filter((p) => p.id !== packageId));
      // Drop the per-package React Query entry so a stray consumer (e.g. a
      // background tab still mounted) doesn't render the cached row after
      // the server has already returned 404. We remove rather than invalidate
      // because the package no longer exists — refetching would just 404.
      queryClient.removeQueries({
        queryKey: ["lo-package", currentOrgId, packageId],
      });
      queryClient.removeQueries({
        queryKey: ["lo", currentOrgId, packageId],
      });
      // Notify the sidebar (and any other listeners) so its "Recents" list
      // drops the deleted package without a manual refresh. The matching
      // handler is registered in `components/sidebar.tsx`.
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("loan-package-deleted", {
            detail: { packageId },
          })
        );
      }
    },
    [currentOrgId, queryClient]
  );

  return { packages, loading, error, refetch: fetchPackages, create, remove };
}

export function useLoanPackage(packageId: string | null | undefined) {
  const { currentOrgId } = useOrg();
  const queryClient = useQueryClient();
  const enabled = Boolean(currentOrgId && packageId);

  // Shared cache key — the layout, the page, and any sibling component that
  // calls `useLoanPackage(packageId)` in the same render tree all hit the
  // same React Query entry. Previously each call site had its own `useState`
  // + `setInterval`, so navigating to a package fired N parallel GETs and
  // started N parallel polls (one per consumer). With the shared cache there
  // is exactly one fetch and one poll regardless of how many tabs / status
  // pips read the data.
  const queryKey = ["lo-package", currentOrgId, packageId] as const;

  const query = useQuery<LoanPackage | null>({
    queryKey,
    queryFn: () => getPackage(currentOrgId!, packageId!),
    enabled,
    staleTime: PACKAGE_STALE_TIME,
    gcTime: PACKAGE_GC_TIME,
    // Stop polling once the pipeline reaches a terminal state. While running,
    // 3s polling keeps the status pip + processing tab in sync without
    // requiring an SSE pipe for the package row itself.
    refetchInterval: (q) => {
      const data = q.state.data;
      if (!data) return PACKAGE_POLL_MS;
      return TERMINAL_STATUSES.has(data.status) ? false : PACKAGE_POLL_MS;
    },
  });

  // Stable refetch handle. We avoid wrapping `query.refetch` directly because
  // its identity changes on every render — callers that put `refetch` in a
  // `useEffect` dep array would re-fire on every render. `queryClient` and
  // the (orgId, packageId) inputs are the actual stability surface.
  const refetch = useCallback(async (): Promise<LoanPackage | null> => {
    if (!currentOrgId || !packageId) return null;
    const data = await queryClient.fetchQuery<LoanPackage>({
      queryKey: ["lo-package", currentOrgId, packageId],
      queryFn: () => getPackage(currentOrgId, packageId),
      staleTime: 0,
    });
    return data ?? null;
  }, [queryClient, currentOrgId, packageId]);

  return {
    package: query.data ?? null,
    // `isPending` is true only on the very first fetch for a given key, so
    // callers that previously gated render on `loading` only blank the page
    // for genuinely-uncached packages. Cache hits return immediately with
    // `loading=false`, which is the whole point of the migration.
    loading: query.isPending && enabled,
    error: query.error
      ? query.error instanceof Error
        ? query.error.message
        : "Failed to load package"
      : null,
    refetch,
  };
}
