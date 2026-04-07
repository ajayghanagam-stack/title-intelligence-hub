import { getToken, clearToken } from "@/lib/auth";
import { API_URL } from "@/lib/config";

export { API_URL };

function handleUnauthorized() {
  clearToken();
  if (typeof window !== "undefined") {
    // If we're on an org-scoped URL, redirect to org login (canonical /{slug})
    const orgMatch = window.location.pathname.match(/^\/org\/([^/]+)/);
    if (orgMatch) {
      window.location.href = `/${orgMatch[1]}`;
    } else {
      window.location.href = "/login";
    }
  }
}

export async function apiFetch<T = unknown>(
  path: string,
  options: RequestInit & { orgId?: string } = {}
): Promise<T> {
  const token = getToken();
  const { orgId, ...fetchOptions } = options;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(fetchOptions.headers as Record<string, string>),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  if (orgId) {
    headers["X-Org-Id"] = orgId;
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...fetchOptions,
    headers,
  });

  if (response.status === 401) {
    handleUnauthorized();
    throw new Error("Session expired");
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail || `API error: ${response.status}`);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json();
}

export async function apiFetchBlob(
  path: string,
  options: RequestInit & { orgId?: string } = {}
): Promise<Blob> {
  const token = getToken();
  const { orgId, ...fetchOptions } = options;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(fetchOptions.headers as Record<string, string>),
  };

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  if (orgId) {
    headers["X-Org-Id"] = orgId;
  }

  const response = await fetch(`${API_URL}${path}`, {
    ...fetchOptions,
    headers,
  });

  if (response.status === 401) {
    handleUnauthorized();
    throw new Error("Session expired");
  }

  if (!response.ok) {
    throw new Error(`API error: ${response.status}`);
  }

  return response.blob();
}

export async function uploadFiles(
  path: string,
  files: File[],
  options: { orgId?: string } = {}
) {
  const token = getToken();

  const headers: Record<string, string> = {};

  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  if (options.orgId) {
    headers["X-Org-Id"] = options.orgId;
  }

  const formData = new FormData();
  files.forEach((file) => formData.append("files", file));

  const response = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers,
    body: formData,
  });

  if (response.status === 401) {
    handleUnauthorized();
    throw new Error("Session expired");
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Upload failed" }));
    throw new Error(error.detail || `API error: ${response.status}`);
  }

  return response.json();
}
