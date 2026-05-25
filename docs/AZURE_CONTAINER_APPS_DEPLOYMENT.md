# Azure Container Apps Deployment (Dash Demo with Azure Files)

This guide takes you from a brand-new Azure account to a working public dashboard URL.

## 0) What You Are Deploying

For this repository state, deploy **two container apps** in the same Container Apps environment:
- `dash` app: public URL, serves Dash via `gunicorn ... wsgi:server`.
- `api` app: internal ingress only, serves FastAPI for data/inference routes used by Dash.

Why two apps: the current dashboard callbacks call backend API endpoints.

Scale recommendation:
- Keep Dash at `minReplicas: 0` for demo cost control.
- Keep API at `minReplicas: 0` for the scale-to-zero demo.
- Dash shows an initialization screen, polls the API while it cold starts, and keeps the API warm while the browser tab remains open.

Data storage strategy:
- Store `.pkl` data in **Azure Files** (outside the image).
- Mount the share read-only into containers at `/app/data`.
- Set `DATA_DIR=/app/data`.

Databricks note:
- Databricks is **not required** for this demo because this is a containerized web app deployment, not a Spark pipeline deployment.

## 1) Prerequisites

- Azure account and subscription (already created).
- This repo checked out locally.
- The required data files available on your machine:
  - `TRAFOS.pkl`
  - `APOYOS.pkl`
  - `SWITCHES.pkl`
  - `REDMT.pkl`
  - `SuperEventos_Criticidad_AguasAbajo_CODEs.pkl`
  - `Eventos_interruptor.pkl`
  - `Eventos_tramo_linea.pkl`
  - `Eventos_transformador.pkl`

## 2) Open Azure CLI (Cloud Shell or Local)

### Option A (recommended): Azure Cloud Shell
1. Go to https://portal.azure.com
2. Click the Cloud Shell icon (`>_`) in the top bar.
3. Choose **Bash**.
4. If prompted, create the default Cloud Shell storage.

### Option B: Local Azure CLI
- Install Azure CLI: https://learn.microsoft.com/cli/azure/install-azure-cli

## 2.1) Install Docker Desktop (Required for Local Build Fallback)

If `az acr build` is blocked in your subscription (for example `TasksOperationsNotAllowed`), you can still deploy by building locally and pushing to ACR.

For Windows + WSL:
1. Install Docker Desktop: https://www.docker.com/products/docker-desktop/
2. Open Docker Desktop and wait for "Engine running".
3. Enable WSL integration:
   - Docker Desktop -> Settings -> Resources -> WSL Integration
   - Enable your Linux distro.
4. In WSL, verify:

```bash
docker version
docker info
```

If `docker info` shows `permission denied ... /var/run/docker.sock`, run:

```bash
sudo groupadd docker 2>/dev/null || true
sudo usermod -aG docker "$USER"
newgrp docker
docker info
```

## 3) Login and Select Subscription

If you are in local CLI:

```bash
az login
```

List subscriptions:

```bash
az account list -o table
```

Set the one you want:

```bash
az account set --subscription "<SUBSCRIPTION_ID_OR_NAME>"
```

Verify:

```bash
az account show --query "{name:name,id:id,tenantId:tenantId}" -o table
```

## 4) Install / Update Container Apps Extension

```bash
az extension add --name containerapp --upgrade
```

Optional check:

```bash
az extension show --name containerapp -o table
```

## 5) Register Required Resource Providers

```bash
for ns in Microsoft.App Microsoft.OperationalInsights Microsoft.ContainerRegistry Microsoft.Storage; do
  az provider register --namespace "$ns" --wait
done
```

Verify registration:

```bash
for ns in Microsoft.App Microsoft.OperationalInsights Microsoft.ContainerRegistry Microsoft.Storage; do
  echo -n "$ns: "
  az provider show --namespace "$ns" --query registrationState -o tsv
done
```

Each should print `Registered`.

## 6) Set Deployment Variables

Run this block and edit values if needed:

```bash
# Core
export LOCATION="eastus"
export RESOURCE_GROUP="rg-chec-dashboard-demo"
export ACA_ENV_NAME="acae-chec-demo"

# App names
export DASH_APP_NAME="chec-dashboard-demo"
export API_APP_NAME="chec-api-demo"

# Image
export IMAGE_REPO="chec-dashboard"
export IMAGE_TAG="v1"

# Unique suffix for globally-unique names (ACR + Storage)
export SUFFIX="$(date +%m%d%H%M%S)"

# Must be lowercase alphanumeric
export ACR_NAME="checacr${SUFFIX}"
export STORAGE_ACCOUNT="checst${SUFFIX}"

# Azure Files
export FILE_SHARE_NAME="checdata"
export STORAGE_MOUNT_NAME="checdata"

# Local folder where the 8 .pkl files are located
export DATA_LOCAL_DIR="/absolute/path/to/your/data"
```

