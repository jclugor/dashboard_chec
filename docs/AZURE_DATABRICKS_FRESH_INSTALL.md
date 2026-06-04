# Fresh Azure + Databricks Install Runbook

This guide explains how to install the CHEC Dashboard Databricks App and bounded
agentic RAG assistant in a new client Azure account. It starts from a clean Azure
subscription and walks through the Azure workspace, Unity Catalog foundation,
Databricks data jobs, Databricks App deployment, AI Search, Model Serving,
conversation memory, and MLflow observability.

Use this as the canonical client deployment guide. The older Azure Container
Apps guide is still useful for the legacy container deployment, but the current
RAG assistant target is the Databricks App path documented here.

## 1. What You Will Deploy

At the end of this guide, the client environment will contain:

- An Azure Databricks workspace in the client Azure subscription.
- A Unity Catalog catalog, normally named `chec_dbx_demo` unless the client
  chooses a different catalog.
- Raw, bronze, silver, gold, ML artifact, skill, conversation, tool, and
  observability schemas/tables.
- A Lakeview summary dashboard and optional reviewer notebooks.
- A Databricks App named `chec-dash-parity`.
- A governed chatbot with:
  - Databricks AI Search retrieval.
  - Databricks Model Serving generation.
  - Unity Catalog function tools for read-only dashboard context.
  - Delta conversation memory and feedback.
  - Structured Spanish answers, citation checks, compliance-language checks.
  - MLflow/Unity Catalog observability and report-only evaluation.

Plan for one working day for a first client install if the Azure subscription,
Databricks account, billing approvals, and source data are ready. Plan for more
time if the client still needs account-admin setup, Unity Catalog metastore
creation, networking review, or quota approvals.

## 2. Roles And Access You Need

Ask the client to identify these people before starting.

| Role | Why it is needed |
|---|---|
| Azure subscription owner or contributor | Creates resource group and Azure Databricks workspace. |
| Azure billing or quota reviewer | Confirms regional vCPU availability and approves cost-bearing services. |
| Databricks account admin | Creates or attaches the Unity Catalog metastore if one does not exist. |
| Databricks workspace admin | Creates SQL warehouse, manages app permissions, enables workspace features. |
| Unity Catalog/metastore admin | Creates catalogs, schemas, volumes, and grants. |
| Deployment operator | Runs this repo's CLI commands from a local machine. |
| Client reviewer group owner | Confirms who should receive dashboard/app access. |

For a first demo, Databricks App authorization is used. The app service
principal receives the runtime permissions and end users interact through the
Databricks App.

## 3. Local Machine Prerequisites

The deployment operator needs:

- Azure CLI.
- Databricks CLI, version `0.205` or newer.
- Git.
- Python 3.12 with `venv`.
- `jq`.
- Optional but useful: `curl`.
- Browser access to the Azure Portal and Databricks workspace.
- The project repository checked out locally.
- The CHEC source data folders available locally or paths configured through
  environment variables.

