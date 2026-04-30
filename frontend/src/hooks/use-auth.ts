"use client";

import { useCallback } from "react";
import { getToken, signOut as authSignOut } from "@/lib/auth";
import { useOrgStore } from "@/stores/org-store";
import { useMe } from "@/hooks/use-me";

/**
 * Auth hook returns { user, isPlatformAdmin, loading, signOut } instead of the
 * standard { data, loading } shape — intentional since auth state is a singleton
 * with role flags and an action (signOut), not a fetchable resource.
 *
 * Backed by `useMe`, so the `/auth/me` round trip is shared with any other
 * component that needs orgs/subscriptions (platform layout, dashboard).
 */
export function useAuth() {
  const { currentOrgSlug } = useOrgStore();
  const hasToken = typeof window !== "undefined" && !!getToken();
  const { data, isLoading, isFetching } = useMe();

  // Without a token the query is disabled (never runs), so `isLoading` stays
  // true forever. Treat "no token" as fully resolved → not authenticated.
  const loading = hasToken ? isLoading || isFetching : false;

  const signOut = useCallback(() => {
    authSignOut(currentOrgSlug ?? undefined);
  }, [currentOrgSlug]);

  return {
    user: data?.user ?? null,
    isPlatformAdmin: data?.is_platform_admin ?? false,
    loading,
    signOut,
  };
}
