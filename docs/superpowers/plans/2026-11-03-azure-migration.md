# Azure Migration Implementation Plan (API_Weaver)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate API_Weaver backend, worker, database, object storage, and frontend SPA from AWS to Microsoft Azure under the Azure for Students plan, preserving isolated container sandbox execution.

**Architecture:** 
- Host: Single Azure Linux VM (`Standard_B2ats_v2`, AMD64, 2 vCPU, 1 GB RAM + 3 GB SSD swap) running Docker Compose (Nginx, FastAPI, Redis, Celery, and Docker Socket Proxy).
- Database: Azure Database for PostgreSQL Flexible Server (`B_Standard_B1ms`, 12-month student free tier).
- Storage: Azure Blob Storage (`artifacts` container) with Managed Identity / connection string.
- Frontend: Azure Static Web Apps (Free tier) with global edge distribution and automatic SPA routing.
- Registry: GitHub Container Registry (`ghcr.io`, free) with native `linux/amd64` builds.

**Tech Stack:** AzureRM Terraform (~> 4.0), Azure CLI, Python 3.12, FastAPI, Celery, `azure-storage-blob`, React 18, Vite, GitHub Actions.

**Spec / Baseline:** Discussion and architecture agreement in conversation `4586d6f1-65e0-4775-bdb3-6bb44ce9df7c`.

## Global Constraints
- Target VM SKU: `Standard_B2als_v2` (AMD64 x86_64, 2 vCPU, 2 GB RAM + 2 GB SSD swap, burstable).
- Auto-Shutdown: Configured via `azurerm_dev_test_global_vm_shutdown_schedule` to automatically deallocate VM at midnight (00:00), cutting compute billing by ~50% to stretch student credit for 12+ months.
- Target DB SKU: `B_Standard_B1ms` (Burstable, 32 GB storage, eligible for Azure for Students 750 free hours/month).
- Strict Zero-Cost Container Registry: Keep GHCR (free); do not provision ACR.
- Frontend: Azure Static Web Apps Free tier ($0).
- Backward Compatibility: Maintain `storage_backend="local"` for local offline development.
- Sandbox Isolation: Celery worker must talk to Docker through `docker-socket-proxy:2375`; no raw socket mounting inside workers.

## Review Focus (Edge Cases & Failure Modes)
1. **Low Memory OOM**: `Standard_B2ats_v2` has 1 GB physical RAM. VM bootstrapper MUST configure 3 GB SSD swap and `vm.swappiness=10` before containers start.
2. **AMD64 vs ARM64 Mismatch**: CI/CD was previously building `linux/arm64`. Workflows must build `linux/amd64` so images run natively on AMD EPYC.
3. **Database Network Isolation**: PostgreSQL Flexible Server is in a private delegated subnet (`Microsoft.DBforPostgreSQL/flexibleServers`) with no public IP. VM must resolve internal Azure private DNS zone to reach port 5432.
4. **Storage Key Traversal**: Blob Storage adapter must run all incoming keys through existing `validate_storage_key()` to prevent directory traversal.
5. **SPA 404 Deep Links**: Azure Static Web Apps must have `staticwebapp.config.json` with a navigation fallback to `/index.html`.

---

