from dataclasses import dataclass
from functools import lru_cache
import operator
import os
from pathlib import Path
import re

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns


REQUIRED_PROBABILITY_FILES = [
    "Eventos_interruptor.pkl",
    "Eventos_tramo_linea.pkl",
    "Eventos_transformador.pkl",
]


@dataclass(frozen=True)
class ProbabilityDataset:
    interruptor: pd.DataFrame
    tramo: pd.DataFrame
    transformador: pd.DataFrame


def _validate_data_dir(data_dir: Path) -> None:
    missing = [name for name in REQUIRED_PROBABILITY_FILES if not (data_dir / name).exists()]
    if missing:
        message = (
            f"Missing required probability data files in '{data_dir}'. Missing: {', '.join(missing)}"
        )
        raise FileNotFoundError(message)


@lru_cache(maxsize=1)
def load_probability_dataset(data_dir_raw: str) -> ProbabilityDataset:
    # Cached once per Python process. Multi-worker deployments still duplicate
    # this memory per worker process.
    data_dir = Path(data_dir_raw)
    _validate_data_dir(data_dir)

    interruptor = pd.read_pickle(data_dir / "Eventos_interruptor.pkl")
    tramo = pd.read_pickle(data_dir / "Eventos_tramo_linea.pkl")
    transformador = pd.read_pickle(data_dir / "Eventos_transformador.pkl")

    for frame in [interruptor, tramo, transformador]:
        if "inicio" in frame.columns:
            frame["inicio"] = pd.to_datetime(frame["inicio"], errors="coerce")
        if "fin" in frame.columns:
            frame["fin"] = pd.to_datetime(frame["fin"], errors="coerce")

    return ProbabilityDataset(
        interruptor=interruptor,
        tramo=tramo,
        transformador=transformador,
    )


def criteria_options() -> list[dict[str, str]]:
    return [
        {"label": "", "value": ""},
        {"label": "Eventos Interruptor", "value": "Eventos Interruptor"},
        {"label": "Eventos Tramo", "value": "Eventos Tramo"},
        {"label": "Eventos Transformador", "value": "Eventos Transformador"},
    ]


def get_dataframe_by_criteria(
    dataset: ProbabilityDataset, criteria: str
) -> pd.DataFrame | None:
    mapping = {
        "Eventos Interruptor": dataset.interruptor,
        "Eventos Tramo": dataset.tramo,
        "Eventos Transformador": dataset.transformador,
    }
    return mapping.get(criteria)


def infer_filter_type(dtype_name: str) -> str:
    if dtype_name in {"object", "int64", "int32"}:
        return "seleccion"
    if dtype_name in {"float32", "float64"}:
        return "rango_num"
    if "datetime" in dtype_name or "period" in dtype_name:
        return "fecha"
    return ""


def apply_filters(
    frame: pd.DataFrame, filters: list[list[str | float | int | None]]
) -> pd.DataFrame:
    filtered = frame.copy()
    for filter_row in filters:
        if len(filter_row) < 4:
            continue
        filter_type = filter_row[0]
        column_name = filter_row[1]
        value_1 = filter_row[2]
        value_2 = filter_row[3]

        if not filter_type or not column_name or value_1 in (None, ""):
            continue
        if column_name not in filtered.columns:
            continue

        try:
            if filter_type == "seleccion":
                column = filtered[column_name]
                if pd.api.types.is_numeric_dtype(column.dtype):
                    filtered = filtered[column == pd.to_numeric(value_1)]
                else:
                    filtered = filtered[column.astype(str) == str(value_1)]
            elif filter_type == "rango_num" and value_2 is not None:
                operators = {
                    "<": operator.lt,
                    ">": operator.gt,
                    "==": operator.eq,
                    "<=": operator.le,
                    ">=": operator.ge,
                    "!=": operator.ne,
                }
                fn = operators.get(str(value_1))
                if fn is None:
                    continue
                filtered = filtered[fn(filtered[column_name], float(value_2))]
            elif filter_type == "fecha" and value_2 not in (None, ""):
                series = pd.to_datetime(filtered[column_name], errors="coerce")
                start = pd.to_datetime(value_1, errors="coerce")
                end = pd.to_datetime(value_2, errors="coerce")
                filtered = filtered[(series >= start) & (series <= end)]
        except Exception:
            continue
    return filtered


def next_output_index(output_dir: Path) -> int:
    existing = output_dir.glob("probability_graph_*.png")
    indexes: list[int] = []
    for file_path in existing:
        match = re.search(r"probability_graph_(\d+)\.png", file_path.name)
        if match:
            indexes.append(int(match.group(1)))
    if not indexes:
        return 0
    return max(indexes) + 1


def generate_probability_graph(
    frame: pd.DataFrame,
    target_column: str,
    probability_text: str,
    output_dir: Path,
) -> Path:
    if target_column not in frame.columns:
        raise ValueError(f"Target column '{target_column}' does not exist in filtered data.")

    series = frame[target_column].dropna()
    if series.empty:
        raise ValueError("Filtered data has no rows with values for the selected target variable.")

    output_dir.mkdir(parents=True, exist_ok=True)
    image_index = next_output_index(output_dir)
    output_path = output_dir / f"probability_graph_{image_index}.png"

    plt.figure(figsize=(10, 6))
    sns.histplot(series, kde=True, color="blue", bins=30, stat="probability")
    plt.title(probability_text, fontsize=10)
    plt.xlabel(str(target_column), fontsize=14)
    plt.ylabel("Probabilidad", fontsize=14)
    plt.grid(True, linestyle="--", alpha=0.7)
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()

    return output_path
