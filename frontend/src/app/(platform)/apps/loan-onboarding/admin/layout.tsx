"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";
import { useOrg } from "@/hooks/use-org";

/**
 * Client-side guard for the Loan Onboarding admin surface. The backend
 * routes are already protected by `require_admin()` (admin/owner only),
 * but typing the admin URL directly should not render the page chrome
 * for a member-role user. This layout redirects non-admin members to
 * the LO loan queue.
 *
 * Platform admins are also blocked — admin pages belong to customer-side
 * Owners/Admins, not Logikality staff.
 */
export default function LoanOnboardingAdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
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
      router.replace("/apps/loan-onboarding");
    }
  }, [loading, allowed, router]);

  if (loading || !allowed) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
        Checking permissions…
      </div>
    );
  }

  return <>{children}</>;
}
