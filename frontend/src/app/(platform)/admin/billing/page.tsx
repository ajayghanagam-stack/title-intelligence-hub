"use client";

import { useEffect, useState, useCallback } from "react";
import { getToken } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { Receipt, Download } from "lucide-react";

import type { Account, OrgUsage } from "@/lib/platform-types";
import { API_URL } from "@/lib/config";

async function adminFetch(path: string, options: RequestInit = {}) {
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const res = await fetch(`${API_URL}${path}`, { ...options, headers });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(err.detail || `Error ${res.status}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

function todayISO(): string {
  return new Date().toISOString().slice(0, 10);
}

function firstOfMonthISO(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-01`;
}

export default function AdminBillingPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [usageMap, setUsageMap] = useState<Record<string, OrgUsage>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [startDate, setStartDate] = useState(firstOfMonthISO());
  const [endDate, setEndDate] = useState(todayISO());
  const [downloading, setDownloading] = useState<string | null>(null);

  const fetchUsage = useCallback(async (accts: Account[]) => {
    const map: Record<string, OrgUsage> = {};
    const results = await Promise.allSettled(
      accts.map((acct) =>
        adminFetch(
          `/api/v1/admin/billing/${acct.id}?start_date=${startDate}&end_date=${endDate}`
        )
      )
    );
    results.forEach((result, idx) => {
      if (result.status === "fulfilled" && result.value) {
        map[accts[idx].id] = result.value as OrgUsage;
      }
    });
    setUsageMap(map);
  }, [startDate, endDate]);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const accts: Account[] = await adminFetch("/api/v1/admin/accounts");
      setAccounts(accts);
      await fetchUsage(accts);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load data");
    }
    setLoading(false);
  }, [fetchUsage]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const handleRefresh = () => {
    fetchData();
  };

  const handleDownloadPdf = async (orgId: string, orgName: string) => {
    setDownloading(orgId);
    try {
      const token = getToken();
      const res = await fetch(
        `${API_URL}/api/v1/admin/billing/${orgId}/pdf?start_date=${startDate}&end_date=${endDate}`,
        {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
        }
      );
      if (!res.ok) throw new Error("Failed to download PDF");

      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `usage_report_${orgName.replace(/\s+/g, "_")}_${startDate}_${endDate}.pdf`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Download failed");
    }
    setDownloading(null);
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">Loading billing data...</p>
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

      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10">
            <Receipt className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h2 className="text-2xl font-bold tracking-tight">Billing</h2>
            <p className="text-sm text-muted-foreground">
              Per-organization usage reports
            </p>
          </div>
        </div>
      </div>

      {/* Date range controls */}
      <Card className="shadow-sm">
        <CardContent className="pt-6">
          <div className="flex flex-wrap items-end gap-4">
            <div className="space-y-1">
              <label htmlFor="start-date" className="text-sm font-medium">
                Start Date
              </label>
              <Input
                id="start-date"
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
                className="w-44"
              />
            </div>
            <div className="space-y-1">
              <label htmlFor="end-date" className="text-sm font-medium">
                End Date
              </label>
              <Input
                id="end-date"
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
                className="w-44"
              />
            </div>
            <Button onClick={handleRefresh}>Update</Button>
          </div>
        </CardContent>
      </Card>

      {/* Per-org usage cards */}
      {accounts.length === 0 ? (
        <Card className="shadow-sm">
          <CardContent className="py-8">
            <div className="rounded-xl border-2 border-dashed p-8 text-center">
              <p className="text-muted-foreground">
                No customer accounts found.
              </p>
            </div>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-4">
          {accounts.map((acct) => {
            const usage = usageMap[acct.id];
            return (
              <Card key={acct.id} className="shadow-sm">
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-lg">{acct.name}</CardTitle>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => handleDownloadPdf(acct.id, acct.name)}
                      disabled={downloading === acct.id}
                    >
                      <Download className="h-4 w-4 mr-2" />
                      {downloading === acct.id
                        ? "Downloading..."
                        : "Download PDF"}
                    </Button>
                  </div>
                </CardHeader>
                <CardContent>
                  {usage && usage.apps.length > 0 ? (
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="border-b text-left">
                            <th className="pb-2 pr-4 font-medium text-muted-foreground">
                              Application
                            </th>
                            <th className="pb-2 pr-4 font-medium text-muted-foreground text-center">
                              Completed
                            </th>
                          </tr>
                        </thead>
                        <tbody>
                          {usage.apps.map((app) => (
                            <tr key={app.app_slug} className="border-b last:border-0">
                              <td className="py-2 pr-4">{app.app_name}</td>
                              <td className="py-2 pr-4 text-center font-medium">
                                {app.completed_count}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : (
                    <p className="text-sm text-muted-foreground">
                      No usage data for this period.
                    </p>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}
