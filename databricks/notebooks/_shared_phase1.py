# Databricks notebook source
from __future__ import annotations

import gc
import json
import math
import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


DEFAULT_WORKSPACE_ROOT = "/Workspace/Shared/chec-phase1"
DEFAULT_CATALOG = "chec_dbx_demo"
DEFAULT_SOURCE_VOLUME = "source_files"
DEFAULT_ARTIFACT_VOLUME = "artifacts"
DEFAULT_MANIFEST_FILENAME = "normalized_vano_assets.json"
DEFAULT_SCHEMA_NAMES = (
    "raw",
    "bronze",
    "silver",
    "gold",
    "ml",
    "agent",
    "agent_config",
    "agent_tools",
    "agent_observability",
)


@dataclass(frozen=True)
class Phase1Context:
    workspace_root_path: str
    catalog_name: str
    source_volume_name: str
    artifact_volume_name: str
    manifest_filename: str = DEFAULT_MANIFEST_FILENAME

    @property
    def source_data_root(self) -> str:
        return f"{self.workspace_root_path.rstrip('/')}/data"

    @property
    def manifest_path(self) -> str:
        return f"{self.workspace_root_path.rstrip('/')}/manifests/{self.manifest_filename}"

    @property
    def source_volume_root(self) -> str:
        return volume_path(self.catalog_name, "raw", self.source_volume_name)

    @property
    def artifact_volume_root(self) -> str:
        return volume_path(self.catalog_name, "ml", self.artifact_volume_name)


def _dbutils() -> Any | None:
    return globals().get("dbutils")


def _candidate_paths(path: str | None, manifest_filename: str = DEFAULT_MANIFEST_FILENAME) -> list[str]:
    candidates: list[str] = []
    if path:
        candidates.append(path)
    candidates.append(f"{DEFAULT_WORKSPACE_ROOT}/manifests/{manifest_filename}")

    notebook_file = globals().get("__file__")
    if notebook_file:
        candidates.append(
            str(Path(notebook_file).resolve().parents[1] / "manifests" / manifest_filename)
        )
    return candidates


def _strip_file_prefix(path: str) -> str:
    return path[5:] if path.startswith("file:") else path


def _read_text_file(path: str) -> str:
    dbutils_obj = _dbutils()
    manifest_filename = Path(path).name if path else DEFAULT_MANIFEST_FILENAME
    for candidate in _candidate_paths(path, manifest_filename=manifest_filename):
        if dbutils_obj is not None:
            for uri in (candidate, f"file:{candidate}"):
                try:
                    return dbutils_obj.fs.head(uri, 1024 * 1024)
                except Exception:
                    pass

        candidate_path = Path(_strip_file_prefix(candidate))
        if candidate_path.exists():
            return candidate_path.read_text(encoding="utf-8")

    raise FileNotFoundError(f"Unable to read phase 1 manifest from: {path}")


def load_manifest(manifest_path: str | None = None) -> dict[str, Any]:
    return json.loads(_read_text_file(manifest_path or ""))


def widget_value(name: str, default: str, dbutils_obj: Any | None = None) -> str:
    dbutils_obj = dbutils_obj or _dbutils()
    if dbutils_obj is None:
        return default
    try:
        value = dbutils_obj.widgets.get(name)
    except Exception:
        return default
    return value if value not in (None, "") else default


def define_standard_widgets(dbutils_obj: Any | None = None) -> None:
    dbutils_obj = dbutils_obj or _dbutils()
    if dbutils_obj is None:
        return
    dbutils_obj.widgets.text("workspace_root_path", DEFAULT_WORKSPACE_ROOT)
    dbutils_obj.widgets.text("catalog_name", DEFAULT_CATALOG)
    dbutils_obj.widgets.text("source_volume_name", DEFAULT_SOURCE_VOLUME)
    dbutils_obj.widgets.text("artifact_volume_name", DEFAULT_ARTIFACT_VOLUME)
    dbutils_obj.widgets.text("manifest_filename", DEFAULT_MANIFEST_FILENAME)