## 7) Create Resource Group

```bash
az group create \
  --name "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  -o table
```

## 8) Create Azure Container Registry (Basic SKU)

```bash
az acr create \
  --name "$ACR_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --sku Basic \
  --admin-enabled true \
  -o table
```

Get ACR metadata:

```bash
export ACR_SERVER="$(az acr show -n "$ACR_NAME" -g "$RESOURCE_GROUP" --query loginServer -o tsv)"
export ACR_USERNAME="$(az acr credential show -n "$ACR_NAME" --query username -o tsv)"
export ACR_PASSWORD="$(az acr credential show -n "$ACR_NAME" --query 'passwords[0].value' -o tsv)"
```

## 9) Build and Push Image (Choose Path A or Path B)

First, validate you are using the correct ACR name:

```bash
az account show --query "{name:name,id:id}" -o table
az acr list -o table
```

If you see `The resource with name ... could not be found`, reset:

```bash
export ACR_NAME="<REAL_NAME_FROM_az_acr_list>"
export ACR_SERVER="$(az acr show -n "$ACR_NAME" --query loginServer -o tsv)"
```

### Path A (Preferred): ACR Cloud Build

```bash
cd /home/jclugor/unal/CHEC/dashboard
az acr build \
  --registry "$ACR_NAME" \
  --image "$IMAGE_REPO:$IMAGE_TAG" \
  .
```

### Path B (Fallback): Local Docker Build + Push

Use this path if Path A fails with `TasksOperationsNotAllowed`.

```bash
cd /home/jclugor/unal/CHEC/dashboard

export ACR_SERVER="$(az acr show -n "$ACR_NAME" --query loginServer -o tsv)"

# Login to ACR using token flow
TOKEN="$(az acr login -n "$ACR_NAME" --expose-token -o tsv --query accessToken)"
echo "$TOKEN" | docker login "$ACR_SERVER" \
  --username 00000000-0000-0000-0000-000000000000 \
  --password-stdin

# Build and push
docker build -t "$IMAGE_REPO:$IMAGE_TAG" .
docker tag "$IMAGE_REPO:$IMAGE_TAG" "$ACR_SERVER/$IMAGE_REPO:$IMAGE_TAG"
docker push "$ACR_SERVER/$IMAGE_REPO:$IMAGE_TAG"

# Verify tag exists in ACR
az acr repository show-tags -n "$ACR_NAME" --repository "$IMAGE_REPO" -o table
```

## 10) Create Container Apps Environment

```bash
az containerapp env create \
  --name "$ACA_ENV_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  -o table
```

Get Managed Environment resource ID:

```bash
export MANAGED_ENV_ID="$(az containerapp env show -n "$ACA_ENV_NAME" -g "$RESOURCE_GROUP" --query id -o tsv)"
```

## 11) Create Storage Account + Azure Files Share

Use locally redundant storage (LRS) for demo cost optimization.

```bash
az storage account create \
  --name "$STORAGE_ACCOUNT" \
  --resource-group "$RESOURCE_GROUP" \
  --location "$LOCATION" \
  --sku Standard_LRS \
  --kind StorageV2 \
  -o table
```

Create file share:

```bash
az storage share-rm create \
  --resource-group "$RESOURCE_GROUP" \
  --storage-account "$STORAGE_ACCOUNT" \
  --name "$FILE_SHARE_NAME" \
  --quota 100 \
  -o table
```

Get storage key:

```bash
export STORAGE_KEY="$(az storage account keys list -g "$RESOURCE_GROUP" -n "$STORAGE_ACCOUNT" --query '[0].value' -o tsv)"
```

## 12) Upload Required `.pkl` Files to Azure Files

Validate local files first:

```bash
for f in \
  TRAFOS.pkl \
  APOYOS.pkl \
  SWITCHES.pkl \
  REDMT.pkl \
  SuperEventos_Criticidad_AguasAbajo_CODEs.pkl \
  Eventos_interruptor.pkl \
  Eventos_tramo_linea.pkl \
  Eventos_transformador.pkl; do
  test -f "$DATA_LOCAL_DIR/$f" || { echo "Missing local file: $DATA_LOCAL_DIR/$f"; exit 1; }
done
```

