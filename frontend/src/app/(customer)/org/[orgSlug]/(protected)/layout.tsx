"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, usePathname, useParams } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/hooks/use-auth";
import { useMe } from "@/hooks/use-me";
import { useOrgStore } from "@/stores/org-store";
import { useOrgSlug } from "@/hooks/use-org-slug";
import { setOrgSlugCookie } from "@/lib/auth";
import { Sidebar } from "@/components/sidebar";
import { ToastProvider } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { LogOut, User, KeyRound, ChevronRight } from "lucide-react";

function useBreadcrumbs() {
  const pathname = usePathname();
  const { orgSlug, orgPath } = useOrgSlug();
  const segments = pathname.split("/").filter(Boolean);

  // Skip "org" and the slug segments for breadcrumb labels
  const crumbs: { label: string; href: string }[] = [];
  let inOrgPrefix = true;
  let path = "";

  for (const segment of segments) {
    path += `/${segment}`;
    // Skip the /org/{slug} prefix
    if (inOrgPrefix && (segment === "org" || segment === orgSlug)) {
      continue;
    }
    inOrgPrefix = false;

    if (segment === "dashboard") {
      crumbs.push({ label: "Dashboard", href: orgPath("/dashboard") });
    } else if (segment === "apps") {
      continue;
    } else if (segment === "title-intelligence") {
      crumbs.push({ label: "Title Intelligence", href: orgPath("/apps/title-intelligence") });
    } else if (segment === "title-search") {
      crumbs.push({ label: "Title Search", href: orgPath("/apps/title-search") });
    } else if (segment === "packs" || segment === "orders") {
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
    } else if (segment === "chain") {
      crumbs.push({ label: "Chain", href: path });
    } else if (segment === "package") {
      crumbs.push({ label: "Package", href: path });
    } else if (segment === "profile") {
      crumbs.push({ label: "Profile", href: path });
    } else if (segment === "admin") {
      crumbs.push({ label: "Admin", href: path });
    } else if (segment === "users") {
      crumbs.push({ label: "Users", href: path });
    } else if (segment === "subscriptions") {
      crumbs.push({ label: "Subscriptions", href: path });
    } else if (segment === "export") {
      crumbs.push({ label: "Export", href: path });
    } else if (segment.match(/^[0-9a-f-]{36}$/)) {
      crumbs.push({ label: "Detail", href: path });
    }
  }

  return crumbs;
}

export default function ProtectedOrgLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const params = useParams();
  const urlSlug = params.orgSlug as string;
  const { user, isPlatformAdmin, loading: authLoading, signOut } = useAuth();
  const { data: me } = useMe();
  const { currentOrgId, setCurrentOrg } = useOrgStore();
  const { orgPath } = useOrgSlug();
  const [checkingOrg, setCheckingOrg] = useState(true);
  const [accessDenied, setAccessDenied] = useState(false);
  const [correctSlug, setCorrectSlug] = useState<string | null>(null);
  const checkedRef = useRef(false);
  const crumbs = useBreadcrumbs();

  useEffect(() => {
    if (authLoading || !user) return;
    if (checkedRef.current) return;

    // Wait for the cached /auth/me payload — it bundles the org list, so no
    // separate /organizations/me fetch is needed here.
    if (!me) return;

    checkedRef.current = true;
    const orgs = me.orgs ?? [];

    // Check if user belongs to the org matching the URL slug
    const matchingOrg = orgs.find((o) => o.slug === urlSlug);

    if (matchingOrg) {
      setCurrentOrg(matchingOrg.id, matchingOrg.name, matchingOrg.slug, matchingOrg.logo_url);
      setOrgSlugCookie(matchingOrg.slug);
    } else if (isPlatformAdmin) {
      // Platform admin can view any org — use current org or first
      if (currentOrgId) {
        setCheckingOrg(false);
        return;
      }
      if (orgs.length > 0) {
        setCurrentOrg(orgs[0].id, orgs[0].name, orgs[0].slug, orgs[0].logo_url);
      }
    } else {
      // User doesn't belong to this org
      setAccessDenied(true);
      if (orgs.length > 0) {
        setCorrectSlug(orgs[0].slug);
      }
    }
    setCheckingOrg(false);
  }, [authLoading, user, isPlatformAdmin, urlSlug, currentOrgId, setCurrentOrg, me]);

  // Redirect unauthenticated users to org login
  useEffect(() => {
    if (!authLoading && !user) {
      router.push(`/${urlSlug}`);
    }
  }, [authLoading, user, router, urlSlug]);

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

  if (accessDenied) {
    return (
      <div className="flex h-screen items-center justify-center">
        <div className="text-center space-y-4">
          <h2 className="text-xl font-semibold">Access Denied</h2>
          <p className="text-sm text-muted-foreground">
            You do not have access to this organization.
          </p>
          {correctSlug && (
            <Link
              href={`/org/${correctSlug}/dashboard`}
              className="text-sm text-primary hover:underline block"
            >
              Go to your organization
            </Link>
          )}
        </div>
      </div>
    );
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
              <Link href={orgPath("/profile")}>
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
          {/* Footer bar */}
          <footer className="flex h-9 items-center justify-center border-t bg-muted/30 px-6 text-[11px] text-muted-foreground shrink-0">
            <span>{useOrgStore.getState().currentOrgName || "Logikality"} &middot; Powered by Logikality</span>
          </footer>
        </div>
      </div>
    </ToastProvider>
  );
}
