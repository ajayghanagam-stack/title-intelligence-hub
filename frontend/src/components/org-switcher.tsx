"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "@/lib/api";
import { useOrgStore } from "@/stores/org-store";
import { cn } from "@/lib/utils";
import type { Org } from "@/lib/platform-types";

interface OrgSwitcherProps {
  variant?: "default" | "sidebar";
}

export function OrgSwitcher({ variant = "default" }: OrgSwitcherProps) {
  const [orgs, setOrgs] = useState<Org[]>([]);
  const { currentOrgId, setCurrentOrg } = useOrgStore();

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
      setCurrentOrg(orgs[0].id, orgs[0].name);
    }
  }, [orgs, currentOrgId, setCurrentOrg]);

  const isSidebar = variant === "sidebar";

  if (orgs.length <= 1) {
    return (
      <p
        className={cn(
          "text-sm mt-1",
          isSidebar ? "text-sidebar-foreground/60" : "text-muted-foreground"
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
        if (org) setCurrentOrg(org.id, org.name);
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
