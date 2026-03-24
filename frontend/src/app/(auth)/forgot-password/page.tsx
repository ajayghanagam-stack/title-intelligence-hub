"use client";

import { useState, type FormEvent } from "react";
import Link from "next/link";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { API_URL } from "@/lib/config";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState("");
  const [submitted, setSubmitted] = useState(false);
  const [loading, setLoading] = useState(false);
  const [resetToken, setResetToken] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError("");
    setLoading(true);

    try {
      const res = await fetch(`${API_URL}/api/v1/auth/forgot-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({ detail: "Request failed" }));
        throw new Error(data.detail || `Error ${res.status}`);
      }

      const data = await res.json();
      setSubmitted(true);
      // In development, the API returns the token for convenience
      if (data.reset_token) {
        setResetToken(data.reset_token);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send reset request");
    } finally {
      setLoading(false);
    }
  }

  if (submitted) {
    return (
      <Card className="border-0 shadow-lg">
        <CardHeader className="space-y-1 pb-4">
          <CardTitle className="text-2xl">Check your email</CardTitle>
          <CardDescription>
            If an account with that email exists, a password reset link has been
            sent.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {resetToken && (
            <div className="rounded-lg border border-amber-200 bg-amber-50/80 p-4 space-y-2">
              <p className="text-sm font-medium text-amber-800">
                Development mode: Reset link
              </p>
              <Link
                href={`/reset-password?token=${resetToken}`}
                className="text-sm text-primary underline break-all"
              >
                Click here to reset your password
              </Link>
            </div>
          )}
          <Link href="/login">
            <Button variant="outline" className="w-full">
              Back to Sign In
            </Button>
          </Link>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card className="border-0 shadow-lg">
      <CardHeader className="space-y-1 pb-4">
        <CardTitle className="text-2xl">Forgot password</CardTitle>
        <CardDescription>
          Enter your email and we&apos;ll send you a reset link
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
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
          {error && <p className="text-sm text-destructive">{error}</p>}
          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? "Sending..." : "Send Reset Link"}
          </Button>
          <div className="text-center">
            <Link
              href="/login"
              className="text-sm text-muted-foreground hover:text-foreground transition-colors"
            >
              Back to Sign In
            </Link>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
