/** @type {import('next').NextConfig} */
const isHttps = (process.env.NEXT_PUBLIC_API_URL || '').startsWith('https://');

const nextConfig = {
  output: process.env.DOCKER_BUILD === 'true' ? 'standalone' : undefined,
  experimental: {},
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: "http://localhost:8000/api/v1/:path*",
      },
    ];
  },
  // Phase 6 cutover (2026-05-10) — the LogikIntake `/loans/*` surface is now
  // canonical. Old bookmarks / external links to the legacy `/packages/*`
  // surface 301 to the new URLs. Keep these for ~7 days post-cutover, then
  // drop in a follow-up PR. `loanId == package_id` so the id segment maps 1:1.
  async redirects() {
    return [
      // Sub-pages: /apps/.../packages/{id}/{processing|results|dashboard|compliance}
      // → /apps/.../loans/{id}  (legacy sub-tabs collapse onto the unified
      // overview; the operator clicks into classify/extract/etc. from there).
      {
        source: "/apps/loan-onboarding/packages/:loanId/:legacyTab(processing|results|dashboard|compliance)",
        destination: "/apps/loan-onboarding/loans/:loanId",
        permanent: true,
      },
      {
        source: "/org/:orgSlug/apps/loan-onboarding/packages/:loanId/:legacyTab(processing|results|dashboard|compliance)",
        destination: "/org/:orgSlug/apps/loan-onboarding/loans/:loanId",
        permanent: true,
      },
      // Bare detail page: /apps/.../packages/{id} → /apps/.../loans/{id}
      {
        source: "/apps/loan-onboarding/packages/:loanId",
        destination: "/apps/loan-onboarding/loans/:loanId",
        permanent: true,
      },
      {
        source: "/org/:orgSlug/apps/loan-onboarding/packages/:loanId",
        destination: "/org/:orgSlug/apps/loan-onboarding/loans/:loanId",
        permanent: true,
      },
      // New-package wizard is replaced by an in-page modal on the queue.
      {
        source: "/apps/loan-onboarding/packages/new",
        destination: "/apps/loan-onboarding",
        permanent: true,
      },
      {
        source: "/org/:orgSlug/apps/loan-onboarding/packages/new",
        destination: "/org/:orgSlug/apps/loan-onboarding",
        permanent: true,
      },
    ];
  },
  async headers() {
    const securityHeaders = [
      { key: "X-Frame-Options", value: "DENY" },
      { key: "X-Content-Type-Options", value: "nosniff" },
      { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
      {
        key: "Permissions-Policy",
        value: "camera=(), microphone=(), geolocation=()",
      },
      {
        // Brand guideline §2 typography — Mona Sans is self-hosted via
        // next/font/google (build-time fetch + bundle), so no external
        // font CDN allowance is needed in style-src / font-src. The
        // previous Typekit allowlist (use.typekit.net, p.typekit.net)
        // has been removed.
        key: "Content-Security-Policy",
        value: process.env.NODE_ENV === 'production'
          ? `default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data: https:; font-src 'self' data:; connect-src 'self' ${isHttps ? 'https://*' : 'http://* https://*'}; frame-ancestors 'none';`
          : "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; font-src 'self' data:; connect-src 'self' http://localhost:8000 https://*.logikality.ai https://*.preview.emergentagent.com https://*.replit.dev https://*.repl.co; frame-ancestors 'none';",
      },
    ];

    // Only add HSTS when serving over HTTPS
    if (isHttps) {
      securityHeaders.push({
        key: "Strict-Transport-Security",
        value: "max-age=63072000; includeSubDomains; preload",
      });
    }

    return [
      {
        source: "/(.*)",
        headers: securityHeaders,
      },
    ];
  },
};

module.exports = nextConfig;
