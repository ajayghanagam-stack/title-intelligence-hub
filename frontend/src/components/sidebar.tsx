"use client";

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
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/use-auth";
import { OrgSwitcher } from "./org-switcher";

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
  { href: "/apps/title-intelligence", label: "Dashboard", icon: FileSearch },
  {
    href: "/apps/title-intelligence/packs/new",
    label: "Upload",
    icon: Upload,
  },
];

const tsaNavItems = [
  { href: "/apps/title-search", label: "Orders", icon: Search },
  {
    href: "/apps/title-search/orders/new",
    label: "New Order",
    icon: Plus,
  },
];

export function Sidebar() {
  const pathname = usePathname();
  const { isPlatformAdmin } = useAuth();

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
      {/* Logo + Brand */}
      <div className="flex flex-col items-center gap-3 px-4 py-5">
        <Link
          href={isPlatformAdmin ? "/admin/accounts" : "/dashboard"}
          className="flex items-center gap-2.5"
        >
          <Image
            src="/logikality_logo.png"
            alt="Logikality"
            width={28}
            height={28}
            className="rounded"
          />
          <span className="text-base font-semibold text-sidebar-foreground tracking-tight">
            logikality
          </span>
        </Link>
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
      <nav aria-label="Main navigation" className="flex-1 p-3 space-y-1">
        {isInsideApp && !isPlatformAdmin && (
          <Link
            href="/dashboard"
            className="flex items-center gap-3 rounded-md px-3 py-2 text-xs font-medium text-sidebar-foreground/50 hover:text-sidebar-foreground transition-colors mb-2"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to Your Apps
          </Link>
        )}

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

        {adminItems.length > 0 && (
          <div className="pt-6">
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

      {/* Footer */}
      <div className="p-3 border-t border-sidebar-border">
        <p className="px-3 text-[11px] text-sidebar-foreground/40">
          Powered by Logikality AI
        </p>
      </div>
    </aside>
  );
}
