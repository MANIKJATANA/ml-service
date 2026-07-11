# Build context = ./frontend. See docker-compose.yml.
# Multi-stage build using Next.js standalone output.
FROM node:24-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# `npm install` (not `npm ci`): the lockfile is generated on the Windows dev host,
# and npm omits some cross-platform optional deps (Tailwind v4 oxide's wasm/@emnapi
# transitive deps), so `npm ci`'s exact-sync check fails on linux. install reconciles.
RUN npm install --no-audit --no-fund

FROM node:24-slim AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:24-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000
# Standalone output bundles only what the server needs.
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
