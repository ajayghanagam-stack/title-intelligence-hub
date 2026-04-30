"use client";

import { useCallback, useEffect, useState } from "react";
import { useOrg } from "@/hooks/use-org";
import {
  createPackage,
  deletePackage,
  getPackage,
  listPackages,
} from "@/lib/loan-onboarding/api";
import type {
  CreateLoanPackageInput,
} from "@/lib/loan-onboarding/api";
import type {
  LoanPackage,
  LoanPackageListItem,
} from "@/lib/loan-onboarding/types";

export function useLoanPackages() {
  const { currentOrgId } = useOrg();
  const [packages, setPackages] = useState<LoanPackageListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchPackages = useCallback(async () => {
    if (!currentOrgId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await listPackages(currentOrgId);
      setPackages(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load packages");
      setPackages([]);
    } finally {
      setLoading(false);
    }
  }, [currentOrgId]);

  useEffect(() => {
    fetchPackages();
  }, [fetchPackages]);

  const create = useCallback(
    async (data: CreateLoanPackageInput) => {
      if (!currentOrgId) throw new Error("No organization selected");
      return createPackage(currentOrgId, data);
    },
    [currentOrgId]
  );

  const remove = useCallback(
    async (packageId: string) => {
      if (!currentOrgId) throw new Error("No organization selected");
      await deletePackage(currentOrgId, packageId);
      // Optimistic local update so the row disappears immediately.
      setPackages((prev) => prev.filter((p) => p.id !== packageId));
      // Notify the sidebar (and any other listeners) so its "Recents" list
      // drops the deleted package without a manual refresh. The matching
      // handler is registered in `components/sidebar.tsx`.
      if (typeof window !== "undefined") {
        window.dispatchEvent(
          new CustomEvent("loan-package-deleted", {
            detail: { packageId },
          })
        );
      }
    },
    [currentOrgId]
  );

  return { packages, loading, error, refetch: fetchPackages, create, remove };
}

export function useLoanPackage(packageId: string | null | undefined) {
  const { currentOrgId } = useOrg();
  const [pkg, setPkg] = useState<LoanPackage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchPackage = useCallback(async (): Promise<LoanPackage | null> => {
    if (!currentOrgId || !packageId) return null;
    setLoading(true);
    setError(null);
    try {
      const data = await getPackage(currentOrgId, packageId);
      setPkg(data);
      return data;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load package");
      setPkg(null);
      return null;
    } finally {
      setLoading(false);
    }
  }, [currentOrgId, packageId]);

  useEffect(() => {
    fetchPackage();
  }, [fetchPackage]);

  return { package: pkg, loading, error, refetch: fetchPackage };
}
