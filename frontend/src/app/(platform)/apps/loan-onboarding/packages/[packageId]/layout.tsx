"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useOrgSlug } from "@/hooks/use-org-slug";

const TABS = [
  { href: "/processing", label: "Processing" },
  { href: "/results", label: "Results" },
  { href: "/dashboard", label: "Dashboard" },
];

export default function LoanPackageDetailLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const params = useParams();
  const pathname = usePathname();
  const { orgPath } = useOrgSlug();
  const packageId = params.packageId as string;
  const basePath = orgPath(`/apps/loan-onboarding/packages/${packageId}`);

  return (
    <div className="space-y-6">
      <nav
        className="flex gap-1 border-b border-border/70 overflow-x-auto"
        data-testid="loan-package-tabs"
        aria-label="Package sections"
      >
        {TABS.map((tab) => {
          const href = `${basePath}${tab.href}`;
          const isActive = pathname === href;
          return (
            <Link
              key={tab.href}
              href={href}
              aria-current={isActive ? "page" : undefined}
              className={`relative px-4 py-2.5 text-sm font-medium whitespace-nowrap transition-colors border-b-2 -mb-px ${
                isActive
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground hover:border-border"
              }`}
            >
              {tab.label}
            </Link>
          );
        })}
      </nav>

      {children}
    </div>
  );
}
