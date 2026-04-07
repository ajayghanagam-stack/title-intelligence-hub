"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api";
import { useOrgStore } from "@/stores/org-store";
import { useOrgSlug } from "@/hooks/use-org-slug";
import { setOrgSlugCookie } from "@/lib/auth";
import { cn } from "@/lib/utils";
import type { Org } from "@/lib/platform-types";

interface OrgSwitcherProps {
  variant?: "default" | "sidebar";
}

export function OrgSwitcher({ variant = "default" }: OrgSwitcherProps) {
  const [orgs, setOrgs] = useState<Org[]>([]);
  const { currentOrgId, setCurrentOrg } = useOrgStore();
  const { isOrgRoute } = useOrgSlug();
  const router = useRouter();

  useEffect(() => {
    apiFetch<Org[]>("/api/v1/organizations/me")
      .then(setOrgs)
      .catch(() => {
        /* Auth redirect handles 401; org list is fetched elsewhere too */
      });
  }, []);

  // Auto-select first org if none selected
  useEffect(() => {
    if (!currentOrgId && orgs.length > 0) {
      setCurrentOrg(orgs[0].id, orgs[0].name, orgs[0].slug, orgs[0].logo_url);
    }
  }, [orgs, currentOrgId, setCurrentOrg]);

  const isSidebar = variant === "sidebar";

  // Hide completely for single org in sidebar (logo is shown at top)
  if (orgs.length <= 1) {
    if (isSidebar) {
      return null;
    }
    return (
      <p
        className={cn(
          "text-sm mt-1",
          "text-muted-foreground"
        )}
      >
        {orgs[0]?.name || "No organization"}
      </p>
    );
  }

  return (
    <select
      aria-label="Select organization"
      className={cn(
        "mt-1 w-full rounded-md px-2 py-1.5 text-sm transition-colors",
        isSidebar
          ? "bg-sidebar-muted border-sidebar-border text-sidebar-foreground focus:ring-sidebar-ring"
          : "border border-input bg-background focus:ring-ring"
      )}
      value={currentOrgId || ""}
      onChange={(e) => {
        const org = orgs.find((o) => o.id === e.target.value);
        if (org) {
          setCurrentOrg(org.id, org.name, org.slug, org.logo_url);
          setOrgSlugCookie(org.slug);
          // Navigate to the new org's dashboard
          if (isOrgRoute) {
            router.push(`/org/${org.slug}/dashboard`);
          }
        }
      }}
    >
      {orgs.map((org) => (
        <option key={org.id} value={org.id}>
          {org.name}
        </option>
      ))}
    </select>
  );
}