def define_probability_widgets(dbutils_obj: Any | None = None) -> None:
    dbutils_obj = dbutils_obj or _dbutils()
    if dbutils_obj is None:
        return
    define_standard_widgets(dbutils_obj)
    dbutils_obj.widgets.dropdown(
        "criteria",
        "Todos",
        [
            "Todos",
            "Eventos Interruptor",
            "Eventos Tramo",
            "Eventos Transformador",
        ],
    )
    dbutils_obj.widgets.text("start_date", "")
    dbutils_obj.widgets.text("end_date", "")
    dbutils_obj.widgets.text("selected_circuit", "Todos")
    dbutils_obj.widgets.text("selected_municipio", "Todos")
    dbutils_obj.widgets.text("target_column", "UITI")


def define_map_widgets(dbutils_obj: Any | None = None) -> None:
    dbutils_obj = dbutils_obj or _dbutils()
    if dbutils_obj is None:
        return
    define_standard_widgets(dbutils_obj)
    dbutils_obj.widgets.dropdown("point_kind", "Todos", ["Todos", "asset", "event"])
    dbutils_obj.widgets.dropdown("geometry_kind", "Todos", ["Todos", "point", "line"])
    dbutils_obj.widgets.text("start_date", "")
    dbutils_obj.widgets.text("end_date", "")
    dbutils_obj.widgets.text("selected_circuit", "Todos")
    dbutils_obj.widgets.text("selected_municipio", "Todos")
    dbutils_obj.widgets.text("selected_family", "Todos")


def build_context(dbutils_obj: Any | None = None) -> Phase1Context:
    dbutils_obj = dbutils_obj or _dbutils()
    if dbutils_obj is None:
        return Phase1Context(
            workspace_root_path=DEFAULT_WORKSPACE_ROOT,
            catalog_name=DEFAULT_CATALOG,
            source_volume_name=DEFAULT_SOURCE_VOLUME,
            artifact_volume_name=DEFAULT_ARTIFACT_VOLUME,
            manifest_filename=DEFAULT_MANIFEST_FILENAME,
        )
    return Phase1Context(
        workspace_root_path=widget_value("workspace_root_path", DEFAULT_WORKSPACE_ROOT, dbutils_obj),
        catalog_name=widget_value("catalog_name", DEFAULT_CATALOG, dbutils_obj),
        source_volume_name=widget_value("source_volume_name", DEFAULT_SOURCE_VOLUME, dbutils_obj),
        artifact_volume_name=widget_value("artifact_volume_name", DEFAULT_ARTIFACT_VOLUME, dbutils_obj),
        manifest_filename=widget_value("manifest_filename", DEFAULT_MANIFEST_FILENAME, dbutils_obj),
    )


def volume_path(catalog_name: str, schema_name: str, volume_name: str, relative_path: str = "") -> str:
    root = f"/Volumes/{catalog_name}/{schema_name}/{volume_name}"
    relative_path = relative_path.strip("/")
    return f"{root}/{relative_path}" if relative_path else root


def table_name(catalog_name: str, schema_name: str, object_name: str) -> str:
    return f"{catalog_name}.{schema_name}.{object_name}"


def resolve_column_name(columns: Iterable[str], requested: str) -> str | None:
    requested_clean = requested.strip().casefold()
    for column in columns:
        if column.strip().casefold() == requested_clean:
            return column
    return None


