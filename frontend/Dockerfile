# Build stage — produces the static Vite production bundle only.
FROM node:24-alpine AS build
WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Runtime stage — no Node, no frontend source, static files + nginx only.
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80

# nginx:alpine ships busybox wget — safe to rely on here (unlike the backend's
# Debian-slim image, which has neither curl nor wget by default). Using the
# explicit IPv4 loopback, not "localhost": /etc/hosts maps localhost to both
# 127.0.0.1 and ::1, BusyBox wget tries ::1 first, and nginx here only listens
# on 0.0.0.0:80 (IPv4) — "localhost" gets refused with no IPv4 fallback.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
    CMD wget -q -O- http://127.0.0.1/ || exit 1
