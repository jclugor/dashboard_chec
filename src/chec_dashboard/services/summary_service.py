from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Any
from pathlib import Path

import pandas as pd

from chec_dashboard.services.time_series_interpretability_service import (
    CriticalityThresholds,
    build_summary_interpretability_payload,
)


SUMMARY_FILE = "SuperEventos_Criticidad_AguasAbajo_CODEs.pkl"
REQUIRED_COLUMNS = {"inicio", "cto_equi_ope", "SAIDI", "SAIFI"}


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

    frame["SAIDI"] = pd.to_numeric(frame["SAIDI"], errors="coerce").fillna(0.0)
    frame["SAIFI"] = pd.to_numeric(frame["SAIFI"], errors="coerce").fillna(0.0)
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
        grouped = pd.DataFrame(index=date_index, columns=["SAIDI", "SAIFI"]).fillna(0.0)
    else:
        grouped = (
            filtered.groupby("fecha_dia")[["SAIDI", "SAIFI"]]
            .sum()
            .reindex(date_index, fill_value=0.0)
        )
    grouped.index.name = "fecha_dia"
    return grouped.reset_index()


def compute_kpis(filtered: pd.DataFrame) -> dict[str, float | int]:
    return {
        "saidi_total": float(filtered["SAIDI"].sum()) if not filtered.empty else 0.0,
        "saifi_total": float(filtered["SAIFI"].sum()) if not filtered.empty else 0.0,
        "event_count": int(len(filtered)),
    }


def _event_detail_frame(filtered: pd.DataFrame) -> pd.DataFrame:
    if filtered.empty:
        return pd.DataFrame()
    frame = filtered.copy()
    rename_map = {
        "inicio": "inicio_ts",
        "fin": "fin_ts",
        "MUN": "municipio",
        "cto_equi_ope": "circuito",
        "SAIDI": "severity_saidi",
        "SAIFI": "severity_saifi",
        "duracion_h": "duration_hours",
    }
    for source, target in rename_map.items():
        if source in frame.columns and target not in frame.columns:
            frame[target] = frame[source]
    if "event_count" not in frame.columns:
        frame["event_count"] = 1
    if "fecha_dia" not in frame.columns:
        frame["fecha_dia"] = pd.to_datetime(frame["inicio_ts"], errors="coerce").dt.floor("D")
    for column in ("severity_saidi", "severity_saifi", "duration_hours", "cnt_usus"):
        if column not in frame.columns:
            frame[column] = 0.0
    return frame


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
            saidi_total=("severity_saidi", "sum"),
            saifi_total=("severity_saifi", "sum"),
            duration_total_h=("duration_hours", "sum"),
            users_affected_total=("cnt_usus", "sum") if "cnt_usus" in frame.columns else ("event_count", "sum"),
        )
        .reset_index()
    )
    return grouped


def get_summary_interpretability_payload(
    dataset: SummaryDataset,
    start_date_raw: str | None,
    end_date_raw: str | None,
    circuito: str | None,
    metric_mode: str | None,
    *,
    max_points: int = 5,
    thresholds: CriticalityThresholds | None = None,
) -> dict[str, Any]:
    start_date, end_date = coerce_window(dataset, start_date_raw, end_date_raw)
    filtered = filter_summary_data(dataset, circuito, start_date, end_date)
    daily_data = aggregate_daily(filtered, start_date, end_date)
    event_frame = _event_detail_frame(filtered)
    attribution_frame = _daily_attribution_frame(event_frame)
    return build_summary_interpretability_payload(
        daily_frame=daily_data,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        circuit_label=circuito or "TODOS",
        metric_mode=metric_mode or "BOTH",
        generated_at=datetime.now(timezone.utc).isoformat(),
        max_points=max_points,
        thresholds=thresholds,
        attribution_frame=attribution_frame,
        event_frame=event_frame,
        environment_frame=None,
    )
