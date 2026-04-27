"use client";

import Link from "next/link";
import { FileStack, Plus } from "lucide-react";
import { useOrgSlug } from "@/hooks/use-org-slug";
import { useLoanPackages } from "@/hooks/use-loan-packages";
import { PackageList } from "@/components/loan-onboarding/package-list";

export default function LoanOnboardingPage() {
  const { orgPath } = useOrgSlug();
  const { packages, loading, remove } = useLoanPackages();

  return (
    <div className="space-y-8" data-testid="loan-onboarding-page">
      {/* Hero Header */}
      <div className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-[oklch(0.178_0.010_50)] to-[oklch(0.250_0.015_55)] p-8 text-white">
        <div className="pointer-events-none absolute -right-10 -top-10 h-40 w-40 rounded-full bg-[oklch(0.750_0.170_65/0.15)]" />
        <div className="pointer-events-none absolute -bottom-6 -left-6 h-28 w-28 rounded-full bg-[oklch(0.560_0.230_340/0.10)]" />

        <div className="relative flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-white/10 ring-1 ring-white/20 backdrop-blur-sm">
              <FileStack className="h-7 w-7 text-[oklch(0.750_0.170_65)]" />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight">
                Loan Onboarding
              </h1>
              <p className="mt-1 text-sm text-white/70">
                Automated classification, splitting, and validation of borrower
                document packages
              </p>
            </div>
          </div>
          <Link
            href={orgPath("/apps/loan-onboarding/packages/new")}
            className="btn-cta gap-2"
            data-testid="new-loan-package-button"
          >
            <Plus className="h-4 w-4" />
            New Package
          </Link>
        </div>
      </div>

      {loading ? (
        <div className="flex flex-col items-center justify-center py-20 gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <p className="text-sm text-muted-foreground">Loading packages...</p>
        </div>
      ) : (
        <PackageList packages={packages} onDelete={remove} />
      )}
    </div>
  );
}
