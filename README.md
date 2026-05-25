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
          |
          v
[Services Layer]
  - data_service.py
  - inference_service.py
  - model_loader.py
  - cache.py
```

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
- Azure Container Apps runbook (from zero account to public URL): `docs/AZURE_CONTAINER_APPS_DEPLOYMENT.md`
- Databricks is not required for the first containerized web demo deployment.
- Databricks App parity runbook: `docs/phase35_databricks_app_parity.md`

## Memory and Performance Notes

- Dash callbacks no longer load probability datasets directly.
- API returns UI-focused payloads, not raw full datasets.
- Summary responses enforce point limits for payload safety.
- Map payloads enforce max HTML size guardrail.
