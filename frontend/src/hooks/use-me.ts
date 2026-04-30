"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchMe, getToken, type MeResponse } from "@/lib/auth";
import { useOrgStore } from "@/stores/org-store";

/**
 * Single source of truth for the bootstrap payload (user + orgs +
 * is_platform_admin + active-org subscriptions). Cached by TanStack Query so
 * tab switches and consumer hooks (`useAuth`, dashboard subs, platform layout)
 * share one round trip.
 *
 * Cache key includes the active org id so changing orgs refetches cleanly
 * (the `subscriptions` field is org-scoped). Without a token we short-circuit
 * to `null` — `enabled` keeps the query idle until the user logs in.
 */
export function useMe() {
  const { currentOrgId } = useOrgStore();

  return useQuery<MeResponse | null>({
    queryKey: ["me", currentOrgId],
    queryFn: () => fetchMe(currentOrgId),
    enabled: typeof window !== "undefined" && !!getToken(),
    staleTime: 30 * 1000,
  });
}
