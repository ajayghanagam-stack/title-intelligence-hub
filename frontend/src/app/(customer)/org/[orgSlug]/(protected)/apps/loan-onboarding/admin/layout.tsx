"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";
import { useOrg } from "@/hooks/use-org";

/**
 * Customer-tree mirror of the platform-tree admin layout. Same role
 * gate (Owner/Admin only, platform admins blocked) but redirects back
 * to the slug-prefixed loan queue when access is denied.
 */
export default function LoanOnboardingAdminLayoutCustomer({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const params = useParams();
  const orgSlug = (params?.orgSlug as string | undefined) ?? "";
  const { orgs, isPlatformAdmin, loading } = useAuth();
  const { currentOrgId } = useOrg();

  const currentOrgRole =
    orgs.find((o) => o.id === currentOrgId)?.role ?? null;
  const allowed =
    !isPlatformAdmin &&
    (currentOrgRole === "admin" || currentOrgRole === "owner");

  useEffect(() => {
    if (loading) return;
    if (!allowed) {
      router.replace(`/org/${orgSlug}/apps/loan-onboarding`);
    }
  }, [loading, allowed, orgSlug, router]);

  if (loading || !allowed) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
        Checking permissions…
      </div>
    );
  }

  return <>{children}</>;
}