Upload all required files:

```bash
for f in \
  TRAFOS.pkl \
  APOYOS.pkl \
  SWITCHES.pkl \
  REDMT.pkl \
  SuperEventos_Criticidad_AguasAbajo_CODEs.pkl \
  Eventos_interruptor.pkl \
  Eventos_tramo_linea.pkl \
  Eventos_transformador.pkl; do
  az storage file upload \
    --account-name "$STORAGE_ACCOUNT" \
    --account-key "$STORAGE_KEY" \
    --share-name "$FILE_SHARE_NAME" \
    --source "$DATA_LOCAL_DIR/$f" \
    --path "$f"

done
```

Note:
- `az storage file upload` (Azure Files) does not support `--overwrite`.

## 13) Register Azure Files Share with Container Apps Environment

```bash
az containerapp env storage set \
  --name "$ACA_ENV_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --storage-name "$STORAGE_MOUNT_NAME" \
  --storage-type AzureFile \
  --azure-file-account-name "$STORAGE_ACCOUNT" \
  --azure-file-account-key "$STORAGE_KEY" \
  --azure-file-share-name "$FILE_SHARE_NAME" \
  --access-mode ReadOnly \
  -o table
```

## 14) Deploy API App (internal ingress)

Refresh ACR credentials before generating YAML, especially if you opened a new shell or ran `newgrp docker`:

```bash
export ACR_SERVER="$(az acr show -n "$ACR_NAME" --query loginServer -o tsv)"
export ACR_USERNAME="$(az acr credential show -n "$ACR_NAME" --query username -o tsv)"
export ACR_PASSWORD="$(az acr credential show -n "$ACR_NAME" --query 'passwords[0].value' -o tsv)"

test -n "$ACR_USERNAME" || { echo "ACR_USERNAME is empty"; exit 1; }
test -n "$ACR_PASSWORD" || { echo "ACR_PASSWORD is empty"; exit 1; }
```

Create API YAML:

```bash
cat > /tmp/chec-api.yaml <<EOFYAML
location: $LOCATION
name: $API_APP_NAME
resourceGroup: $RESOURCE_GROUP
type: Microsoft.App/containerApps
properties:
  managedEnvironmentId: $MANAGED_ENV_ID
  configuration:
    activeRevisionsMode: Single
    ingress:
      external: false
      allowInsecure: false
      targetPort: 8000
      transport: auto
    registries:
      - server: $ACR_SERVER
        username: $ACR_USERNAME
        passwordSecretRef: acr-password
    secrets:
      - name: acr-password
        value: "$ACR_PASSWORD"
  template:
    containers:
      - name: $API_APP_NAME
        image: $ACR_SERVER/$IMAGE_REPO:$IMAGE_TAG
        command:
          - python
        args:
          - run_api.py
        resources:
          cpu: 0.5
          memory: 1Gi
        env:
          - name: API_HOST
            value: "0.0.0.0"
          - name: API_PORT
            value: "8000"
          - name: API_RELOAD
            value: "false"
          - name: DATA_DIR
            value: "/app/data"
          - name: OUTPUT_DIR
            value: "/tmp/outputs"
          - name: MODEL_BACKEND
            value: "mock"
          - name: LOG_LEVEL
            value: "INFO"
        volumeMounts:
          - volumeName: azurefiles-data
            mountPath: /app/data
            readOnly: true
    scale:
      minReplicas: 0
      maxReplicas: 1
    volumes:
      - name: azurefiles-data
        storageType: AzureFile
        storageName: $STORAGE_MOUNT_NAME
EOFYAML
```

Deploy API:

```bash
az containerapp create \
  --name "$API_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --yaml /tmp/chec-api.yaml
```

## 15) Deploy Dash App (public ingress)

You already have a reusable template at:
- `deploy/containerapp.azurefiles.yaml`

For a fast deploy, generate a concrete file with your values:

