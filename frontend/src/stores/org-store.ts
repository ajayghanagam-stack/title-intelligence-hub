import { create } from "zustand";
import { persist } from "zustand/middleware";

interface OrgState {
  currentOrgId: string | null;
  currentOrgName: string | null;
  currentOrgSlug: string | null;
  currentOrgLogoUrl: string | null;
  setCurrentOrg: (orgId: string, orgName: string, orgSlug?: string, logoUrl?: string | null) => void;
  clearOrg: () => void;
}

export const useOrgStore = create<OrgState>()(
  persist(
    (set) => ({
      currentOrgId: null,
      currentOrgName: null,
      currentOrgSlug: null,
      currentOrgLogoUrl: null,
      setCurrentOrg: (orgId, orgName, orgSlug, logoUrl) =>
        set({
          currentOrgId: orgId,
          currentOrgName: orgName,
          currentOrgSlug: orgSlug ?? null,
          currentOrgLogoUrl: logoUrl ?? null,
        }),
      clearOrg: () =>
        set({ currentOrgId: null, currentOrgName: null, currentOrgSlug: null, currentOrgLogoUrl: null }),
    }),
    { name: "org-store" }
  )
);
