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

export function useStacksQuery(orgId: string | null, packageId: string) {
  return useQuery({
    queryKey: key(orgId, packageId, LO_QUERY_KINDS.stacks),
    queryFn: () => getStacks(orgId!, packageId),
    enabled: enabled(orgId, packageId),
  });
}

export function useValidationResultsQuery(
  orgId: string | null,
  packageId: string,
) {
  return useQuery({
    queryKey: key(orgId, packageId, LO_QUERY_KINDS.validation),
    queryFn: () => getValidationResults(orgId!, packageId),
    enabled: enabled(orgId, packageId),
  });
}

export function usePageOverridesQuery(
  orgId: string | null,
  packageId: string,
) {
  return useQuery({
    queryKey: key(orgId, packageId, LO_QUERY_KINDS.pageOverrides),
    queryFn: () => listPageOverrides(orgId!, packageId),
    enabled: enabled(orgId, packageId),
  });
}

export function useExtractionsQuery(orgId: string | null, packageId: string) {
  return useQuery({
    queryKey: key(orgId, packageId, LO_QUERY_KINDS.extractions),
    queryFn: () => getExtractions(orgId!, packageId).then((r) => r.stacks),
    enabled: enabled(orgId, packageId),
  });
}

export function useExtractionOverridesQuery(
  orgId: string | null,
  packageId: string,
) {
  return useQuery({
    queryKey: key(orgId, packageId, LO_QUERY_KINDS.extractionOverrides),
    queryFn: () => listExtractionOverrides(orgId!, packageId),
    enabled: enabled(orgId, packageId),
  });
}

export function useComplianceQuery(orgId: string | null, packageId: string) {
  return useQuery({
    queryKey: key(orgId, packageId, LO_QUERY_KINDS.compliance),
    queryFn: () => getComplianceRun(orgId!, packageId),
    enabled: enabled(orgId, packageId),
  });
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