Install instructions for Windows, macOS, and Linux are in
[Annex A: Installing Local Prerequisites](#annex-a-installing-local-prerequisites).

After installation, verify the local tools:

```bash
az version
databricks version
git --version
python --version || python3 --version
jq --version
curl --version
```

## 4. Choose Client Deployment Values

Pick these values before running commands.

```bash
export AZURE_SUBSCRIPTION_ID="<client-subscription-id>"
export AZURE_RESOURCE_GROUP="rg-chec-databricks-demo"
export AZURE_REGION="eastus"
export DATABRICKS_WORKSPACE_NAME="dbw-chec-demo"
export DATABRICKS_HOST="https://adb-<workspace-id>.<region>.azuredatabricks.net"

export CATALOG_NAME="chec_dbx_demo"
export APP_CATALOG_NAME="${CATALOG_NAME}"
export APP_NAME="chec-dash-parity"
export APP_WAREHOUSE_ID="<sql-warehouse-id>"
export REVIEWER_PRINCIPAL="users"
```

The repository defaults use `chec_dbx_demo`. That is convenient for the demo
workspace, but client installs should rename it if they need environment or
tenant isolation, for example `chec_client_dev` or `chec_prod`. If you choose a
different catalog, use the same value consistently for:

- Databricks bundle variable `catalog_name`.
- `CATALOG_NAME`.
- `APP_CATALOG_NAME`.

Default schemas created or used by this setup:

```text
raw
bronze
silver
gold
ml
agent
agent_config
agent_tools
agent_observability
```

Default chatbot resources:

```text
App name: chec-dash-parity
AI Search endpoint: chec-agent-search
AI Search index: <catalog>.gold.technical_doc_chunks_current_index
Embedding endpoint: databricks-qwen3-embedding-0-6b
AI Search query type: hybrid
LLM endpoint: databricks-qwen3-next-80b-a3b-instruct
MLflow experiment: /Shared/chec_dash_parity/agent_observability
Prompt name: chec_chatbot_answer_prompt
Prompt alias: production
```

Prompt Registry note: some Databricks organizations do not have Prompt Registry
enabled. If prompt registration returns `FEATURE_DISABLED`, the app will still
answer by using the local governed prompt template and will report
`mlflow_prompt_source=local` in `/chatbot/status`.

## 5. Create The Azure Databricks Workspace

Sign in and select the client subscription:

```bash
az login
az account set --subscription "${AZURE_SUBSCRIPTION_ID}"
az account show -o table
```

Create the resource group:

```bash
az group create \
  --name "${AZURE_RESOURCE_GROUP}" \
  --location "${AZURE_REGION}"
```

Create the Azure Databricks workspace:

```bash
az databricks workspace create \
  --resource-group "${AZURE_RESOURCE_GROUP}" \
  --name "${DATABRICKS_WORKSPACE_NAME}" \
  --location "${AZURE_REGION}" \
  --sku premium
```

Open the workspace from the Azure Portal. Confirm:

- The workspace launches successfully.
- You can log in as a workspace admin.
- Unity Catalog is available or can be attached by an account admin.

Official reference:
https://learn.microsoft.com/en-us/azure/databricks/admin/workspace/azure-cli

## 6. Configure Unity Catalog

In a new Azure account, an account admin may need to create or attach a Unity
Catalog metastore before the project can create catalogs, schemas, and volumes.

Confirm from the Databricks workspace:

```bash
export DATABRICKS_HOST="https://adb-<workspace-id>.<region>.azuredatabricks.net"
databricks auth login --host "${DATABRICKS_HOST}"
databricks current-user me -o json
databricks metastores current -o json
```

Expected result:

- `databricks current-user me` returns your Databricks user.
- `databricks metastores current` returns a `metastore_id`.

If there is no metastore:

1. Ask the Databricks account admin to open the account console.
2. Create a Unity Catalog metastore in the same Azure region as the workspace.
3. Attach the workspace to that metastore.
4. Grant the deployment operator enough catalog/schema privileges for this
   install.

Official reference:
https://learn.microsoft.com/en-us/azure/databricks/data-governance/unity-catalog/get-started

## 7. Prepare The Local Repository

Clone or copy the repo so the default data paths make sense:

```text
<CHEC_ROOT>/
  dashboard/                  # this repository
  data/                       # raw .pkl, .xlsx, model.pth, mask.npy
  Dashboard_CHEC/
    Unstructured_Files/       # curated chatbot PDFs
```

Then create the Python environment:

```bash
cd <CHEC_ROOT>/dashboard
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

On Windows PowerShell:

```powershell
cd <CHEC_ROOT>\dashboard
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

If the client stores data elsewhere, set these variables before uploads:

```bash
export CHEC_SOURCE_DATA_DIR="<path-to-data>"
export CHATBOT_SOURCE_DOCS_DIR="<path-to-unstructured-pdfs>"
export CHATBOT_VARIABLES_SOURCE_DIR="<path-to-arbol-decision-workbooks>"
export CHATBOT_CORPUS_SOURCE_DIR="<path-to-generated-chatbot-corpus>"
```

Run local tests before deploying:

```bash
cd <CHEC_ROOT>/dashboard
source .venv/bin/activate
pytest -q
```

## 8. Phase 1: Build The Databricks Data Foundation

Run preflight from the repo root:

```bash
cd <CHEC_ROOT>/dashboard
export DATABRICKS_HOST="https://adb-<workspace-id>.<region>.azuredatabricks.net"
export AZURE_REGION="eastus"
export CATALOG_NAME="chec_dbx_demo"
bash databricks/scripts/preflight_phase1_deploy.sh
```

Expected result:

- Azure subscription details print.
- Databricks metastore details print.
- Enabled node types and regional quota checks pass.
- The script ends with `Preflight PASSED.`

Deploy and run the Databricks Asset Bundle:

```bash
cd <CHEC_ROOT>/dashboard/databricks
databricks bundle validate -t dev --var catalog_name="${CATALOG_NAME}"
databricks bundle deploy -t dev --var catalog_name="${CATALOG_NAME}"
databricks bundle run -t dev chec_phase1_bootstrap --var catalog_name="${CATALOG_NAME}"
```

Upload raw files and ML artifacts:

```bash
cd <CHEC_ROOT>/dashboard
CATALOG_NAME="${CATALOG_NAME}" bash databricks/scripts/upload_phase1_assets.sh
```

Run ingest, validation, and gold-table build:

```bash
cd <CHEC_ROOT>/dashboard/databricks
databricks bundle run -t dev chec_phase1_ingest_validation --var catalog_name="${CATALOG_NAME}"
```

If serverless jobs are not available, use the classic fallback jobs:

```bash
databricks bundle run -t dev chec_phase1_bootstrap_classic --var catalog_name="${CATALOG_NAME}"
databricks bundle run -t dev chec_phase1_ingest_validation_classic --var catalog_name="${CATALOG_NAME}"
```

Verify the data foundation:

```bash
databricks tables list "${CATALOG_NAME}" gold -o table
databricks tables list "${CATALOG_NAME}" silver -o table
```

Key gold tables expected by the app include:

```text
gold_saidi_saifi_daily
gold_saidi_saifi_circuit_summary
gold_probability_inputs
gold_map_points
gold_map_line_segments
gold_map_filter_index
gold_map_event_days
```

## 9. Phase 2: Publish Dashboard And Pilot Assets

Deploy the bundle again if needed:

```bash
cd <CHEC_ROOT>/dashboard/databricks
databricks bundle validate -t dev --var catalog_name="${CATALOG_NAME}"
databricks bundle deploy -t dev --var catalog_name="${CATALOG_NAME}"
```

Publish notebooks and the Lakeview dashboard:

```bash
bash scripts/publish_phase2_notebooks.sh
bash scripts/publish_phase2_dashboard.sh
```

Apply pilot permissions:

```bash
REVIEWER_PRINCIPAL="${REVIEWER_PRINCIPAL}" \
bash scripts/apply_phase2_pilot_permissions.sh
```

Optional direct notebook and SQL access:

```bash
GRANT_REVIEWER_NOTEBOOK_ACCESS=true \
REVIEWER_PRINCIPAL="${REVIEWER_PRINCIPAL}" \
bash scripts/apply_phase2_pilot_permissions.sh

GRANT_REVIEWER_DATA_ACCESS=true \
PILOT_REVIEWER_PRINCIPAL="<client-reviewer-group>" \
bash scripts/apply_phase2_pilot_permissions.sh
```

## 10. Upload Chatbot Documents, Corpus, And Skills

Build the local fallback corpus if it does not already exist:

```bash
cd <CHEC_ROOT>/dashboard
source .venv/bin/activate
python scripts/build_chatbot_corpus.py \
  --source-dir ../Dashboard_CHEC/Unstructured_Files \
  --source-dir ../data/arbol_decision_recomendaciones \
  --output-dir ../data/chatbot_corpus
```

Upload curated documents, generated corpus files, and active skill files:

```bash
cd <CHEC_ROOT>/dashboard
CATALOG_NAME="${CATALOG_NAME}" bash databricks/scripts/upload_chatbot_assets.sh
```

This script:

- Uploads curated PDFs to `<catalog>.raw.source_files/chatbot_documents`.
- Uploads `chunks.jsonl` and manifests to `<catalog>.raw.source_files/chatbot_corpus`.
- Ensures skill lifecycle folders exist:
  - `active`
  - `draft`
  - `archive`
- Validates active skill files before upload.
- Uploads active governed skills to `<catalog>.agent_config.skills/active`.

Runtime only uses active skills. Draft and archive are lifecycle areas for client
editing and promotion.

## 11. Prepare Databricks Compute And App Settings

Create or identify a SQL Warehouse in the Databricks UI:

1. Open Databricks.
2. Go to SQL Warehouses.
3. Create or select a warehouse.
4. Copy the warehouse ID from the warehouse page or CLI output.

Export app settings:

```bash
export APP_NAME="chec-dash-parity"
export APP_CATALOG_NAME="${CATALOG_NAME}"
export APP_WAREHOUSE_ID="<sql-warehouse-id>"
export APP_GOLD_SCHEMA="gold"
export APP_SILVER_SCHEMA="silver"

export APP_CHATBOT_ENABLED="true"
export APP_CHATBOT_CONVERSATION_BACKEND="databricks_sql"
export APP_CHATBOT_CONVERSATION_SCHEMA="agent"
export APP_CHATBOT_CONTEXT_TOOLS_SCHEMA="agent_tools"
export APP_CHATBOT_MEMORY_MAX_TURNS="8"

export APP_RETRIEVER_BACKEND="databricks_ai_search"
export APP_AI_SEARCH_ENDPOINT_NAME="chec-agent-search"
export APP_AI_SEARCH_INDEX_FULL_NAME="${CATALOG_NAME}.gold.technical_doc_chunks_current_index"
export APP_AI_SEARCH_TOP_K="8"
export APP_AI_SEARCH_QUERY_TYPE="hybrid"
export APP_AI_SEARCH_EMBEDDING_ENDPOINT_NAME="databricks-qwen3-embedding-0-6b"
export APP_AI_SEARCH_ENDPOINT_TYPE="STANDARD"

export APP_LLM_PROVIDER="databricks_model_serving"
export APP_LLM_ENDPOINT_NAME="databricks-qwen3-next-80b-a3b-instruct"
export APP_LLM_MAX_TOKENS="1200"
export APP_LLM_TEMPERATURE="0.2"

export APP_CHATBOT_OBSERVABILITY_ENABLED="true"
export APP_CHATBOT_TELEMETRY_SCHEMA="agent_observability"
export APP_CHATBOT_EVAL_REPORT_ONLY="true"
export APP_CHATBOT_EVAL_LLM_JUDGES_ENABLED="false"
export APP_CHATBOT_EVAL_ENFORCE="false"
export APP_MLFLOW_TRACKING_URI="databricks"
export APP_MLFLOW_EXPERIMENT_NAME="/Shared/chec_dash_parity/agent_observability"
export APP_MLFLOW_PROMPT_NAME="chec_chatbot_answer_prompt"
export APP_MLFLOW_PROMPT_ALIAS="production"
```

The app uses Databricks App resources and `valueFrom` for runtime-bound values:

- `chatbot_corpus_volume` exposes the read-only corpus/source volume.
- `chatbot_skills_volume` exposes active/draft/archive skill files.
- `chatbot_ai_search_index` exposes the AI Search index name.
- `chatbot_llm_endpoint` exposes the Model Serving endpoint name.

Official reference:
https://docs.databricks.com/gcp/en/dev-tools/databricks-apps/resources

## 12. Deploy The Databricks App

Deploy from the repo root:

```bash
cd <CHEC_ROOT>/dashboard
bash databricks/scripts/deploy_phase35_databricks_app.sh
```

The deploy script stages and deploys the app, and also runs the Phase 3-9 setup:

- `setup_phase3_conversation_tables.py`
- `setup_phase4_context_tools.py`
- `setup_phase5_ai_search.py`
- `setup_phase9_observability.py`

It creates or updates:

- Conversation tables in `<catalog>.agent`.
- Read-only context views/functions in `<catalog>.gold` and `<catalog>.agent_tools`.
- Delta document chunk tables in `<catalog>.silver` and `<catalog>.gold`.
- AI Search endpoint/index.
- Telemetry/evaluation tables in `<catalog>.agent_observability`.
- MLflow experiment under `/Shared/chec_dash_parity/agent_observability`.

Apply app and data permissions:

```bash
cd <CHEC_ROOT>/dashboard
EDITOR_PRINCIPAL="<deployer-email>" \
REVIEWER_PRINCIPAL="${REVIEWER_PRINCIPAL}" \
APP_TELEMETRY_SCHEMA="agent_observability" \
APP_MLFLOW_EXPERIMENT_NAME="/Shared/chec_dash_parity/agent_observability" \
bash databricks/scripts/apply_phase35_app_permissions.sh
```

Expected final deploy output includes the Databricks App URL:

```text
https://<app-name>-<workspace-id>.<region>.databricksapps.com
```

## 13. Validate The Deployment

Check app readiness from the Databricks App URL:

```bash
APP_URL="https://<app-name>-<workspace-id>.<region>.databricksapps.com"
curl -sS "${APP_URL}/ready"
```

For authenticated app endpoints, use a browser session or keep the token in
process memory. Do not paste bearer tokens into commands, tickets, or docs.

Example authenticated status smoke:

```bash
python - <<'PY'
import json
import subprocess
import urllib.request

app_url = "https://<app-name>-<workspace-id>.<region>.databricksapps.com"
token = json.loads(
    subprocess.check_output(["databricks", "auth", "token", "-o", "json"], text=True)
)["access_token"]
req = urllib.request.Request(
    app_url + "/chatbot/status",
    headers={"Authorization": "Bearer " + token},
)
data = json.loads(urllib.request.urlopen(req, timeout=60).read().decode("utf-8"))
keys = [
    "ready",
    "llm_provider",
    "model_endpoint_name",
    "retriever_backend",
    "ai_search_index_name",
    "observability_enabled",
    "observability_configured",
    "mlflow_prompt_source",
    "chatbot_telemetry_schema",
    "last_evaluation_summary",
]
print(json.dumps({key: data.get(key) for key in keys}, indent=2))
PY
```

Expected status:

```text
ready: true
llm_provider: databricks_model_serving
retriever_backend: databricks_ai_search
observability_enabled: true
observability_configured: true
```

Smoke the chatbot in the app UI:

1. Open the Databricks App URL.
2. Go to the technical assistant tab.
3. Select a dashboard context.
4. Ask: `CREG 015 SAIDI SAIFI`.
5. Ask follow-ups:
   - `historial del circuito CKT-1`
   - `que revisar en el activo seleccionado`
6. Confirm the answer shows citations, structured sections, validation warnings
   when relevant, and tool trace metadata.

Check AI Search rows and telemetry rows:

```bash
PYTHONPATH=src \
DATABRICKS_SQL_WAREHOUSE_ID="${APP_WAREHOUSE_ID}" \
DATABRICKS_CATALOG_NAME="${CATALOG_NAME}" \
CHATBOT_TELEMETRY_SCHEMA="agent_observability" \
python - <<'PY'
from chec_dashboard.core.config import load_settings
from chec_dashboard.services.databricks_sql import DatabricksSQLWarehouseClient

settings = load_settings()
client = DatabricksSQLWarehouseClient(settings)
df = client.fetch_dataframe("""
SELECT
  (SELECT count(*) FROM chec_dbx_demo.gold.technical_doc_chunks_current) AS chunks,
  (SELECT count(*) FROM chec_dbx_demo.agent_observability.agent_turn_traces) AS traces,
  (SELECT count(*) FROM chec_dbx_demo.agent_observability.agent_release_reports) AS release_reports,
  (SELECT count(*) FROM chec_dbx_demo.agent_observability.agent_evaluation_examples) AS eval_examples
""")
print(df.to_string(index=False))
PY
```

If the client changed `CATALOG_NAME`, replace `chec_dbx_demo` in the SQL string
with the chosen catalog.

Run the report-only evaluation:

```bash
cd <CHEC_ROOT>/dashboard
APP_WAREHOUSE_ID="${APP_WAREHOUSE_ID}" \
APP_CATALOG_NAME="${CATALOG_NAME}" \
APP_CHATBOT_TELEMETRY_SCHEMA="agent_observability" \
APP_CHATBOT_EVAL_REPORT_ONLY="true" \
APP_CHATBOT_EVAL_LLM_JUDGES_ENABLED="false" \
APP_CHATBOT_EVAL_ENFORCE="false" \
python databricks/scripts/run_phase9_evaluation.py
```

Expected result:

- Script exits `0` in report-only mode.
- `agent_release_reports` receives a new row.
- `/chatbot/status` shows `last_evaluation_summary`.
- The evaluation report is visible in Unity Catalog telemetry and the app
  status payload.

## 14. Troubleshooting

### Azure CLI login fails

Run:

```bash
az login
az account show -o table
az account set --subscription "<subscription-id-or-name>"
```

If the browser login is blocked, ask the client IT team whether conditional
access, MFA, or a corporate proxy is blocking CLI auth.

### Databricks CLI cannot authenticate

Run:

```bash
databricks auth login --host "${DATABRICKS_HOST}"
databricks current-user me -o json
```

If the CLI is old, install a current Databricks CLI. The project expects the
new CLI family, not the legacy `databricks-cli` Python package.

### No Unity Catalog metastore

`databricks metastores current` must return a metastore. If it does not, an
account admin must create or attach a Unity Catalog metastore in the same Azure
region as the workspace.

### Catalog creation or grants fail

The deployment operator may not be a metastore admin or catalog owner. Ask a
Unity Catalog admin to grant catalog/schema creation rights or pre-create the
catalog with a managed location.

### Preflight reports quota or SKU failure

Use serverless where possible. If classic fallback jobs are required, the Azure
subscription must have enough regional vCPU quota and Databricks must expose the
configured node types. Ask the client Azure admin to approve quota or choose a
supported region/SKU.

### Upload script reports missing files

Confirm the local folder layout:

```text
<CHEC_ROOT>/data
<CHEC_ROOT>/Dashboard_CHEC/Unstructured_Files
<CHEC_ROOT>/dashboard
```

Or set `CHEC_SOURCE_DATA_DIR`, `CHATBOT_SOURCE_DOCS_DIR`,
`CHATBOT_VARIABLES_SOURCE_DIR`, and `CHATBOT_CORPUS_SOURCE_DIR`.

### AI Search index is not ready

Run the app deploy script again; the Phase 5 setup is idempotent. Then check the
index in Databricks UI under Catalog Explorer or AI Search/Vector Search,
depending on the workspace UI. Exact labels vary by Databricks workspace
release.

### Model Serving timeout

The app returns a Spanish non-fatal error and preserves citations/metadata when
the endpoint times out. Retry after the endpoint warms up. If it keeps failing,
confirm the endpoint exists, the app resource has `CAN_QUERY`, and the workspace
supports the selected foundation model.

### Prompt Registry disabled

If setup prints `FEATURE_DISABLED: CreatePrompt`, continue. This is allowed for
the current deployment. Runtime falls back to the local prompt template and
still records prompt metadata.

### Databricks CLI EOF or transient API errors

The app deploy and permission scripts include retries for common transient EOF
errors. Rerun the same command. The setup scripts are idempotent.

## 15. Cost And Shutdown Notes

Cost drivers to discuss with the client:

- Databricks App runtime while running.
- SQL Warehouse runtime; enable auto-stop for non-production.
- AI Search endpoint fixed hourly cost.
- Model Serving token usage.
- Serverless/jobs compute for data setup and refresh.
- MLflow and telemetry storage/evaluation.

For non-production environments:

```bash
databricks apps stop "${APP_NAME}"
```

Also consider stopping the SQL Warehouse in the UI and reviewing whether the AI
Search endpoint should remain online outside demo windows.

Do not delete production Unity Catalog tables unless the client has approved
data retention and backup requirements.

## 16. Repeat-Install Checklist

Copy this block for each new client.

```text
Client:
Azure subscription:
Azure region:
Resource group:
Databricks workspace:
Databricks host:
Unity Catalog metastore:
Catalog name:
SQL Warehouse ID:
Reviewer group:
App name:
App URL:
AI Search endpoint:
AI Search index:
LLM endpoint:
MLflow experiment:
Prompt Registry enabled? yes/no

Completed:
[ ] Local prerequisites installed
[ ] Azure CLI authenticated
[ ] Databricks CLI authenticated
[ ] Workspace created
[ ] Unity Catalog metastore attached
[ ] Preflight passed
[ ] Bundle validated/deployed
[ ] Phase 1 bootstrap succeeded
[ ] Raw files uploaded
[ ] Phase 1 ingest validation succeeded
[ ] Phase 2 dashboard published
[ ] Chatbot assets uploaded
[ ] Databricks App deployed
[ ] App permissions applied
[ ] /ready passed
[ ] /chatbot/status ready=true
[ ] Guided chatbot smoke passed
[ ] Follow-up chatbot smoke passed
[ ] Telemetry rows written
[ ] Evaluation report written
[ ] Cost/shutdown plan reviewed
```

## Annex A: Installing Local Prerequisites

This annex is for the deployment operator's laptop or build machine. If the
client uses a locked-down machine, ask IT to install these tools or provide an
approved development VM.

### A.1 Azure CLI

Official docs:
https://learn.microsoft.com/cli/azure/install-azure-cli

Windows PowerShell:

```powershell
winget install --exact --id Microsoft.AzureCLI
az version
```

macOS with Homebrew:

```bash
brew update
brew install azure-cli
az version
```

Ubuntu/Debian:

```bash
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
az version
```

Authentication:

```bash
az login
az account list -o table
az account set --subscription "<subscription-id-or-name>"
az account show -o table
```

### A.2 Databricks CLI

Official docs:
https://learn.microsoft.com/en-us/azure/databricks/dev-tools/cli/install

The project expects Databricks CLI `0.205` or newer.

Windows PowerShell with WinGet:

```powershell
winget install Databricks.DatabricksCLI
databricks version
```

macOS or Linux with Homebrew:

```bash
brew tap databricks/tap
brew install databricks
databricks version
```

Linux/macOS curl installer:

```bash
curl -fsSL https://raw.githubusercontent.com/databricks/setup-cli/main/install.sh | sh
databricks version
```

Authentication:

```bash
export DATABRICKS_HOST="https://adb-<workspace-id>.<region>.azuredatabricks.net"
databricks auth login --host "${DATABRICKS_HOST}"
databricks current-user me -o json
```

If `databricks version` reports an old CLI or the command group names do not
match this runbook, remove the old legacy Python package and install the current
CLI from the official docs.

### A.3 Git

Official docs:
https://git-scm.com/book/en/v2/Getting-Started-Installing-Git

Windows PowerShell:

```powershell
winget install --exact --id Git.Git
git --version
```

macOS:

```bash
brew install git
git --version
```

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y git
git --version
```

Clone the repo:

```bash
git clone <repo-url> dashboard
cd dashboard
git status
```

### A.4 Python 3.12 And venv

Official Python downloads:
https://www.python.org/downloads/

Official `venv` docs:
https://docs.python.org/3.12/library/venv.html

Windows PowerShell:

```powershell
winget install --exact --id Python.Python.3.12
py -3.12 --version
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python --version
```

macOS with Homebrew:

```bash
brew install python@3.12
python3.12 --version
python3.12 -m venv .venv
source .venv/bin/activate
python --version
```

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y python3.12 python3.12-venv python3-pip
python3.12 --version
python3.12 -m venv .venv
source .venv/bin/activate
python --version
```

PowerShell execution policy note:

If virtual environment activation is blocked on Windows, run PowerShell as the
same user and allow local scripts for the current user:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

Then reopen PowerShell and activate again.

### A.5 jq

Official download page:
https://jqlang.org/download/

Windows PowerShell:

```powershell
winget install --exact --id jqlang.jq
jq --version
```

macOS:

```bash
brew install jq
jq --version
```

Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y jq
jq --version
```

### A.6 curl

`curl` is usually preinstalled on macOS, Linux, and modern Windows. On Windows,
Microsoft documents `curl` as included with Windows.

Check:

```bash
curl --version
```

If missing on Ubuntu/Debian:

```bash
sudo apt-get update
sudo apt-get install -y curl
```

If missing on macOS:

```bash
brew install curl
```

### A.7 Common Local Install Fixes

PATH not updated:

- Close and reopen the terminal.
- On Windows, confirm the installed tool is visible in a new PowerShell window.
- Run `where az`, `where databricks`, or `where python` on Windows.
- Run `which az`, `which databricks`, or `which python` on macOS/Linux.

Python command differs:

- Windows commonly uses `py -3.12`.
- macOS/Linux commonly use `python3.12` or `python3`.
- Inside an activated `.venv`, `python` should point to the virtual environment.

Corporate proxy or firewall:

- Allow HTTPS access to Azure, Databricks, PyPI, Git provider, GitHub release
  downloads, and Microsoft package endpoints.
- Ask IT whether the machine needs `HTTPS_PROXY` or a trusted corporate CA
  bundle configured.

Databricks CLI old-version warning:

- Use `databricks version`.
- If the version is below `0.205`, install the current CLI from the official
  Databricks docs.
- Avoid mixing the old Python `databricks-cli` package with the current CLI.

### A.8 Final Prerequisite Verification

Run this before the deployment begins:

```bash
echo "Azure CLI:"
az version

echo "Databricks CLI:"
databricks version

echo "Git:"
git --version

echo "Python:"
python --version || python3 --version || py -3.12 --version

echo "jq:"
jq --version

echo "curl:"
curl --version

echo "Azure account:"
az account show -o table

echo "Databricks user:"
databricks current-user me -o json
```

Only continue after every command succeeds.
