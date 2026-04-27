"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { useOrgSlug } from "@/hooks/use-org-slug";
import { useLoanPackage } from "@/hooks/use-loan-packages";

const TERMINAL = new Set(["completed", "failed", "awaiting_review"]);

/**
 * Root of the package detail route — does not render its own UI. Redirects
 * to /processing if the pipeline is still running or to /results once it
 * has reached a terminal state. The dedicated sub-routes keep each tab's
 * URL stable and let /processing auto-push to /results on completion.
 */
export default function LoanPackageRootRedirect() {
  const router = useRouter();
  const params = useParams();
  const packageId = params.packageId as string;
  const { orgPath } = useOrgSlug();
  const { package: pkg, loading } = useLoanPackage(packageId);

  useEffect(() => {
    if (loading || !pkg) return;
    const base = orgPath(`/apps/loan-onboarding/packages/${packageId}`);
    const target = TERMINAL.has(pkg.status)
      ? `${base}/results`
      : `${base}/processing`;
    router.replace(target);
  }, [loading, pkg, packageId, orgPath, router]);

  return (
    <div className="flex flex-col items-center justify-center py-20 gap-3">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      <p className="text-sm text-muted-foreground">Loading package…</p>
    </div>
  );
}
