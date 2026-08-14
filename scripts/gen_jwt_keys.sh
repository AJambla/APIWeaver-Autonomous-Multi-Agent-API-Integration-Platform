#!/usr/bin/env bash
# Generate the RS256 keypair used to sign/verify platform JWTs (Security.md §4).
#
# The private key never leaves this host in a real deployment — production keys are
# provisioned into Vault and mounted by the Vault Agent Injector (Deployment.md §9).
# This script exists only for local development.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SECRETS_DIR="${ROOT_DIR}/secrets"
PRIVATE_KEY="${SECRETS_DIR}/jwt_private.pem"
PUBLIC_KEY="${SECRETS_DIR}/jwt_public.pem"

mkdir -p "${SECRETS_DIR}"

if [[ -f "${PRIVATE_KEY}" ]]; then
  echo "refusing to overwrite existing key: ${PRIVATE_KEY}" >&2
  echo "delete it explicitly if you intend to rotate." >&2
  exit 1
fi

openssl genrsa -out "${PRIVATE_KEY}" 2048
openssl rsa -in "${PRIVATE_KEY}" -pubout -out "${PUBLIC_KEY}"
chmod 600 "${PRIVATE_KEY}"

echo "wrote ${PRIVATE_KEY}"
echo "wrote ${PUBLIC_KEY}"
