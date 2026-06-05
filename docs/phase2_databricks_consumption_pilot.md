# Phase 2 Databricks Consumption Pilot

This guide covers the first client-facing Databricks pilot on top of the Phase 1 `gold` layer.

## Pilot Deliverables
- AI/BI summary dashboard draft: `CHEC Summary Pilot`
- Probability exploration notebook: `04_probability_explorer`
- Map exploration notebook: `06_map_explorer`
- Paused scheduled refresh job: `chec-phase2-pilot-refresh`

## Data Sources
- `chec_dbx_demo.gold.gold_saidi_saifi_daily`
- `chec_dbx_demo.gold.gold_saidi_saifi_circuit_summary`
- `chec_dbx_demo.gold.gold_probability_inputs`
- `chec_dbx_demo.gold.gold_map_points`

## Recommended Deployment Order
1. Validate and deploy the bundle.
2. Publish the analyst notebooks into the shared workspace folder.
3. Publish the dashboard draft.
4. Apply pilot permissions.
5. Unpause the refresh schedule only after the stakeholder pilot is ready.

## Commands
```bash
cd /home/jclugor/unal/CHEC/dashboard/databricks

# bundle update

databricks bundle validate -t dev
databricks bundle deploy -t dev

# publish analyst notebooks
bash scripts/publish_phase2_notebooks.sh

# publish dashboard
bash scripts/publish_phase2_dashboard.sh

# if you refine the dashboard in the Lakeview UI, sync that working draft back into the repo
bash scripts/sync_phase2_dashboard_from_workspace.sh

# apply pilot permissions
bash scripts/apply_phase2_pilot_permissions.sh

# optional: grant reviewers direct notebook read access
GRANT_REVIEWER_NOTEBOOK_ACCESS=true bash scripts/apply_phase2_pilot_permissions.sh

# optional: grant reviewers direct SQL read access to gold/silver
PILOT_REVIEWER_PRINCIPAL="<reviewer-group>" GRANT_REVIEWER_DATA_ACCESS=true bash scripts/apply_phase2_pilot_permissions.sh
```

## Default Paths And Identifiers
- Dashboard display name: `CHEC Summary Pilot`
- Live draft display name after bundle deploy: `[dev <user>] CHEC Summary Pilot`
- Dashboard parent path: `/Shared/CHEC Phase2 Pilot`
- Notebook publish path: `/Shared/CHEC Phase2 Pilot/Notebooks`
- Warehouse ID: created/reused by `databricks/scripts/fresh_install_databricks.sh`,
  or set explicitly with `APP_WAREHOUSE_ID` / `WAREHOUSE_ID`
- Scheduled refresh job name suffix: `chec-phase2-pilot-refresh`

## Pilot Validation
### Dashboard parity
Run these checks after deployment:

```sql
SELECT *
FROM chec_dbx_demo.silver.phase1_validation_results
WHERE check_status <> 'PASS';

SELECT *
FROM chec_dbx_demo.gold.gold_saidi_saifi_daily
LIMIT 20;

SELECT *
FROM chec_dbx_demo.gold.gold_saidi_saifi_circuit_summary
LIMIT 20;
```

### Notebook readiness
- `04_probability_explorer` should load `gold_probability_inputs` and render a filtered distribution.
- `06_map_explorer` should load `gold_map_points`, show grouped counts, and render a point map when geographic rows are available.

### Refresh behavior
The pilot refresh job is created as paused. When you are ready to activate it, unpause it in Databricks Jobs and confirm that:
- `stage_bronze_tables` succeeds
- `validate_ingest` returns no failing checks
- `build_silver_gold` refreshes the gold tables
- `stage_ml_assets` completes without changing the dashboard interface contract

## Sharing Defaults
- `publish_phase2_dashboard.sh` defaults to shared-data publishing by embedding publisher credentials.
- `apply_phase2_pilot_permissions.sh` defaults the reviewer audience to the Databricks workspace `users` group and the editor principal to the currently authenticated Databricks user.
- Reviewer dashboard access uses the permission levels the live workspace actually supports. For Lakeview dashboards that is currently `CAN_READ`, not `CAN_VIEW`.
- Widget bindings authored directly in the Lakeview UI are more reliable than hand-written widget JSON. After UI-side dashboard repairs, run `sync_phase2_dashboard_from_workspace.sh` so the repo keeps the working structure.
- Direct reviewer notebook access is off by default. Enable it with `GRANT_REVIEWER_NOTEBOOK_ACCESS=true`.
- Direct reviewer SQL access is off by default so the script does not grant read access broadly. Enable it only after setting a narrower `PILOT_REVIEWER_PRINCIPAL`, then rerun with `GRANT_REVIEWER_DATA_ACCESS=true`.
- Pilot assets under `/Shared` inherit broad workspace access from parent folders. If you need strict reviewer-versus-editor separation, move the pilot root out of `/Shared` before relying on ACLs alone.
