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
import { useOrgSlug } from "@/hooks/use-org-slug";
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

const ORG_LOGOS: Record<string, string> = {
  "6cc2b64a-d3ab-4b98-8246-96c6e98efedf": "/grid151-logo.jpeg",      // Grid151
  "5e704ee4-fc88-4d1e-855f-50d379ea6c0f": "/society-title-logo.svg", // Society Title
};

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

export function Sidebar() {
  const pathname = usePathname();
  const { isPlatformAdmin } = useAuth();
  const { orgFetch, currentOrgId } = useOrg();
  const { orgPath } = useOrgSlug();
  const [recentPacks, setRecentPacks] = useState<RecentPack[]>([]);
  const [recentOrders, setRecentOrders] = useState<RecentOrder[]>([]);

  // Strip /org/{slug} prefix for path matching
  const normalizedPath = pathname.replace(/^\/org\/[^/]+/, "");

  const isInsideTI = normalizedPath.startsWith("/apps/title-intelligence");
  const isInsideTSA = normalizedPath.startsWith("/apps/title-search");
  const isInsideApp = isInsideTI || isInsideTSA;

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

  useEffect(() => {
    fetchRecentPacks();
  }, [fetchRecentPacks]);

  useEffect(() => {
    fetchRecentOrders();
  }, [fetchRecentOrders]);

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

  const handleDismissRecentPack = useCallback((packId: string) => {
    setRecentPacks((prev) => prev.filter((p) => p.id !== packId));
  }, []);

  const handleDismissRecentOrder = useCallback((orderId: string) => {
    setRecentOrders((prev) => prev.filter((o) => o.id !== orderId));
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
                <Image
                  src={
                    currentOrgId && ORG_LOGOS[currentOrgId]
                      ? ORG_LOGOS[currentOrgId]
                      : "/society-title-logo.svg"
                  }
                  alt="Organization Logo"
                  width={224}
                  height={224}
                  priority
                  style={{
                    height: 56,
                    width: "auto",
                    display: "block",
                  }}
                />
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

        <div className="space-y-1">
          {navItems.map((item) => {
            const itemNormalized = item.href.replace(/^\/org\/[^/]+/, "");
            const isActive =
              itemNormalized === "/apps/title-intelligence" ||
              itemNormalized === "/apps/title-search"
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
