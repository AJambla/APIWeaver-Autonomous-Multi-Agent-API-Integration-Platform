#!/usr/bin/env bash
set -eo pipefail

# Qdrant HTTP /readyz healthcheck probe
exec 3<>/dev/tcp/127.0.0.1/6333
printf "GET /readyz HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n" >&3
read -r response_line <&3
exec 3>&- 3<&-

case "$response_line" in
    *" 200 "*) exit 0 ;;
    *) echo "Qdrant unhealthy: $response_line" >&2; exit 1 ;;
esac
