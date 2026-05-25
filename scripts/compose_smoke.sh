#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

cleanup() {
  docker compose down -v || true
}
trap cleanup EXIT

docker compose up -d --build

wait_for() {
  local url="$1"
  local label="$2"
  local attempts=40
  local sleep_seconds=2

  for _ in $(seq 1 "$attempts"); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "[ok] $label"
      return 0
    fi
    sleep "$sleep_seconds"
  done

  echo "[error] timed out waiting for $label at $url"
  return 1
}

wait_for "http://127.0.0.1:8000/health" "API /health"
wait_for "http://127.0.0.1:8000/ready" "API /ready"
wait_for "http://127.0.0.1:8050" "Dash root"

python - <<'PY'
from __future__ import annotations

import json
import urllib.request

BASE = "http://127.0.0.1:8000"


def get_json(url: str):
    with urllib.request.urlopen(url, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))


def post_json(path: str, payload: dict):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


map_meta = get_json(f"{BASE}/data?section=map")["map"]
summary_meta = get_json(f"{BASE}/data?section=summary")["summary"]
prob_meta = get_json(f"{BASE}/data?section=probability")["probability"]

map_date = map_meta.get("default_date") or (map_meta.get("dates") or [None])[0]
map_mun = map_meta.get("default_municipio") or (map_meta.get("municipios") or [None])[0]
if not map_date or not map_mun:
    raise SystemExit("Map metadata missing default values")

summary_start = summary_meta.get("default_start")
summary_end = summary_meta.get("default_end")
if not summary_start or not summary_end:
    raise SystemExit("Summary metadata missing default window")

criteria_options = [opt for opt in prob_meta.get("criteria_options", []) if opt.get("value")]
if not criteria_options:
    raise SystemExit("Probability metadata has no selectable criteria")
criteria = criteria_options[0]["value"]

map_response = post_json(
    "/data",
    {
        "mode": "map",
        "map": {
            "selected_period": map_date,
            "selected_municipio": map_mun,
            "day": 1,
        },
    },
)
assert map_response["mode"] == "map"

summary_response = post_json(
    "/data",
    {
        "mode": "summary",
        "summary": {
            "start_date": summary_start,
            "end_date": summary_end,
            "circuito": summary_meta.get("default_circuit"),
            "metric_mode": "BOTH",
        },
    },
)
assert summary_response["mode"] == "summary"

columns_response = post_json(
    "/data",
    {
        "mode": "probability_metadata",
        "probability_metadata": {
            "action": "columns",
            "criteria": criteria,
        },
    },
)
columns = columns_response["probability_metadata"].get("columns", [])
if not columns:
    raise SystemExit("Probability columns metadata is empty")

target_column = "duracion_h" if "duracion_h" in columns else columns[0]

prob_response = post_json(
    "/data",
    {
        "mode": "probability",
        "probability": {
            "criteria": criteria,
            "target_column": target_column,
            "filters": [],
        },
    },
)
assert prob_response["mode"] == "probability"

print("compose smoke test passed")
PY

printf '\nCompose smoke test completed successfully.\n'
