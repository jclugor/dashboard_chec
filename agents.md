# Dashboard Agents Guide

## Purpose
This repo is a deploy-ready CHEC dashboard using **Dash + FastAPI**.

- Dash: UI layout, charts, user interactions, callback orchestration.
- FastAPI: endpoint contracts, heavy data processing, inference orchestration.

Tabs/features in scope:
- Map (base mode)
- Probability distributions
- SAIDI/SAIFI summary by circuit and date window
- Technical chatbot / RAG assessment from a selected event or network element

## Architecture

```text
Dash Frontend
  -> API_BASE_URL
FastAPI Backend (/health, /ready, /data, /inference)
  -> services/data_service.py
  -> services/inference_service.py
  -> services/chatbot_service.py
  -> services/model_loader.py
  -> services/cache.py
```

### Governed Simulator Spine

The chatbot now accepts optional `analysis_stage` values for internal/API workflows while preserving the existing `briefing_type` behavior. Stage-aware execution stays inside the same Dash/FastAPI service runtime:

```text
Selected dashboard context
  -> agent_context_service
  -> skill_service resolves briefing_type + optional analysis_stage
  -> agent_routing_service runs only approved read-only tools
  -> capability_registry marks available / partial / unavailable behavior
  -> prompt_service renders guided or stage prompt with contract metadata
  -> llm_output_validation_service validates citations, claims, and skeleton safety
  -> conversation_service + observability_service persist additive metadata
```

Capability maturity:
- `existing_integrated`: structured context, local/AI Search retrieval, time-series interpretability, skills, prompt fallback, observability shell.
- `implement_now`: stage skills/prompts/contracts, capability registry, evidence policy, citation validation, LLM output validation, metadata persistence.
- `skeleton_only`: model evidence without explicit features, absent feature masks, three-way synthesis beyond evidence, intervention candidates, what-if simulation, evidence report context.
- `deferred_external_dependency`: production Databricks model endpoint behavior, production feature-vector builder, approved intervention registry, production report artifact storage.

## Key Modules
- `src/chec_dashboard/dash_app/api_client.py`: Dash->API HTTP calls.
- `src/chec_dashboard/pages/probability_page.py`: probability callbacks (API-driven metadata + inference orchestration).
- `src/chec_dashboard/pages/chatbot_page.py`: Spanish contextual technical chatbot UI.
- `src/chec_dashboard/api/routes/data.py`: map/summary/probability + probability metadata actions.
- `src/chec_dashboard/api/routes/chatbot.py`: chatbot status, context options, and assessment routes.
- `src/chec_dashboard/api/routes/health.py`: liveness/readiness checks.
- `src/chec_dashboard/services/inference_service.py`: backend switch + retries + normalized errors.
- `src/chec_dashboard/services/chatbot_service.py`: corpus loading, lexical retrieval, context lookup, prompt assembly, and Gemini calls.

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
- `GET /chatbot/status`: reports enabled, Gemini, and corpus readiness.
- `POST /chatbot/context-options`: returns events or network elements for the selected dashboard context.
- `POST /chatbot/assess`: returns a Spanish technical assessment and document citations.

## Guardrails
- Keep heavy logic in FastAPI/services, not Dash callbacks.
- Keep RAG retrieval, prompt assembly, Gemini calls, and document-index access in service/API layers, not Dash callbacks.
- Keep CHEC visual identity (`#00782b` family) unless explicitly changed.
- Never hardcode cloud tokens/keys.
- Never commit Gemini API keys or generated private document indexes.
- Keep dashboard user-facing chatbot copy in Spanish, even when repo docs remain in English.
- Prefer structured context payloads for event/asset metadata, indicator values, circuit, municipio, time window, and external conditions instead of concatenating ad hoc prompt strings in callbacks.
- Do not invent predictions, masks, simulations, intervention candidates, citations, or report artifacts when a capability is skeleton-only or not configured; return structured Spanish unavailable/partial metadata instead.
- Do not add LangChain/LlamaIndex or arbitrary SQL/Python/tool execution paths for the governed simulator.
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
