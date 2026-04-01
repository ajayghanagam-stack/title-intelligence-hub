"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/hooks/use-auth";
import { useOrgStore } from "@/stores/org-store";
import { apiFetch } from "@/lib/api";
import { Sidebar } from "@/components/sidebar";
import { Onboarding } from "@/components/onboarding";
import { ToastProvider } from "@/components/ui/toast";
import type { Org } from "@/lib/platform-types";
import { Button } from "@/components/ui/button";
import { LogOut, User, KeyRound, ChevronRight } from "lucide-react";

function useBreadcrumbs() {
  const pathname = usePathname();
  const segments = pathname.split("/").filter(Boolean);
  const crumbs: { label: string; href: string }[] = [];

  let path = "";
  for (const segment of segments) {
    path += `/${segment}`;
    if (segment === "dashboard") {
      crumbs.push({ label: "Dashboard", href: path });
    } else if (segment === "apps") {
      continue;
    } else if (segment === "title-intelligence") {
      crumbs.push({ label: "Title Intelligence", href: "/apps/title-intelligence" });
    } else if (segment === "packs") {
      continue;
    } else if (segment === "new") {
      crumbs.push({ label: "Upload New", href: path });
    } else if (segment === "results") {
      crumbs.push({ label: "Results", href: path });
    } else if (segment === "documents") {
      crumbs.push({ label: "Documents", href: path });
    } else if (segment === "chat") {
      crumbs.push({ label: "Chat", href: path });
    } else if (segment === "flags") {
      crumbs.push({ label: "Flags", href: path });
    } else if (segment === "profile") {
      crumbs.push({ label: "Profile", href: path });
    } else if (segment === "admin") {
      crumbs.push({ label: "Admin", href: path });
    } else if (segment === "accounts") {
      crumbs.push({ label: "Accounts", href: path });
    } else if (segment === "users") {
      crumbs.push({ label: "Users", href: path });
    } else if (segment === "subscriptions") {
      crumbs.push({ label: "Subscriptions", href: path });
    } else if (segment.match(/^[0-9a-f-]{36}$/)) {
      crumbs.push({ label: "Pack Detail", href: path });
    }
  }

  return crumbs;
}

export default function PlatformLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const { user, isPlatformAdmin, loading: authLoading, signOut } = useAuth();
  const { currentOrgId, setCurrentOrg } = useOrgStore();
  const [checkingOrg, setCheckingOrg] = useState(true);
  const [hasOrg, setHasOrg] = useState(!!currentOrgId);
  const checkedRef = useRef(false);
  const crumbs = useBreadcrumbs();

  useEffect(() => {
    if (authLoading || !user) return;
    if (checkedRef.current) return;

    // Platform admin doesn't need org context for admin pages
    if (isPlatformAdmin) {
      checkedRef.current = true;
      setHasOrg(true);
      setCheckingOrg(false);
      return;
    }

    if (currentOrgId) {
      setHasOrg(true);
      setCheckingOrg(false);
      checkedRef.current = true;
      return;
    }

    checkedRef.current = true;

    apiFetch<Org[]>("/api/v1/organizations/me")
      .then((orgs) => {
        if (orgs.length > 0) {
          setCurrentOrg(orgs[0].id, orgs[0].name);
          setHasOrg(true);
        } else {
          setHasOrg(false);
        }
      })
      .catch(() => {
        setHasOrg(false);
      })
      .finally(() => setCheckingOrg(false));
  }, [authLoading, user, isPlatformAdmin]);

  // Listen for org store changes (from onboarding)
  useEffect(() => {
    if (currentOrgId) {
      setHasOrg(true);
      setCheckingOrg(false);
    }
  }, [currentOrgId]);

  // Redirect unauthenticated users to the appropriate login page
  useEffect(() => {
    if (!authLoading && !user) {
      // If on an admin route, redirect to admin login
      const isAdminRoute = window.location.pathname.startsWith("/admin");
      router.push(isAdminRoute ? "/manage-customers" : "/login");
    }
  }, [authLoading, user, router]);

  if (authLoading || checkingOrg) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <p className="text-sm text-muted-foreground">Loading...</p>
        </div>
      </div>
    );
  }

  if (!isPlatformAdmin && !hasOrg) {
    return <Onboarding />;
  }

  return (
    <ToastProvider>
      <div className="flex h-screen bg-background">
        <Sidebar />
        <div className="flex flex-1 flex-col overflow-hidden">
          {/* Top bar with breadcrumbs + user controls */}
          <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b bg-card/80 px-6 backdrop-blur-md">
            <nav className="flex items-center gap-1.5 text-sm text-muted-foreground">
              {crumbs.map((crumb, i) => (
                <span key={crumb.href} className="flex items-center gap-1.5">
                  {i > 0 && <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/40" />}
                  {i === crumbs.length - 1 ? (
                    <span className="font-medium text-foreground">{crumb.label}</span>
                  ) : (
                    <Link href={crumb.href} className="hover:text-foreground transition-colors">
                      {crumb.label}
                    </Link>
                  )}
                </span>
              ))}
            </nav>
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-2 rounded-full bg-muted/60 px-3 py-1.5">
                <User className="h-3.5 w-3.5 text-muted-foreground" />
                <span className="text-xs text-muted-foreground font-medium">
                  {user?.email}
                </span>
              </div>
              <Link href="/profile">
                <Button
                  variant="outline"
                  size="sm"
                  className="text-muted-foreground hover:text-foreground gap-1.5 h-8 text-xs"
                >
                  <KeyRound className="h-3.5 w-3.5" />
                  Profile
                </Button>
              </Link>
              <Button
                variant="outline"
                size="sm"
                onClick={signOut}
                className="text-muted-foreground hover:text-foreground gap-1.5 h-8 text-xs"
              >
                <LogOut className="h-3.5 w-3.5" />
                Logout
              </Button>
            </div>
          </header>
          <main className="flex-1 overflow-auto p-6">{children}</main>
          {/* GAP-014: Footer bar */}
          <footer className="flex h-9 items-center justify-center border-t bg-muted/30 px-6 text-[11px] text-muted-foreground shrink-0">
            <span>{useOrgStore.getState().currentOrgName || "Logikality"} &middot; Powered by Logikality</span>
          </footer>
        </div>
      </div>
    </ToastProvider>
  );
}
