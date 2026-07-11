import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Emit a minimal self-contained server bundle for the Docker image.
  output: "standalone",
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
