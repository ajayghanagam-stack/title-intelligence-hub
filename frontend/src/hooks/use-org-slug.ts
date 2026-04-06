"use client";

import { useParams } from "next/navigation";
import { useOrgStore } from "@/stores/org-store";
import { orgPath as buildOrgPath } from "@/lib/paths";
import { useCallback } from "react";

/**
 * Returns the current org slug from URL params (preferred) or Zustand store (fallback).
 * Also provides a helper to build org-scoped paths.
 *
 * When inside /org/{slug}/ routes, paths are prefixed with /org/{slug}.
 * When inside legacy (platform) routes (no slug in URL), paths are returned as-is.
 */
export function useOrgSlug() {
  const params = useParams();
  const { currentOrgSlug } = useOrgStore();

  // URL slug takes priority — means we're in the /org/{slug}/ route group
  const urlSlug = params?.orgSlug as string | undefined;
  const slug = urlSlug || currentOrgSlug || "";
  const isOrgRoute = !!urlSlug;

  const orgPath = useCallback(
    (path: string) => (isOrgRoute && slug ? buildOrgPath(slug, path) : path),
    [isOrgRoute, slug]
  );

  return { orgSlug: slug, orgPath, isOrgRoute };
}
