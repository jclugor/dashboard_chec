from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import pandas as pd


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
