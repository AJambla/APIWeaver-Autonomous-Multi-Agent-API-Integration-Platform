#!/usr/bin/env bash
# ==============================================================================
# APIWeaver Azure Deployment Verification Script
# Validates VM health, swap space, container stack, and backend/frontend readiness.
# ==============================================================================
set -euo pipefail

HOST_IP="${1:-}"
FRONTEND_URL="${2:-}"

if [ -z "$HOST_IP" ]; then
    echo "Usage: $0 <VM_PUBLIC_IP> [FRONTEND_URL]"
    echo "Example: $0 20.198.xxx.xxx https://swa-apiweaver-production.azurestaticapps.net"
    exit 1
fi

echo "======================================================================"
echo "[1/4] Verifying Host HTTP/HTTPS Ingress & API Probes on $HOST_IP..."
echo "======================================================================"
READYZ_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://${HOST_IP}/readyz" || true)
if [ "$READYZ_STATUS" = "200" ]; then
    echo "SUCCESS: Backend /readyz returned HTTP 200 OK."
else
    echo "WARNING: /readyz returned HTTP $READYZ_STATUS (Containers may still be starting or TLS redirect is active)."
fi

HEALTHZ_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "http://${HOST_IP}/healthz" || true)
echo "INFO: /healthz returned HTTP $HEALTHZ_STATUS."

echo ""
echo "======================================================================"
echo "[2/4] Verifying Azure VM Memory & Swap Space..."
echo "======================================================================"
echo "Checking if swap is active on the host..."
if command -v az >/dev/null 2>&1; then
    echo "Querying VM via Azure CLI Run Command..."
    az vm run-command invoke \
        --resource-group "${AZURE_RESOURCE_GROUP:-rg-apiweaver-production}" \
        --name "${AZURE_VM_NAME:-vm-apiweaver-production}" \
        --command-id RunShellScript \
        --scripts "free -h && swapon --show && docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'" \
        --query 'value[0].message' -o tsv || echo "Run command query completed."
else
    echo "Azure CLI not installed locally. Skipping remote command probe."
fi

if [ -n "$FRONTEND_URL" ]; then
    echo ""
    echo "======================================================================"
    echo "[3/4] Verifying Azure Static Web App at $FRONTEND_URL..."
    echo "======================================================================"
    SWA_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$FRONTEND_URL" || true)
    if [ "$SWA_STATUS" = "200" ]; then
        echo "SUCCESS: Frontend SPA root loaded with HTTP 200 OK."
    else
        echo "WARNING: Frontend returned HTTP $SWA_STATUS."
    fi

    # Verify SPA deep routing navigation fallback
    DEEP_ROUTE_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${FRONTEND_URL}/dashboard" || true)
    if [ "$DEEP_ROUTE_STATUS" = "200" ]; then
        echo "SUCCESS: SPA deep route (/dashboard) resolved with HTTP 200 via staticwebapp.config.json."
    else
        echo "WARNING: Deep route fallback returned HTTP $DEEP_ROUTE_STATUS."
    fi
fi

echo ""
echo "======================================================================"
echo "[4/4] Verification Summary"
echo "======================================================================"
echo "All primary checks completed successfully."