```bash
cat > /tmp/chec-dash.yaml <<EOFYAML
location: $LOCATION
name: $DASH_APP_NAME
resourceGroup: $RESOURCE_GROUP
type: Microsoft.App/containerApps
properties:
  managedEnvironmentId: $MANAGED_ENV_ID
  configuration:
    activeRevisionsMode: Single
    ingress:
      external: true
      allowInsecure: false
      targetPort: 8050
      transport: auto
    registries:
      - server: $ACR_SERVER
        username: $ACR_USERNAME
        passwordSecretRef: acr-password
    secrets:
      - name: acr-password
        value: "$ACR_PASSWORD"
  template:
    containers:
      - name: $DASH_APP_NAME
        image: $ACR_SERVER/$IMAGE_REPO:$IMAGE_TAG
        resources:
          cpu: 0.5
          memory: 1Gi
        env:
          - name: PORT
            value: "8050"
          - name: DEBUG
            value: "false"
          - name: DATA_DIR
            value: "/app/data"
          - name: OUTPUT_DIR
            value: "/tmp/outputs"
          - name: WEB_CONCURRENCY
            value: "1"
          - name: WEB_THREADS
            value: "2"
          - name: API_BASE_URL
            value: "http://$API_APP_NAME"
          - name: API_STARTUP_POLL_SECONDS
            value: "3"
          - name: API_KEEPALIVE_SECONDS
            value: "60"
          - name: API_STARTUP_MAX_ATTEMPTS
            value: "0"
        volumeMounts:
          - volumeName: azurefiles-data
            mountPath: /app/data
            readOnly: true
    scale:
      minReplicas: 0
      maxReplicas: 1
    volumes:
      - name: azurefiles-data
        storageType: AzureFile
        storageName: $STORAGE_MOUNT_NAME
EOFYAML
```

Deploy Dash:

```bash
az containerapp create \
  --name "$DASH_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --yaml /tmp/chec-dash.yaml
```

## 16) Get Public Dashboard URL

```bash
export DASH_FQDN="$(az containerapp show -n "$DASH_APP_NAME" -g "$RESOURCE_GROUP" --query properties.configuration.ingress.fqdn -o tsv)"
echo "https://$DASH_FQDN"
```

Open the printed URL in your browser.

## 17) Test Health Endpoint

```bash
curl -i "https://$DASH_FQDN/health"
```

Expected body:

```json
{"status":"ok"}
```

## 18) View Logs

Dash logs:

```bash
az containerapp logs show \
  --name "$DASH_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --follow
```

If Dash logs show requests like `GET http://chec-api-demo/data?... "HTTP/1.1 503 Service Unavailable"` during startup, that can be normal while the API is waking. The dashboard should show the initialization screen and keep retrying.

Check API scaling:

```bash
az containerapp show \
  --name "$API_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --query "{runningStatus:properties.runningStatus,scale:properties.template.scale}" \
  -o yaml
```

For pure scale-to-zero demo mode, use:

```bash
az containerapp update \
  --name "$API_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --min-replicas 0 \
  --max-replicas 1
```

If you prefer lower first-load latency later, set API `--min-replicas 1`.

API logs:

```bash
az containerapp logs show \
  --name "$API_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --follow
```

## 19) Update / Redeploy After Code Changes

Build a new image tag:

```bash
export IMAGE_TAG="v2"

cd /home/jclugor/unal/CHEC/dashboard
```

Build with one of these options:

Path A (`az acr build`):

```bash
az acr build \
  --registry "$ACR_NAME" \
  --image "$IMAGE_REPO:$IMAGE_TAG" \
  .
```

Path B (local Docker fallback if ACR Tasks are blocked):

```bash
TOKEN="$(az acr login -n "$ACR_NAME" --expose-token -o tsv --query accessToken)"
echo "$TOKEN" | docker login "$ACR_SERVER" \
  --username 00000000-0000-0000-0000-000000000000 \
  --password-stdin

docker build -t "$IMAGE_REPO:$IMAGE_TAG" .
docker tag "$IMAGE_REPO:$IMAGE_TAG" "$ACR_SERVER/$IMAGE_REPO:$IMAGE_TAG"
docker push "$ACR_SERVER/$IMAGE_REPO:$IMAGE_TAG"
```

Update API app image:

```bash
az containerapp update \
  --name "$API_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --image "$ACR_SERVER/$IMAGE_REPO:$IMAGE_TAG"
```

Update Dash app image:

```bash
az containerapp update \
  --name "$DASH_APP_NAME" \
  --resource-group "$RESOURCE_GROUP" \
  --image "$ACR_SERVER/$IMAGE_REPO:$IMAGE_TAG"
```

## 20) Update Data Files Without Rebuilding Image

Because data is externalized in Azure Files, update data independently:

```bash
# Upload only changed files
az storage file upload \
  --account-name "$STORAGE_ACCOUNT" \
  --account-key "$STORAGE_KEY" \
  --share-name "$FILE_SHARE_NAME" \
  --source "$DATA_LOCAL_DIR/TRAFOS.pkl" \
  --path "TRAFOS.pkl"
```

