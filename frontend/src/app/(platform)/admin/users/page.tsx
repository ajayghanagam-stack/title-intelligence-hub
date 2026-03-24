"use client";

import { useEffect, useState } from "react";
import { useOrg } from "@/hooks/use-org";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { Users, UserPlus, Copy, Check, KeyRound, Trash2 } from "lucide-react";
import type { User } from "@/lib/platform-types";

interface InviteResult {
  email: string;
  temporary_password: string;
}

export default function AdminUsersPage() {
  const { currentOrgId, orgFetch } = useOrg();
  const [users, setUsers] = useState<User[]>([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("member");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [inviteResult, setInviteResult] = useState<InviteResult | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const fetchUsers = async () => {
    if (!currentOrgId) return;
    try {
      const data = await orgFetch<User[]>(
        `/api/v1/organizations/${currentOrgId}/users`
      );
      setUsers(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load users");
    }
    setLoading(false);
  };

  useEffect(() => {
    fetchUsers();
  }, [currentOrgId]);

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!currentOrgId) return;
    setInviteResult(null);
    try {
      const result = await orgFetch<InviteResult & Record<string, unknown>>(
        `/api/v1/organizations/${currentOrgId}/users/invite`,
        {
          method: "POST",
          body: JSON.stringify({ email: inviteEmail, role: inviteRole }),
        }
      );
      setInviteResult({
        email: result.email,
        temporary_password: result.temporary_password,
      });
      setInviteEmail("");
      fetchUsers();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to invite user");
    }
  };

  const handleDelete = async (userId: string) => {
    if (!currentOrgId) return;
    setDeleting(true);
    setError(null);
    try {
      await orgFetch(
        `/api/v1/organizations/${currentOrgId}/users/${userId}`,
        { method: "DELETE" }
      );
      setConfirmDeleteId(null);
      fetchUsers();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to remove user");
    }
    setDeleting(false);
  };

  const handleCopy = async () => {
    if (!inviteResult) return;
    await navigator.clipboard.writeText(inviteResult.temporary_password);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2">
        <div className="h-5 w-5 animate-spin rounded-full border-2 border-primary border-t-transparent" />
        <p className="text-sm text-muted-foreground">Loading users...</p>
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
          <Users className="h-5 w-5 text-primary" />
        </div>
        <h2 className="text-2xl font-bold tracking-tight">Manage Users</h2>
      </div>

      <Card className="shadow-sm">
        <CardHeader className="pb-4">
          <div className="flex items-center gap-2">
            <UserPlus className="h-4 w-4 text-primary" />
            <CardTitle className="text-lg">Invite User</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="space-y-4">
          <form onSubmit={handleInvite} className="flex gap-3">
            <Input
              type="email"
              placeholder="Email address"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
              required
              className="flex-1"
            />
            <select
              className="rounded-lg border border-input bg-background px-3 py-2 text-sm"
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value)}
            >
              <option value="member">Member</option>
              <option value="admin">Admin</option>
            </select>
            <Button type="submit">Invite</Button>
          </form>

          {inviteResult && (
            <div className="rounded-xl border border-amber-200 bg-amber-50/80 p-4 space-y-2">
              <div className="flex items-center gap-2">
                <KeyRound className="h-4 w-4 text-amber-700" />
                <p className="text-sm font-medium text-amber-800">
                  User invited successfully
                </p>
              </div>
              <p className="text-sm text-amber-700">
                Share these credentials with <strong>{inviteResult.email}</strong>:
              </p>
              <div className="flex items-center gap-2">
                <code className="flex-1 rounded-md bg-white px-3 py-2 text-sm font-mono border border-amber-200">
                  {inviteResult.temporary_password}
                </code>
                <button
                  onClick={handleCopy}
                  className="flex h-9 w-9 items-center justify-center rounded-md border border-amber-200 bg-white text-amber-700 hover:bg-amber-100 transition-colors"
                  title="Copy password"
                >
                  {copied ? (
                    <Check className="h-4 w-4" />
                  ) : (
                    <Copy className="h-4 w-4" />
                  )}
                </button>
              </div>
              <p className="text-xs text-amber-600">
                This password is shown only once. The user should change it after first login.
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      <Card className="shadow-sm">
        <CardHeader className="pb-4">
          <CardTitle className="text-lg">Team Members</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            {users.map((user) => (
              <div
                key={user.id}
                className="flex items-center justify-between rounded-lg border p-3.5 hover:bg-muted/30 transition-colors"
              >
                <div>
                  <p className="font-medium">
                    {user.full_name || user.email}
                  </p>
                  <p className="text-sm text-muted-foreground">{user.email}</p>
                </div>
                <div className="flex items-center gap-2">
                  <Badge
                    className={
                      user.role === "owner"
                        ? "bg-primary text-primary-foreground border-0"
                        : ""
                    }
                    variant={user.role === "owner" ? "default" : "secondary"}
                  >
                    {user.role}
                  </Badge>
                  {user.role !== "owner" && (
                    <>
                      {confirmDeleteId === user.id ? (
                        <div className="flex items-center gap-1.5">
                          <Button
                            size="sm"
                            variant="destructive"
                            onClick={() => handleDelete(user.id)}
                            disabled={deleting}
                            className="h-7 px-2 text-xs"
                          >
                            {deleting ? "Removing..." : "Confirm"}
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
                          onClick={() => setConfirmDeleteId(user.id)}
                          className="flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground/50 hover:text-red-600 hover:bg-red-50 transition-colors"
                          title="Remove user"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      )}
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
