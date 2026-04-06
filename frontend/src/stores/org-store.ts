import { create } from "zustand";
import { persist } from "zustand/middleware";

interface OrgState {
  currentOrgId: string | null;
  currentOrgName: string | null;
  currentOrgSlug: string | null;
  setCurrentOrg: (orgId: string, orgName: string, orgSlug?: string) => void;
  clearOrg: () => void;
}

export const useOrgStore = create<OrgState>()(
  persist(
    (set) => ({
      currentOrgId: null,
      currentOrgName: null,
      currentOrgSlug: null,
      setCurrentOrg: (orgId, orgName, orgSlug) =>
        set({ currentOrgId: orgId, currentOrgName: orgName, currentOrgSlug: orgSlug ?? null }),
      clearOrg: () => set({ currentOrgId: null, currentOrgName: null, currentOrgSlug: null }),
    }),
    { name: "org-store" }
  )
);
