import type { NextConfig } from "next";

// Response headers for every route (plan SEC-15). These are the ones that can't
// break the app. A full script-src CSP needs per-request nonces to coexist with
// Next's inline bootstrap scripts — add that separately and test it in a browser.
const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  // Modern equivalent of X-Frame-Options; blocks clickjacking of the operator console.
  { key: "Content-Security-Policy", value: "frame-ancestors 'none'; base-uri 'self'; form-action 'self'" },
  { key: "Referrer-Policy", value: "same-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  ...(process.env.NODE_ENV === "production"
    ? [{ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }]
    : []),
];

const nextConfig: NextConfig = {
  // Avoid Next inferring the wrong workspace root from the parent lockfile.
  outputFileTracingRoot: __dirname,
  poweredByHeader: false,
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  // Behind a reverse proxy (Dokploy/nginx) that rewrites Host, Server Actions
  // reject requests whose Origin doesn't match x-forwarded-host. If actions
  // start failing with "Invalid Server Actions request" after deploy, list the
  // public hostname here:
  // experimental: { serverActions: { allowedOrigins: ["console.example.com"] } },
};

export default nextConfig;
