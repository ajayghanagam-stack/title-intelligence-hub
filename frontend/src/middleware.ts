import { NextResponse, type NextRequest } from "next/server";

const PUBLIC_PATHS = new Set(["/login", "/manage-customers", "/forgot-password", "/reset-password"]);

/**
 * Edge middleware for route protection.
 *
 * JWT tokens are stored in localStorage (client-side only, not accessible from
 * Edge middleware). We use a `has_session` marker cookie set on login and cleared
 * on logout to gate protected routes server-side. Full JWT validation happens on
 * every API call via the backend's auth middleware — this layer prevents serving
 * page shells to users who have explicitly logged out or never logged in.
 */
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const hasSession = request.cookies.get("has_session")?.value === "1";
  const orgSlugCookie = request.cookies.get("org_slug")?.value;

  // Allow public paths and static assets
  if (PUBLIC_PATHS.has(pathname) || pathname === "/") {
    return NextResponse.next();
  }

  // --- Vanity URLs: /<slug> is the canonical customer login URL ---
  // Rewrite (not redirect) so the URL stays as /<slug> in the browser.
  const RESERVED_PREFIXES = new Set([
    "/login", "/manage-customers", "/forgot-password", "/reset-password",
    "/dashboard", "/profile", "/admin", "/apps", "/org", "/error",
    "/logikality",
  ]);
  if (/^\/[a-z0-9]+$/i.test(pathname) && !RESERVED_PREFIXES.has(pathname)) {
    const slug = pathname.slice(1);
    if (hasSession) {
      return NextResponse.redirect(new URL(`/org/${slug}/dashboard`, request.url));
    }
    return NextResponse.rewrite(new URL(`/org/${slug}/login`, request.url));
  }

  // --- Customer org routes: /org/{slug}/... ---
  const orgMatch = pathname.match(/^\/org\/([^/]+)(\/(.*))?$/);
  if (orgMatch) {
    const slug = orgMatch[1];
    const rest = orgMatch[3] || "";

    // /org/{slug}/login → redirect to canonical /{slug}
    if (rest === "login") {
      return NextResponse.redirect(new URL(`/${slug}`, request.url));
    }

    // /org/{slug} (exact) → redirect based on session
    if (!rest) {
      if (hasSession) {
        return NextResponse.redirect(new URL(`/org/${slug}/dashboard`, request.url));
      }
      return NextResponse.redirect(new URL(`/${slug}`, request.url));
    }

    // /org/{slug}/* (other routes) → require session
    if (!hasSession) {
      return NextResponse.redirect(new URL(`/${slug}`, request.url));
    }

    return NextResponse.next();
  }

  // --- Admin routes: /admin/* ---
  if (pathname.startsWith("/admin")) {
    if (!hasSession) {
      const loginUrl = new URL("/manage-customers", request.url);
      return NextResponse.redirect(loginUrl);
    }
    return NextResponse.next();
  }

  // --- Legacy routes: /dashboard, /apps/*, /profile ---
  // If user has a session + org_slug cookie, redirect to org-scoped URL
  if (
    orgSlugCookie &&
    hasSession &&
    (pathname === "/dashboard" ||
      pathname.startsWith("/apps/") ||
      pathname === "/profile" ||
      pathname.startsWith("/profile/"))
  ) {
    const orgPath = `/org/${orgSlugCookie}${pathname}`;
    return NextResponse.redirect(new URL(orgPath, request.url));
  }

  // Protected routes: check for the session marker cookie
  if (!hasSession) {
    const loginUrl = new URL("/login", request.url);
    loginUrl.searchParams.set("redirect", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico|api|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
  ],
};