### Task 1: Python Azure Blob Storage Adapter & Configuration

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/services/storage_service.py`
- Modify: `backend/pyproject.toml`
- Create: `backend/tests/unit/test_azure_storage.py`

- [x] **Step 1: Add dependencies to `backend/pyproject.toml`**
  Add `azure-storage-blob>=12.19.0` and `azure-identity>=1.15.0`.
  Run `pip install -e .` (or verify imports).

- [x] **Step 2: Update `backend/app/core/config.py`**
  Add settings:
  ```python
  azure_storage_connection_string: str | None = None
  azure_storage_account_name: str | None = None
  azure_storage_account_key: str | None = None
  azure_storage_container_artifacts: str = "artifacts"
  azure_storage_container_uploads: str = "uploads"
  ```
  Allow `storage_backend` to accept `"azure"` alongside `"local"` and `"s3"`.

- [x] **Step 3: Implement `AsyncAzureBlobStorage` in `backend/app/services/storage_service.py`**
  Implement the `ObjectStorage` protocol:
  - `get(*, key: str, bucket: str | None = None) -> bytes | None`
  - `put(*, key: str, content: bytes, content_type: str | None = None, bucket: str | None = None) -> None`
  - `delete(*, key: str, bucket: str | None = None) -> None`
  - `upload(key: str, content: bytes, bucket: str | None = None) -> None`
  - `download(key: str, bucket: str | None = None) -> bytes`
  Support initialization via Managed Identity (`DefaultAzureCredential`) or connection string.
  Ensure `create_object_storage(settings)` returns `AsyncAzureBlobStorage` when `storage_backend == "azure"`.

- [x] **Step 4: Write unit test in `backend/tests/unit/test_azure_storage.py`**
  Test `AsyncAzureBlobStorage` methods using a mocked `BlobServiceClient` and verify error handling and `validate_storage_key`.
  Run: `pytest backend/tests/unit/test_azure_storage.py`
  Confirm all tests pass.

- [x] **Step 5: Commit changes**
  `git commit -m "feat(storage): add Azure Blob Storage adapter conforming to ObjectStorage protocol"`

---

### Task 2: Azure Terraform Infrastructure (`infra/terraform-azure/`)

**Files:**
- Create: `infra/terraform-azure/versions.tf`
- Create: `infra/terraform-azure/variables.tf`
- Create: `infra/terraform-azure/main.tf`
- Create: `infra/terraform-azure/network.tf`
- Create: `infra/terraform-azure/postgres.tf`
- Create: `infra/terraform-azure/storage.tf`
- Create: `infra/terraform-azure/vm.tf`
- Create: `infra/terraform-azure/static_web_app.tf`
- Create: `infra/terraform-azure/outputs.tf`
- Create: `infra/terraform-azure/cloud-init.yaml`
- Create: `infra/terraform-azure/terraform.tfvars.example`

- [x] **Step 1: Write `versions.tf` and `variables.tf`**
  - Provider: `hashicorp/azurerm ~> 4.0`.
  - Variables: `app_name`, `environment`, `azure_region` (default: `centralindia` or `eastus`), `vm_size` (default: `Standard_B2ats_v2`), `db_admin_username`, `db_admin_password`.

- [x] **Step 2: Write `network.tf`**
  - Resource Group: `azurerm_resource_group.rg`
  - VNet: `10.0.0.0/16`
  - App Subnet: `10.0.1.0/24` (with NSG allowing inbound 80, 443; blocking 22)
  - DB Subnet: `10.0.2.0/24` with delegation `Microsoft.DBforPostgreSQL/flexibleServers`
  - Public IP: Standard Static SKU for the VM.

- [x] **Step 3: Write `postgres.tf`**
  - `azurerm_postgresql_flexible_server`:
    - SKU: `B_Standard_B1ms` (Student free tier eligible)
    - Version: `16`
    - Storage: 32 GB
    - Delegated subnet ID & private DNS zone integration.

- [x] **Step 4: Write `storage.tf`**
  - `azurerm_storage_account`: Standard LRS, TLS 1.2 minimum.
  - `azurerm_storage_container`: `artifacts` (private).
  - Lifecycle rule: delete objects with prefix `artifacts/` after 14 days.

- [x] **Step 5: Write `cloud-init.yaml` and `vm.tf`**
  - `cloud-init.yaml`:
    1. Create 3 GB swapfile on `/swapfile`, set `vm.swappiness=10`.
    2. Install Docker Engine, Docker Compose v2, curl, jq, ca-certificates.
    3. Configure Docker daemon log rotation (`max-size: 10m`, `max-file: 3`).
    4. Create `/opt/apiweaver` directory for docker-compose stack.
  - `vm.tf`:
    - `azurerm_linux_virtual_machine`: Ubuntu 24.04 LTS AMD64, `Standard_B2als_v2`, 30 GB OS disk.
    - System-Assigned Managed Identity.
    - Role Assignment: `Storage Blob Data Contributor` on the Storage Account.
    - `azurerm_dev_test_global_vm_shutdown_schedule`: Nightly auto-shutdown at 00:00 to reduce student credit burn by ~50%.

- [x] **Step 6: Write `static_web_app.tf` and `outputs.tf`**
  - `azurerm_static_web_app`: Free SKU (`Free`), global.
  - Outputs: VM public IP, Postgres FQDN, Storage account name, Static Web App default hostname, SSH/Run Command instructions.

- [x] **Step 7: Validate Terraform syntax**
  Run: `cd infra/terraform-azure && terraform fmt && terraform init -backend=false && terraform validate`
  Ensure configuration is valid.

- [x] **Step 8: Commit changes**
  `git commit -m "feat(infra): add Azure Terraform configuration for student plan and B2als_v2 VM"`

---

### Task 3: Production Docker Stack Configuration for Azure

**Files:**
- Create: `frontend/staticwebapp.config.json`
- Modify: `infra/docker/sweet-spot/docker-compose.prod.yml`
- Modify: `infra/docker/sweet-spot/.env.prod.example`

- [x] **Step 1: Create `frontend/staticwebapp.config.json`**
  Configure navigation fallback for React SPA deep routing:
  ```json
  {
    "navigationFallback": {
      "rewrite": "/index.html",
      "exclude": ["/assets/*.{css,js}", "/favicon.ico", "/*.{png,jpg,svg}"]
    },
    "mimeTypes": {
      ".json": "application/json"
    }
  }
  ```

- [x] **Step 2: Update `docker-compose.prod.yml` and `.env.prod.example`**
  - Add Azure storage environment variables (`AZURE_STORAGE_ACCOUNT_NAME`, `AZURE_STORAGE_CONTAINER_ARTIFACTS`, `STORAGE_BACKEND=azure`).
  - Update `DATABASE_URL` format for Azure Flexible Server: `postgresql+asyncpg://<user>:<password>@<db-host>.postgres.database.azure.com:5432/<dbname>?ssl=require`.