If your CLI returns a file-exists conflict, replace file explicitly:

```bash
az storage file delete \
  --account-name "$STORAGE_ACCOUNT" \
  --account-key "$STORAGE_KEY" \
  --share-name "$FILE_SHARE_NAME" \
  --path "TRAFOS.pkl"

az storage file upload \
  --account-name "$STORAGE_ACCOUNT" \
  --account-key "$STORAGE_KEY" \
  --share-name "$FILE_SHARE_NAME" \
  --source "$DATA_LOCAL_DIR/TRAFOS.pkl" \
  --path "TRAFOS.pkl"
```

If needed, restart apps to force immediate reload:

```bash
az containerapp revision restart --name "$API_APP_NAME" --resource-group "$RESOURCE_GROUP"
az containerapp revision restart --name "$DASH_APP_NAME" --resource-group "$RESOURCE_GROUP"
```

## 21) Local Docker Smoke Test

Build image locally:

```bash
cd /home/jclugor/unal/CHEC/dashboard
docker build -t chec-dashboard:local .
```

Run Dash container with local data mounted at `/app/data`:

```bash
docker run --rm -p 8050:8050 \
  -e PORT=8050 \
  -e DEBUG=false \
  -e DATA_DIR=/app/data \
  -e OUTPUT_DIR=/tmp/outputs \
  -e WEB_CONCURRENCY=1 \
  -e WEB_THREADS=2 \
  -v /absolute/path/to/your/data:/app/data:ro \
  chec-dashboard:local
```

Smoke checks:

```bash
curl http://localhost:8050/health
```

Open:

```text
http://localhost:8050
```

Note:
- This smoke test validates container startup and `/health`.
- The interactive dashboard pages require the API backend (`API_BASE_URL`) to be reachable.

## 22) Cost Control (Demo-Focused)

- `minReplicas: 0` lets the app scale to zero when idle.
- In scale-to-zero mode, first load can take longer because Dash and API both cold start.
- Dash keeps the API warm while a browser tab is open by sending a lightweight heartbeat.
- `maxReplicas: 1` prevents surprise autoscaling cost spikes.
- `cpu: 0.5`, `memory: 1Gi` is the demo baseline.
- If pandas/data loading fails due memory pressure, raise memory to `2Gi`.
- Use `ACR Basic` for this demo.
- Use storage `Standard_LRS` (locally redundant) for this demo.
- Keep data in Azure Files instead of baking into image.
- After demo, delete the whole resource group.
- Optional: create an Azure Budget alert in Cost Management.

## 23) Cleanup to Stop All Costs

```bash
az group delete --name "$RESOURCE_GROUP" --yes --no-wait
```

## 24) Troubleshooting (Validated in This Deployment)

### A) `TasksOperationsNotAllowed` on `az acr build`

Symptom:
- `ACR Tasks requests ... are not permitted`.

Meaning:
- Your subscription does not currently allow ACR Tasks.

Fix:
- Use Section 9 Path B (local Docker build + push), or upgrade subscription type and retry Path A.

### B) `The resource with name '<acr>' ... could not be found`

Symptom:
- `az acr show` / `az acr login` cannot find registry.

Fix:

```bash
az account show --query "{name:name,id:id}" -o table
az acr list -o table
export ACR_NAME="<real registry name from list>"
export ACR_SERVER="$(az acr show -n "$ACR_NAME" --query loginServer -o tsv)"
```

### C) `permission denied ... /var/run/docker.sock`

Symptom:
- Docker installed, but current user cannot access daemon.

Fix:

```bash
sudo groupadd docker 2>/dev/null || true
sudo usermod -aG docker "$USER"
newgrp docker
docker info
```

### D) `az acr login` asks for Docker / Docker not detected

Use token login flow:

```bash
TOKEN="$(az acr login -n "$ACR_NAME" --expose-token -o tsv --query accessToken)"
echo "$TOKEN" | docker login "$ACR_SERVER" \
  --username 00000000-0000-0000-0000-000000000000 \
  --password-stdin
```

### E) `The JSON value could not be converted to System.Boolean` when using `--yaml`

This is a known Azure Container Apps YAML parsing edge case.

Fix:
- Explicitly set `allowInsecure: false` under `properties.configuration.ingress`.
- Ensure boolean fields are true booleans (`true`/`false`) and not quoted strings.