def manifest_source_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    def metadata_json(value: Any) -> str:
        return json.dumps(value if value is not None else [], ensure_ascii=False, sort_keys=True)

    rows: list[dict[str, Any]] = []
    for entry in manifest.get("raw_sources", []):
        relative_path = entry["relative_path"]
        rows.append(
            {
                "logical_name": entry["logical_name"],
                "source_file_name": Path(relative_path).name,
                "relative_path": relative_path,
                "load_mode": entry.get("load_mode", ""),
                "bronze_table": entry.get("bronze_table"),
                "expected_rows": entry.get("expected_rows"),
                "primary_key": metadata_json(entry.get("primary_key", [])),
                "natural_key": metadata_json(entry.get("natural_key", [])),
                "foreign_keys": metadata_json(entry.get("foreign_keys", [])),
                "required_columns": metadata_json(entry.get("required_columns", [])),
                "date_columns": metadata_json(entry.get("date_columns", [])),
                "weather_variables": metadata_json(entry.get("weather_variables", [])),
                "weather_offsets": metadata_json(entry.get("weather_offsets", [])),
            }
        )
    return rows


def manifest_artifact_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in manifest.get("ml_artifacts", []):
        relative_path = entry["relative_path"]
        rows.append(
            {
                "logical_name": entry["logical_name"],
                "source_file_name": Path(relative_path).name,
                "relative_path": relative_path,
                "target_schema": entry.get("target_schema", "ml"),
                "target_volume": entry.get("target_volume", DEFAULT_ARTIFACT_VOLUME),
            }
        )
    return rows


def manifest_secret_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in manifest.get("sensitive_files", []):
        relative_path = entry["relative_path"]
        rows.append(
            {
                "logical_name": Path(relative_path).stem,
                "source_file_name": Path(relative_path).name,
                "relative_path": relative_path,
                "disposition": entry.get("disposition", "review"),
                "reason": entry.get("reason", ""),
            }
        )
    return rows


