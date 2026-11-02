#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Initial TLS Certificate Provisioner (Let's Encrypt / Certbot)
# Avoids Nginx crash on fresh deployment when certificates do not yet exist.
# ==============================================================================

if [ "$#" -lt 2 ]; then
    echo "Usage: ./init-ssl.sh <DOMAIN> <EMAIL>"
    echo "Example: ./init-ssl.sh api.yourdomain.com admin@yourdomain.com"
    exit 1
fi

DOMAIN="$1"
EMAIL="$2"
CERT_PATH="./certbot/conf/live/apiweaver"

echo "==> Configuring SSL for domain: ${DOMAIN} with email: ${EMAIL}"

mkdir -p "${CERT_PATH}"
mkdir -p "./certbot/www"

# 1. Create temporary self-signed certificate so Nginx can start
if [ ! -f "${CERT_PATH}/fullchain.pem" ]; then
    echo "==> Generating temporary self-signed certificate..."
    openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
        -keyout "${CERT_PATH}/privkey.pem" \
        -out "${CERT_PATH}/fullchain.pem" \
        -subj "/CN=localhost"
fi

# 2. Start Nginx container
echo "==> Starting Nginx to answer ACME challenge..."
docker compose -f docker-compose.prod.yml up -d nginx

# 3. Request real Let's Encrypt certificate
echo "==> Requesting official Let's Encrypt certificate for ${DOMAIN}..."
docker compose -f docker-compose.prod.yml run --rm --entrypoint "\
    certbot certonly --webroot -w /var/www/certbot \
    --cert-name apiweaver \
    -d ${DOMAIN} \
    --email ${EMAIL} \
    --agree-tos \
    --no-eff-email \
    --force-renewal" certbot

# 4. Reload Nginx with the official certificate
echo "==> Reloading Nginx with new certificate..."
docker compose -f docker-compose.prod.yml exec nginx nginx -s reload

echo "==> SSL initialization completed successfully!"
