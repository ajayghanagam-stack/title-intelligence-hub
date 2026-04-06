/**
 * Centralized path helpers for org-scoped routing.
 * All customer-facing links should use orgPath() to ensure URLs
 * include the org slug prefix.
 */

export function orgPath(slug: string, path: string): string {
  return `/org/${slug}${path}`;
}
