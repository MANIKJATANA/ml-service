import type { NextConfig } from "next";

// BP8c (decisions/0051): the browser-facing security headers. Only the Next BFF talks to the
// browser (the FastAPI backend is reached via /api proxying), so THIS is where headers
// actually protect users. The CSP is sized to the app's real needs; `'unsafe-eval'` is added
// only in dev (React's HMR/debug uses eval — never in prod) and `'unsafe-inline'` covers
// Next's inline bootstrap + Tailwind (a nonce-based strict CSP via proxy.ts is a follow-up).
const isDev = process.env.NODE_ENV !== "production";

const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`,
  "style-src 'self' 'unsafe-inline'",
  // Signed image/video URLs load straight from Supabase; blob:/data: for object URLs.
  "img-src 'self' https://*.supabase.co data: blob:",
  "media-src 'self' https://*.supabase.co blob:",
  // fetch/XHR: same-origin (the /api BFF) + direct-to-Supabase upload/download.
  "connect-src 'self' https://*.supabase.co",
  "font-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  // Isolate the browsing context from cross-origin popups (XS-Leaks/Spectre defense). COEP
  // is deliberately omitted — it would require CORP headers on the Supabase image responses.
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
  // Browsers ignore HSTS over http, so it's safe to always send (enforced only over https).
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
  { key: "Content-Security-Policy", value: csp },
];

const nextConfig: NextConfig = {
  // Emit a minimal self-contained server bundle for the Docker image.
  output: "standalone",
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  // Gallery/reference photos are served as Supabase Storage **signed** URLs (path
  // /storage/v1/object/sign/<bucket>/... — covered by the `**` below) that carry a
  // `?token=<jwt>` query string. We intentionally omit `search` so those query params
  // are allowed; do NOT add `search: ""` (it would block signed URLs). decisions/0030.
  // Host is <ref>.supabase.co — exactly one subdomain segment, so `*` (not `**`).
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "*.supabase.co",
        pathname: "/storage/v1/object/**",
      },
    ],
  },
};

export default nextConfig;
