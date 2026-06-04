# Phase 3-5 Databricks App Parity

> Historical note: this document explains the original Databricks App parity
> path. For a new client install from a fresh Azure account, use the canonical
> runbook: `docs/AZURE_DATABRICKS_FRESH_INSTALL.md`.

This guide covers the Databricks-native parity path for the full CHEC Dash experience.

## Goal
- Keep the Lakeview summary dashboard as the stakeholder landing page.
- Reproduce the full `summary`, `probability`, `map`, and technical chatbot user journeys inside a Databricks App.
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

Current chatbot deployments use Databricks-native RAG settings supplied through
Databricks App environment variables and app resources:
- `CHATBOT_ENABLED`
- `LLM_PROVIDER=databricks_model_serving`
- `LLM_ENDPOINT_NAME` from the Databricks App resource key `chatbot_llm_endpoint`
- `LLM_MAX_TOKENS`
- `LLM_TEMPERATURE`
- `RETRIEVER_BACKEND=databricks_ai_search`
- `AI_SEARCH_ENDPOINT_NAME`
- `AI_SEARCH_INDEX_NAME` from the Databricks App resource key `chatbot_ai_search_index`
- `AI_SEARCH_TOP_K`
- `AI_SEARCH_QUERY_TYPE=hybrid`
- `CHATBOT_CORPUS_VOLUME_DIR` from the Databricks App resource key `chatbot_corpus_volume`
- `CHATBOT_CORPUS_SUBDIR`
- `CHATBOT_SKILLS_VOLUME_DIR` from the Databricks App resource key `chatbot_skills_volume`
- `CHATBOT_SKILLS_SUBDIR=active`
- `CHATBOT_CONVERSATION_BACKEND=databricks_sql`
- `CHATBOT_CONVERSATION_SCHEMA=agent`
- `CHATBOT_CONTEXT_TOOLS_SCHEMA=agent_tools`
- `CHATBOT_OBSERVABILITY_ENABLED=true`
- `CHATBOT_TELEMETRY_SCHEMA=agent_observability`
- `MLFLOW_TRACKING_URI=databricks`
- `MLFLOW_EXPERIMENT_NAME=/Shared/chec_dash_parity/agent_observability`
- `CHATBOT_CORPUS_DIR` only as a local/dev explicit override
- `CHATBOT_RETRIEVAL_TOP_K`
- `CHATBOT_MAX_CONTEXT_CHARS`

Do not commit real vendor keys or generated private document indexes to the
repository. Store the generated chatbot corpus in
`chec_dbx_demo.raw.source_files/chatbot_corpus`, bind that volume to the app as
a read-only resource key named `chatbot_corpus_volume`, and reference it from
`app.yaml` with `valueFrom`. Production chatbot generation should use
Databricks Model Serving. Direct Gemini configuration remains a prototype-only
fallback and should be supplied through Databricks secrets if ever used.

Build and upload chatbot document artifacts before enabling Databricks AI
Search-backed answers:

```bash
cd /home/jclugor/unal/CHEC/dashboard
./.venv/bin/python scripts/build_chatbot_corpus.py \
  --source-dir ../Dashboard_CHEC/Unstructured_Files \
  --source-dir ../data/arbol_decision_recomendaciones \
  --output-dir ../data/chatbot_corpus

cd /home/jclugor/unal/CHEC/dashboard
bash databricks/scripts/upload_chatbot_assets.sh
```

The current deploy script binds the uploaded corpus volume, skill volume, AI
Search index, and Model Serving endpoint to the Databricks App. If you need to
inspect the resource shape manually, it follows the same app-resource pattern:

```bash
databricks apps update chec-dash-parity \
  --json '{"description":"CHEC Databricks App for full Dash parity","resources":[{"name":"chatbot_corpus_volume","description":"Read-only CHEC chatbot corpus and source documents volume","uc_securable":{"securable_type":"VOLUME","securable_full_name":"chec_dbx_demo.raw.source_files","permission":"READ_VOLUME"}}]}'
```

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

### Technical Chatbot / RAG Assessment
- chatbot tab loads and `/chatbot/status` reports `databricks_model_serving`, `databricks_ai_search`, `databricks_sql`, and `agent_observability` readiness
- selected event or network-element context is carried into the prompt payload as structured metadata
- answer is generated in Spanish through Databricks Model Serving once the app endpoint resource has `CAN_QUERY`
- citations come from the Databricks AI Search index and include title/path/page/snippet metadata
- conversation turns persist to Delta tables in `chec_dbx_demo.agent`
- observability records persist to `chec_dbx_demo.agent_observability`
- missing documents or missing selected context produce a graceful Spanish message

## Notes
- The Dash contract remains the parity reference even in Databricks-native mode.
- The current Phase 2 notebooks remain useful for exploration, but the parity target is the Databricks App, not notebook-only interaction.
- The existing external Dash deployment should remain available until Databricks App parity is signed off.
