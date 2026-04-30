"use client";

import { useCallback } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useOrg } from "@/hooks/use-org";
import {
  createPackage,
  deletePackage,
  getPackage,
  listPackages,
} from "@/lib/loan-onboarding/api";
import type { CreateLoanPackageInput } from "@/lib/loan-onboarding/api";
import type {
  LoanPackage,
  LoanPackageListItem,
} from "@/lib/loan-onboarding/types";

/**
 * Cache keys are exported so other hooks/components can invalidate after
 * mutations they own (e.g. process/cancel buttons in the package detail view).
 */
export const loanPackageKeys = {
  all: ["loan-packages"] as const,
  list: (orgId: string | null) => ["loan-packages", "list", orgId] as const,
  detail: (orgId: string | null, packageId: string | null | undefined) =>
    ["loan-packages", "detail", orgId, packageId] as const,
};

export function useLoanPackages() {
  const { currentOrgId } = useOrg();
  const queryClient = useQueryClient();

  const query = useQuery<LoanPackageListItem[]>({
    queryKey: loanPackageKeys.list(currentOrgId),
    queryFn: () => listPackages(currentOrgId as string),
    enabled: !!currentOrgId,
  });

  const createMutation = useMutation({
    mutationFn: (data: CreateLoanPackageInput) => {
      if (!currentOrgId) throw new Error("No organization selected");
      return createPackage(currentOrgId, data);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: loanPackageKeys.list(currentOrgId),
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (packageId: string) => {
      if (!currentOrgId) throw new Error("No organization selected");
      await deletePackage(currentOrgId, packageId);
      return packageId;
    },
    onSuccess: (packageId) => {
      // Optimistic local update so the row disappears immediately.
      queryClient.setQueryData<LoanPackageListItem[] | undefined>(
        loanPackageKeys.list(currentOrgId),
        (prev) => prev?.filter((p) => p.id !== packageId)
      );
      queryClient.invalidateQueries({
        queryKey: loanPackageKeys.list(currentOrgId),
      });
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
  });

  const create = useCallback(
    (data: CreateLoanPackageInput) => createMutation.mutateAsync(data),
    [createMutation]
  );

  const remove = useCallback(
    (packageId: string) => deleteMutation.mutateAsync(packageId).then(() => undefined),
    [deleteMutation]
  );

  const refetch = useCallback(async () => {
    await query.refetch();
  }, [query]);

  return {
    packages: query.data ?? [],
    loading: query.isLoading,
    error: query.error instanceof Error ? query.error.message : null,
    refetch,
    create,
    remove,
  };
}

export function useLoanPackage(packageId: string | null | undefined) {
  const { currentOrgId } = useOrg();

  const query = useQuery<LoanPackage | null>({
    queryKey: loanPackageKeys.detail(currentOrgId, packageId),
    queryFn: () => getPackage(currentOrgId as string, packageId as string),
    enabled: !!currentOrgId && !!packageId,
  });

  const refetch = useCallback(async (): Promise<LoanPackage | null> => {
    const result = await query.refetch();
    return result.data ?? null;
  }, [query]);

  return {
    package: query.data ?? null,
    loading: query.isLoading,
    error: query.error instanceof Error ? query.error.message : null,
    refetch,
  };
}
