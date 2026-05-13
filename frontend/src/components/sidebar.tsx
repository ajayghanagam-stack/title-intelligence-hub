"use client";

import { useEffect, useState, useCallback } from "react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Blocks,
  Users,
  CreditCard,
  Building2,
  LayoutGrid,
  FileSearch,
  Upload,
  Search,
  Plus,
  ArrowLeft,
  Clock,
  CheckCircle2,
  Loader2,
  XCircle,
  X,
  Eye,
  FileText,
  FileStack,
  FileCheck,
  FormInput,
  Inbox,
  Receipt,
  ListChecks,
  Layers,
  ShieldCheck,
  Settings,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/use-auth";
import { useOrg } from "@/hooks/use-org";
import { useOrgSlug } from "@/hooks/use-org-slug";
import { useLoanDocuments } from "@/hooks/use-loan-operator";
import { useLoanPackage } from "@/hooks/use-loan-packages";
import type { LoanStack } from "@/lib/loan-onboarding/types";
import { OrgSwitcher } from "./org-switcher";

interface RecentPack {
  id: string;
  name: string;
  status: string;
  created_at: string;
  property_address: string | null;
}

interface RecentOrder {
  id: string;
  property_address: string;
  county: string | null;
  state_code: string | null;
  borrower_name: string | null;
  status: string;
  pipeline_stage: string | null;
  created_at: string;
}

interface RecentLoanPackage {
  id: string;
  name: string;
  borrower_name: string | null;
  status: string;
  pipeline_stage: string | null;
  updated_at: string;
  created_at: string;
}


function PackStatusIcon({ status }: { status: string }) {
  switch (status) {
    case "completed":
      return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />;
    case "processing":
      return <Loader2 className="h-3.5 w-3.5 text-amber-500 animate-spin" />;
    case "failed":
      return <XCircle className="h-3.5 w-3.5 text-red-400" />;
    default:
      return <Clock className="h-3.5 w-3.5 text-muted-foreground/50" />;
  }
}

function OrderStatusIcon({ status }: { status: string }) {
  switch (status) {
    case "completed":
      return <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />;
    case "processing":
      return <Loader2 className="h-3.5 w-3.5 text-amber-500 animate-spin" />;
    case "failed":
      return <XCircle className="h-3.5 w-3.5 text-red-400" />;
    case "awaiting_abstractor":
    case "review_required":
      return <Clock className="h-3.5 w-3.5 text-blue-400" />;
    default:
      return <Clock className="h-3.5 w-3.5 text-muted-foreground/50" />;
  }
}

