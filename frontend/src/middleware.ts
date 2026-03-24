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
 *
 * If a higher security posture is required (e.g., httpOnly JWT cookie), the auth
 * system would need to be refactored to use cookie-based token storage with a
 * server-side token refresh endpoint.
 */
export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Allow public paths and static assets
  if (PUBLIC_PATHS.has(pathname) || pathname === "/") {
    return NextResponse.next();
  }

  // Protected routes: check for the session marker cookie
  // (set by the client on login, cleared on logout)
  const hasSession = request.cookies.get("has_session");
  if (!hasSession || hasSession.value !== "1") {
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
