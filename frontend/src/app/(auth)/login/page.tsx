"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { login, setOrgSlugCookie } from "@/lib/auth";
import { useOrgStore } from "@/stores/org-store";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Loader2 } from "lucide-react";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const { setCurrentOrg } = useOrgStore();

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError("");

    try {
      const data = await login(email, password);

      if (data.orgs.length > 0) {
        setCurrentOrg(data.orgs[0].id, data.orgs[0].name, data.orgs[0].slug, data.orgs[0].logo_url);
        setOrgSlugCookie(data.orgs[0].slug);
      }
      if (data.is_platform_admin) {
        router.push("/admin/accounts");
      } else if (data.orgs.length > 0) {
        router.push(`/org/${data.orgs[0].slug}/dashboard`);
      } else {
        router.push("/dashboard");
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Login failed");
      setLoading(false);
    }
  };

  return (
    <Card className="border-0 shadow-lg">
      <CardHeader className="space-y-1 pb-4">
        <CardTitle className="text-2xl">Welcome back</CardTitle>
        <CardDescription>
          Sign in to your account to continue
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
  );
}
