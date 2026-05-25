# Dashboard Agents Guide

## Purpose
This repo is a deploy-ready CHEC dashboard using **Dash + FastAPI**.

- Dash: UI layout, charts, user interactions, callback orchestration.
- FastAPI: endpoint contracts, heavy data processing, inference orchestration.

Tabs/features in scope:
- Map (base mode)
- Probability distributions
- SAIDI/SAIFI summary by circuit and date window

## Architecture

```text
Dash Frontend
  -> API_BASE_URL
FastAPI Backend (/health, /ready, /data, /inference)
  -> services/data_service.py
  -> services/inference_service.py
  -> services/model_loader.py
  -> services/cache.py
```

## Key Modules
- `src/chec_dashboard/dash_app/api_client.py`: Dash->API HTTP calls.
- `src/chec_dashboard/pages/probability_page.py`: probability callbacks (API-driven metadata + inference orchestration).
- `src/chec_dashboard/api/routes/data.py`: map/summary/probability + probability metadata actions.
- `src/chec_dashboard/api/routes/health.py`: liveness/readiness checks.
- `src/chec_dashboard/services/inference_service.py`: backend switch + retries + normalized errors.

## Run Commands
- FastAPI: `python run_api.py`
- Dash: `API_BASE_URL=http://127.0.0.1:8000 python run_dash.py`
- Compatibility entrypoint: `python run.py`
- Tests: `pytest -q`
- Docker compose: `docker compose up --build`
- Compose smoke: `./scripts/compose_smoke.sh`

## API Contract Notes
- `GET /health`: liveness.
- `GET /ready`: readiness (required files + backend config/model load).
- `GET /data`: lightweight metadata.
- `POST /data` modes:
  - `map`
  - `summary`
  - `probability`
  - `probability_metadata` (`criteria`, `columns`, `filter_options`).
- `POST /inference`: returns payload with `request_id` and header `X-Request-ID`.

## Guardrails
- Keep heavy logic in FastAPI/services, not Dash callbacks.
- Keep CHEC visual identity (`#00782b` family) unless explicitly changed.
- Never hardcode cloud tokens/keys.
- Keep worker counts conservative by default (`1`) until memory/load baselines are validated.

## Data Contract
Default data directory: `../data`.

Required files:
- Map: `TRAFOS.pkl`, `APOYOS.pkl`, `SWITCHES.pkl`, `REDMT.pkl`, `SuperEventos_Criticidad_AguasAbajo_CODEs.pkl`
- Probability: `Eventos_interruptor.pkl`, `Eventos_tramo_linea.pkl`, `Eventos_transformador.pkl`

## Memory/Performance Notes
- Dataset/model cache is process-local; each worker duplicates memory.
- Summary payloads are guardrailed by `MAX_SUMMARY_POINTS`.
- Map HTML payloads are guardrailed by `MAX_MAP_HTML_CHARS`.
- Only cache safe shared computations.

## Output Artifacts
- Probability graph images are written to `outputs/`.
- `outputs/` stays out of source control.
