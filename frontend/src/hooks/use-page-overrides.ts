"use client";

import { useCallback, useEffect, useState } from "react";

import { useOrg } from "@/hooks/use-org";
import {
  applyPageOverride,
  listPageOverrides,
  removePageOverride,
} from "@/lib/loan-onboarding/api";
import type {
  LoanOverrideRebuildSummary,
  LoanPageOverride,
  LoanPageOverrideRequest,
  LoanPageOverrideResult,
} from "@/lib/loan-onboarding/types";

/**
 * Hook for the "Move to…" flow. Wraps the override list + single-page mutate
 * endpoints, exposes the rebuild summary from the last mutation so callers
 * can toast the blast radius (e.g. "3 stacks now need review"), and keeps an
 * in-memory override list so the Documents tab can badge moved pages without
 * re-fetching.
 */
export function usePageOverrides(packageId: string | null | undefined) {
  const { currentOrgId } = useOrg();

  const [overrides, setOverrides] = useState<LoanPageOverride[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingPageId, setPendingPageId] = useState<string | null>(null);
  const [lastRebuild, setLastRebuild] =
    useState<LoanOverrideRebuildSummary | null>(null);

  const refetch = useCallback(async () => {
    if (!currentOrgId || !packageId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await listPageOverrides(currentOrgId, packageId);
      setOverrides(data);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load overrides"
      );
      setOverrides([]);
    } finally {
      setLoading(false);
    }
  }, [currentOrgId, packageId]);

  useEffect(() => {
    refetch();
  }, [refetch]);

  const overrideByPageId = useCallback(
    (pageId: string) => overrides.find((o) => o.page_id === pageId) ?? null,
    [overrides]
  );

  const applyOverride = useCallback(
    async (
      pageId: string,
      body: LoanPageOverrideRequest
    ): Promise<LoanPageOverrideResult> => {
      if (!currentOrgId || !packageId) {
        throw new Error("No organization or package selected");
      }
      setPendingPageId(pageId);
      setError(null);
      try {
        const result = await applyPageOverride(
          currentOrgId,
          packageId,
          pageId,
          body
        );
        setLastRebuild(result.rebuild);
        // Replace-or-insert the new override locally so the UI doesn't wait
        // on a follow-up list fetch to badge the page.
        if (result.override) {
          setOverrides((prev) => {
            const next = prev.filter((o) => o.page_id !== pageId);
            next.push(result.override!);
            return next;
          });
        }
        return result;
      } catch (err) {
        setError(err instanceof Error ? err.message : "Move failed");
        throw err;
      } finally {
        setPendingPageId(null);
      }
    },
    [currentOrgId, packageId]
  );

  const clearOverride = useCallback(
    async (pageId: string): Promise<LoanPageOverrideResult> => {
      if (!currentOrgId || !packageId) {
        throw new Error("No organization or package selected");
      }
      setPendingPageId(pageId);
      setError(null);
      try {
        const result = await removePageOverride(
          currentOrgId,
          packageId,
          pageId
        );
        setLastRebuild(result.rebuild);
        setOverrides((prev) => prev.filter((o) => o.page_id !== pageId));
        return result;
      } catch (err) {
        setError(err instanceof Error ? err.message : "Undo failed");
        throw err;
      } finally {
        setPendingPageId(null);
      }
    },
    [currentOrgId, packageId]
  );

  return {
    overrides,
    overrideByPageId,
    loading,
    error,
    pendingPageId,
    lastRebuild,
    refetch,
    applyOverride,
    clearOverride,
  };
}
