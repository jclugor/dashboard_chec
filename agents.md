# Dashboard Agents Guide

## Purpose
This repo is a minimal, deploy-ready copy of the CHEC dashboard with three focused tabs:
- Map (base mode only)
- Probability distributions
- SAIDI/SAIFI summary by circuit and date window

## Project Layout
- `src/chec_dashboard/app.py`: app factory, shell wiring, page switching.
- `src/chec_dashboard/config.py`: runtime config (`DATA_DIR`, `PORT`, `DEBUG`, `HOST`, `OUTPUT_DIR`).
- `src/chec_dashboard/pages/map_page.py`: map UI and callbacks.
- `src/chec_dashboard/pages/probability_page.py`: probability UI and callbacks.
- `src/chec_dashboard/services/map_service.py`: map data load/filter/render.
- `src/chec_dashboard/services/probability_service.py`: probability data, filtering, graph generation.

## Run Commands
- Local dev: `python run.py`
- Prod-style: `PYTHONPATH=src gunicorn --bind 0.0.0.0:8050 wsgi:server`
- Quick validation: `python -m compileall src run.py wsgi.py`

## Data Contract
By default data is loaded from `../data` relative to project root.

Required map files:
- `TRAFOS.pkl`
- `APOYOS.pkl`
- `SWITCHES.pkl`
- `REDMT.pkl`
- `SuperEventos_Criticidad_AguasAbajo_CODEs.pkl`

Required probability files:
- `Eventos_interruptor.pkl`
- `Eventos_tramo_linea.pkl`
- `Eventos_transformador.pkl`

## Guardrails For Future Changes
- Keep the project limited to the current tab scope unless requested.
- Keep CHEC color identity (`#00782b` and related greens).
- Do not reintroduce heavy unused dependencies (torch, tabnet, geopandas, langchain stack, etc.).
- Keep map scope as base mode only (no criticidad/recommendation flow).
- Keep graph download manual (download button only, never auto-trigger).

## Output Artifacts
- Generated probability images are written to `outputs/`.
- `outputs/` is intentionally ignored in git.
