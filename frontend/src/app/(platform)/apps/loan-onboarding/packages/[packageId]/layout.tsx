"use client";

import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import {
  Activity,
  Layers,
  LayoutDashboard,
  Loader2,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";
import { useOrgSlug } from "@/hooks/use-org-slug";
import { useLoanPackage } from "@/hooks/use-loan-packages";
import { cn } from "@/lib/utils";

interface TabDef {
  href: string;
  label: string;
  icon: LucideIcon;
  description: string;
}

const TABS: TabDef[] = [
  {
    href: "/processing",
    label: "Processing",
    icon: Activity,
    description: "Live pipeline progress and run summary",
  },
  {
    href: "/results",
    label: "Results",
    icon: Layers,
    description: "Document stacks, validation, and overrides",
  },
  {
    href: "/dashboard",
    label: "Dashboard",
    icon: LayoutDashboard,
    description: "Field extractions and exportable feed",
  },
  {
    href: "/compliance",
    label: "Compliance",
    icon: ShieldCheck,
    description: "Regulatory findings and remediation",
  },
];

/**
 * Tiny status pip rendered to the right of the Processing tab label, driven
 * by `LoanPackage.status`. Gives reviewers an at-a-glance signal of where
 * the package is in its lifecycle regardless of which tab they're on.
 */
function ProcessingStatusPip({ status }: { status?: string }) {
  if (!status) return null;
  if (status === "processing" || status === "uploading") {
    return (
      <Loader2
        className="h-3.5 w-3.5 animate-spin text-amber-600"
        aria-label="Pipeline running"
      />
    );
  }
  const dotClass =
    status === "completed"
      ? "bg-emerald-500"
      : status === "failed"
        ? "bg-red-500"
        : status === "awaiting_review"
          ? "bg-amber-500"
          : "bg-muted-foreground/40";
  return (
    <span
      className={cn("h-2 w-2 rounded-full", dotClass)}
      aria-label={`Status: ${status}`}
    />
  );
}

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

  const { package: pkg } = useLoanPackage(packageId);

  // Identify the currently-active tab so we can render a sub-line description
  // beneath the strip — gives the user a one-line orientation cue without
  // making the tabs themselves verbose.
  const activeTab =
    TABS.find((t) => pathname === `${basePath}${t.href}`) ?? null;

  return (
    <div className="space-y-6">
      <div className="space-y-2.5">
        <nav
          className={cn(
            "inline-flex items-center gap-1 rounded-xl border border-border/60 bg-muted/40 p-1",
            "shadow-sm backdrop-blur-sm",
            "max-w-full overflow-x-auto"
          )}
          data-testid="loan-package-tabs"
          aria-label="Package sections"
        >
          {TABS.map((tab) => {
            const href = `${basePath}${tab.href}`;
            const isActive = pathname === href;
            const Icon = tab.icon;
            return (
              <Link
                key={tab.href}
                href={href}
                aria-current={isActive ? "page" : undefined}
                title={tab.description}
                className={cn(
                  "group relative inline-flex items-center gap-2 whitespace-nowrap",
                  "rounded-lg px-3.5 py-1.5 text-sm font-medium",
                  "transition-all duration-200 ease-out",
                  isActive
                    ? "bg-background text-foreground shadow-sm ring-1 ring-border/70"
                    : "text-muted-foreground hover:text-foreground hover:bg-background/60"
                )}
              >
                <Icon
                  className={cn(
                    "h-4 w-4 transition-colors",
                    isActive
                      ? "text-primary"
                      : "text-muted-foreground/70 group-hover:text-foreground"
                  )}
                  aria-hidden="true"
                />
                <span>{tab.label}</span>
                {tab.href === "/processing" && pkg ? (
                  <ProcessingStatusPip status={pkg.status} />
                ) : null}
              </Link>
            );
          })}
        </nav>

        {activeTab ? (
          <p
            className="text-xs text-muted-foreground/80 ml-1"
            data-testid="loan-package-tab-description"
          >
            {activeTab.description}
          </p>
        ) : null}
      </div>

      {children}
    </div>
  );
}
