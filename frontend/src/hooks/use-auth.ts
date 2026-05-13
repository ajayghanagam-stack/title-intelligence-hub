"use client";

import { useCallback, useEffect, useState } from "react";
import { getToken, fetchMe, signOut as authSignOut } from "@/lib/auth";
import { useOrgStore } from "@/stores/org-store";
import type { AuthUser } from "@/lib/platform-types";

export interface AuthOrgMembership {
  id: string;
  name: string;
  slug: string;
  logo_url: string | null;
  role: string | null;
}

/**
 * Auth hook returns { user, isPlatformAdmin, orgs, loading, signOut } instead
 * of the standard { data, loading } shape — intentional since auth state is a
 * singleton with role flags and an action (signOut), not a fetchable resource.
 *
 * `orgs` carries per-org role so the UI can gate admin-only widgets (e.g. the
 * Loan Onboarding Admin sidebar group) without a separate membership fetch.
 */
export function useAuth() {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isPlatformAdmin, setIsPlatformAdmin] = useState(false);
  const [orgs, setOrgs] = useState<AuthOrgMembership[]>([]);
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
        setOrgs(data?.orgs ?? []);
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

  return { user, isPlatformAdmin, orgs, loading, signOut };
}