def manifest_gold_rows(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for entry in manifest.get("gold_tables", []):
        rows.append(
            {
                "table_name": entry["table_name"],
                "description": entry.get("description", ""),
            }
        )
    return rows


def normalize_object_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return pd.to_datetime(value, errors="coerce").to_pydatetime()
    if isinstance(value, (list, tuple, set, dict)):
        return json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def normalize_pandas_frame(frame: pd.DataFrame, date_columns: Iterable[str] = ()) -> pd.DataFrame:
    normalized = frame.copy()
    normalized.columns = [str(column).strip() for column in normalized.columns]
    date_column_set = {str(column).strip().casefold() for column in date_columns}

    for column in normalized.columns:
        series = normalized[column]
        column_key = column.casefold()
        if column_key in date_column_set or column_key in {"fecha", "inicio", "fin", "date_fab"}:
            normalized[column] = pd.to_datetime(series, errors="coerce")
        elif isinstance(series.dtype, pd.PeriodDtype):
            normalized[column] = series.dt.to_timestamp()
        elif pd.api.types.is_object_dtype(series):
            normalized[column] = series.map(normalize_object_value).astype("string")
        elif pd.api.types.is_bool_dtype(series):
            normalized[column] = series.astype("boolean")
        elif pd.api.types.is_numeric_dtype(series):
            numeric_series = pd.to_numeric(series, errors="coerce")
            # Spark Connect rejects Arrow half-precision floats, so upcast all floats.
            if pd.api.types.is_float_dtype(numeric_series):
                numeric_series = numeric_series.astype("float64")
            normalized[column] = numeric_series

    return normalized


def source_file_path(context: Phase1Context, relative_path: str) -> Path:
    return Path(context.source_volume_root) / relative_path


def volume_file_path(context: Phase1Context, relative_path: str, schema_name: str = "raw", volume_name: str | None = None) -> Path:
    volume_name = volume_name or context.source_volume_name
    return Path(volume_path(context.catalog_name, schema_name, volume_name, relative_path))


def copy_file(source_path: Path | str, destination_path: Path | str) -> dict[str, Any]:
    source = Path(source_path)
    destination = Path(destination_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    stat_result = destination.stat()
    return {
        "source_path": str(source),
        "destination_path": str(destination),
        "bytes": int(stat_result.st_size),
    }


def copy_tree(source_root: Path | str, destination_root: Path | str) -> list[dict[str, Any]]:
    source_root_path = Path(source_root)
    destination_root_path = Path(destination_root)
    copied: list[dict[str, Any]] = []

    if not source_root_path.exists():
        return copied

    for file_path in source_root_path.rglob("*"):
        if not file_path.is_file() or file_path.name.startswith("."):
            continue
        relative_path = file_path.relative_to(source_root_path)
        destination_path = destination_root_path / relative_path
        copy_result = copy_file(file_path, destination_path)
        copied.append(
            {
                "relative_path": relative_path.as_posix(),
                "source_path": copy_result["source_path"],
                "destination_path": copy_result["destination_path"],
                "bytes": copy_result["bytes"],
            }
        )
    return copied


def load_source_frame(source_path: Path, load_mode: str) -> pd.DataFrame:
    if load_mode == "pickle":
        return pd.read_pickle(source_path)
    if load_mode == "parquet":
        return pd.read_parquet(source_path)
    if load_mode == "csv":
        return pd.read_csv(source_path)
    if load_mode == "excel":
        return pd.read_excel(source_path)
    raise ValueError(f"Unsupported load mode: {load_mode}")


def spark_frame_from_pandas(spark: Any, frame: pd.DataFrame) -> Any:
    try:
        return spark.createDataFrame(frame)
    except Exception:
        fallback = frame.copy()
        for column in fallback.columns:
            if pd.api.types.is_datetime64_any_dtype(fallback[column]):
                continue
            fallback[column] = fallback[column].astype("string")
        return spark.createDataFrame(fallback)


def pandas_frame_size_bytes(frame: pd.DataFrame) -> int:
    return int(frame.memory_usage(deep=True).sum())


def pandas_frame_chunks(
    frame: pd.DataFrame,
    target_chunk_bytes: int = 64 * 1024 * 1024,
    max_rows_per_chunk: int = 50_000,
) -> Iterable[pd.DataFrame]:
    row_count = len(frame.index)
    if row_count == 0:
        yield frame.copy()
        return

    total_bytes = pandas_frame_size_bytes(frame)
    bytes_per_row = max(1, math.ceil(total_bytes / row_count)) if total_bytes > 0 else 1
    chunk_row_count = max(1, min(max_rows_per_chunk, target_chunk_bytes // bytes_per_row))

    for start in range(0, row_count, chunk_row_count):
        yield frame.iloc[start : start + chunk_row_count].copy()


def write_pandas_frame_to_delta(
    spark: Any,
    frame: pd.DataFrame,
    fully_qualified_table_name: str,
    *,
    target_chunk_bytes: int = 64 * 1024 * 1024,
) -> None:
    write_mode = "overwrite"

    for chunk in pandas_frame_chunks(frame, target_chunk_bytes=target_chunk_bytes):
        spark_frame = spark_frame_from_pandas(spark, chunk)
        writer = spark_frame.write.format("delta").mode(write_mode)
        if write_mode == "overwrite":
            writer = writer.option("overwriteSchema", "true")
        writer.saveAsTable(fully_qualified_table_name)
        write_mode = "append"


def source_date_bounds(frame: pd.DataFrame, date_columns: Iterable[str]) -> dict[str, Any]:
    bounds: dict[str, Any] = {"min_date": None, "max_date": None}
    date_series: list[pd.Series] = []

    for column in date_columns:
        if column in frame.columns:
            date_series.append(pd.to_datetime(frame[column], errors="coerce"))

    if not date_series:
        return bounds

    combined = pd.concat(date_series, axis=0).dropna()
    if combined.empty:
        return bounds

    bounds["min_date"] = combined.min().to_pydatetime()
    bounds["max_date"] = combined.max().to_pydatetime()
    return bounds


def safe_count(frame: pd.DataFrame) -> int:
    return int(len(frame.index))


def drop_references() -> None:
    gc.collect()
