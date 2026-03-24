"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import { useOrg } from "@/hooks/use-org";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { LayoutGrid, FileSearch, Search, Sparkles, ArrowRight } from "lucide-react";
import type { Subscription } from "@/lib/platform-types";

const APP_ICONS: Record<string, typeof FileSearch> = {
  "title-intelligence": FileSearch,
  "title-search": Search,
};

const APP_GRADIENTS: Record<string, string> = {
  "title-intelligence":
    "from-amber-500/15 to-orange-500/15 ring-amber-500/10",
  "title-search": "from-blue-500/15 to-cyan-500/15 ring-blue-500/10",
};

const APP_ICON_COLORS: Record<string, string> = {
  "title-intelligence": "text-amber-700",
  "title-search": "text-blue-700",
};

export default function DashboardPage() {
  const { currentOrgId, orgFetch } = useOrg();
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [toggling, setToggling] = useState<string | null>(null);

  const fetchSubscriptions = useCallback(async () => {
    if (!currentOrgId) return;
    try {
      const subs = await orgFetch<Subscription[]>("/api/v1/subscriptions");
      setSubscriptions(subs);
      setError(null);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Failed to load subscriptions"
      );
    }
    setLoading(false);
  }, [currentOrgId, orgFetch]);

  useEffect(() => {
    fetchSubscriptions();
  }, [fetchSubscriptions]);

  const toggleApp = async (subId: string, currentStatus: string) => {
    setToggling(subId);
    try {
      const action = currentStatus === "active" ? "disable" : "enable";
      await orgFetch<unknown>(`/api/v1/subscriptions/${subId}/${action}`, {
        method: "PATCH",
      });
      await fetchSubscriptions();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Failed to update subscription"
      );
    }
    setToggling(null);
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">Loading your apps...</p>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {error && (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {error}
        </div>
      )}
      <div className="flex items-center gap-4">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-brand-amber/20 to-brand-magenta/20 ring-1 ring-brand-amber/10">
          <LayoutGrid className="h-6 w-6 text-brand-charcoal" />
        </div>
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Your Apps</h2>
          <p className="text-sm text-muted-foreground mt-0.5">
            Micro apps available for your organization
          </p>
        </div>
      </div>

      {subscriptions.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 rounded-2xl border-2 border-dashed border-border/60">
          <div className="flex h-16 w-16 items-center justify-center rounded-2xl bg-muted/50 mb-4">
            <Sparkles className="h-7 w-7 text-muted-foreground/60" />
          </div>
          <p className="text-lg font-medium text-foreground/80 mb-1">
            No apps yet
          </p>
          <p className="text-sm text-muted-foreground">
            Contact your platform administrator to get started
          </p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2">
          {subscriptions.map((sub) => {
            const app = sub.micro_app;
            const slug = app?.slug || "";
            const isActive = sub.status === "active";
            const Icon = APP_ICONS[slug] || Sparkles;
            const gradient = APP_GRADIENTS[slug] || "from-muted to-muted";
            const iconColor = APP_ICON_COLORS[slug] || "text-muted-foreground";

            return (
              <div
                key={sub.id}
                className="card-warm p-5 flex flex-col gap-4"
              >
                <div className="flex items-start justify-between">
                  <div className="flex items-center gap-3">
                    <div
                      className={`flex h-11 w-11 items-center justify-center rounded-xl bg-gradient-to-br ring-1 ${gradient}`}
                    >
                      <Icon className={`h-5 w-5 ${iconColor}`} />
                    </div>
                    <div>
                      <p className="font-semibold text-base">
                        {app?.name || "Unknown App"}
                      </p>
                      <Badge
                        className={`mt-0.5 ${
                          isActive
                            ? "bg-emerald-100 text-emerald-700 border-0"
                            : "bg-red-100 text-red-700 border-0"
                        }`}
                      >
                        {isActive ? "Active" : "Disabled"}
                      </Badge>
                    </div>
                  </div>
                </div>
                <p className="text-sm text-muted-foreground line-clamp-2">
                  {app?.description || "No description"}
                </p>
                <div className="flex items-center gap-2 mt-auto pt-2 border-t">
                  {isActive && (
                    <Link
                      href={`/apps/${slug}`}
                      className="btn-cta gap-1.5 text-xs py-2 px-4"
                    >
                      Open App
                      <ArrowRight className="h-3.5 w-3.5" />
                    </Link>
                  )}
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={toggling === sub.id}
                    onClick={() => toggleApp(sub.id, sub.status)}
                    className="text-xs h-8"
                  >
                    {toggling === sub.id
                      ? "Updating..."
                      : isActive
                        ? "Disable"
                        : "Enable"}
                  </Button>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
