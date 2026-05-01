"use client";

import { useEffect, useState, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { getToken } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import Image from "next/image";
import { ArrowLeft, Building2, Users, Package, Plus, Trash2, KeyRound, ImageIcon } from "lucide-react";

import type { AccountDetail, MicroApp } from "@/lib/platform-types";
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

export default function AccountDetailPage() {
  const params = useParams();
  const router = useRouter();
  const orgId = params.orgId as string;

  const [account, setAccount] = useState<AccountDetail | null>(null);
  const [allApps, setAllApps] = useState<MicroApp[]>([]);
  const [loading, setLoading] = useState(true);
  const [actionLoading, setActionLoading] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [resetUserId, setResetUserId] = useState<string | null>(null);
  const [newPassword, setNewPassword] = useState("");
  const [resetSuccess, setResetSuccess] = useState("");
  const [confirmDeleteUserId, setConfirmDeleteUserId] = useState<string | null>(null);
  const [logoUrlDraft, setLogoUrlDraft] = useState("");
  const [logoSavedMsg, setLogoSavedMsg] = useState("");

  const fetchData = useCallback(async () => {
    try {
      const [acct, apps] = await Promise.all([
        adminFetch(`/api/v1/admin/accounts/${orgId}`),
        adminFetch("/api/v1/admin/apps"),
      ]);
      setAccount(acct);
      setLogoUrlDraft(acct.logo_url ?? "");
      setAllApps(apps.filter((a: MicroApp) => a.is_active));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to load account");
    }
    setLoading(false);
  }, [orgId]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const enableApp = async (appId: string) => {
    setActionLoading(appId);
    setError("");
    try {
      await adminFetch(`/api/v1/admin/accounts/${orgId}/subscriptions`, {
        method: "POST",
        body: JSON.stringify({ app_id: appId }),
      });
      await fetchData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to enable app");
    }
    setActionLoading(null);
  };

  const disableApp = async (subId: string) => {
    setActionLoading(subId);
    setError("");
    try {
      await adminFetch(`/api/v1/admin/accounts/${orgId}/subscriptions/${subId}`, {
        method: "DELETE",
      });
      await fetchData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to disable app");
    }
    setActionLoading(null);
  };

  const deleteUser = async (userId: string) => {
    setActionLoading(userId);
    setError("");
    try {
      await adminFetch(`/api/v1/admin/accounts/${orgId}/users/${userId}`, {
        method: "DELETE",
      });
      setConfirmDeleteUserId(null);
      await fetchData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to delete user");
    }
    setActionLoading(null);
  };

  const saveLogoUrl = async () => {
    setActionLoading("logo");
    setError("");
    setLogoSavedMsg("");
    try {
      const trimmed = logoUrlDraft.trim();
      // Platform-admin route — bypasses TenantContextMiddleware (which would
      // otherwise demand X-Org-Id matching the platform admin's *own* org).
      // Empty string clears the logo (sent as null).
      await adminFetch(`/api/v1/admin/accounts/${orgId}`, {
        method: "PATCH",
        body: JSON.stringify({ logo_url: trimmed === "" ? null : trimmed }),
      });
      setLogoSavedMsg("Logo updated. Reload the org's login page or sign in again to see the change.");
      await fetchData();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to update logo");
    }
    setActionLoading(null);
  };

  const resetPassword = async (userId: string) => {
    if (newPassword.length < 6) {
      setError("Password must be at least 6 characters");
      return;
    }
    setActionLoading(userId);
    setError("");
    setResetSuccess("");
    try {
      await adminFetch(`/api/v1/admin/accounts/${orgId}/users/${userId}/password`, {
        method: "PATCH",
        body: JSON.stringify({ new_password: newPassword }),
      });
      setResetSuccess("Password reset successfully");
      setResetUserId(null);
      setNewPassword("");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to reset password");
    }
    setActionLoading(null);
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">Loading account...</p>
      </div>
    );
  }

  if (!account) {
    return (
      <div className="space-y-4">
        <p className="text-destructive">{error || "Account not found"}</p>
        <Button variant="outline" onClick={() => router.push("/admin/accounts")}>
          <ArrowLeft className="h-4 w-4 mr-2" /> Back to Accounts
        </Button>
      </div>
    );
  }

  const subscribedAppIds = new Set(account.subscriptions.map((s) => s.app_id));
  const availableApps = allApps.filter((app) => !subscribedAppIds.has(app.id));

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <Button variant="ghost" size="icon" onClick={() => router.push("/admin/accounts")}>
          <ArrowLeft className="h-5 w-5" />
        </Button>
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-primary/10">
          <Building2 className="h-5 w-5 text-primary" />
        </div>
        <div>
          <h2 className="text-2xl font-bold tracking-tight">{account.name}</h2>
          <p className="text-sm text-muted-foreground">
            {account.slug} &middot; Created{" "}
            {new Date(account.created_at).toLocaleDateString()}
          </p>
        </div>
        <Badge
          className={`ml-2 ${
            account.is_active
              ? "bg-green-100 text-green-700 border-0"
              : "bg-red-100 text-red-700 border-0"
          }`}
        >
          {account.is_active ? "Active" : "Inactive"}
        </Badge>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {resetSuccess && <p className="text-sm text-green-600">{resetSuccess}</p>}

      {/* Branding — sets logo shown on /{slug}/login + sidebar after login */}
      <Card className="shadow-sm">
        <CardHeader className="pb-4">
          <CardTitle className="text-lg flex items-center gap-2">
            <ImageIcon className="h-5 w-5" />
            Branding
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
            <div className="flex h-24 w-48 shrink-0 items-center justify-center rounded-lg border bg-muted/30">
              {account.logo_url ? (
                <Image
                  src={account.logo_url}
                  alt={`${account.name} logo`}
                  width={200}
                  height={80}
                  className="max-h-20 w-auto"
                />
              ) : (
                <span className="text-xs text-muted-foreground">No logo set</span>
              )}
            </div>
            <div className="flex-1 space-y-2">
              <label className="text-sm font-medium" htmlFor="logo-url-input">
                Logo URL
              </label>
              <Input
                id="logo-url-input"
                value={logoUrlDraft}
                onChange={(e) => setLogoUrlDraft(e.target.value)}
                placeholder="/logikcore-primary.svg or https://cdn.example.com/logo.svg"
              />
              <p className="text-xs text-muted-foreground">
                Public asset path (e.g. <code>/logikcore-primary.svg</code>) or an absolute URL. Shown on the org&rsquo;s
                login page (<code>/{account.slug}/login</code>) and in the sidebar after login.
              </p>
              {logoSavedMsg && <p className="text-xs text-green-600">{logoSavedMsg}</p>}
              <div className="flex gap-2 pt-1">
                <Button
                  size="sm"
                  onClick={saveLogoUrl}
                  disabled={actionLoading === "logo" || logoUrlDraft.trim() === (account.logo_url ?? "")}
                >
                  {actionLoading === "logo" ? "Saving..." : "Save logo"}
                </Button>
                {account.logo_url && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setLogoUrlDraft("");
                    }}
                    disabled={actionLoading === "logo"}
                  >
                    Clear
                  </Button>
                )}
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Enabled Micro Apps */}
      <Card className="shadow-sm">
        <CardHeader className="pb-4">
          <CardTitle className="text-lg flex items-center gap-2">
            <Package className="h-5 w-5" />
            Enabled Micro Apps ({account.subscriptions.length})
          </CardTitle>
        </CardHeader>
        <CardContent>
          {account.subscriptions.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No micro apps enabled for this customer.
            </p>
          ) : (
            <div className="space-y-2">
              {account.subscriptions.map((sub) => (
                <div
                  key={sub.id}
                  className="flex items-center justify-between rounded-lg border p-4"
                >
                  <div>
                    <p className="font-medium">{sub.app_name}</p>
                    <p className="text-sm text-muted-foreground">{sub.app_slug}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge className="bg-green-100 text-green-700 border-0">
                      {sub.status}
                    </Badge>
                    <Button
                      variant="outline"
                      size="sm"
                      className="text-destructive hover:text-destructive"
                      disabled={actionLoading === sub.id}
                      onClick={() => disableApp(sub.id)}
                    >
                      <Trash2 className="h-4 w-4 mr-1" />
                      {actionLoading === sub.id ? "Removing..." : "Remove"}
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Available Micro Apps */}
      {availableApps.length > 0 && (
        <Card className="shadow-sm">
          <CardHeader className="pb-4">
            <CardTitle className="text-lg flex items-center gap-2">
              <Plus className="h-5 w-5" />
              Available Micro Apps
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {availableApps.map((app) => (
                <div
                  key={app.id}
                  className="flex items-center justify-between rounded-lg border border-dashed p-4"
                >
                  <div>
                    <p className="font-medium">{app.name}</p>
                    <p className="text-sm text-muted-foreground">{app.slug}</p>
                  </div>
                  <Button
                    size="sm"
                    disabled={actionLoading === app.id}
                    onClick={() => enableApp(app.id)}
                  >
                    <Plus className="h-4 w-4 mr-1" />
                    {actionLoading === app.id ? "Enabling..." : "Enable"}
                  </Button>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Users */}
      <Card className="shadow-sm">
        <CardHeader className="pb-4">
          <CardTitle className="text-lg flex items-center gap-2">
            <Users className="h-5 w-5" />
            Users ({account.users.length})
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {account.users.map((user) => (
              <div key={user.id} className="rounded-lg border p-4 space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="font-medium">
                      {user.full_name || user.email}
                    </p>
                    <p className="text-sm text-muted-foreground">{user.email}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline">{user.role}</Badge>
                    <Badge
                      className={
                        user.is_active
                          ? "bg-green-100 text-green-700 border-0"
                          : "bg-red-100 text-red-700 border-0"
                      }
                    >
                      {user.is_active ? "Active" : "Inactive"}
                    </Badge>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setResetUserId(resetUserId === user.id ? null : user.id);
                        setNewPassword("");
                        setError("");
                        setResetSuccess("");
                      }}
                    >
                      <KeyRound className="h-4 w-4 mr-1" />
                      Reset Password
                    </Button>
                    {confirmDeleteUserId === user.id ? (
                      <div className="flex items-center gap-1.5">
                        <Button
                          size="sm"
                          variant="destructive"
                          disabled={actionLoading === user.id}
                          onClick={() => deleteUser(user.id)}
                          className="h-7 px-2 text-xs"
                        >
                          {actionLoading === user.id ? "Deleting..." : "Confirm"}
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setConfirmDeleteUserId(null)}
                          className="h-7 px-2 text-xs"
                        >
                          Cancel
                        </Button>
                      </div>
                    ) : (
                      <Button
                        variant="outline"
                        size="sm"
                        className="text-destructive hover:text-destructive"
                        onClick={() => setConfirmDeleteUserId(user.id)}
                      >
                        <Trash2 className="h-4 w-4 mr-1" />
                        Delete
                      </Button>
                    )}
                  </div>
                </div>
                {resetUserId === user.id && (
                  <div className="flex items-center gap-2 pl-1">
                    <Input
                      type="password"
                      placeholder="New password (min 6 chars)"
                      value={newPassword}
                      onChange={(e) => setNewPassword(e.target.value)}
                      className="max-w-xs"
                    />
                    <Button
                      size="sm"
                      disabled={actionLoading === user.id}
                      onClick={() => resetPassword(user.id)}
                    >
                      {actionLoading === user.id ? "Resetting..." : "Confirm"}
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => { setResetUserId(null); setNewPassword(""); }}
                    >
                      Cancel
                    </Button>
                  </div>
                )}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