- [x] **Step 3: Commit changes**
  `git commit -m "chore(config): configure production docker-compose and static web app routing for Azure"`

---

### Task 4: CI/CD Workflows (`.github/workflows/`)

**Files:**
- Modify: `.github/workflows/deploy-backend.yml`
- Modify: `.github/workflows/deploy-frontend.yml`

- [x] **Step 1: Update `.github/workflows/deploy-backend.yml`**
  - Change target platform from `linux/arm64` to `linux/amd64` in `docker/build-push-action`.
  - Remove QEMU setup step (native x86_64 runners build directly without emulation).
  - Replace AWS SSM deployment step with Azure CLI:
    - Use `azure/login@v2` with client credentials or GitHub OIDC.
    - Execute deployment command via `az vm run-command invoke`:
      ```bash
      az vm run-command invoke \
        --resource-group "${{ secrets.AZURE_RESOURCE_GROUP }}" \
        --name "${{ secrets.AZURE_VM_NAME }}" \
        --command-id RunShellScript \
        --scripts "cd /opt/apiweaver && docker compose -f docker-compose.prod.yml pull api agent-worker && docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head && docker compose -f docker-compose.prod.yml up -d --remove-orphans"
      ```

- [x] **Step 2: Update `.github/workflows/deploy-frontend.yml`**
  - Remove AWS S3 sync and CloudFront invalidation steps.
  - Add `Azure/static-web-apps-deploy@v1` action:
    ```yaml
    - name: Build And Deploy to Azure Static Web Apps
      uses: Azure/static-web-apps-deploy@v1
      with:
        azure_static_web_apps_api_token: ${{ secrets.AZURE_STATIC_WEB_APPS_API_TOKEN }}
        repo_token: ${{ secrets.GITHUB_TOKEN }}
        action: "upload"
        app_location: "frontend"
        output_location: "dist"
    ```

- [x] **Step 3: Commit changes**
  `git commit -m "ci: switch backend build to amd64 and update deployments to Azure VM and Static Web Apps"`

---

### Task 5: End-to-End Verification & Healthcheck

**Files:**
- Create: `scripts/verify-azure-deployment.sh`

- [x] **Step 1: Write verification script `scripts/verify-azure-deployment.sh`**
  A lightweight bash script testing:
  1. VM connectivity & swap status (`free -m` verifying 3 GB swap).
  2. Docker services health (`curl -fsS http://<vm-ip>:80/readyz`).
  3. Postgres database connectivity via backend.
  4. Frontend Static Web App HTTP 200 response and SPA deep link fallback.

- [x] **Step 2: Commit script**
  `git commit -m "test: add end-to-end azure deployment verification script"`
