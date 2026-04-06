"use client";

import { useCallback, useEffect, useState } from "react";
import { getToken, fetchMe, signOut as authSignOut } from "@/lib/auth";
import { useOrgStore } from "@/stores/org-store";
import type { AuthUser } from "@/lib/platform-types";

/**
 * Auth hook returns { user, isPlatformAdmin, loading, signOut } instead of the
 * standard { data, loading } shape — intentional since auth state is a singleton
 * with role flags and an action (signOut), not a fetchable resource.
 */
export function useAuth() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isPlatformAdmin, setIsPlatformAdmin] = useState(false);
  const [loading, setLoading] = useState(true);
  const { currentOrgSlug } = useOrgStore();

  useEffect(() => {
    const token = getToken();
    if (!token) {
      setUser(null);
      setLoading(false);
      return;
    }

    fetchMe()
      .then((data) => {
        setUser(data?.user ?? null);
        setIsPlatformAdmin(data?.is_platform_admin ?? false);
      })
      .catch(() => {
        setUser(null);
      })
      .finally(() => {
        setLoading(false);
      });
  }, []);

  const signOut = useCallback(() => {
    authSignOut(currentOrgSlug ?? undefined);
  }, [currentOrgSlug]);

  return { user, isPlatformAdmin, loading, signOut };
}
