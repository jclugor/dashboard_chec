# CHEC Dashboard (Dash + FastAPI + Databricks App)

The project now supports two runtime patterns:
- Dash: UI, visualization, callback orchestration.
- FastAPI: data/inference APIs, validation, preprocessing, backend orchestration.
- Databricks App: the same Dash UI running with an in-process Databricks-backed data provider.

## Architecture (Text Diagram)

```text
[Dash Frontend]
  - layout/charts/user interactions
  - lightweight callback orchestration
  - contextual technical chatbot tab
          |\
          | \ in-process provider
          |  \
          |   v
          | [Databricks SQL / Unity Catalog]
          |
          | HTTP (API_BASE_URL)
          v
[FastAPI Backend]
  - GET /health
  - GET /ready
  - GET /data      (light metadata)
  - POST /data     (map/summary/probability heavy payloads)
  - POST /inference
  - GET /chatbot/status
  - POST /chatbot/context-options
  - POST /chatbot/assess
          |
          v
[Services Layer]
  - data_service.py
  - inference_service.py
  - model_loader.py
  - chatbot_service.py
  - cache.py
```

## Dashboard Features

- Map explorer for circuits, network elements, and event layers.
- Probability distributions for interruption event families.
- SAIDI/SAIFI summary by circuit and date window.
- Asistente técnico con recuperación documental. Esta pestaña funciona como una herramienta de análisis guiado en español, no como un chat general de respuesta abierta. La persona usuaria puede analizar una vista filtrada del tablero, un evento específico o un elemento de red desde confiabilidad, cumplimiento basado en evidencia y mantenimiento. El asistente recibe contexto estructurado como resúmenes de indicadores, metadatos de eventos o activos, circuito, municipio, ventana temporal y variables de condiciones externas. Recupera requisitos técnicos relevantes desde documentos indexados y explica el estado observado, banderas de evidencia, posibles factores externos u operativos y revisiones recomendadas.

## Project Structure

```text
dashboard/
  src/chec_dashboard/
    core/
    dash_app/
    api/
    pages/
    services/
  tests/
  docs/
  scripts/
  run_dash.py
  run_api.py
  docker-compose.yml
```

## Environment Variables

Use `.env.example` as baseline.

Core:
- `ENVIRONMENT`, `LOG_LEVEL`, `DEBUG`
- `DATA_BACKEND` (`pickle|databricks_sql`)
- `API_TRANSPORT` (`http|inproc`)
- `HOST`, `PORT`, `API_HOST`, `API_PORT`, `API_BASE_URL`
- `DATA_DIR`, `OUTPUT_DIR`, `CACHE_ENABLED`

Inference:
- `MODEL_BACKEND` (`mock|local|azure_ml|databricks`)
- `REQUEST_TIMEOUT_SECONDS`
- `INFERENCE_HTTP_RETRIES`
- `INFERENCE_RETRY_BACKOFF_MS`
- `DATABRICKS_HOST`, `DATABRICKS_TOKEN`, `DATABRICKS_MODEL_ENDPOINT`
- `AZURE_ML_ENDPOINT`, `AZURE_ML_KEY`

Technical chatbot / RAG assessment:
- `CHATBOT_ENABLED` (`true|false`; the tab loads either way and reports the configured state)
- `GEMINI_API_KEY` (placeholder only; provide through environment variables or a secret manager)
- `GEMINI_MODEL` (defaults to `gemini-2.5-flash`)
- `CHATBOT_CORPUS_DIR` (local/dev explicit directory containing `chunks.jsonl` and chatbot manifests)
- `CHATBOT_CORPUS_VOLUME_DIR` (Databricks App resource path exposed with `valueFrom`)
- `CHATBOT_CORPUS_SUBDIR` (defaults to `chatbot_corpus`)
- `CHATBOT_RETRIEVAL_TOP_K`
- `CHATBOT_MAX_CONTEXT_CHARS`

Databricks SQL parity runtime:
- `DATABRICKS_SQL_WAREHOUSE_ID`
- `DATABRICKS_SQL_HTTP_PATH` (optional; derived from warehouse id when omitted)
- `DATABRICKS_CATALOG_NAME`
- `DATABRICKS_GOLD_SCHEMA`
- `DATABRICKS_SILVER_SCHEMA`

