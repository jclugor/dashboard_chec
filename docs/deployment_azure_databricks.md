# Deployment Runbook: Azure + Databricks

## Topology
- Deploy Dash and FastAPI as separate services (App Service or Container Apps).
- Keep Dash configured with `API_BASE_URL` pointing to FastAPI.
- Prefer external model hosting (Azure ML or Databricks Model Serving) for larger models.

## Baseline Worker Settings
- Start with:
  - `GUNICORN_WORKERS=1` (Dash)
  - `UVICORN_WORKERS=1` (FastAPI)
- Reason: dataset/model caches are process-local and each worker duplicates memory.
- Scale workers only after load + memory baselines are measured.

## Health and Readiness
- Liveness: `GET /health`
- Readiness: `GET /ready`
  - checks required dataset files
  - checks inference backend configuration and local model load (if `MODEL_BACKEND=local`)

## Inference Backends

### Mock/Local
- `MODEL_BACKEND=mock` for local dev and smoke testing.
- `MODEL_BACKEND=local` when serving an in-process model via `model_loader.py`.

### Azure ML
- Set:
  - `MODEL_BACKEND=azure_ml`
  - `AZURE_ML_ENDPOINT`
  - `AZURE_ML_KEY`
- Requests include `X-Request-ID` for traceability.

### Databricks Model Serving
- Set:
  - `MODEL_BACKEND=databricks`
  - `DATABRICKS_HOST`
  - `DATABRICKS_TOKEN`
  - `DATABRICKS_MODEL_ENDPOINT`
- Keep all secrets in environment/secret stores, never in code.

## Reliability Controls
- Tune:
  - `REQUEST_TIMEOUT_SECONDS`
  - `INFERENCE_HTTP_RETRIES`
  - `INFERENCE_RETRY_BACKOFF_MS`
- API maps inference timeout/backend failures to explicit HTTP statuses.

## Payload and Cache Guardrails
- `MAX_SUMMARY_POINTS` limits summary response size.
- `MAX_MAP_HTML_CHARS` protects against oversized Folium payloads.
- Cache only safe shared computations (`CACHE_ENABLED=true`).

## Validation Checklist
1. `GET /health` returns `status=ok`.
2. `GET /ready` returns HTTP 200 before exposing traffic.
3. Dash root loads and can call map/summary/probability flows.
4. Inference requests include `X-Request-ID` in responses and logs.
5. Memory baseline validated at worker count = 1 before scale-out.
