# CHEC Dashboard (Minimal 2-Tab)

Minimal, deploy-ready Dash clone with:
- Map tab (base mode only)
- Probability distributions tab (full current filtering flow)
- SAIDI/SAIFI summary tab by circuit and time window

This project is isolated from `Dashboard_CHEC` and reads shared datasets from `../data` by default.

## Project structure

```text
dashboard/
  src/chec_dashboard/
    app.py
    config.py
    pages/
    services/
    ui/
    assets/
  run.py
  wsgi.py
  requirements.txt
  Dockerfile
```

## Environment variables

- `DATA_DIR` (default: `../data`)
- `PORT` (default: `8050`)
- `DEBUG` (default: `false`)
- `HOST` (default: `0.0.0.0`)
- `OUTPUT_DIR` (default: `./outputs`)

## Local run

```bash
cd /home/jclugor/unal/CHEC/dashboard
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python run.py
```

Open `http://127.0.0.1:8050`.

## Production run (gunicorn)

```bash
cd /home/jclugor/unal/CHEC/dashboard
PYTHONPATH=src gunicorn --bind 0.0.0.0:8050 wsgi:server
```

## Docker

```bash
cd /home/jclugor/unal/CHEC/dashboard
docker build -t chec-dashboard-minimal .
docker run --rm -p 8050:8050 -e PORT=8050 -e DATA_DIR=/app/data -v /home/jclugor/unal/CHEC/data:/app/data chec-dashboard-minimal
```
