import { API_URL } from "@/lib/config";

const TOKEN_KEY = "auth_token";
const SESSION_TOKEN_KEY = "admin_session_token";
const ORG_SLUG_COOKIE = "org_slug";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  // Session token (admin) takes priority — cleared on browser close
  return sessionStorage.getItem(SESSION_TOKEN_KEY) || localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string, sessionOnly = false): void {
  if (sessionOnly) {
    sessionStorage.setItem(SESSION_TOKEN_KEY, token);
  } else {
    localStorage.setItem(TOKEN_KEY, token);
  }
  // Set a marker cookie so middleware can gate protected routes server-side
  document.cookie = "has_session=1; path=/; SameSite=Lax";
}

export function setOrgSlugCookie(slug: string): void {
  document.cookie = `${ORG_SLUG_COOKIE}=${encodeURIComponent(slug)}; path=/; SameSite=Lax`;
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(SESSION_TOKEN_KEY);
  // Remove the session marker cookie so middleware redirects to login
  document.cookie = "has_session=; path=/; max-age=0";
  document.cookie = `${ORG_SLUG_COOKIE}=; path=/; max-age=0`;
}

export function isAdminSession(): boolean {
  if (typeof window === "undefined") return false;
  return sessionStorage.getItem(SESSION_TOKEN_KEY) !== null;
}

export async function login(
  email: string,
  password: string,
  sessionOnly = false
): Promise<{
  access_token: string;
  user: { id: string; email: string; full_name: string | null };
  orgs: { id: string; name: string; slug: string; logo_url: string | null }[];
  is_platform_admin: boolean;
}> {
  const res = await fetch(`${API_URL}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Login failed" }));
    throw new Error(err.detail || "Login failed");
  }

  const data = await res.json();
  // Clear any stale tokens from a previous session (e.g. admin session token
  // lingering in sessionStorage when logging in as a customer via localStorage)
  clearToken();
  setToken(data.access_token, sessionOnly);
  return data;
}

export function signOut(orgSlug?: string): void {
  const wasAdmin = isAdminSession();
  clearToken();
  if (wasAdmin) {
    window.location.href = "/manage-customers";
  } else if (orgSlug) {
    window.location.href = `/${orgSlug}`;
  } else {
    window.location.href = "/login";
  }
}

export interface MeResponse {
  user: { id: string; email: string; full_name: string | null };
  orgs: { id: string; name: string; slug: string; logo_url: string | null }[];
  is_platform_admin: boolean;
  /**
   * Bundled subscriptions for the active org when X-Org-Id is passed.
   * `null` when the header is absent or the user isn't a member of that org —
   * callers should fall back to GET /subscriptions in that case.
   */
  subscriptions: import("@/lib/platform-types").Subscription[] | null;
}

export async function fetchMe(orgId?: string | null): Promise<MeResponse | null> {
  const token = getToken();
  if (!token) return null;

  const headers: Record<string, string> = {
    Authorization: `Bearer ${token}`,
  };
  if (orgId) headers["X-Org-Id"] = orgId;

  const res = await fetch(`${API_URL}/api/v1/auth/me`, { headers });

  if (!res.ok) {
    if (res.status === 401) {
      clearToken();
      return null;
    }
    return null;
  }

  return res.json();
}
