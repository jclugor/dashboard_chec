from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from chec_dashboard.services.impact_metrics import empty_metric_totals, normalize_metric_key
from chec_dashboard.services.map_service import FilteredMapDataset, normalize_selected_circuits, render_base_map
from chec_dashboard.services.probability_service import apply_filters, generate_probability_graph
from chec_dashboard.services.time_series_interpretability_service import (
    CriticalityThresholds,
    build_circuit_history_12m_payload,
    build_summary_interpretability_payload,
)


TABLE_NAMES = [
    "causas",
    "equipos_proteccion",
    "apoyos",
    "vanos",
    "transformador_profiles",
    "eventos",
    "evento_vano_trafo",
    "clima_vano_fecha",
]


@dataclass(frozen=True)
class NormalizedDataset:
    tables: dict[str, pd.DataFrame]
    fact: pd.DataFrame
    min_date: date
    max_date: date


def _num(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series.astype("string").str.replace(",", ".", regex=False).replace("", pd.NA), errors="coerce").fillna(0.0)


def _text(series: pd.Series, default: str = "") -> pd.Series:
    return series.astype("string").fillna("").str.strip().replace("", default)


def _optional_text(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(pd.NA, index=frame.index, dtype="string")
    return frame[column].astype("string").str.strip().replace("", pd.NA)


@lru_cache(maxsize=2)
def load_normalized_dataset(data_dir_raw: str) -> NormalizedDataset:
    data_dir = Path(data_dir_raw)
    tables = {name: pd.read_parquet(data_dir / f"{name}.parquet") for name in TABLE_NAMES}
    vanos = tables["vanos"].rename(
        columns={
            "municipio": "municipio_vano",
            "municipio_source": "municipio_vano_source",
            "municipio_confidence": "municipio_vano_confidence",
        }
    )
    transformador_profiles = tables["transformador_profiles"].rename(
        columns={
            "municipio": "municipio_trafo",
            "municipio_source": "municipio_trafo_source",
            "municipio_confidence": "municipio_trafo_confidence",
        }
    )

    fact = (
        tables["evento_vano_trafo"]
        .merge(tables["eventos"], on="event_id", how="left", validate="many_to_one")
        .merge(vanos, on="FID_VANO", how="left", validate="many_to_one")
        .merge(tables["equipos_proteccion"], on="FID_SW", how="left", validate="many_to_one")
        .merge(tables["causas"], on="COD_CAUSA", how="left", validate="many_to_one")
        .merge(transformador_profiles, on="trafo_profile_id", how="left", validate="many_to_one")
    )
    fact["fecha_dia"] = pd.to_datetime(fact["FECHA"], errors="coerce").dt.floor("D")
    fact = fact.dropna(subset=["fecha_dia"]).copy()
    fact["circuito"] = _text(fact["CIRCUITO"], "Sin circuito")
    fact["municipio"] = _optional_text(fact, "municipio_vano").combine_first(
        _optional_text(fact, "municipio_trafo")
    ).fillna("Sin municipio")
    fact["municipio_source"] = _optional_text(fact, "municipio_vano_source").combine_first(
        _optional_text(fact, "municipio_trafo_source")
    )
    fact["municipio_confidence"] = _optional_text(fact, "municipio_vano_confidence").combine_first(
        _optional_text(fact, "municipio_trafo_confidence")
    ).fillna("unresolved")
    fact["causa"] = _text(fact["DESC_CAUSA"], "Sin causa")
    fact["event_family"] = "Eventos Vano"
    fact["criteria_group"] = "Eventos Vano"
    fact["equipo_ope"] = _text(fact["FID_SW"], "Sin equipo")
    fact["tipo_equi_ope"] = _text(fact["TIPO"], "Proteccion")
    fact["tipo_elemento"] = _text(fact["TIPO_TAX"], "Vano")
    fact["UITI"] = _num(fact["UITI"])
    fact["UITI_VANO"] = _num(fact["UITI_VANO"])
    fact["DURATION_RAW"] = _num(fact["DURACION"])
    fact["USERS"] = _num(fact["CNT_USUS"])
    fact["EVENT_COUNT"] = 1.0
    fact["LATITUD"] = _num(fact["Y1"])
    fact["LONGITUD"] = _num(fact["X1"])
    fact["LATITUD2"] = _num(fact["Y2"])
    fact["LONGITUD2"] = _num(fact["X2"])
    fact["map_period"] = fact["fecha_dia"].dt.strftime("%Y-%m")
    fact["map_day"] = fact["fecha_dia"].dt.day

    min_date = fact["fecha_dia"].min().date()
    max_date = fact["fecha_dia"].max().date()
    return NormalizedDataset(tables=tables, fact=fact, min_date=min_date, max_date=max_date)


def default_window(dataset: NormalizedDataset, days: int = 180) -> tuple[date, date]:
    end_date = dataset.max_date
    return max(dataset.min_date, end_date - timedelta(days=max(days - 1, 0))), end_date


def coerce_window(dataset: NormalizedDataset, start_raw: str | None, end_raw: str | None) -> tuple[date, date]:
    default_start, default_end = default_window(dataset)
    start_date = pd.to_datetime(start_raw, errors="coerce").date() if start_raw else default_start
    end_date = pd.to_datetime(end_raw, errors="coerce").date() if end_raw else default_end
    if start_date > end_date:
        start_date, end_date = end_date, start_date
    return max(start_date, dataset.min_date), min(end_date, dataset.max_date)


def summary_metadata(dataset: NormalizedDataset) -> dict[str, Any]:
    circuits = sorted(dataset.fact["circuito"].dropna().astype(str).unique().tolist())
    start_date, end_date = default_window(dataset)
    return {
        "circuits": circuits,
        "default_circuit": circuits[0] if circuits else None,
        "min_date": dataset.min_date.isoformat(),
        "max_date": dataset.max_date.isoformat(),
        "default_start": start_date.isoformat(),
        "default_end": end_date.isoformat(),
    }


def _filter_fact(dataset: NormalizedDataset, start_date: date, end_date: date, circuito: str | None) -> pd.DataFrame:
    frame = dataset.fact
    filtered = frame[(frame["fecha_dia"].dt.date >= start_date) & (frame["fecha_dia"].dt.date <= end_date)]
    if circuito:
        filtered = filtered[filtered["circuito"] == circuito]
    return filtered.copy()


def _round(value: Any, digits: int = 4) -> float:
    coerced = pd.to_numeric(value, errors="coerce")
    if pd.isna(coerced):
        return 0.0
    return round(float(coerced), digits)


def _value(value: Any) -> Any | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if str(value).strip() == "":
        return None
    return value


def _text_value(row: pd.Series, column: str, default: str = "") -> str:
    value = _value(row.get(column))
    return default if value is None else str(value)


def _event_record(row: pd.Series) -> dict[str, Any]:
    inicio = _value(row.get("FECHA"))
    parsed = pd.to_datetime(inicio, errors="coerce")
    fecha_dia = _value(row.get("fecha_dia"))
    if isinstance(fecha_dia, pd.Timestamp):
        fecha_text = fecha_dia.date().isoformat()
    elif fecha_dia is None:
        fecha_text = None if pd.isna(parsed) else parsed.date().isoformat()
    else:
        fecha_text = str(fecha_dia)
    event_id = _text_value(row, "event_id")
    inicio_text = parsed.strftime("%Y-%m-%d %H:%M") if not pd.isna(parsed) else str(inicio or "sin fecha")
    equipo = _text_value(row, "equipo_ope", "Evento")
    causa = _text_value(row, "causa", "Sin causa")
    uiti_vano = _round(row.get("UITI_VANO"))
    label = f"{inicio_text} | {equipo} | {causa} | UITI vano {uiti_vano:.4f} | {event_id}"
    return {
        "event_id": event_id,
        "label": label,
        "fecha_dia": fecha_text,
        "inicio_ts": None if pd.isna(parsed) else parsed.isoformat(),
        "fin_ts": None,
        "circuito": _text_value(row, "circuito"),
        "municipio": _text_value(row, "municipio"),
        "causa": causa,
        "event_family": _text_value(row, "event_family"),
        "equipo_ope": equipo,
        "tipo_equi_ope": _text_value(row, "tipo_equi_ope"),
        "tipo_elemento": _text_value(row, "tipo_elemento"),
        "duration_raw": _round(row.get("DURATION_RAW"), 2),
        "uiti": _round(row.get("UITI")),
        "uiti_vano": uiti_vano,
        "users_affected": _round(row.get("USERS"), 2),
    }


def event_options(
    dataset: NormalizedDataset,
    start_raw: str | None,
    end_raw: str | None,
    circuito: str | None,
    *,
    limit: int = 200,
) -> dict[str, Any]:
    start_date, end_date = coerce_window(dataset, start_raw, end_raw)
    filtered = _filter_fact(dataset, start_date, end_date, circuito)
    safe_limit = max(1, min(int(limit), 500))
    if filtered.empty:
        return {
            "events": [],
            "default_event_id": None,
            "status_text": "No se encontraron eventos para la ventana y circuito seleccionados.",
        }
    work = (
        filtered.sort_values(["fecha_dia", "UITI_VANO"], ascending=[True, False])
        .drop_duplicates(subset=["event_id"], keep="first")
        .head(safe_limit)
    )
    events = [_event_record(row) for _, row in work.iterrows()]
    return {
        "events": events,
        "default_event_id": None,
        "status_text": f"Se encontraron {len(events)} eventos para la ventana y circuito seleccionados.",
    }


def event_history_12m(dataset: NormalizedDataset, selected_event: dict[str, Any]) -> dict[str, Any]:
    event_date = pd.to_datetime(selected_event.get("fecha_dia") or selected_event.get("inicio_ts"), errors="coerce")
    circuit = selected_event.get("circuito")
    if pd.isna(event_date) or not circuit:
        return {"available": False, "reason": "missing_event_date_or_circuit"}
    end_date = event_date.date()
    start_date = max(dataset.min_date, end_date - timedelta(days=365))
    filtered = _filter_fact(dataset, start_date, end_date, str(circuit))
    daily = _daily_frame(filtered, start_date, end_date)
    return {
        "available": True,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "event_count": int(daily["EVENT_COUNT"].sum()) if "EVENT_COUNT" in daily else 0,
        "uiti_total": _round(daily["UITI"].sum() if "UITI" in daily else 0.0),
        "uiti_vano_total": _round(daily["UITI_VANO"].sum() if "UITI_VANO" in daily else 0.0),
        "duration_raw_total": _round(daily["DURATION_RAW"].sum() if "DURATION_RAW" in daily else 0.0, 2),
        "users_affected_total": _round(daily["USERS"].sum() if "USERS" in daily else 0.0, 2),
    }


def selected_event_record(
    dataset: NormalizedDataset,
    start_raw: str | None,
    end_raw: str | None,
    circuito: str | None,
    selected_event_id: str | None,
) -> dict[str, Any] | None:
    if not selected_event_id:
        return None
    start_date, end_date = coerce_window(dataset, start_raw, end_raw)
    filtered = _filter_fact(dataset, start_date, end_date, circuito)
    matches = filtered[filtered["event_id"].astype(str) == str(selected_event_id)]
    if matches.empty:
        return None
    record = _event_record(matches.iloc[0])
    record["circuit_history_12m"] = event_history_12m(dataset, record)
    return record


def _daily_frame(filtered: pd.DataFrame, start_date: date, end_date: date) -> pd.DataFrame:
    date_index = pd.date_range(start=start_date, end=end_date, freq="D")
    if filtered.empty:
        grouped = pd.DataFrame(index=date_index, columns=["UITI", "UITI_VANO", "EVENT_COUNT", "USERS", "DURATION_RAW"]).fillna(0.0)
    else:
        event_daily = (
            filtered.groupby(["fecha_dia", "event_id"], dropna=False)
            .agg(
                UITI=("UITI_VANO", "sum"),
                UITI_VANO=("UITI_VANO", "sum"),
                EVENT_COUNT=("event_id", "nunique"),
                USERS=("USERS", "sum"),
                DURATION_RAW=("DURATION_RAW", "max"),
            )
            .reset_index()
        )
        grouped = event_daily.groupby("fecha_dia")[["UITI", "UITI_VANO", "EVENT_COUNT", "USERS", "DURATION_RAW"]].sum()
        grouped = grouped.reindex(date_index, fill_value=0.0)
    grouped.index.name = "fecha_dia"
    return grouped.reset_index()


def summary_payload(dataset: NormalizedDataset, start_raw: str | None, end_raw: str | None, circuito: str | None, metric_key: str | None) -> dict[str, Any]:
    metric_key = normalize_metric_key(metric_key)
    start_date, end_date = coerce_window(dataset, start_raw, end_raw)
    filtered = _filter_fact(dataset, start_date, end_date, circuito)
    daily = _daily_frame(filtered, start_date, end_date)
    totals = empty_metric_totals()
    for key in totals:
        totals[key] = float(daily[key].sum()) if key in daily.columns else 0.0
    event_count = int(totals["EVENT_COUNT"])
    daily_records = [
        {
            "fecha_dia": pd.to_datetime(row["fecha_dia"]).date().isoformat(),
            "metrics": {key: float(row[key]) for key in totals},
        }
        for _, row in daily.iterrows()
    ]
    circuit_label = circuito or "TODOS"
    return {
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "circuit_label": circuit_label,
        "metric_key": metric_key,
        "metric_totals": totals,
        "event_count": event_count,
        "daily_data": daily_records,
        "status_text": f"Circuito: {circuit_label}. Ventana: {start_date.isoformat()} a {end_date.isoformat()}. Eventos: {event_count}.",
    }


def attribution_frame(filtered: pd.DataFrame) -> pd.DataFrame:
    if filtered.empty:
        return pd.DataFrame()
    return (
        filtered.groupby(["fecha_dia", "circuito", "municipio", "causa", "event_family", "equipo_ope", "tipo_equi_ope"], dropna=False)
        .agg(
            event_count=("event_id", "nunique"),
            uiti_total=("UITI_VANO", "sum"),
            uiti_vano_total=("UITI_VANO", "sum"),
            duration_raw_total=("DURATION_RAW", "sum"),
            users_affected_total=("USERS", "sum"),
        )
        .reset_index()
    )


def interpretability_payload(
    dataset: NormalizedDataset,
    start_raw: str | None,
    end_raw: str | None,
    circuito: str | None,
    metric_key: str | None,
    *,
    max_points: int,
    thresholds: CriticalityThresholds | None = None,
    selected_event_id: str | None = None,
) -> dict[str, Any]:
    _ = selected_event_id
    metric_key = normalize_metric_key(metric_key)
    start_date, end_date = coerce_window(dataset, start_raw, end_raw)
    filtered = _filter_fact(dataset, start_date, end_date, circuito)
    daily = _daily_frame(filtered, start_date, end_date)
    event_frame = filtered.rename(columns={"FECHA": "inicio_ts"}).copy()
    history_start = max(dataset.min_date, end_date - timedelta(days=365))
    history_filtered = _filter_fact(dataset, history_start, end_date, circuito)
    history_daily = _daily_frame(history_filtered, history_start, end_date)
    history_event_frame = history_filtered.rename(columns={"FECHA": "inicio_ts"}).copy()
    payload = build_summary_interpretability_payload(
        daily_frame=daily,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        circuit_label=circuito or "TODOS",
        metric_key=metric_key,
        generated_at=pd.Timestamp.utcnow().isoformat(),
        max_points=max_points,
        thresholds=thresholds,
        attribution_frame=attribution_frame(filtered),
        event_frame=event_frame,
        environment_frame=None,
    )
    payload["circuit_history_12m"] = build_circuit_history_12m_payload(
        daily_frame=history_daily,
        start_date=history_start.isoformat(),
        end_date=end_date.isoformat(),
        circuit_label=circuito or "TODOS",
        metric_key=metric_key,
        max_points=max_points,
        thresholds=thresholds,
        attribution_frame=attribution_frame(history_filtered),
        event_frame=history_event_frame,
        environment_frame=None,
    )
    payload["selected_event"] = None
    return payload


def probability_frame(dataset: NormalizedDataset) -> pd.DataFrame:
    columns = [
        "criteria_group",
        "fecha_dia",
        "circuito",
        "municipio",
        "causa",
        "event_family",
        "UITI",
        "UITI_VANO",
        "EVENT_COUNT",
        "USERS",
        "DURATION_RAW",
        "FID_VANO",
        "trafo_profile_id",
    ]
    frame = dataset.fact[columns].copy()
    frame["source_date"] = frame["fecha_dia"].dt.date.astype(str)
    frame["target_flag"] = (frame["UITI_VANO"] > 0).astype(int)
    return frame


def map_metadata(dataset: NormalizedDataset) -> dict[str, Any]:
    dates = sorted(dataset.fact["map_period"].dropna().unique().tolist())
    municipios = sorted(dataset.fact["municipio"].dropna().astype(str).unique().tolist())
    return {
        "action": None,
        "dates": dates,
        "municipios": municipios,
        "default_date": dates[0] if dates else None,
        "default_municipio": municipios[0] if municipios else None,
        "circuits": [],
        "default_circuit": "Todos",
        "outputs": ["BASE"],
        "default_output": "BASE",
    }


def map_filter_metadata(dataset: NormalizedDataset, selected_period: str, selected_municipio: str) -> dict[str, Any]:
    frame = dataset.fact[(dataset.fact["map_period"] == selected_period) & (dataset.fact["municipio"] == selected_municipio)]
    circuits = ["Todos", *sorted(frame["circuito"].dropna().astype(str).unique().tolist())]
    return {
        "action": "circuits",
        "dates": [],
        "municipios": [],
        "default_date": selected_period,
        "default_municipio": selected_municipio,
        "circuits": circuits,
        "default_circuit": circuits[0],
        "outputs": ["BASE"],
        "default_output": "BASE",
    }


def map_payload(dataset: NormalizedDataset, selected_period: str, selected_municipio: str, selected_circuit: str | None, selected_circuits: list[str] | None, selected_output: str | None, day: int, max_html_chars: int) -> dict[str, Any]:
    circuits = normalize_selected_circuits(selected_circuit=selected_circuit, selected_circuits=selected_circuits)
    frame = dataset.fact[(dataset.fact["map_period"] == selected_period) & (dataset.fact["municipio"] == selected_municipio)]
    if circuits is not None:
        frame = frame[frame["circuito"].isin(circuits)]
    safe_day = max(1, min(int(day), 31))
    events_by_day = [frame[frame["map_day"] == current_day].copy() for current_day in range(1, 32)]
    redmt = (
        frame.drop_duplicates("FID_VANO")
        .rename(columns={"CONDUCTOR": "MATERIALCONDUCTOR", "LONGITUD": "LENGTH", "CALIBRE_NEUTRO": "CALIBRECONDUCTOR"})
        .copy()
    )
    filtered = FilteredMapDataset(
        trafos=pd.DataFrame(),
        apoyos=pd.DataFrame(),
        switches=frame.drop_duplicates("FID_SW").copy(),
        redmt=redmt,
        events_by_day=events_by_day,
    )
    map_html = render_base_map(filtered, day=safe_day)
    if len(map_html) > max_html_chars:
        raise ValueError("Rendered map payload is too large for safe transfer.")
    return {
        "map_html": map_html,
        "current_day": safe_day,
        "status_text": f"Mapa cargado para {selected_municipio}, período {selected_period}. Día actual: {safe_day}.",
    }
