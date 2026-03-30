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
  FileText,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/use-auth";
import { useOrg } from "@/hooks/use-org";
import { OrgSwitcher } from "./org-switcher";

interface RecentPack {
  id: string;
  name: string;
  status: string;
  created_at: string;
  readiness_score: number | null;
  property_address: string | null;
}

const customerNavItems = [
  { href: "/dashboard", label: "Your Apps", icon: LayoutGrid },
];

const customerAdminItems = [
  { href: "/admin/users", label: "Users", icon: Users },
  { href: "/admin/subscriptions", label: "Subscriptions", icon: CreditCard },
];

const platformAdminItems = [
  { href: "/admin/accounts", label: "Accounts", icon: Building2 },
  { href: "/admin/apps", label: "Micro Apps", icon: Blocks },
];

const tiNavItems = [
  {
    href: "/apps/title-intelligence/packs/new",
    label: "New Package",
    icon: Plus,
    isButton: true,
  },
  { href: "/apps/title-intelligence", label: "Current Analysis", icon: FileSearch },
];

const tsaNavItems = [
  { href: "/apps/title-search", label: "Orders", icon: Search },
  {
    href: "/apps/title-search/orders/new",
    label: "New Order",
    icon: Plus,
  },
];

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

export function Sidebar() {
  const pathname = usePathname();
  const { isPlatformAdmin } = useAuth();
  const { orgFetch } = useOrg();
  const [recentPacks, setRecentPacks] = useState<RecentPack[]>([]);

  const isInsideTI_ = pathname.startsWith("/apps/title-intelligence");

  const fetchRecentPacks = useCallback(() => {
    if (!isInsideTI_ || isPlatformAdmin) return;
    orgFetch<{ packs: RecentPack[] }>("/api/v1/apps/title-intelligence/packs?limit=5")
      .then((data) => {
        const packs = Array.isArray(data) ? data : data.packs || [];
        setRecentPacks(packs.slice(0, 5));
      })
      .catch(() => {});
  }, [isInsideTI_, isPlatformAdmin, orgFetch]);

  useEffect(() => {
    fetchRecentPacks();
  }, [fetchRecentPacks]);

  // Poll while any pack is still processing so status updates in real time
  const hasProcessing = recentPacks.some((p) => p.status === "processing");
  // Also poll if any pack has no address yet (might be recently completed)
  const hasNoAddress = recentPacks.some((p) => p.status === "completed" && !p.property_address);
  
  useEffect(() => {
    if (!hasProcessing && !hasNoAddress) return;
    const interval = setInterval(fetchRecentPacks, hasProcessing ? 5000 : 3000);
    return () => clearInterval(interval);
  }, [hasProcessing, hasNoAddress, fetchRecentPacks]);

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

  const handleDismissRecentPack = useCallback((packId: string) => {
    setRecentPacks((prev) => prev.filter((p) => p.id !== packId));
  }, []);

  const isInsideTI = pathname.startsWith("/apps/title-intelligence");
  const isInsideTSA = pathname.startsWith("/apps/title-search");
  const isInsideApp = isInsideTI || isInsideTSA;

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
            href="/dashboard"
            className="flex items-center"
          >
            <Image
              src="/society-title-logo.svg"
              alt="Society Title"
              width={160}
              height={40}
              priority
              onError={(e) => {
                // Fallback if logo doesn't exist
                e.currentTarget.style.display = 'none';
              }}
            />
          </Link>
        ) : (
          <Link
            href="/admin/accounts"
            className="flex items-center"
          >
            <Image
              src="/Logo_rev_no-tagline.svg"
              alt="Logikality"
              width={140}
              height={36}
              priority
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
            href="/dashboard"
            className="flex items-center gap-3 rounded-md px-3 py-2 text-xs font-medium text-sidebar-foreground/50 hover:text-sidebar-foreground transition-colors mb-2"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to Your Apps
          </Link>
        )}

        <div className="space-y-1">
          {navItems.map((item) => {
            const isActive =
              item.href === "/apps/title-intelligence" ||
              item.href === "/apps/title-search"
                ? pathname === item.href
                : pathname === item.href || pathname.startsWith(item.href + "/");
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

        {/* Recent Packages — below nav actions, visually separated */}
        {isInsideTI && recentPacks.length > 0 && (
          <div className="mt-5 pt-4 border-t border-sidebar-border/60">
            <div className="flex items-center justify-between px-3 mb-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-sidebar-foreground/40">
                Recent
              </p>
              <Link
                href="/apps/title-intelligence"
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
                      href={`/apps/title-intelligence/packs/${pack.id}`}
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
                          {pack.property_address || pack.name}
                        </p>
                        <p className={cn(
                          "text-[10px] mt-0.5",
                          isActive ? "text-amber-600/60" : "text-sidebar-foreground/35"
                        )}>
                          {formatRelativeDate(pack.created_at)}
                          {pack.readiness_score != null && (
                            <span className="ml-1.5">
                              &middot; {Math.round(pack.readiness_score / 10)}/10
                            </span>
                          )}
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

        {adminItems.length > 0 && (
          <div className="mt-5 pt-4 border-t border-sidebar-border/60">
            <p className="px-3 text-[11px] font-semibold uppercase tracking-wider text-sidebar-foreground/40 mb-2">
              Admin
            </p>
            {adminItems.map((item) => {
              const isActive =
                pathname === item.href || pathname.startsWith(item.href + "/");
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
          src="/Logo_rev_no-tagline.svg"
          alt="Logikality"
          width={100}
          height={26}
        />
        <p className="text-[10px] text-sidebar-foreground/40">
          Powered by Logikality
        </p>
      </div>
    </aside>
  );
}
