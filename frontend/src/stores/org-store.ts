import { create } from "zustand";
import { persist } from "zustand/middleware";

interface OrgState {
  currentOrgId: string | null;
  currentOrgName: string | null;
  setCurrentOrg: (orgId: string, orgName: string) => void;
  clearOrg: () => void;
}

export const useOrgStore = create<OrgState>()(
  persist(
    (set) => ({
      currentOrgId: null,
      currentOrgName: null,
      setCurrentOrg: (orgId, orgName) =>
        set({ currentOrgId: orgId, currentOrgName: orgName }),
      clearOrg: () => set({ currentOrgId: null, currentOrgName: null }),
    }),
    { name: "org-store" }
  )
);
