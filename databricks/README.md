# CHEC Databricks Migration Bundle

This folder now contains the Databricks bundle scaffold for the Phase 1 foundation,
the Phase 2 consumption pilot, and the Phase 3-5 Dash-parity app scaffolding.

## What Is Included
- A bundle configuration at `databricks.yml`.
- A shared manifest at `manifests/phase1_assets.json`.
- Databricks-native notebook sources under `notebooks/`.
- A bundle-managed AI/BI dashboard definition under `dashboards/`.
- Legacy reference notebooks vendored under `references/`.
- Serverless-first bootstrap and ingest-validation workflows.
- Classic fallback bootstrap and ingest-validation workflows with approved East US SKUs.
- A paused Phase 2 pilot refresh workflow.
- Local scripts for preflight, upload, notebook promotion, dashboard publishing, and pilot permissions.
- A Databricks App staging/deploy workflow for full Dash parity.

## Bundle Layout
```text
databricks/
  databricks.yml
  dashboards/
  manifests/
  notebooks/
  references/
  resources/
  scripts/
  apps/
  README.md
```

## Phase 1 Flow
Set your Databricks auth first. The bundle reads the workspace host from your
environment or CLI profile, so export `DATABRICKS_HOST` before validating:

```bash
cd /home/jclugor/unal/CHEC/dashboard/databricks
export DATABRICKS_HOST="https://adb-<workspace-id>.<region>.azuredatabricks.net"
databricks auth login --host "$DATABRICKS_HOST"
bash scripts/preflight_phase1_deploy.sh
databricks bundle validate -t dev
databricks bundle deploy -t dev
databricks bundle run -t dev chec_phase1_bootstrap
bash scripts/upload_phase1_assets.sh
databricks bundle run -t dev chec_phase1_ingest_validation
```

The default workflow is intentionally split in two:
- `chec_phase1_bootstrap` creates the catalog, schemas, volumes, and registry tables.
- `upload_phase1_assets.sh` uploads the local raw files and ML artifacts into Unity Catalog volumes.
- `chec_phase1_ingest_validation` reads from those volumes, builds bronze/silver/gold tables, and validates the result.

## Phase 2 Flow
Phase 2 assumes the gold tables already exist and focuses on the stakeholder pilot.

```bash
cd /home/jclugor/unal/CHEC/dashboard/databricks
databricks bundle validate -t dev
databricks bundle deploy -t dev
bash scripts/publish_phase2_notebooks.sh
bash scripts/publish_phase2_dashboard.sh
bash scripts/apply_phase2_pilot_permissions.sh

# optional: add reviewer notebook read access
GRANT_REVIEWER_NOTEBOOK_ACCESS=true bash scripts/apply_phase2_pilot_permissions.sh

# optional: add reviewer SQL read access for a narrower reviewer group
PILOT_REVIEWER_PRINCIPAL="<reviewer-group>" GRANT_REVIEWER_DATA_ACCESS=true bash scripts/apply_phase2_pilot_permissions.sh
```

Lakeview dashboards are safest to refine in the Databricks UI once the first draft exists. If you make widget or layout fixes in the UI, sync the live draft back into the repo before the next bundle deployment:

```bash
cd /home/jclugor/unal/CHEC/dashboard/databricks
bash scripts/sync_phase2_dashboard_from_workspace.sh
```

What Phase 2 adds:
- `chec_phase2_summary_pilot`: a bundle-managed AI/BI summary dashboard draft.
- `chec_phase2_pilot_refresh`: a paused scheduled refresh job that reruns the phase-1 ingest and gold build sequence.
- `04_probability_explorer.py`: notebook-first analyst workflow for probability exploration.
- `06_map_explorer.py`: notebook-first map pilot for filtered point exploration.

Bundle-managed dashboards are deployed with the target prefix in the live workspace, so the draft appears as `[dev <user>] CHEC Summary Pilot` even though the local resource suffix is `CHEC Summary Pilot`.

## Phase 3-5 Flow
Phase 3-5 keeps the current Lakeview dashboard as the summary landing page and
introduces a Databricks App for the full `summary`, `probability`, and `map`
parity experience.

