from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
import hashlib
import json
from typing import Any
from pathlib import Path

import pandas as pd

from chec_dashboard.services.time_series_interpretability_service import (
    CriticalityThresholds,
    build_circuit_history_12m_payload,
    build_summary_interpretability_payload,
)


SUMMARY_FILE = "SuperEventos_Criticidad_AguasAbajo_CODEs.pkl"
REQUIRED_COLUMNS = {"inicio", "cto_equi_ope"}
METRIC_COLUMNS = ["UITI", "UITI_VANO", "EVENT_COUNT", "USERS", "DURATION_RAW"]


def _round(value: Any, digits: int = 4) -> float:
    coerced = pd.to_numeric(value, errors="coerce")
    if pd.isna(coerced):
        return 0.0
    return round(float(coerced), digits)


@dataclass(frozen=True)
class SummaryDataset:
    frame: pd.DataFrame
    min_date: date
    max_date: date


def _validate_data_file(data_dir: Path) -> Path:
    file_path = data_dir / SUMMARY_FILE
    if not file_path.exists():
        raise FileNotFoundError(
            f"Missing required summary data file in '{data_dir}': {SUMMARY_FILE}"
        )
    return file_path


@lru_cache(maxsize=1)
def load_summary_dataset(data_dir_raw: str) -> SummaryDataset:
    # Cached once per Python process. Multi-worker deployments still duplicate
    # this memory per worker process.
    data_dir = Path(data_dir_raw)
    file_path = _validate_data_file(data_dir)

    frame = pd.read_pickle(file_path).copy()
    missing_cols = REQUIRED_COLUMNS.difference(frame.columns)
    if missing_cols:
        raise ValueError(
            f"Summary dataset is missing required columns: {', '.join(sorted(missing_cols))}"
        )

    frame["inicio"] = pd.to_datetime(frame["inicio"], errors="coerce")
    frame = frame.dropna(subset=["inicio", "cto_equi_ope"]).copy()
    frame["cto_equi_ope"] = frame["cto_equi_ope"].astype(str).str.strip()
    frame = frame[frame["cto_equi_ope"] != ""].copy()

    if "UITI" not in frame.columns:
        frame["UITI"] = 0.0
    if "UITI_VANO" not in frame.columns:
        frame["UITI_VANO"] = frame["UITI"]
    if "EVENT_COUNT" not in frame.columns:
        frame["EVENT_COUNT"] = 1.0
    if "USERS" not in frame.columns:
        frame["USERS"] = frame["cnt_usus"] if "cnt_usus" in frame.columns else 0.0
    if "DURATION_RAW" not in frame.columns:
        frame["DURATION_RAW"] = frame["duracion_h"] if "duracion_h" in frame.columns else 0.0
    for column in METRIC_COLUMNS:
        frame[column] = pd.to_numeric(frame[column], errors="coerce").fillna(0.0)
    frame["fecha_dia"] = frame["inicio"].dt.floor("D")

    if frame.empty:
        raise ValueError("Summary dataset has no valid records after normalization.")

    min_date = frame["fecha_dia"].min().date()
    max_date = frame["fecha_dia"].max().date()
    return SummaryDataset(frame=frame, min_date=min_date, max_date=max_date)


def get_circuit_options(dataset: SummaryDataset) -> list[str]:
    return sorted(dataset.frame["cto_equi_ope"].dropna().astype(str).unique().tolist())


def get_default_window(dataset: SummaryDataset, days: int = 180) -> tuple[date, date]:
    end_date = dataset.max_date
    start_candidate = end_date - timedelta(days=max(days - 1, 0))
    start_date = max(dataset.min_date, start_candidate)
    return start_date, end_date


def coerce_window(
    dataset: SummaryDataset,
    start_date_raw: str | None,
    end_date_raw: str | None,
) -> tuple[date, date]:
    default_start, default_end = get_default_window(dataset)
    start_date = (
        pd.to_datetime(start_date_raw, errors="coerce").date()
        if start_date_raw
        else default_start
    )
    end_date = (
        pd.to_datetime(end_date_raw, errors="coerce").date()
        if end_date_raw
        else default_end
    )
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    start_date = max(start_date, dataset.min_date)
    end_date = min(end_date, dataset.max_date)
    return start_date, end_date


