"use client";

import { useEffect, useState, useCallback } from "react";
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
import { Blocks, Plus } from "lucide-react";

import type { MicroApp } from "@/lib/platform-types";
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
  return res.json();
}

export default function AdminAppsPage() {
  const [apps, setApps] = useState<MicroApp[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);

  // Form state
  const [appName, setAppName] = useState("");
  const [appSlug, setAppSlug] = useState("");
  const [appDescription, setAppDescription] = useState("");
  const [appIcon, setAppIcon] = useState("");
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState("");
  const [error, setError] = useState<string | null>(null);

  const fetchApps = useCallback(async () => {
    try {
      const data = await adminFetch("/api/v1/admin/apps");
      setApps(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load apps");
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    fetchApps();
  }, [fetchApps]);

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    setCreating(true);
    setFormError("");

    const slug =
      appSlug.trim() ||
      appName
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-|-$/g, "");

    try {
      await adminFetch("/api/v1/admin/apps", {
        method: "POST",
        body: JSON.stringify({
          name: appName.trim(),
          slug,
          description: appDescription.trim() || null,
          icon: appIcon.trim() || null,
        }),
      });
      setAppName("");
      setAppSlug("");
      setAppDescription("");
      setAppIcon("");
      setShowForm(false);
      fetchApps();
    } catch (err: unknown) {
      setFormError(err instanceof Error ? err.message : "Failed to create app");
    } finally {
      setCreating(false);
    }
  };

  const handleToggle = async (app: MicroApp) => {
    try {
      await adminFetch(`/api/v1/admin/apps/${app.id}`, {
        method: "PATCH",
        body: JSON.stringify({ is_active: !app.is_active }),
      });
      fetchApps();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update app");
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">Loading apps...</p>
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
            <Blocks className="h-5 w-5 text-primary" />
          </div>
          <div>
            <h2 className="text-2xl font-bold tracking-tight">Micro Apps</h2>
            <p className="text-sm text-muted-foreground">
              Manage available applications
            </p>
          </div>
        </div>
        <Button onClick={() => setShowForm(!showForm)}>
          <Plus className="h-4 w-4 mr-2" />
          New App
        </Button>
      </div>

      {showForm && (
        <Card className="shadow-sm border-primary/20">
          <CardHeader className="pb-4">
            <CardTitle className="text-lg">Create Micro App</CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleCreate} className="space-y-4">
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <label htmlFor="app-name" className="text-sm font-medium">Name</label>
                  <Input
                    id="app-name"
                    placeholder="Title Intelligence"
                    value={appName}
                    onChange={(e) => setAppName(e.target.value)}
                    required
                  />
                </div>
                <div className="space-y-2">
                  <label htmlFor="app-slug" className="text-sm font-medium">
                    Slug (auto-generated if blank)
                  </label>
                  <Input
                    id="app-slug"
                    placeholder="title-intelligence"
                    value={appSlug}
                    onChange={(e) => setAppSlug(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <label htmlFor="app-description" className="text-sm font-medium">Description</label>
                  <Input
                    id="app-description"
                    placeholder="AI-powered analysis..."
                    value={appDescription}
                    onChange={(e) => setAppDescription(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <label htmlFor="app-icon" className="text-sm font-medium">
                    Icon (lucide name)
                  </label>
                  <Input
                    id="app-icon"
                    placeholder="file-search"
                    value={appIcon}
                    onChange={(e) => setAppIcon(e.target.value)}
                  />
                </div>
              </div>

              {formError && (
                <p className="text-sm text-destructive">{formError}</p>
              )}

              <div className="flex gap-3">
                <Button type="submit" disabled={creating}>
                  {creating ? "Creating..." : "Create App"}
                </Button>
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => {
                    setShowForm(false);
                    setFormError("");
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
            All Apps ({apps.length})
          </CardTitle>
        </CardHeader>
        <CardContent>
          {apps.length === 0 ? (
            <div className="rounded-xl border-2 border-dashed p-8 text-center">
              <p className="text-muted-foreground">
                No micro apps yet. Click &quot;New App&quot; to create one.
              </p>
            </div>
          ) : (
            <div className="space-y-2">
              {apps.map((app) => (
                <div
                  key={app.id}
                  className="flex items-center justify-between rounded-lg border p-4 hover:bg-muted/30 transition-colors"
                >
                  <div>
                    <p className="font-medium">{app.name}</p>
                    <p className="text-sm text-muted-foreground">
                      {app.slug}
                      {app.description ? ` — ${app.description}` : ""}
                    </p>
                  </div>
                  <div className="flex items-center gap-3">
                    <Badge
                      className={
                        app.is_active
                          ? "bg-green-100 text-green-700 border-0"
                          : "bg-red-100 text-red-700 border-0"
                      }
                    >
                      {app.is_active ? "Active" : "Disabled"}
                    </Badge>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => handleToggle(app)}
                    >
                      {app.is_active ? "Disable" : "Enable"}
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
