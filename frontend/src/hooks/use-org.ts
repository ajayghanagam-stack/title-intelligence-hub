"use client";

import { useCallback, useRef } from "react";
import { useOrgStore } from "@/stores/org-store";
import { apiFetch, apiFetchBlob } from "@/lib/api";

export function useOrg() {
  const { currentOrgId, currentOrgName, setCurrentOrg, clearOrg } =
    useOrgStore();

  // Use a ref so orgFetch always sees the latest orgId without being recreated
  const orgIdRef = useRef(currentOrgId);
  orgIdRef.current = currentOrgId;

  const orgFetch = useCallback(<T = unknown>(path: string, options: RequestInit = {}): Promise<T> => {
    if (!orgIdRef.current) {
      throw new Error("No organization selected");
    }
    return apiFetch<T>(path, { ...options, orgId: orgIdRef.current });
  }, []);

  const orgFetchBlob = useCallback((path: string, options: RequestInit = {}) => {
    if (!orgIdRef.current) {
      throw new Error("No organization selected");
    }
    return apiFetchBlob(path, { ...options, orgId: orgIdRef.current });
  }, []);

  return {
    currentOrgId,
    currentOrgName,
    setCurrentOrg,
    clearOrg,
    orgFetch,
    orgFetchBlob,
  };
}