```bash
cd /home/jclugor/unal/CHEC/dashboard
./.venv/bin/python databricks/scripts/stage_phase35_databricks_app.py

cd /home/jclugor/unal/CHEC/dashboard/databricks
bash scripts/deploy_phase35_databricks_app.sh
bash scripts/apply_phase35_app_permissions.sh
```

Use these environment variables before staging if you need non-default targets:
- `APP_WAREHOUSE_ID`
- `APP_CATALOG_NAME`
- `APP_GOLD_SCHEMA`
- `APP_SILVER_SCHEMA`

The Databricks App path is documented in:
- `docs/phase35_databricks_app_parity.md`

What Phase 3-5 adds:
- `DATA_BACKEND=databricks_sql` provider mode for Dash/FastAPI parity paths.
- `API_TRANSPORT=inproc` so the Dash app can run in Databricks without an external API base URL.
- New gold presentation tables for map parity:
  - `gold_map_line_segments`
  - `gold_map_filter_index`
  - `gold_map_event_days`
- A staged Databricks App source bundle under `databricks/build/` for deployment.

## Current Defaults
- Catalog: `chec_dbx_demo`
- Dashboard warehouse: `4437a6195e05c59c` (`Serverless Starter Warehouse`)
- Dashboard parent path: `/Shared/CHEC Phase2 Pilot`
- Shared notebook path: `/Shared/CHEC Phase2 Pilot/Notebooks`
- Pilot refresh schedule: daily at `06:00` `America/Bogota`, created as `PAUSED`

## Classic Fallback Jobs
If a workload later proves incompatible with serverless, the bundle also defines classic fallback jobs with built-in retries:

```bash
databricks bundle run -t dev chec_phase1_bootstrap_classic
bash scripts/upload_phase1_assets.sh
databricks bundle run -t dev chec_phase1_ingest_validation_classic
```

The classic fallback profiles are:
- `chec_phase1_bootstrap_classic`: single-node `Standard_DC4as_v5`
- `chec_phase1_ingest_validation_classic`: single-node `Standard_L4aos_v4`

Each classic fallback task retries up to 3 total attempts with a 10-minute backoff. If a classic fallback run still fails after retries, rerun `bash scripts/preflight_phase1_deploy.sh` before trying another region or SKU.

## Expected Workspace Shape
- `chec_dbx_demo` Unity Catalog catalog by default.
- `raw`, `bronze`, `silver`, `gold`, and `ml` schemas.
- Managed volumes for source files and model artifacts.
- A draft AI/BI dashboard named `CHEC Summary Pilot`.
- Promoted notebooks under `/Shared/CHEC Phase2 Pilot/Notebooks`.

## Source, Secrets, And Sharing
- Raw data files are uploaded directly into Unity Catalog volumes instead of being synced through workspace files.
- `OPENAI_API_Key.txt` is intentionally excluded from sync and must be moved to a secret scope or Key Vault-backed secret store.
- `model.pth` and `mask.npy` are uploaded into the ML artifacts volume and registered by the validation workflow.
- `publish_phase2_dashboard.sh` publishes the draft dashboard and can optionally embed publisher credentials for a broader pilot review path.
- `sync_phase2_dashboard_from_workspace.sh` pulls the current Lakeview draft back into `dashboards/chec_summary_pilot.lvdash.json` after UI-side widget repairs.
- `apply_phase2_pilot_permissions.sh` resolves the live permission levels Databricks supports before applying dashboard, notebook-folder, job, and optional UC read grants for the pilot.
- `stage_phase35_databricks_app.py` builds the deployable Databricks App source from the main Dash repo without duplicating the UI code in two places.
- `deploy_phase35_databricks_app.sh` creates the Databricks App if needed, uploads the staged source to workspace files, and deploys it in `SNAPSHOT` mode.
- `apply_phase35_app_permissions.sh` applies reviewer/editor permissions to the Databricks App using the permission levels the live workspace actually supports.
- The default reviewer audience is the workspace `users` group. Direct reviewer notebook and SQL access are opt-in so the script does not grant broad read access accidentally.
- Pilot assets under `/Shared` inherit broad workspace access from parent folders. Use a restricted parent folder instead if you need strict reviewer-versus-editor separation.
