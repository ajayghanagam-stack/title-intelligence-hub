/** @type {import('next').NextConfig} */
const nextConfig = {
  output: process.env.DOCKER_BUILD === 'true' ? 'standalone' : undefined,
  experimental: {},
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains; preload",
          },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=()",
          },
          {
            key: "Content-Security-Policy",
            value: process.env.NODE_ENV === 'production' 
              ? "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data: https:; font-src 'self'; connect-src 'self' https://*; frame-ancestors 'none';"
              : "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; font-src 'self'; connect-src 'self' http://localhost:8000 https://*.logikality.com https://*.preview.emergentagent.com https://*.replit.dev https://*.repl.co; frame-ancestors 'none';",
          },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
