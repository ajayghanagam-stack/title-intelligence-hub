"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import Image from "next/image";
import { login, setOrgSlugCookie } from "@/lib/auth";
import { useOrgStore } from "@/stores/org-store";
import { orgPath } from "@/lib/paths";
import { API_URL } from "@/lib/config";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Loader2 } from "lucide-react";

interface OrgInfo {
  id: string;
  name: string;
  slug: string;
  logo_url: string | null;
}

export default function CustomerLoginPage() {
  const params = useParams();
  const orgSlug = params.orgSlug as string;
  const router = useRouter();
  const { setCurrentOrg } = useOrgStore();

  const [orgInfo, setOrgInfo] = useState<OrgInfo | null>(null);
  const [orgLoading, setOrgLoading] = useState(true);
  const [orgError, setOrgError] = useState("");

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    fetch(`${API_URL}/api/v1/organizations/by-slug/${encodeURIComponent(orgSlug)}`)
      .then(async (res) => {
        if (!res.ok) {
          setOrgError("Organization not found");
          return;
        }
        const data = await res.json();
        setOrgInfo(data);
      })
      .catch(() => setOrgError("Failed to load organization"))
      .finally(() => setOrgLoading(false));
  }, [orgSlug]);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");

    try {
      const data = await login(email, password);

      // Verify user belongs to this org
      const userOrg = data.orgs.find((o) => o.slug === orgSlug);
      if (!userOrg && !data.is_platform_admin) {
        setError("You do not have access to this organization");
        setLoading(false);
        return;
      }

      const org = userOrg || data.orgs[0];
      if (org) {
        setCurrentOrg(org.id, org.name, org.slug);
        setOrgSlugCookie(org.slug);
      }

      router.push(orgPath(orgSlug, "/dashboard"));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Login failed");
      setLoading(false);
    }
  };

  if (orgLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-background to-muted">
        <div className="flex flex-col items-center gap-3">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
          <p className="text-sm text-muted-foreground">Loading...</p>
        </div>
      </div>
    );
  }

  if (orgError) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-background to-muted">
        <Card className="w-full max-w-md border-0 shadow-lg">
          <CardContent className="pt-6 text-center">
            <p className="text-lg font-medium text-foreground mb-2">Organization not found</p>
            <p className="text-sm text-muted-foreground mb-4">
              The URL you visited does not match any organization.
            </p>
            <Link href="/login" className="text-sm text-primary hover:underline">
              Go to platform login
            </Link>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-background to-muted p-4">
      <div className="w-full max-w-md space-y-6">
        {/* Org branding */}
        <div className="flex flex-col items-center gap-3">
          {orgInfo?.logo_url ? (
            <Image
              src={orgInfo.logo_url}
              alt={orgInfo.name}
              width={200}
              height={80}
              className="h-14 w-auto"
            />
          ) : (
            <div className="flex h-14 items-center justify-center">
              <span className="text-xl font-bold text-foreground">{orgInfo?.name}</span>
            </div>
          )}
        </div>

        <Card className="border-0 shadow-lg">
          <CardHeader className="space-y-1 pb-4">
            <CardTitle className="text-2xl">Welcome back</CardTitle>
            <CardDescription>
              Sign in to {orgInfo?.name}
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleLogin} className="space-y-4">
              <div className="space-y-2">
                <label className="text-sm font-medium" htmlFor="email">
                  Email
                </label>
                <Input
                  id="email"
                  type="email"
                  placeholder="name@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-sm font-medium" htmlFor="password">
                    Password
                  </label>
                  <Link
                    href="/forgot-password"
                    className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                  >
                    Forgot password?
                  </Link>
                </div>
                <Input
                  id="password"
                  type="password"
                  placeholder="Enter your password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
              </div>
              {error && (
                <p className="text-sm text-destructive">{error}</p>
              )}
              <button
                type="submit"
                className="btn-cta w-full gap-2"
                disabled={loading}
              >
                {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                {loading ? "Signing in..." : "Sign In"}
              </button>
            </form>
          </CardContent>
        </Card>

        <p className="text-center text-xs text-muted-foreground">
          Powered by Logikality
        </p>
      </div>
    </div>
  );
}
