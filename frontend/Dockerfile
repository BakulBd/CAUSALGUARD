# syntax=docker/dockerfile:1.7
# ---------------------------------------------------------------------------
# CausalGuard frontend — Vite build served by a hardened, non-root nginx.
# ---------------------------------------------------------------------------
ARG NODE_VERSION=20

FROM node:${NODE_VERSION}-alpine AS builder
WORKDIR /app
ENV CI=1
COPY package.json ./
COPY bun.lock* package-lock.json* ./
RUN npm install --no-audit --no-fund
COPY . .
# API base is same-origin in the container; nginx reverse-proxies /api.
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime
LABEL org.opencontainers.image.title="CausalGuard Frontend"

# nginx-unprivileged already runs as uid 101 and listens on 8080.
COPY --chown=nginx:nginx nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder --chown=nginx:nginx /app/dist /usr/share/nginx/html

EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=4s --start-period=10s --retries=3 \
    CMD ["/bin/sh", "-c", "wget -qO- http://localhost:8080/healthz || exit 1"]
