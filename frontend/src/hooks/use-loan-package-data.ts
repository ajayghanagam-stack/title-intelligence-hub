"use client";

import { useCallback } from "react";
import { useQueryClient, useQuery } from "@tanstack/react-query";
import {
  getComplianceRun,
  getExtractions,
  getStacks,
  getValidationResults,
  listExtractionOverrides,
  listPageOverrides,
} from "@/lib/loan-onboarding/api";

/**
 * Centralised React Query hooks for the per-package data the dashboard,
 * results, and compliance tabs all need. Switching tabs hits the cache (no
 * refetch) within `staleTime`, so the second tab visit is instant.
 *
 * Cache key shape: `["lo", orgId, packageId, kind]`. Bump kinds in
 * `LO_QUERY_KINDS` so call sites stay typo-safe and `invalidatePackage()`
 * touches every kind in one call.
 */

export const LO_QUERY_KINDS = {
  stacks: "stacks",
  validation: "validation",
  pageOverrides: "page-overrides",
  extractions: "extractions",
  extractionOverrides: "extraction-overrides",
  compliance: "compliance",
} as const;

type Kind = (typeof LO_QUERY_KINDS)[keyof typeof LO_QUERY_KINDS];

const key = (orgId: string | null, packageId: string, kind: Kind) =>
  ["lo", orgId, packageId, kind] as const;

const enabled = (orgId: string | null | undefined, packageId: string) =>
  Boolean(orgId && packageId);

// Per-package data is treated as fresh for 60s. That covers the common
// "click around the Recent sidebar" pattern: revisiting a package within a
// minute returns instantly from cache instead of waterfalling four GETs
// (`/stacks`, `/validation-results`, `/overrides`, `/extractions`) every
// time. After 60s React Query background-revalidates on next mount.
//
// The pipeline-terminal effect on the results page already invalidates the
// whole `["lo", orgId, packageId]` subtree when the package finishes
// processing, so a stale cache from a not-yet-completed run is replaced with
// the post-completion data the moment we observe the terminal status — not
// 60s later.
const STALE_TIME = 60_000;
const GC_TIME = 5 * 60_000;

const baseQuery = <T,>(
  queryKey: readonly unknown[],
  queryFn: () => Promise<T>,
  isEnabled: boolean,
) => ({
  queryKey,
  queryFn,
  enabled: isEnabled,
  staleTime: STALE_TIME,
  gcTime: GC_TIME,
});

export function useStacksQuery(orgId: string | null, packageId: string) {
  return useQuery(
    baseQuery(
      key(orgId, packageId, LO_QUERY_KINDS.stacks),
      () => getStacks(orgId!, packageId),
      enabled(orgId, packageId),
    ),
  );
}

export function useValidationResultsQuery(
  orgId: string | null,
  packageId: string,
) {
  return useQuery(
    baseQuery(
      key(orgId, packageId, LO_QUERY_KINDS.validation),
      () => getValidationResults(orgId!, packageId),
      enabled(orgId, packageId),
    ),
  );
}

export function usePageOverridesQuery(
  orgId: string | null,
  packageId: string,
) {
  return useQuery(
    baseQuery(
      key(orgId, packageId, LO_QUERY_KINDS.pageOverrides),
      () => listPageOverrides(orgId!, packageId),
      enabled(orgId, packageId),
    ),
  );
}

export function useExtractionsQuery(orgId: string | null, packageId: string) {
  return useQuery(
    baseQuery(
      key(orgId, packageId, LO_QUERY_KINDS.extractions),
      () => getExtractions(orgId!, packageId).then((r) => r.stacks),
      enabled(orgId, packageId),
    ),
  );
}

export function useExtractionOverridesQuery(
  orgId: string | null,
  packageId: string,
) {
  return useQuery(
    baseQuery(
      key(orgId, packageId, LO_QUERY_KINDS.extractionOverrides),
      () => listExtractionOverrides(orgId!, packageId),
      enabled(orgId, packageId),
    ),
  );
}

export function useComplianceQuery(orgId: string | null, packageId: string) {
  return useQuery(
    baseQuery(
      key(orgId, packageId, LO_QUERY_KINDS.compliance),
      () => getComplianceRun(orgId!, packageId),
      enabled(orgId, packageId),
    ),
  );
}

/**
 * Invalidate every cached query for a package. Call when the pipeline
 * transitions to a terminal state, when a page override / extraction override
 * is mutated, or when compliance context is edited — anything that can change
 * the underlying server data.
 */
export function useInvalidateLoanPackage() {
  const qc = useQueryClient();
  // Memoize so callers can safely include the returned function in
  // `useEffect` / `useCallback` dependency arrays without firing on every
  // render. Previously this returned a fresh arrow on every render, which
  // caused the results page's "pipeline-terminal → invalidate" effect to
  // re-fire on every render, which in turn refetched and re-rendered, etc.
  // — an infinite loop that prevented the Results tab from settling.
  return useCallback(
    (orgId: string | null, packageId: string) =>
      qc.invalidateQueries({ queryKey: ["lo", orgId, packageId] }),
    [qc],
  );
}
