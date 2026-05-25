# Phase 3-5 Databricks App Parity

This guide covers the Databricks-native parity path for the full CHEC Dash experience.

## Goal
- Keep the Lakeview summary dashboard as the stakeholder landing page.
- Reproduce the full `summary`, `probability`, and `map` user journeys inside a Databricks App.
- Reuse the current Dash UI behavior and the `/data` contract while switching the backing data source to Unity Catalog tables.

## Runtime Model
- `DATA_BACKEND=pickle` keeps the current local/Azure-container behavior.
- `DATA_BACKEND=databricks_sql` switches the data provider to Databricks SQL over Unity Catalog tables.
- `API_TRANSPORT=http` keeps the current Dash-to-FastAPI HTTP pattern.
- `API_TRANSPORT=inproc` lets the Dash app call the same provider functions in-process and also exposes `/data` and `/ready` from the Dash server.

## Databricks App Inputs
Set these values when staging or deploying the app:

```bash
export APP_WAREHOUSE_ID=4437a6195e05c59c
export APP_CATALOG_NAME=chec_dbx_demo
export APP_GOLD_SCHEMA=gold
export APP_SILVER_SCHEMA=silver
```

The staged app runtime then receives:
- `DATA_BACKEND=databricks_sql`
- `API_TRANSPORT=inproc`
- `DATABRICKS_SQL_WAREHOUSE_ID`
- `DATABRICKS_CATALOG_NAME`
- `DATABRICKS_GOLD_SCHEMA`
- `DATABRICKS_SILVER_SCHEMA`

## Stage And Deploy
Build the app source bundle from the main dashboard repo:

```bash
cd /home/jclugor/unal/CHEC/dashboard
./.venv/bin/python databricks/scripts/stage_phase35_databricks_app.py
```

That writes the deployable app source under:

```text
databricks/build/chec_dash_parity/
```

Deploy it to Databricks:

```bash
cd /home/jclugor/unal/CHEC/dashboard/databricks
bash scripts/deploy_phase35_databricks_app.sh
```

## App Permissions
Grant app access to reviewers and editors:

```bash
cd /home/jclugor/unal/CHEC/dashboard/databricks
bash scripts/apply_phase35_app_permissions.sh
```

Optional overrides:

```bash
APP_NAME=chec-dash-parity \
REVIEWER_PRINCIPAL=users \
EDITOR_PRINCIPAL=someone@company.com \
bash scripts/apply_phase35_app_permissions.sh
```

## Data Tables Used By Parity Runtime
- `chec_dbx_demo.gold.gold_saidi_saifi_daily`
- `chec_dbx_demo.gold.gold_saidi_saifi_circuit_summary`
- `chec_dbx_demo.gold.gold_probability_inputs`
- `chec_dbx_demo.gold.gold_map_points`
- `chec_dbx_demo.gold.gold_map_line_segments`
- `chec_dbx_demo.gold.gold_map_filter_index`
- `chec_dbx_demo.gold.gold_map_event_days`

## Validation Checklist
### Summary
- default 180-day window ends on the max available date
- KPI totals match the existing Dash summary payload
- daily trend stays daily, not monthly
- metric modes `SAIDI`, `SAIFI`, `BOTH` all work

### Probability
- criteria selector loads the three event families
- dynamic columns load per criteria
- filter option narrowing honors previous filters
- numeric, date, and selection filters all work
- chart renders and download remains available

### Map
- month and municipio selectors populate correctly
- dependent circuit selector updates from Databricks-backed metadata
- `Todos` and specific-circuit behavior both work
- day slider changes only the event layer
- `REDMT` line geometry renders alongside points

## Notes
- The Dash contract remains the parity reference even in Databricks-native mode.
- The current Phase 2 notebooks remain useful for exploration, but the parity target is the Databricks App, not notebook-only interaction.
- The existing external Dash deployment should remain available until Databricks App parity is signed off.