def filter_summary_data(
    dataset: SummaryDataset,
    circuito: str | None,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    frame = dataset.frame
    filtered = frame[
        (frame["fecha_dia"].dt.date >= start_date)
        & (frame["fecha_dia"].dt.date <= end_date)
    ]
    if circuito:
        filtered = filtered[filtered["cto_equi_ope"] == circuito]
    return filtered.copy()


def aggregate_daily(
    filtered: pd.DataFrame,
    start_date: date,
    end_date: date,
) -> pd.DataFrame:
    date_index = pd.date_range(start=start_date, end=end_date, freq="D")
    if filtered.empty:
        grouped = pd.DataFrame(index=date_index, columns=METRIC_COLUMNS).fillna(0.0)
    else:
        grouped = (
            filtered.groupby("fecha_dia")[METRIC_COLUMNS]
            .sum()
            .reindex(date_index, fill_value=0.0)
        )
    grouped.index.name = "fecha_dia"
    return grouped.reset_index()


def compute_kpis(filtered: pd.DataFrame) -> dict[str, float | int]:
    return {
        "uiti_total": float(filtered["UITI"].sum()) if not filtered.empty else 0.0,
        "uiti_vano_total": float(filtered["UITI_VANO"].sum()) if not filtered.empty else 0.0,
        "users_affected_total": float(filtered["USERS"].sum()) if not filtered.empty else 0.0,
        "duration_raw_total": float(filtered["DURATION_RAW"].sum()) if not filtered.empty else 0.0,
        "event_count": int(len(filtered)),
    }


def _event_detail_frame(filtered: pd.DataFrame) -> pd.DataFrame:
    if filtered.empty:
        return pd.DataFrame()
    frame = filtered.copy()
    frame = _ensure_event_ids(frame)
    rename_map = {
        "inicio": "inicio_ts",
        "fin": "fin_ts",
        "MUN": "municipio",
        "cto_equi_ope": "circuito",
        "DURATION_RAW": "duration_raw",
        "USERS": "users_affected",
    }
    for source, target in rename_map.items():
        if source in frame.columns and target not in frame.columns:
            frame[target] = frame[source]
    if "event_count" not in frame.columns:
        frame["event_count"] = 1
    if "fecha_dia" not in frame.columns:
        frame["fecha_dia"] = pd.to_datetime(frame["inicio_ts"], errors="coerce").dt.floor("D")
    for column in ("UITI", "UITI_VANO", "duration_raw", "users_affected"):
        if column not in frame.columns:
            frame[column] = 0.0
    return frame


def _event_id_payload(row: pd.Series) -> dict[str, Any]:
    def _first_text(*keys: str) -> str:
        for key in keys:
            if key not in row.index:
                continue
            value = row.get(key)
            try:
                if value is None or pd.isna(value):
                    continue
            except (TypeError, ValueError):
                if value is None:
                    continue
            text = str(value).strip()
            if text:
                return text
        return ""

    return {
        "inicio": _first_text("inicio", "inicio_ts"),
        "cto_equi_ope": _first_text("cto_equi_ope", "circuito"),
        "equipo_ope": _first_text("equipo_ope"),
        "causa": _first_text("causa"),
        "UITI": _first_text("UITI"),
        "UITI_VANO": _first_text("UITI_VANO"),
    }


def _generated_event_id(row: pd.Series) -> str:
    digest = hashlib.sha1(
        json.dumps(_event_id_payload(row), sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]
    return f"local-event-{digest}"


def _ensure_event_ids(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    result = frame.copy()
    if "event_id" not in result.columns:
        result["event_id"] = None
    result["event_id"] = result["event_id"].astype("object")
    missing = result["event_id"].isna() | (result["event_id"].astype(str).str.strip() == "")
    if missing.any():
        result.loc[missing, "event_id"] = result.loc[missing].apply(_generated_event_id, axis=1)
    result["event_id"] = result["event_id"].astype(str)
    return result


def _event_value(row: pd.Series, candidates: list[str]) -> Any:
    for column in candidates:
        if column in row.index:
            value = row.get(column)
            if value is not None and not pd.isna(value) and str(value).strip() != "":
                return value
    return None


def _event_record(row: pd.Series) -> dict[str, Any]:
    inicio = _event_value(row, ["inicio_ts", "inicio", "fecha_dia"])
    fecha_dia = _event_value(row, ["fecha_dia"])
    if fecha_dia is None and inicio is not None:
        parsed = pd.to_datetime(inicio, errors="coerce")
        fecha_dia = None if pd.isna(parsed) else parsed.date().isoformat()
    elif isinstance(fecha_dia, (pd.Timestamp, datetime)):
        fecha_dia = pd.to_datetime(fecha_dia).date().isoformat()
    event_id = str(_event_value(row, ["event_id"]) or _generated_event_id(row))
    return {
        "event_id": event_id,
        "label": _event_label(row, event_id=event_id),
        "fecha_dia": None if fecha_dia is None else str(fecha_dia),
        "inicio_ts": None if inicio is None else str(inicio),
        "fin_ts": None if _event_value(row, ["fin_ts", "fin"]) is None else str(_event_value(row, ["fin_ts", "fin"])),
        "circuito": None if _event_value(row, ["circuito", "cto_equi_ope"]) is None else str(_event_value(row, ["circuito", "cto_equi_ope"])),
        "municipio": None if _event_value(row, ["municipio", "MUN"]) is None else str(_event_value(row, ["municipio", "MUN"])),
        "causa": None if _event_value(row, ["causa"]) is None else str(_event_value(row, ["causa"])),
        "event_family": None if _event_value(row, ["event_family", "tipo_equi_ope"]) is None else str(_event_value(row, ["event_family", "tipo_equi_ope"])),
        "equipo_ope": None if _event_value(row, ["equipo_ope", "CODE"]) is None else str(_event_value(row, ["equipo_ope", "CODE"])),
        "tipo_equi_ope": None if _event_value(row, ["tipo_equi_ope"]) is None else str(_event_value(row, ["tipo_equi_ope"])),
        "tipo_elemento": None if _event_value(row, ["tipo_elemento"]) is None else str(_event_value(row, ["tipo_elemento"])),
        "duration_raw": _round(_event_value(row, ["duration_raw", "DURATION_RAW", "duracion_h"]), 2),
        "uiti": _round(_event_value(row, ["uiti", "UITI", "uiti_total"])),
        "uiti_vano": _round(_event_value(row, ["uiti_vano", "UITI_VANO", "uiti_vano_total"])),
        "users_affected": _round(_event_value(row, ["users_affected", "USERS", "cnt_usus"]), 2),
    }


def _event_label(row: pd.Series, *, event_id: str) -> str:
    inicio = _event_value(row, ["inicio_ts", "inicio", "fecha_dia"])
    parsed = pd.to_datetime(inicio, errors="coerce")
    inicio_text = parsed.strftime("%Y-%m-%d %H:%M") if not pd.isna(parsed) else str(inicio or "sin fecha")
    equipo = _event_value(row, ["equipo_ope", "CODE"]) or "Evento"
    causa = _event_value(row, ["causa"]) or "Sin causa"
    uiti_vano = _round(_event_value(row, ["UITI_VANO", "uiti_vano", "uiti_vano_total"]))
    return f"{inicio_text} | {equipo} | {causa} | UITI vano {uiti_vano:.4f} | {event_id}"


def event_options(
    dataset: SummaryDataset,
    start_date_raw: str | None,
    end_date_raw: str | None,
    circuito: str | None,
    *,
    limit: int = 200,
) -> dict[str, Any]:
    start_date, end_date = coerce_window(dataset, start_date_raw, end_date_raw)
    filtered = _ensure_event_ids(filter_summary_data(dataset, circuito, start_date, end_date))
    safe_limit = max(1, min(int(limit), 500))
    if filtered.empty:
        return {
            "events": [],
            "default_event_id": None,
            "status_text": "No se encontraron eventos para la ventana y circuito seleccionados.",
        }
    work = filtered.copy()
    work["_impact"] = pd.to_numeric(work.get("UITI_VANO", work.get("UITI", 0.0)), errors="coerce").fillna(0.0)
    work = work.sort_values(["fecha_dia", "_impact"], ascending=[True, False]).head(safe_limit)
    events = [_event_record(row) for _, row in work.iterrows()]
    return {
        "events": events,
        "default_event_id": None,
        "status_text": f"Se encontraron {len(events)} eventos para la ventana y circuito seleccionados.",
    }


def event_history_12m(dataset: SummaryDataset, selected_event: dict[str, Any]) -> dict[str, Any]:
    event_date_raw = selected_event.get("fecha_dia") or selected_event.get("inicio_ts")
    circuit = selected_event.get("circuito")
    event_date = pd.to_datetime(event_date_raw, errors="coerce")
    if pd.isna(event_date) or not circuit:
        return {"available": False, "reason": "missing_event_date_or_circuit"}
    end_date = event_date.date()
    start_date = max(dataset.min_date, end_date - timedelta(days=365))
    filtered = filter_summary_data(dataset, str(circuit), start_date, end_date)
    kpis = compute_kpis(filtered)
    return {
        "available": True,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "event_count": int(kpis["event_count"]),
        "uiti_total": _round(kpis.get("uiti_total")),
        "uiti_vano_total": _round(kpis.get("uiti_vano_total")),
        "duration_raw_total": _round(kpis.get("duration_raw_total"), 2),
        "users_affected_total": _round(kpis.get("users_affected_total"), 2),
    }


def selected_event_record(
    dataset: SummaryDataset,
    start_date_raw: str | None,
    end_date_raw: str | None,
    circuito: str | None,
    selected_event_id: str | None,
) -> dict[str, Any] | None:
    if not selected_event_id:
        return None
    start_date, end_date = coerce_window(dataset, start_date_raw, end_date_raw)
    filtered = _ensure_event_ids(filter_summary_data(dataset, circuito, start_date, end_date))
    if filtered.empty:
        return None
    matches = filtered[filtered["event_id"].astype(str) == str(selected_event_id)]
    if matches.empty:
        return None
    record = _event_record(matches.iloc[0])
    record["circuit_history_12m"] = event_history_12m(dataset, record)
    return record


def _daily_attribution_frame(event_frame: pd.DataFrame) -> pd.DataFrame:
    if event_frame.empty:
        return pd.DataFrame()
    frame = event_frame.copy()
    for column in ("causa", "event_family", "tipo_equi_ope", "equipo_ope", "circuito", "municipio"):
        if column not in frame.columns:
            frame[column] = "Sin dato"
    grouped = (
        frame.groupby(
            ["fecha_dia", "circuito", "municipio", "causa", "event_family", "tipo_equi_ope", "equipo_ope"],
            dropna=False,
        )
        .agg(
            event_count=("event_count", "sum"),
            uiti_total=("UITI", "sum"),
            uiti_vano_total=("UITI_VANO", "sum"),
            duration_raw_total=("duration_raw", "sum"),
            users_affected_total=("users_affected", "sum") if "users_affected" in frame.columns else ("event_count", "sum"),
        )
        .reset_index()
    )
    return grouped


def get_summary_interpretability_payload(
    dataset: SummaryDataset,
    start_date_raw: str | None,
    end_date_raw: str | None,
    circuito: str | None,
    metric_key: str | None,
    *,
    max_points: int = 5,
    thresholds: CriticalityThresholds | None = None,
    selected_event_id: str | None = None,
) -> dict[str, Any]:
    _ = selected_event_id
    start_date, end_date = coerce_window(dataset, start_date_raw, end_date_raw)
    filtered = _ensure_event_ids(filter_summary_data(dataset, circuito, start_date, end_date))
    daily_data = aggregate_daily(filtered, start_date, end_date)
    event_frame = _event_detail_frame(filtered)
    attribution_frame = _daily_attribution_frame(event_frame)
    history_start = max(dataset.min_date, end_date - timedelta(days=365))
    history_filtered = _ensure_event_ids(filter_summary_data(dataset, circuito, history_start, end_date))
    history_daily = aggregate_daily(history_filtered, history_start, end_date)
    history_event_frame = _event_detail_frame(history_filtered)
    history_attribution_frame = _daily_attribution_frame(history_event_frame)
    payload = build_summary_interpretability_payload(
        daily_frame=daily_data,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        circuit_label=circuito or "TODOS",
        metric_key=metric_key or "UITI",
        generated_at=datetime.now(timezone.utc).isoformat(),
        max_points=max_points,
        thresholds=thresholds,
        attribution_frame=attribution_frame,
        event_frame=event_frame,
        environment_frame=None,
    )
    payload["circuit_history_12m"] = build_circuit_history_12m_payload(
        daily_frame=history_daily,
        start_date=history_start.isoformat(),
        end_date=end_date.isoformat(),
        circuit_label=circuito or "TODOS",
        metric_key=metric_key or "UITI",
        max_points=max_points,
        thresholds=thresholds,
        attribution_frame=history_attribution_frame,
        event_frame=history_event_frame,
        environment_frame=None,
    )
    payload["selected_event"] = None
    return payload
