"use client";

import { useEffect, useState } from "react";
import { useOrg } from "@/hooks/use-org";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { CreditCard } from "lucide-react";
import type { Subscription } from "@/lib/platform-types";

export default function AdminSubscriptionsPage() {
  const { currentOrgId, orgFetch } = useOrg();
  const [subscriptions, setSubscriptions] = useState<Subscription[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = async () => {
    if (!currentOrgId) return;
    try {
      const subs = await orgFetch<Subscription[]>("/api/v1/subscriptions");
      setSubscriptions(subs);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load subscriptions");
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchData();
  }, [currentOrgId]);

  const handleToggle = async (subId: string, currentStatus: string) => {
    const action = currentStatus === "active" ? "disable" : "enable";
    try {
      await orgFetch<unknown>(`/api/v1/subscriptions/${subId}/${action}`, {
        method: "PATCH",
      });
      fetchData();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update subscription");
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">Loading subscriptions...</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4 text-sm text-destructive">
          {error}
        </div>
      )}
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10">
          <CreditCard className="h-5 w-5 text-primary" />
        </div>
        <h2 className="text-2xl font-bold tracking-tight">Manage Subscriptions</h2>
      </div>

      <Card className="shadow-sm">
        <CardHeader className="pb-4">
          <CardTitle className="text-lg">Active Subscriptions</CardTitle>
        </CardHeader>
        <CardContent>
          {subscriptions.length === 0 ? (
            <div className="rounded-xl border-2 border-dashed p-8 text-center">
              <p className="text-muted-foreground">No subscriptions yet.</p>
            </div>
          ) : (
            <div className="space-y-2">
              {subscriptions.map((sub) => (
                <div
                  key={sub.id}
                  className="flex items-center justify-between rounded-lg border p-3.5 hover:bg-muted/30 transition-colors"
                >
                  <div>
                    <p className="font-medium">
                      {sub.micro_app?.name || "Unknown App"}
                    </p>
                    <p className="text-sm text-muted-foreground">
                      {sub.micro_app?.description}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge
                      className={
                        sub.status === "active"
                          ? "bg-success text-success-foreground border-0"
                          : ""
                      }
                      variant={sub.status === "active" ? "default" : "secondary"}
                    >
                      {sub.status}
                    </Badge>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleToggle(sub.id, sub.status)}
                    >
                      {sub.status === "active" ? "Disable" : "Enable"}
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

    </div>
  );
}
