"use client";

import { useState } from "react";
import Image from "next/image";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { apiFetch } from "@/lib/api";
import { useOrgStore } from "@/stores/org-store";
import type { Org, MicroApp } from "@/lib/platform-types";

export function Onboarding() {
  const [orgName, setOrgName] = useState("");
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const { setCurrentOrg } = useOrgStore();

  const handleCreate = async () => {
    if (!orgName.trim()) return;
    setCreating(true);
    setError("");

    try {
      // Create organization (also creates user record as owner)
      const slug = orgName
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-|-$/g, "");

      const org = await apiFetch<Org>("/api/v1/organizations", {
        method: "POST",
        body: JSON.stringify({ name: orgName.trim(), slug }),
      });

      // Subscribe to Title Intelligence
      const apps = await apiFetch<MicroApp[]>("/api/v1/micro-apps");
      const tiApp = apps.find((a) => a.slug === "title-intelligence");
      if (tiApp) {
        await apiFetch<unknown>("/api/v1/subscriptions", {
          method: "POST",
          body: JSON.stringify({ app_id: tiApp.id }),
          orgId: org.id,
        });
      }

      // Set org in store
      setCurrentOrg(org.id, org.name);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to create organization");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="flex h-screen items-center justify-center bg-muted/30">
      <div className="mx-auto w-full max-w-md space-y-8 p-8">
        <div className="text-center">
          <div className="flex items-center justify-center gap-2.5 mb-4">
            <Image
              src="/logikality_logo.png"
              alt="Logikality"
              width={36}
              height={36}
              className="rounded"
            />
            <span className="text-xl font-semibold tracking-tight">logikality</span>
          </div>
          <h1 className="text-2xl font-bold">Welcome</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Create your organization to get started.
          </p>
        </div>

        <div className="space-y-4 rounded-xl border bg-card p-6 shadow-sm">
          <div className="space-y-2">
            <label htmlFor="org-name" className="text-sm font-medium">Organization Name</label>
            <Input
              id="org-name"
              value={orgName}
              onChange={(e) => setOrgName(e.target.value)}
              placeholder="e.g., Acme Title Company"
              onKeyDown={(e) => e.key === "Enter" && handleCreate()}
            />
          </div>

          {error && (
            <p className="text-sm text-destructive">{error}</p>
          )}

          <Button
            onClick={handleCreate}
            disabled={!orgName.trim() || creating}
            className="w-full"
          >
            {creating ? "Setting up..." : "Create Organization"}
          </Button>
        </div>
      </div>
    </div>
  );
}