Payload guardrails:
- `MAX_SUMMARY_POINTS`
- `MAX_MAP_HTML_CHARS`

## API Contract

### Health
- `GET /health`: liveness
- `GET /ready`: readiness checks (data backend + inference backend)

### Data
- `GET /data?section=map|summary|probability|all`
- `POST /data` modes:
  - `map`
  - `summary`
  - `probability`
  - `probability_metadata` with actions:
    - `criteria`
    - `columns`
    - `filter_options`

### Inference
- `POST /inference`
- Response includes `request_id` and `X-Request-ID` header for traceability.

### Technical Chatbot
- `GET /chatbot/status`: reports feature, Gemini, and corpus readiness.
- `POST /chatbot/context-options`: returns selectable events or network elements from the dashboard data context.
- `POST /chatbot/assess`: retrieves technical document chunks and, when Gemini is configured, generates the Spanish technical assessment.

## Chatbot Data Roadmap

La primera implementación del asistente usa solo los datos existentes del tablero CHEC y el corpus técnico desplegado. Buenas fuentes futuras para análisis más ricos de confiabilidad y cumplimiento en Colombia incluyen:
- SUI/Superservicios for official utility-reported quality data and benchmarking.
- CREG and MinEnergía for versioned regulatory updates, especially CREG 015/2018 and RETIE Resolución 40117 of April 2, 2024.
- IDEAM DHIME for official hydrometeorological station series.
- XM/SIMEM/Sinergox for SIN/MEM operating context, demand, hydrology, restrictions, and market signals.
- IGAC/DANE for official boundaries, rural/urban context, terrain, cartography, and socioeconomic overlays.
- SGC/UNGRD for landslide, hazard, and emergency-event overlays in mountainous service areas.

## Local Setup

```bash
cd /home/jclugor/unal/CHEC/dashboard
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run FastAPI

```bash
cd /home/jclugor/unal/CHEC/dashboard
source .venv/bin/activate
python run_api.py
```

## Run Dash

```bash
cd /home/jclugor/unal/CHEC/dashboard
source .venv/bin/activate
export API_BASE_URL=http://127.0.0.1:8000
python run_dash.py
```

## Run Dash Against Databricks Data

```bash
cd /home/jclugor/unal/CHEC/dashboard
source .venv/bin/activate
export DATA_BACKEND=databricks_sql
export API_TRANSPORT=inproc
export DATABRICKS_SQL_WAREHOUSE_ID=4437a6195e05c59c
export DATABRICKS_CATALOG_NAME=chec_dbx_demo
python run_dash.py
```

## Tests

```bash
cd /home/jclugor/unal/CHEC/dashboard
source .venv/bin/activate
pytest -q
```

## Lightweight Load Validation

Included tests run concurrent map/summary requests via FastAPI `TestClient`:
- `tests/test_load_light.py`

## Docker Compose

```bash
cd /home/jclugor/unal/CHEC/dashboard
docker compose up --build
```

## Compose Smoke Test

Runs API+Dash happy paths (map/summary/probability):

```bash
cd /home/jclugor/unal/CHEC/dashboard
./scripts/compose_smoke.sh
```

## CI Pipeline

GitHub Actions workflow:
- run tests (`pytest -q`)
- import smoke (`run_dash`, `run_api`, `run`, `wsgi`)
- Docker build smoke

File: `.github/workflows/ci.yml`

## Deployment Notes

- Start with conservative workers (`1`) for both Dash and API.
- Each worker can duplicate dataset/model memory due process-local caching.
- Prefer Azure ML or Databricks Model Serving for large model hosting.
- Keep cloud tokens/secrets in environment variables or secret managers.
- Provide the Gemini key through environment variables or platform secrets only; never commit real keys or generated private document indexes.
- Azure Container Apps runbook (from zero account to public URL): `docs/AZURE_CONTAINER_APPS_DEPLOYMENT.md`
- Databricks is not required for the first containerized web demo deployment.
- Databricks App parity runbook: `docs/phase35_databricks_app_parity.md`

## Memory and Performance Notes

- Dash callbacks no longer load probability datasets directly.
- API returns UI-focused payloads, not raw full datasets.
- Summary responses enforce point limits for payload safety.
- Map payloads enforce max HTML size guardrail.
