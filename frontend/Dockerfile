FROM node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Unprivileged build of the same nginx 1.31.6 (`audit M10`): the master process runs as uid 101,
# so a compromise of the request path does not land on root. Adding `USER 101` to the stock image
# is not enough and was measured to fail - `docker run --user 101 nginx:alpine` aborts with
# `mkdir() "/var/cache/nginx/client_temp" failed (13: Permission denied)`, because that image owns
# its cache and pid paths as root - whereas this one has /var/cache/nginx owned by `nginx` and its
# pid at /tmp/nginx.pid.
FROM nginxinc/nginx-unprivileged:alpine@sha256:26b0bf6fbf07297983cb341998d79c831508787de26627dd2a112321b9c3a4af
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
# 127.0.0.1, not localhost: nginx binds the IPv4 wildcard only (`/proc/net/tcp` shows
# 0.0.0.0:8080 and nothing in `/proc/net/tcp6`), while Alpine resolves `localhost` to ::1
# first, so the probe was refused and the container could never report healthy.
HEALTHCHECK --interval=30s --timeout=5s CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:8080/ || exit 1
CMD ["nginx", "-g", "daemon off;"]