function formatRelativeDate(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffDays = Math.floor(diffMs / (1000 * 60 * 60 * 24));

  if (diffDays === 0) return "Today";
  if (diffDays === 1) return "Yesterday";
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/**
 * Pick the first stack that still needs operator action in the Classification
 * stage, so the sidebar deep-link lands somewhere actionable instead of doc #1
 * every time. Falls back to the first stack when nothing needs review.
 */
function pickClassifyDoc(docs: LoanStack[]): LoanStack | null {
  if (docs.length === 0) return null;
  return (
    docs.find(
      (d) =>
        d.classification_status === "needs_review" ||
        d.classification_status === "unclassifiable",
    ) ?? docs[0]
  );
}

/** Same idea for Extraction Review — prefer `needs_review`, then `extracted`. */
function pickExtractDoc(docs: LoanStack[]): LoanStack | null {
  if (docs.length === 0) return null;
  return (
    docs.find(
      (d) =>
        d.extraction_status === "needs_review" ||
        d.extraction_status === "extracted",
    ) ?? docs[0]
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const { isPlatformAdmin, orgs: authOrgs } = useAuth();
  const { orgFetch, currentOrgId, currentOrgName, currentOrgLogoUrl } = useOrg();
  const [hasLoSubscription, setHasLoSubscription] = useState(false);
  const { orgPath } = useOrgSlug();
  const [recentPacks, setRecentPacks] = useState<RecentPack[]>([]);
  const [recentOrders, setRecentOrders] = useState<RecentOrder[]>([]);
  const [recentLoanPackages, setRecentLoanPackages] = useState<
    RecentLoanPackage[]
  >([]);

  // Strip /org/{slug} prefix for path matching
  const normalizedPath = pathname.replace(/^\/org\/[^/]+/, "");

  // When the user is inside a specific loan file we surface the Review Stages
  // group (Classification / Doc Validation / Extraction Review / Data
  // Validation). The active loan is whatever the URL pins — null on the queue
  // page or other LO routes — so the section auto-shows on /loans/{id}/* and
  // hides again on the queue. Mirrors the prototype's logik-intake sidebar.
  const activeLoanIdMatch = normalizedPath.match(
    /^\/apps\/loan-onboarding\/loans\/([^/]+)/,
  );
  const activeLoanId = activeLoanIdMatch?.[1] ?? null;
  const { data: activeLoanDocs = [] } = useLoanDocuments(activeLoanId);
  const { package: activeLoan } = useLoanPackage(activeLoanId);

  const isInsideTI = normalizedPath.startsWith("/apps/title-intelligence");
  const isInsideTSA = normalizedPath.startsWith("/apps/title-search");
  const isInsideLoanOnboarding = normalizedPath.startsWith(
    "/apps/loan-onboarding"
  );
  const isInsideApp = isInsideTI || isInsideTSA || isInsideLoanOnboarding;

  const customerNavItems = [
    { href: orgPath("/dashboard"), label: "Your Apps", icon: LayoutGrid },
  ];

  const customerAdminItems = [
    { href: orgPath("/admin/users"), label: "Users", icon: Users },
    { href: orgPath("/admin/subscriptions"), label: "Subscriptions", icon: CreditCard },
  ];

  const platformAdminItems = [
    { href: "/admin/accounts", label: "Accounts", icon: Building2 },
    { href: "/admin/apps", label: "Micro Apps", icon: Blocks },
    { href: "/admin/billing", label: "Billing", icon: Receipt },
  ];

  const tiNavItems = [
    {
      href: orgPath("/apps/title-intelligence/packs/new"),
      label: "New Package",
      icon: Plus,
      isButton: true,
    },
    { href: orgPath("/apps/title-intelligence"), label: "Current Analysis", icon: FileSearch },
  ];

  const tsaNavItems = [
    { href: orgPath("/apps/title-search"), label: "Orders", icon: Search },
    {
      href: orgPath("/apps/title-search/orders/new"),
      label: "New Order",
      icon: Plus,
    },
  ];

  // Phase 6 cutover (2026-05-10) — legacy /packages/new wizard is gone;
  // the new loan-file flow opens a modal from the queue page itself, so
  // the sidebar just deep-links to the queue and the user clicks
  // "New File" there.
  const loanOnboardingNavItems = [
    {
      href: orgPath("/apps/loan-onboarding"),
      label: "File Queue",
      icon: Inbox,
    },
  ];

  // Loan Onboarding admin links — surfaced only when the operator is
  // inside the Loan Onboarding app (so it doesn't pollute the sidebar of
  // Title Intelligence / Title Search / the customer dashboard).
  // Visibility additionally requires that the active org has the LO
  // subscription and the signed-in user is an org Owner or Admin.
  // Platform admins are explicitly excluded (they are Logikality staff,
  // not customer-side admins).
  const loanOnboardingAdminItems = [
    {
      href: orgPath("/apps/loan-onboarding/admin"),
      label: "Configuration Hub",
      icon: LayoutGrid,
    },
    {
      href: orgPath("/apps/loan-onboarding/admin/document-types"),
      label: "Document Types",
      icon: FileText,
    },
    {
      href: orgPath("/apps/loan-onboarding/admin/extraction-schemas"),
      label: "Extraction Schemas",
      icon: Layers,
    },
    {
      href: orgPath("/apps/loan-onboarding/admin/validation-rules"),
      label: "Validation Rules",
      icon: ShieldCheck,
    },
    {
      href: orgPath("/apps/loan-onboarding/admin/program-profiles"),
      label: "Program Profiles",
      icon: ListChecks,
    },
    {
      href: orgPath("/apps/loan-onboarding/admin/global-settings"),
      label: "Global Settings",
      icon: Settings,
    },
  ];

  // Active-org role lookup. `authOrgs` carries per-org role from /auth/me;
  // we resolve to the org currently selected in the org-store. Falls back
  // to null for platform admins (who have no customer-side membership) or
  // before auth has hydrated.
  const currentOrgRole =
    authOrgs.find((o) => o.id === currentOrgId)?.role ?? null;
  const isOrgAdminOrOwner =
    currentOrgRole === "admin" || currentOrgRole === "owner";

  // Probe the active org's subscriptions to decide whether to render the
  // LO admin group. Scoped to the LO app context — no point fetching this
  // when the user is inside TI/TSA or on the dashboard. Platform admins
  // are also excluded.
  useEffect(() => {
    if (
      !currentOrgId ||
      isPlatformAdmin ||
      !isOrgAdminOrOwner ||
      !isInsideLoanOnboarding
    ) {
      setHasLoSubscription(false);
      return;
    }
    let cancelled = false;
    orgFetch<{ id: string; status: string; micro_app: { slug: string } | null }[]>(
      "/api/v1/subscriptions"
    )
      .then((subs) => {
        if (cancelled) return;
        const hasLo = subs.some(
          (s) =>
            s.status === "active" &&
            s.micro_app?.slug === "loan-onboarding"
        );
        setHasLoSubscription(hasLo);
      })
      .catch(() => {
        if (!cancelled) setHasLoSubscription(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    currentOrgId,
    isPlatformAdmin,
    isOrgAdminOrOwner,
    isInsideLoanOnboarding,
    orgFetch,
  ]);

  const showLoAdminGroup =
    !isPlatformAdmin &&
    isOrgAdminOrOwner &&
    isInsideLoanOnboarding &&
    hasLoSubscription;

  const fetchRecentPacks = useCallback(() => {
    if (!isInsideTI || isPlatformAdmin) return;
    orgFetch<{ packs: RecentPack[] }>("/api/v1/apps/title-intelligence/packs?limit=5")
      .then((data) => {
        const packs = Array.isArray(data) ? data : data.packs || [];
        setRecentPacks(packs.slice(0, 5));
      })
      .catch(() => {});
  }, [isInsideTI, isPlatformAdmin, orgFetch]);

  const fetchRecentOrders = useCallback(() => {
    if (!isInsideTSA || isPlatformAdmin) return;
    orgFetch<RecentOrder[]>("/api/v1/apps/title-search/orders?size=5")
      .then((data) => {
        const orders = Array.isArray(data) ? data : [];
        setRecentOrders(orders.slice(0, 5));
      })
      .catch(() => {});
  }, [isInsideTSA, isPlatformAdmin, orgFetch]);

  const fetchRecentLoanPackages = useCallback(() => {
    if (!isInsideLoanOnboarding || isPlatformAdmin) return;
    orgFetch<RecentLoanPackage[]>("/api/v1/apps/loan-onboarding/packages")
      .then((data) => {
        const pkgs = Array.isArray(data) ? data : [];
        const sorted = [...pkgs].sort(
          (a, b) =>
            new Date(b.updated_at || b.created_at).getTime() -
            new Date(a.updated_at || a.created_at).getTime()
        );
        setRecentLoanPackages(sorted.slice(0, 5));
      })
      .catch(() => {});
  }, [isInsideLoanOnboarding, isPlatformAdmin, orgFetch]);

  useEffect(() => {
    fetchRecentPacks();
  }, [fetchRecentPacks]);

  useEffect(() => {
    fetchRecentOrders();
  }, [fetchRecentOrders]);

  useEffect(() => {
    fetchRecentLoanPackages();
  }, [fetchRecentLoanPackages]);

  // Poll while any pack is still processing so status updates in real time
  const hasProcessing = recentPacks.some((p) => p.status === "processing");
  const hasNoAddress = recentPacks.some((p) => p.status === "completed" && !p.property_address);

  useEffect(() => {
    if (!hasProcessing && !hasNoAddress) return;
    const interval = setInterval(fetchRecentPacks, hasProcessing ? 5000 : 3000);
    return () => clearInterval(interval);
  }, [hasProcessing, hasNoAddress, fetchRecentPacks]);

  const hasProcessingOrders = recentOrders.some(
    (o) => o.status === "processing" || o.status === "awaiting_abstractor"
  );
  useEffect(() => {
    if (!hasProcessingOrders) return;
    const interval = setInterval(fetchRecentOrders, 5000);
    return () => clearInterval(interval);
  }, [hasProcessingOrders, fetchRecentOrders]);

  const hasProcessingLoanPackages = recentLoanPackages.some(
    (p) => p.status === "processing" || p.status === "uploading"
  );
  useEffect(() => {
    if (!hasProcessingLoanPackages) return;
    const interval = setInterval(fetchRecentLoanPackages, 5000);
    return () => clearInterval(interval);
  }, [hasProcessingLoanPackages, fetchRecentLoanPackages]);

  useEffect(() => {
    const handler = () => fetchRecentPacks();
    window.addEventListener("pack-deleted", handler);
    window.addEventListener("pack-created", handler);
    window.addEventListener("pack-uploaded", handler);
    window.addEventListener("pack-completed", handler);
    return () => {
      window.removeEventListener("pack-deleted", handler);
      window.removeEventListener("pack-created", handler);
      window.removeEventListener("pack-uploaded", handler);
      window.removeEventListener("pack-completed", handler);
    };
  }, [fetchRecentPacks]);

  useEffect(() => {
    const handler = () => fetchRecentOrders();
    window.addEventListener("order-created", handler);
    window.addEventListener("order-deleted", handler);
    window.addEventListener("order-completed", handler);
    return () => {
      window.removeEventListener("order-created", handler);
      window.removeEventListener("order-deleted", handler);
      window.removeEventListener("order-completed", handler);
    };
  }, [fetchRecentOrders]);

  useEffect(() => {
    const handler = () => fetchRecentLoanPackages();
    window.addEventListener("loan-package-created", handler);
    window.addEventListener("loan-package-deleted", handler);
    window.addEventListener("loan-package-completed", handler);
    return () => {
      window.removeEventListener("loan-package-created", handler);
      window.removeEventListener("loan-package-deleted", handler);
      window.removeEventListener("loan-package-completed", handler);
    };
  }, [fetchRecentLoanPackages]);

  const handleDismissRecentPack = useCallback((packId: string) => {
    setRecentPacks((prev) => prev.filter((p) => p.id !== packId));
  }, []);

  const handleDismissRecentOrder = useCallback((orderId: string) => {
    setRecentOrders((prev) => prev.filter((o) => o.id !== orderId));
  }, []);

  const handleDismissRecentLoanPackage = useCallback((packageId: string) => {
    setRecentLoanPackages((prev) => prev.filter((p) => p.id !== packageId));
  }, []);

  let navItems;
  let adminItems: typeof customerAdminItems = [];
  let appLabel = "";

  if (isPlatformAdmin) {
    navItems = platformAdminItems;
    appLabel = "Platform Admin";
  } else if (isInsideTI) {
    navItems = tiNavItems;
    appLabel = "Title Intelligence";
  } else if (isInsideTSA) {
    navItems = tsaNavItems;
    appLabel = "Title Search";
  } else if (isInsideLoanOnboarding) {
    navItems = loanOnboardingNavItems;
    appLabel = "Loan Boarding";
  } else {
    navItems = customerNavItems;
    adminItems = customerAdminItems;
  }

  return (
    <aside className="flex h-full w-64 flex-col sidebar-gradient border-r border-sidebar-border">
      {/* Org Logo + App Label */}
      <div className="flex flex-col items-center gap-3 px-4 py-5">
        {!isPlatformAdmin ? (
          <Link
            href={orgPath("/dashboard")}
            className="flex items-center w-full group"
          >
            <div className="w-full flex justify-center items-center">
              <div
                className="overflow-hidden rounded-xl transition-all duration-300 group-hover:scale-[1.02]"
                style={{
                  boxShadow: "0 4px 18px rgba(0,0,0,0.18), 0 1px 4px rgba(0,0,0,0.10)",
                  border: "1px solid rgba(255,255,255,0.12)",
                }}
              >
                {currentOrgLogoUrl ? (
                  <Image
                    src={currentOrgLogoUrl}
                    alt={currentOrgName || "Organization Logo"}
                    width={224}
                    height={224}
                    priority
                    style={{
                      height: 56,
                      width: "auto",
                      display: "block",
                    }}
                  />
                ) : (
                  <div
                    className="flex items-center justify-center px-4"
                    style={{ height: 56 }}
                  >
                    <span className="text-lg font-bold text-foreground">
                      {currentOrgName || "Organization"}
                    </span>
                  </div>
                )}
              </div>
            </div>
          </Link>
        ) : (
          <Link
            href="/admin/accounts"
            className="flex items-center"
          >
            <Image
              src="/Logo_withTagline.svg"
              alt="Logikality"
              width={140}
              height={56}
              priority
              style={{ height: "auto" }}
            />
          </Link>
        )}
        {appLabel && (
          <span className="text-[11px] font-bold uppercase tracking-[0.15em] text-amber-700/80">
            {appLabel}
          </span>
        )}
        <div className="divider-brand w-full" />
      </div>

      {/* Org Switcher */}
      {!isPlatformAdmin && (
        <div className="px-4 pb-3">
          <OrgSwitcher variant="sidebar" />
        </div>
      )}

      {/* Navigation */}
      <nav aria-label="Main navigation" className="flex-1 p-3 overflow-y-auto">
        {isInsideApp && !isPlatformAdmin && (
          <Link
            href={orgPath("/dashboard")}
            className="flex items-center gap-3 rounded-md px-3 py-2 text-xs font-medium text-sidebar-foreground/50 hover:text-sidebar-foreground transition-colors mb-2"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to Your Apps
          </Link>
        )}

        {isInsideLoanOnboarding && !isPlatformAdmin && (
          <p className="px-3 pb-1.5 text-[10px] font-bold uppercase tracking-[0.15em] text-sidebar-foreground/40">
            Workspace
          </p>
        )}
        <div className="space-y-1">
          {navItems.map((item) => {
            const itemNormalized = item.href.replace(/^\/org\/[^/]+/, "");
            const isActive =
              itemNormalized === "/apps/title-intelligence" ||
              itemNormalized === "/apps/title-search" ||
              itemNormalized === "/apps/loan-onboarding"
                ? normalizedPath === itemNormalized
                : normalizedPath === itemNormalized || normalizedPath.startsWith(itemNormalized + "/");
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={isActive ? "page" : undefined}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors",
                  isActive
                    ? "sidebar-nav-active"
                    : "text-sidebar-foreground/70 sidebar-nav-hover hover:text-sidebar-foreground"
                )}
              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </div>

        {/* Active File + Review Stages — visible when inside a specific loan.
            Mirrors the LogikIntake prototype: a single top-level link to the
            loan overview followed by deep-links into each of the four review
            stages. Classify and Extract auto-target the first stack that
            still needs operator attention; Doc Validation and Data Validation
            are loan-scoped and don't take a docId. */}
        {isInsideLoanOnboarding && activeLoanId && (() => {
          const fileHref = orgPath(
            `/apps/loan-onboarding/loans/${activeLoanId}`,
          );
          const docValidationHref = orgPath(
            `/apps/loan-onboarding/loans/${activeLoanId}/doc-validation`,
          );
          const dataValidationHref = orgPath(
            `/apps/loan-onboarding/loans/${activeLoanId}/validation`,
          );
          const classifyBase = `/apps/loan-onboarding/loans/${activeLoanId}/classify`;
          const extractBase = `/apps/loan-onboarding/loans/${activeLoanId}/extract`;
          // If the user is already viewing a specific doc (/classify/{X} or
          // /extract/{X}), reuse that docId for both stage links so jumping
          // between Classification ↔ Extraction Review stays on the SAME
          // stack. Without this the sidebar would re-pick the first HITL
          // stack via pickClassifyDoc/pickExtractDoc, dragging the operator
          // away from the doc they were reviewing (see
          // https://github.com/.../issues/loan-onboarding-doc-switch).
          const activeDocIdMatch = normalizedPath.match(
            new RegExp(
              `^/apps/loan-onboarding/loans/${activeLoanId}/(?:classify|extract)/([^/]+)`,
            ),
          );
          const activeDocId = activeDocIdMatch?.[1] ?? null;
          const activeDoc = activeDocId
            ? activeLoanDocs.find((d) => d.id === activeDocId) ?? null
            : null;
          // Resolve the "target doc" for each stage link:
          //   - If the URL already names a docId, reuse it so Classification ↔
          //     Extraction Review keep the user on the SAME stack.
          //   - Otherwise fall back to the first stack still needing operator
          //     attention (pickClassifyDoc / pickExtractDoc). We surface that
          //     stack's doc_type as a sublabel next to the stage row so the
          //     operator can SEE which doc the sidebar shortcut targets —
          //     prior versions silently jumped to the first HITL stack with
          //     no visual hint, which read as "the sidebar always shows the
          //     first file's data" when two different stages happened to
          //     pre-pick the same stack (e.g. flood_cert HITL on both).
          const classifyTarget = activeDoc ?? pickClassifyDoc(activeLoanDocs);
          const extractTarget = activeDoc ?? pickExtractDoc(activeLoanDocs);
          // When the doc list hasn't loaded yet (or the loan is mid-pipeline
          // with zero stacks) we fall back to the loan overview — gives the
          // operator a working link instead of a broken /classify/undefined.
          const classifyHref = classifyTarget
            ? orgPath(`${classifyBase}/${classifyTarget.id}`)
            : fileHref;
          const extractHref = extractTarget
            ? orgPath(`${extractBase}/${extractTarget.id}`)
            : fileHref;

          const reviewStages: {
            href: string;
            label: string;
            sublabel: string | null;
            icon: typeof Eye;
            isActive: boolean;
          }[] = [
            {
              href: classifyHref,
              label: "Classification",
              sublabel: classifyTarget?.doc_type ?? null,
              icon: Eye,
              // Any /classify/<docId> under this loan keeps the row active,
              // even if the user clicked through to a different doc than the
              // sidebar's default target.
              isActive: normalizedPath.startsWith(`${classifyBase}/`),
            },
            {
              href: docValidationHref,
              label: "Doc Validation",
              sublabel: null,
              icon: FileCheck,
              isActive:
                normalizedPath ===
                `/apps/loan-onboarding/loans/${activeLoanId}/doc-validation`,
            },
            {
              href: extractHref,
              label: "Extraction Review",
              sublabel: extractTarget?.doc_type ?? null,
              icon: FormInput,
              isActive: normalizedPath.startsWith(`${extractBase}/`),
            },
            {
              href: dataValidationHref,
              label: "Data Validation",
              sublabel: null,
              icon: ShieldCheck,
              isActive:
                normalizedPath ===
                `/apps/loan-onboarding/loans/${activeLoanId}/validation`,
            },
          ];

          const fileLabel = activeLoan?.name ?? activeLoanId;
          const fileSublabel = activeLoan?.borrower_name ?? undefined;
          const fileActive =
            normalizedPath ===
            `/apps/loan-onboarding/loans/${activeLoanId}`;

          return (
            <>
              <div className="mt-5 pt-4 border-t border-sidebar-border/60">
                <p className="px-3 pb-1.5 text-[10px] font-bold uppercase tracking-[0.15em] text-sidebar-foreground/40">
                  Active File
                </p>
                <Link
                  href={fileHref}
                  aria-current={fileActive ? "page" : undefined}
                  className={cn(
                    "flex items-start gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors",
                    fileActive
                      ? "sidebar-nav-active"
                      : "text-sidebar-foreground/70 sidebar-nav-hover hover:text-sidebar-foreground",
                  )}
                >
                  <FileText className="mt-0.5 h-4 w-4 shrink-0" />
                  <span className="flex min-w-0 flex-col">
                    <span className="truncate">{fileLabel}</span>
                    {fileSublabel && (
                      <span
                        className={cn(
                          "truncate text-[10px] font-normal",
                          fileActive
                            ? "text-sidebar-foreground/60"
                            : "text-sidebar-foreground/40",
                        )}
                      >
                        {fileSublabel}
                      </span>
                    )}
                  </span>
                </Link>
              </div>

              <div className="mt-4">
                <p className="px-3 pb-1.5 text-[10px] font-bold uppercase tracking-[0.15em] text-sidebar-foreground/40">
                  Review Stages
                </p>
                <div className="space-y-1">
                  {reviewStages.map((s) => (
                    <Link
                      key={s.label}
                      href={s.href}
                      aria-current={s.isActive ? "page" : undefined}
                      className={cn(
                        "flex items-start gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors",
                        s.isActive
                          ? "sidebar-nav-active"
                          : "text-sidebar-foreground/70 sidebar-nav-hover hover:text-sidebar-foreground",
                      )}
                    >
                      <s.icon className="mt-0.5 h-4 w-4 shrink-0" />
                      <span className="flex min-w-0 flex-col">
                        <span className="truncate">{s.label}</span>
                        {s.sublabel && (
                          <span
                            className={cn(
                              "truncate text-[10px] font-normal lowercase tracking-wide",
                              s.isActive
                                ? "text-sidebar-foreground/60"
                                : "text-sidebar-foreground/40",
                            )}
                          >
                            {s.sublabel}
                          </span>
                        )}
                      </span>
                    </Link>
                  ))}
                </div>
              </div>
            </>
          );
        })()}

        {/* Recent Packages — below nav actions, visually separated */}
        {isInsideTI && recentPacks.length > 0 && (
          <div className="mt-5 pt-4 border-t border-sidebar-border/60">
            <div className="flex items-center justify-between px-3 mb-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-sidebar-foreground/40">
                Recent
              </p>
              <Link
                href={orgPath("/apps/title-intelligence")}
                className="text-[10px] font-medium text-amber-600/70 hover:text-amber-700 transition-colors"
              >
                View all
              </Link>
            </div>
            <div className="space-y-0.5">
              {recentPacks.map((pack) => {
                const isActive = pathname.includes(pack.id);
                return (
                  <div
                    key={pack.id}
                    className={cn(
                      "group flex items-center gap-2.5 rounded-lg px-3 py-2 text-xs transition-all",
                      isActive
                        ? "bg-amber-50 text-amber-800 ring-1 ring-amber-200/60"
                        : "text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground"
                    )}
                  >
                    <Link
                      href={orgPath(`/apps/title-intelligence/packs/${pack.id}`)}
                      className="flex items-center gap-2.5 min-w-0 flex-1"
                    >
                      <div className="shrink-0">
                        <PackStatusIcon status={pack.status} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className={cn(
                          "font-medium truncate leading-tight",
                          isActive ? "text-amber-800" : "text-sidebar-foreground/80 group-hover:text-sidebar-foreground"
                        )}>
                          {(pack.property_address && !["N/A", "n/a", "NA", "None", "Unknown"].includes(pack.property_address)) ? pack.property_address : pack.name}
                        </p>
                        <p className={cn(
                          "text-[10px] mt-0.5",
                          isActive ? "text-amber-600/60" : "text-sidebar-foreground/35"
                        )}>
                          {formatRelativeDate(pack.created_at)}
                        </p>
                      </div>
                    </Link>
                    <button
                      onClick={() => handleDismissRecentPack(pack.id)}
                      className="shrink-0 opacity-0 group-hover:opacity-100 p-0.5 rounded text-sidebar-foreground/30 hover:text-red-500 hover:bg-red-50 transition-all"
                      title="Dismiss from recents"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Recent Orders — Title Search */}
        {isInsideTSA && recentOrders.length > 0 && (
          <div className="mt-5 pt-4 border-t border-sidebar-border/60">
            <div className="flex items-center justify-between px-3 mb-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-sidebar-foreground/40">
                Recent
              </p>
              <Link
                href={orgPath("/apps/title-search")}
                className="text-[10px] font-medium text-amber-600/70 hover:text-amber-700 transition-colors"
              >
                View all
              </Link>
            </div>
            <div className="space-y-0.5">
              {recentOrders.map((order) => {
                const isActive = pathname.includes(order.id);
                const label =
                  order.property_address ||
                  order.borrower_name ||
                  "Untitled Order";
                const sublabel = [order.county, order.state_code]
                  .filter(Boolean)
                  .join(", ");
                return (
                  <div
                    key={order.id}
                    className={cn(
                      "group flex items-center gap-2.5 rounded-lg px-3 py-2 text-xs transition-all",
                      isActive
                        ? "bg-amber-50 text-amber-800 ring-1 ring-amber-200/60"
                        : "text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground"
                    )}
                  >
                    <Link
                      href={orgPath(`/apps/title-search/orders/${order.id}`)}
                      className="flex items-center gap-2.5 min-w-0 flex-1"
                    >
                      <div className="shrink-0">
                        <OrderStatusIcon status={order.status} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p
                          className={cn(
                            "font-medium truncate leading-tight",
                            isActive
                              ? "text-amber-800"
                              : "text-sidebar-foreground/80 group-hover:text-sidebar-foreground"
                          )}
                        >
                          {label}
                        </p>
                        <p
                          className={cn(
                            "text-[10px] mt-0.5 truncate",
                            isActive
                              ? "text-amber-600/60"
                              : "text-sidebar-foreground/35"
                          )}
                        >
                          {sublabel || formatRelativeDate(order.created_at)}
                          {sublabel && (
                            <span className="ml-1.5">
                              &middot; {formatRelativeDate(order.created_at)}
                            </span>
                          )}
                        </p>
                      </div>
                    </Link>
                    <button
                      onClick={() => handleDismissRecentOrder(order.id)}
                      className="shrink-0 opacity-0 group-hover:opacity-100 p-0.5 rounded text-sidebar-foreground/30 hover:text-red-500 hover:bg-red-50 transition-all"
                      title="Dismiss from recents"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Recent Loan Packages */}
        {isInsideLoanOnboarding && recentLoanPackages.length > 0 && (
          <div className="mt-5 pt-4 border-t border-sidebar-border/60">
            <div className="flex items-center justify-between px-3 mb-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-sidebar-foreground/40">
                Recent
              </p>
              <Link
                href={orgPath("/apps/loan-onboarding")}
                className="text-[10px] font-medium text-amber-600/70 hover:text-amber-700 transition-colors"
              >
                View all
              </Link>
            </div>
            <div className="space-y-0.5">
              {recentLoanPackages.map((pkg) => {
                const isActive = pathname.includes(pkg.id);
                const sublabel = pkg.borrower_name || "";
                return (
                  <div
                    key={pkg.id}
                    className={cn(
                      "group flex items-center gap-2.5 rounded-lg px-3 py-2 text-xs transition-all",
                      isActive
                        ? "bg-amber-50 text-amber-800 ring-1 ring-amber-200/60"
                        : "text-sidebar-foreground/60 hover:bg-sidebar-accent hover:text-sidebar-foreground"
                    )}
                  >
                    <Link
                      href={orgPath(
                        `/apps/loan-onboarding/loans/${pkg.id}`
                      )}
                      className="flex items-center gap-2.5 min-w-0 flex-1"
                    >
                      <div className="shrink-0">
                        <PackStatusIcon status={pkg.status} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p
                          className={cn(
                            "font-medium truncate leading-tight",
                            isActive
                              ? "text-amber-800"
                              : "text-sidebar-foreground/80 group-hover:text-sidebar-foreground"
                          )}
                        >
                          {pkg.name}
                        </p>
                        <p
                          className={cn(
                            "text-[10px] mt-0.5 truncate",
                            isActive
                              ? "text-amber-600/60"
                              : "text-sidebar-foreground/35"
                          )}
                        >
                          {sublabel
                            ? `${sublabel} · ${formatRelativeDate(pkg.updated_at || pkg.created_at)}`
                            : formatRelativeDate(
                                pkg.updated_at || pkg.created_at
                              )}
                        </p>
                      </div>
                    </Link>
                    <button
                      onClick={() => handleDismissRecentLoanPackage(pkg.id)}
                      className="shrink-0 opacity-0 group-hover:opacity-100 p-0.5 rounded text-sidebar-foreground/30 hover:text-red-500 hover:bg-red-50 transition-all"
                      title="Dismiss from recents"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {adminItems.length > 0 && (
          <div className="mt-5 pt-4 border-t border-sidebar-border/60">
            <p className="px-3 text-[11px] font-semibold uppercase tracking-wider text-sidebar-foreground/40 mb-2">
              Admin
            </p>
            {adminItems.map((item) => {
              const itemNormalized = item.href.replace(/^\/org\/[^/]+/, "");
              const isActive =
                normalizedPath === itemNormalized || normalizedPath.startsWith(itemNormalized + "/");
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={isActive ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors",
                    isActive
                      ? "sidebar-nav-active"
                      : "text-sidebar-foreground/70 sidebar-nav-hover hover:text-sidebar-foreground"
                  )}
                >
                  <item.icon className="h-4 w-4" />
                  {item.label}
                </Link>
              );
            })}
          </div>
        )}

        {showLoAdminGroup && (
          <div className="mt-5 pt-4 border-t border-sidebar-border/60">
            <p className="px-3 pb-1.5 text-[10px] font-bold uppercase tracking-[0.15em] text-sidebar-foreground/40">
              Admin
            </p>
            {loanOnboardingAdminItems.map((item) => {
              const itemNormalized = item.href.replace(/^\/org\/[^/]+/, "");
              // The Configuration Hub root path is a prefix of every leaf
              // admin page; require an exact match for it so the hub link
              // only highlights when the user is actually on the hub page.
              const isHub = itemNormalized === "/apps/loan-onboarding/admin";
              const isActive = isHub
                ? normalizedPath === itemNormalized
                : normalizedPath === itemNormalized ||
                  normalizedPath.startsWith(itemNormalized + "/");
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={isActive ? "page" : undefined}
                  className={cn(
                    "flex items-center gap-3 rounded-md px-3 py-2.5 text-sm font-medium transition-colors",
                    isActive
                      ? "sidebar-nav-active"
                      : "text-sidebar-foreground/70 sidebar-nav-hover hover:text-sidebar-foreground"
                  )}
                >
                  <item.icon className="h-4 w-4" />
                  {item.label}
                </Link>
              );
            })}
          </div>
        )}
      </nav>

      {/* Footer with Logikality Logo */}
      <div className="p-4 border-t border-sidebar-border flex flex-col items-center gap-2">
        <Image
          src="/Logo_withTagline.svg"
          alt="Logikality"
          width={100}
          height={40}
          style={{ height: "auto" }}
        />
        <p className="text-[10px] text-sidebar-foreground/40">
          Powered by Logikality
        </p>
      </div>
    </aside>
  );
}
