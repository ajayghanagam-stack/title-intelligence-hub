"use client";

import { useEffect, useState, useCallback } from "react";
import { apiFetch } from "@/lib/api";
import { getToken } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { Building2, UserPlus, Check, ChevronRight, Trash2 } from "lucide-react";
import Link from "next/link";

import type { Account, MicroApp } from "@/lib/platform-types";
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

export default function AdminAccountsPage() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [apps, setApps] = useState<MicroApp[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  // Form state
  const [companyName, setCompanyName] = useState("");
  const [adminEmail, setAdminEmail] = useState("");
  const [adminPassword, setAdminPassword] = useState("");
  const [adminFullName, setAdminFullName] = useState("");
  const [selectedApps, setSelectedApps] = useState<string[]>([]);
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState("");
  const [formSuccess, setFormSuccess] = useState("");
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const fetchData = useCallback(async () => {
    try {
      const [accts, allApps] = await Promise.all([
        adminFetch("/api/v1/admin/accounts"),
        adminFetch("/api/v1/admin/apps"),
      ]);
      setAccounts(accts);
      setApps(allApps.filter((a: MicroApp) => a.is_active));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load accounts");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const toggleApp = (slug: string) => {
    setSelectedApps((prev) =>
      prev.includes(slug) ? prev.filter((s) => s !== slug) : [...prev, slug]
    );
  };

  const handleDeleteOrg = async (orgId: string) => {
    setDeleting(true);
    setError(null);
    try {
      await adminFetch(`/api/v1/admin/accounts/${orgId}`, { method: "DELETE" });
      setConfirmDeleteId(null);
      fetchData();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete organization");
    }
    setDeleting(false);
  };

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreating(true);
    setFormError("");
    setFormSuccess("");

    const slug = companyName
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "");

    try {
      const result = await adminFetch("/api/v1/admin/accounts", {
        method: "POST",
        body: JSON.stringify({
          email: adminEmail,
          password: adminPassword,
          full_name: adminFullName,
          org_name: companyName.trim(),
          org_slug: slug,
          app_slugs: selectedApps,
        }),
      });
      setFormSuccess(
        `Account created for ${result.org_name}. User: ${result.email}`
      );
      setCompanyName("");
      setAdminEmail("");
      setAdminPassword("");
      setAdminFullName("");
      setSelectedApps([]);
      fetchData();
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "Failed to create account");
    } finally {
      setCreating(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">Loading accounts...</p>
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
            <Building2 className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h2 className="text-2xl font-bold tracking-tight">
              Customer Accounts
            </h2>
            <p className="text-sm text-muted-foreground">
              Onboard new customers and manage existing accounts
            </p>
          </div>
        </div>
        <Button onClick={() => setShowForm(!showForm)}>
          <UserPlus className="h-4 w-4 mr-2" />
          New Customer
        </Button>
      </div>

      {showForm && (
        <Card className="shadow-sm border-primary/20">
          <CardHeader className="pb-4">
            <CardTitle className="text-lg">Onboard New Customer</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleCreate} className="space-y-4">
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <label htmlFor="company-name" className="text-sm font-medium">Company Name</label>
                  <Input
                    id="company-name"
                    placeholder="Acme Title Co."
                    value={companyName}
                    onChange={(e) => setCompanyName(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <label htmlFor="admin-full-name" className="text-sm font-medium">Admin Full Name</label>
                  <Input
                    id="admin-full-name"
                    placeholder="Jane Smith"
                    value={adminFullName}
                    onChange={(e) => setAdminFullName(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <label htmlFor="admin-email" className="text-sm font-medium">Admin Email</label>
                  <Input
                    id="admin-email"
                    type="email"
                    placeholder="admin@acmetitle.com"
                    value={adminEmail}
                    onChange={(e) => setAdminEmail(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <label htmlFor="admin-password" className="text-sm font-medium">Password</label>
                  <Input
                    id="admin-password"
                    type="password"
                    placeholder="Min 6 characters"
                    value={adminPassword}
                    onChange={(e) => setAdminPassword(e.target.value)}
                    minLength={6}
                    required
                  />
                </div>
              </div>

              {apps.length > 0 && (
                <div className="space-y-2">
                  <span className="text-sm font-medium">
                    Enable Micro Apps
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {apps.map((app) => {
                      const selected = selectedApps.includes(app.slug);
                      return (
                        <button
                          key={app.id}
                          type="button"
                          onClick={() => toggleApp(app.slug)}
                          className={`inline-flex items-center gap-1.5 rounded-lg border px-3 py-2 text-sm font-medium transition-colors ${
                            selected
                              ? "border-primary bg-primary/10 text-primary"
                              : "border-input bg-background text-muted-foreground hover:bg-muted"
                          }`}
                        >
                          {selected && <Check className="h-3.5 w-3.5" />}
                          {app.name}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}

              {formError && (
                <p className="text-sm text-destructive">{formError}</p>
              )}
              {formSuccess && (
                <p className="text-sm text-green-600">{formSuccess}</p>
              )}

              <div className="flex gap-3">
                <Button type="submit" disabled={creating}>
                  {creating ? "Creating..." : "Create Account"}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setShowForm(false);
                    setFormError("");
                    setFormSuccess("");
                  }}
                >
                  Cancel
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      <Card className="shadow-sm">
        <CardHeader className="pb-4">
          <CardTitle className="text-lg">
            All Customers ({accounts.length})
          </CardTitle>
        </CardHeader>
        <CardContent>
          {accounts.length === 0 ? (
            <div className="rounded-xl border-2 border-dashed p-8 text-center">
              <p className="text-muted-foreground">
                No customer accounts yet. Click &quot;New Customer&quot; to
                onboard your first customer.
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {accounts.map((acct) => (
                <div
                  key={acct.id}
                  className="flex items-center justify-between rounded-lg border p-4 hover:bg-muted/30 transition-colors"
                >
                  <Link
                    href={`/admin/accounts/${acct.id}`}
                    className="flex-1 cursor-pointer"
                  >
                    <p className="font-medium">{acct.name}</p>
                    <p className="text-sm text-muted-foreground">
                      {acct.slug} &middot; {acct.user_count} user
                      {acct.user_count !== 1 ? "s" : ""}
                    </p>
                  </Link>
                  <div className="flex items-center gap-2">
                    <Badge
                      className={
                        acct.is_active
                          ? "bg-green-100 text-green-700 border-0"
                          : "bg-red-100 text-red-700 border-0"
                      }
                    >
                      {acct.is_active ? "Active" : "Inactive"}
                    </Badge>
                    {confirmDeleteId === acct.id ? (
                      <div className="flex items-center gap-1.5">
                        <Button
                          size="sm"
                          variant="destructive"
                          onClick={() => handleDeleteOrg(acct.id)}
                          disabled={deleting}
                          className="h-7 px-2 text-xs"
                        >
                          {deleting ? "Deleting..." : "Confirm"}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setConfirmDeleteId(null)}
                          className="h-7 px-2 text-xs"
                        >
                          Cancel
                        </Button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConfirmDeleteId(acct.id)}
                        className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground/50 hover:text-red-600 hover:bg-red-50 transition-colors"
                        title="Delete organization"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                    <Link href={`/admin/accounts/${acct.id}`}>
                      <ChevronRight className="h-4 w-4 text-muted-foreground" />
                    </Link>
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
