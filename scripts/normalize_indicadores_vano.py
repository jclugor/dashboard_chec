#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BASE_COLUMNS = [
    "CIRCUITO",
    "FID_SW",
    "COD_EQ_PROTEGE",
    "FID_VANO",
    "T_USUS_EQ_PROT",
    "LVSW",
    "CNT_VN",
    "CNT_VN_SW",
    "FECHA",
    "DURACION",
    "UITI",
    "UITI_VANO",
    "TOT_USUS",
    "CNT_TRF",
    "COD_CAUSA",
    "DESC_CAUSA",
    "TIPO",
    "PORC_APORTE_VANO",
    "LONGITUD",
    "CNT_FASES",
    "CONDUCTOR",
    "CALIBRE_NEUTRO",
    "NG_RED",
    "FECHA_OPERACION_VANO",
    "X1",
    "Y1",
    "X2",
    "Y2",
    "COD_APOYO_FIN",
    "FID_APOYO_FIN",
    "ALTURA",
    "CANTIDAD_TIERRA",
    "PROPIETARIO",
    "CLASE",
    "ELEMENTO",
    "NORMA",
    "VAL_CRIT_APOYO",
    "FID_TRAFO",
    "CODIGO",
    "CAPACIDAD_NOMINAL",
    "CNT_USUS",
    "FECHA_OPERACION_TRF",
    "PROMEDIO_KWH_TRF",
    "TIPO_TAX",
    "NR_T",
    "LONG_CRUCETA",
    "PROMEDIO_KWH_VANO",
    "DDT",
]

WEATHER_VARIABLES = [
    "prep",
    "pres",
    "sp",
    "rh",
    "solar_rad",
    "temp",
    "wind_gust_spd",
    "wind_spd",
    "clouds",
]
WEATHER_OFFSETS = list(range(25))
WEATHER_COLUMNS = [f"{variable}_{offset}" for variable in WEATHER_VARIABLES for offset in WEATHER_OFFSETS]
SOURCE_COLUMNS = BASE_COLUMNS + WEATHER_COLUMNS

CAUSE_COLUMNS = ["COD_CAUSA", "DESC_CAUSA"]
EQUIPO_COLUMNS = ["FID_SW", "COD_EQ_PROTEGE", "CIRCUITO", "T_USUS_EQ_PROT", "CNT_VN_SW", "TIPO"]
VANO_COLUMNS = [
    "FID_VANO",
    "FID_SW",
    "LVSW",
    "CNT_VN",
    "PORC_APORTE_VANO",
    "LONGITUD",
    "CNT_FASES",
    "CONDUCTOR",
    "CALIBRE_NEUTRO",
    "NG_RED",
    "FECHA_OPERACION_VANO",
    "X1",
    "Y1",
    "X2",
    "Y2",
    "FID_APOYO_FIN",
    "NORMA",
    "TIPO_TAX",
    "NR_T",
    "LONG_CRUCETA",
    "PROMEDIO_KWH_VANO",
    "DDT",
]
APOYO_COLUMNS = [
    "FID_APOYO_FIN",
    "COD_APOYO_FIN",
    "ALTURA",
    "CANTIDAD_TIERRA",
    "PROPIETARIO",
    "CLASE",
    "ELEMENTO",
    "VAL_CRIT_APOYO",
]
TRAFO_PROFILE_COLUMNS = [
    "FID_TRAFO",
    "CODIGO",
    "CAPACIDAD_NOMINAL",
    "CNT_USUS",
    "FECHA_OPERACION_TRF",
    "PROMEDIO_KWH_TRF",
]
EVENT_COLUMNS = ["FECHA", "DURACION", "UITI", "TOT_USUS", "CNT_TRF", "COD_CAUSA"]
WEATHER_KEY_COLUMNS = ["FID_VANO", "FECHA"]
FACT_NATURAL_KEY_COLUMNS = ["event_id", "FID_VANO", "trafo_profile_id"]

TABLE_ORDER = [
    "causas",
    "equipos_proteccion",
    "apoyos",
    "vanos",
    "transformador_profiles",
    "eventos",
    "evento_vano_trafo",
    "clima_vano_fecha",
    "clima_vano_fecha_long",
]


class NormalizationError(RuntimeError):
    """Raised when a verification proves the split would be unsafe."""


def _load_pandas():
    try:
        import pandas as pd
    except ImportError as exc:
        raise SystemExit(
            "This script requires pandas. Install it in the execution environment, "
            "for example with `pip install pandas pyarrow`."
        ) from exc
    return pd


def _sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _prepare_output_dir(output_dir: Path, *, overwrite: bool) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        if not overwrite:
            raise NormalizationError(
                f"Output directory is not empty: {output_dir}. "
                "Pass --overwrite to replace generated outputs."
            )
        for child in output_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)


def _read_source(path: Path, *, encoding: str):
    pd = _load_pandas()
    df = pd.read_csv(
        path,
        dtype=str,
        keep_default_na=False,
        na_filter=False,
        encoding=encoding,
        low_memory=False,
    )
    return df


def _verify_schema(df: Any) -> None:
    actual = list(df.columns)
    if actual == SOURCE_COLUMNS:
        return

    missing = [column for column in SOURCE_COLUMNS if column not in actual]
    extra = [column for column in actual if column not in SOURCE_COLUMNS]
    wrong_positions = [
        {"position": index, "expected": expected, "actual": actual[index] if index < len(actual) else None}
        for index, expected in enumerate(SOURCE_COLUMNS)
        if index >= len(actual) or actual[index] != expected
    ][:20]
    raise NormalizationError(
        "Unexpected input schema. "
        f"Expected {len(SOURCE_COLUMNS)} columns, found {len(actual)}. "
        f"Missing={missing[:20]}, extra={extra[:20]}, first_wrong_positions={wrong_positions}"
    )


def _verify_no_missing_after_read(df: Any) -> None:
    missing = df.isna().sum()
    bad = missing[missing > 0]
    if not bad.empty:
        raise NormalizationError(
            "The source contains pandas NA values after reading. "
            "This should not happen because na_filter=False is used. "
            f"Columns: {bad.to_dict()}"
        )


def _verify_functional_dependency(
    df: Any,
    *,
    key_columns: list[str],
    dependent_columns: list[str],
    name: str,
    nonblank_key_column: str | None = None,
) -> dict[str, Any]:
    checked = df
    if nonblank_key_column is not None:
        checked = checked[checked[nonblank_key_column] != ""]

    columns = key_columns + [column for column in dependent_columns if column not in key_columns]
    distinct = checked[columns].drop_duplicates()
    violations = distinct.groupby(key_columns, dropna=False).size()
    violations = violations[violations > 1]
    if not violations.empty:
        examples = []
        for key in violations.head(5).index:
            if not isinstance(key, tuple):
                key = (key,)
            mask = distinct[key_columns].eq(list(key)).all(axis=1)
            examples.append(
                {
                    "key": dict(zip(key_columns, key, strict=True)),
                    "distinct_rows": distinct[mask].head(5).to_dict(orient="records"),
                }
            )
        raise NormalizationError(
            f"Functional dependency failed for {name}: "
            f"{key_columns} did not determine {dependent_columns}. Examples: {examples}"
        )

    return {
        "name": name,
        "key_columns": key_columns,
        "dependent_columns": dependent_columns,
        "checked_rows": int(len(checked)),
        "distinct_keys": int(distinct[key_columns].drop_duplicates().shape[0]),
        "status": "ok",
    }


def _unique_table(df: Any, *, columns: list[str], key_columns: list[str], name: str):
    dependent_columns = [column for column in columns if column not in key_columns]
    verification = _verify_functional_dependency(
        df,
        key_columns=key_columns,
        dependent_columns=dependent_columns,
        name=name,
    )
    table = df[columns].drop_duplicates(keep="first").reset_index(drop=True)
    if table[key_columns].duplicated().any():
        raise NormalizationError(f"{name} has duplicated keys after de-duplication: {key_columns}")
    return table, verification


def _add_surrogate_id(table: Any, *, id_column: str, prefix: str):
    table = table.copy()
    width = max(len(str(len(table))), 6)
    values = [f"{prefix}{index:0{width}d}" for index in range(1, len(table) + 1)]
    table.insert(0, id_column, values)
    return table


def _build_weather_long(weather_wide: Any):
    pd = _load_pandas()
    frames = []
    for offset in WEATHER_OFFSETS:
        columns = WEATHER_KEY_COLUMNS + [f"{variable}_{offset}" for variable in WEATHER_VARIABLES]
        frame = weather_wide[columns].rename(
            columns={f"{variable}_{offset}": variable for variable in WEATHER_VARIABLES}
        )
        frame = frame.copy()
        frame.insert(len(WEATHER_KEY_COLUMNS), "offset", str(offset))
        frames.append(frame)
    return pd.concat(frames, ignore_index=True)


def _build_tables(df: Any, *, weather_shape: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    pd = _load_pandas()
    validations: list[dict[str, Any]] = []

    causas, verification = _unique_table(
        df,
        columns=CAUSE_COLUMNS,
        key_columns=["COD_CAUSA"],
        name="causas",
    )
    validations.append(verification)

    equipos, verification = _unique_table(
        df,
        columns=EQUIPO_COLUMNS,
        key_columns=["FID_SW"],
        name="equipos_proteccion",
    )
    validations.append(verification)

    apoyos, verification = _unique_table(
        df,
        columns=APOYO_COLUMNS,
        key_columns=["FID_APOYO_FIN"],
        name="apoyos",
    )
    validations.append(verification)

    vanos, verification = _unique_table(
        df,
        columns=VANO_COLUMNS,
        key_columns=["FID_VANO"],
        name="vanos",
    )
    validations.append(verification)

    # Blank FID_TRAFO rows are not a real transformer identity in this file:
    # FECHA_OPERACION_TRF varies for blank FID_TRAFO. A profile surrogate keeps
    # all transformer-like source columns reconstructable without inventing a
    # false one-to-one relationship for missing transformers.
    validations.append(
        _verify_functional_dependency(
            df,
            key_columns=["FID_TRAFO"],
            dependent_columns=[column for column in TRAFO_PROFILE_COLUMNS if column != "FID_TRAFO"],
            name="transformadores_nonblank",
            nonblank_key_column="FID_TRAFO",
        )
    )
    trafo_profiles = (
        df[TRAFO_PROFILE_COLUMNS]
        .drop_duplicates(keep="first")
        .reset_index(drop=True)
    )
    trafo_profiles = _add_surrogate_id(trafo_profiles, id_column="trafo_profile_id", prefix="TRFPROF_")

    eventos = df[EVENT_COLUMNS].drop_duplicates(keep="first").reset_index(drop=True)
    eventos = _add_surrogate_id(eventos, id_column="event_id", prefix="EVT_")

    weather_wide, verification = _unique_table(
        df,
        columns=WEATHER_KEY_COLUMNS + WEATHER_COLUMNS,
        key_columns=WEATHER_KEY_COLUMNS,
        name="clima_vano_fecha",
    )
    validations.append(verification)

    fact = df[["row_id", "FID_VANO", "UITI_VANO"] + EVENT_COLUMNS + TRAFO_PROFILE_COLUMNS].merge(
        eventos[["event_id"] + EVENT_COLUMNS],
        on=EVENT_COLUMNS,
        how="left",
        sort=False,
        validate="many_to_one",
    )
    fact = fact.merge(
        trafo_profiles[["trafo_profile_id"] + TRAFO_PROFILE_COLUMNS],
        on=TRAFO_PROFILE_COLUMNS,
        how="left",
        sort=False,
        validate="many_to_one",
    )
    if fact["event_id"].isna().any() or fact["trafo_profile_id"].isna().any():
        raise NormalizationError("Some fact rows failed to map to event_id or trafo_profile_id.")

    fact = fact[["row_id"] + FACT_NATURAL_KEY_COLUMNS + ["UITI_VANO"]].copy()
    duplicated_fact_keys = fact[FACT_NATURAL_KEY_COLUMNS].duplicated(keep=False)
    if duplicated_fact_keys.any():
        examples = fact.loc[duplicated_fact_keys, ["row_id"] + FACT_NATURAL_KEY_COLUMNS].head(10)
        raise NormalizationError(
            "The proposed fact natural key is not unique. "
            f"Examples: {examples.to_dict(orient='records')}"
        )

    tables = {
        "causas": causas,
        "equipos_proteccion": equipos,
        "apoyos": apoyos,
        "vanos": vanos,
        "transformador_profiles": trafo_profiles,
        "eventos": eventos,
        "evento_vano_trafo": fact,
        "clima_vano_fecha": weather_wide,
    }

    if weather_shape in {"long", "both"}:
        weather_long = _build_weather_long(weather_wide)
        expected_long_rows = len(weather_wide) * len(WEATHER_OFFSETS)
        if len(weather_long) != expected_long_rows:
            raise NormalizationError(
                f"Long weather table row count mismatch: expected {expected_long_rows}, got {len(weather_long)}"
            )
        if weather_long[WEATHER_KEY_COLUMNS + ["offset"]].duplicated().any():
            raise NormalizationError("Long weather table has duplicated FID_VANO, FECHA, offset keys.")
        tables["clima_vano_fecha_long"] = weather_long

    if weather_shape == "long":
        del tables["clima_vano_fecha"]

    validations.append(
        {
            "name": "fact_natural_key",
            "key_columns": FACT_NATURAL_KEY_COLUMNS,
            "checked_rows": int(len(fact)),
            "distinct_keys": int(fact[FACT_NATURAL_KEY_COLUMNS].drop_duplicates().shape[0]),
            "status": "ok",
        }
    )

    return tables, validations


def _wide_weather_from_long(weather_long: Any):
    if weather_long is None:
        return None

    wide = weather_long.pivot(
        index=WEATHER_KEY_COLUMNS,
        columns="offset",
        values=WEATHER_VARIABLES,
    )
    wide.columns = [f"{variable}_{offset}" for variable, offset in wide.columns]
    wide = wide.reset_index()
    return wide[WEATHER_KEY_COLUMNS + WEATHER_COLUMNS]


def _reconstruct(tables: dict[str, Any]):
    weather_wide = tables.get("clima_vano_fecha")
    if weather_wide is None:
        weather_wide = _wide_weather_from_long(tables["clima_vano_fecha_long"])

    fact = tables["evento_vano_trafo"]
    reconstructed = fact.merge(
        tables["eventos"],
        on="event_id",
        how="left",
        sort=False,
        validate="many_to_one",
    )
    reconstructed = reconstructed.merge(
        tables["vanos"],
        on="FID_VANO",
        how="left",
        sort=False,
        validate="many_to_one",
    )
    reconstructed = reconstructed.merge(
        tables["equipos_proteccion"],
        on="FID_SW",
        how="left",
        sort=False,
        validate="many_to_one",
    )
    reconstructed = reconstructed.merge(
        tables["apoyos"],
        on="FID_APOYO_FIN",
        how="left",
        sort=False,
        validate="many_to_one",
    )
    reconstructed = reconstructed.merge(
        tables["causas"],
        on="COD_CAUSA",
        how="left",
        sort=False,
        validate="many_to_one",
    )
    reconstructed = reconstructed.merge(
        tables["transformador_profiles"],
        on="trafo_profile_id",
        how="left",
        sort=False,
        validate="many_to_one",
    )
    reconstructed = reconstructed.merge(
        weather_wide,
        on=WEATHER_KEY_COLUMNS,
        how="left",
        sort=False,
        validate="many_to_one",
    )

    missing_columns = [column for column in SOURCE_COLUMNS if column not in reconstructed.columns]
    if missing_columns:
        raise NormalizationError(f"Reconstruction is missing source columns: {missing_columns}")

    null_counts = reconstructed[SOURCE_COLUMNS].isna().sum()
    bad_nulls = null_counts[null_counts > 0]
    if not bad_nulls.empty:
        raise NormalizationError(f"Reconstruction produced nulls: {bad_nulls.to_dict()}")

    return reconstructed.sort_values("row_id", kind="stable").reset_index(drop=True)


def _verify_reconstruction(original: Any, tables: dict[str, Any]) -> dict[str, Any]:
    reconstructed = _reconstruct(tables)
    expected = original[SOURCE_COLUMNS].reset_index(drop=True)
    actual = reconstructed[SOURCE_COLUMNS].reset_index(drop=True)

    if expected.shape != actual.shape:
        raise NormalizationError(f"Reconstruction shape mismatch: expected {expected.shape}, got {actual.shape}")

    if not expected.equals(actual):
        mismatch_mask = expected.ne(actual)
        row_index, column_index = next(zip(*mismatch_mask.to_numpy().nonzero(), strict=True))
        column = SOURCE_COLUMNS[column_index]
        context = {
            "row_index": int(row_index),
            "column": column,
            "expected": expected.iat[row_index, column_index],
            "actual": actual.iat[row_index, column_index],
        }
        raise NormalizationError(f"Reconstruction mismatch. First mismatch: {context}")

    return {
        "name": "full_reconstruction",
        "checked_rows": int(len(expected)),
        "checked_columns": int(len(SOURCE_COLUMNS)),
        "status": "ok",
    }


def _write_table(table: Any, *, name: str, output_dir: Path, output_format: str) -> Path:
    if output_format == "parquet":
        path = output_dir / f"{name}.parquet"
        table.to_parquet(path, index=False)
        return path

    if output_format == "csv":
        path = output_dir / f"{name}.csv"
        table.to_csv(path, index=False, lineterminator="\n")
        return path

    raise ValueError(f"Unsupported output format: {output_format}")


def _write_outputs(
    tables: dict[str, Any],
    *,
    output_dir: Path,
    output_format: str,
) -> dict[str, str]:
    written = {}
    for name in TABLE_ORDER:
        table = tables.get(name)
        if table is None:
            continue
        path = _write_table(table, name=name, output_dir=output_dir, output_format=output_format)
        written[name] = str(path)
    return written


def normalize(
    *,
    input_path: Path,
    output_dir: Path,
    output_format: str,
    weather_shape: str,
    encoding: str,
    overwrite: bool,
    skip_file_hash: bool,
) -> dict[str, Any]:
    if not input_path.exists():
        raise NormalizationError(f"Input file does not exist: {input_path}")

    _prepare_output_dir(output_dir, overwrite=overwrite)

    source_hash = None if skip_file_hash else _sha256_file(input_path)
    df = _read_source(input_path, encoding=encoding)
    _verify_schema(df)
    _verify_no_missing_after_read(df)
    if df.empty:
        raise NormalizationError("Input file has no data rows.")

    df = df.copy()
    df.insert(0, "row_id", range(len(df)))

    tables, validations = _build_tables(df, weather_shape=weather_shape)
    validations.append(_verify_reconstruction(df, tables))

    written = _write_outputs(tables, output_dir=output_dir, output_format=output_format)
    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "input_path": str(input_path),
        "input_sha256": source_hash,
        "encoding": encoding,
        "output_dir": str(output_dir),
        "output_format": output_format,
        "weather_shape": weather_shape,
        "source_rows": int(len(df)),
        "source_columns": len(SOURCE_COLUMNS),
        "tables": {
            name: {
                "rows": int(len(table)),
                "columns": list(table.columns),
                "path": written.get(name),
            }
            for name, table in tables.items()
        },
        "validations": validations,
    }

    manifest_path = output_dir / "normalization_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Split Indicadores_vano_v3.csv into normalized tables and verify that "
            "the split reconstructs the original file exactly."
        )
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path.home() / "unal/CHEC/data/Indicadores_vano_v3.csv",
        help="Path to Indicadores_vano_v3.csv.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.home() / "unal/CHEC/data/Indicadores_vano_v3_normalized",
        help="Directory where normalized tables and the manifest will be written.",
    )
    parser.add_argument(
        "--output-format",
        choices=["parquet", "csv"],
        default="parquet",
        help="Output table format. Parquet is safer for preserving string IDs.",
    )
    parser.add_argument(
        "--weather-shape",
        choices=["wide", "long", "both"],
        default="wide",
        help=(
            "Write weather as one wide row per FID_VANO+FECHA, one long row per "
            "FID_VANO+FECHA+offset, or both."
        ),
    )
    parser.add_argument(
        "--encoding",
        default="utf-8-sig",
        help="CSV encoding used to read the source. The script does not repair text encoding.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace existing files in the output directory.",
    )
    parser.add_argument(
        "--skip-file-hash",
        action="store_true",
        help="Skip computing the source file SHA-256 hash.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        manifest = normalize(
            input_path=args.input,
            output_dir=args.output_dir,
            output_format=args.output_format,
            weather_shape=args.weather_shape,
            encoding=args.encoding,
            overwrite=args.overwrite,
            skip_file_hash=args.skip_file_hash,
        )
    except NormalizationError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc

    print("Normalization completed and verified.")
    print(f"Output directory: {manifest['output_dir']}")
    for name in TABLE_ORDER:
        table = manifest["tables"].get(name)
        if table is not None:
            print(f"  {name}: {table['rows']} rows -> {table['path']}")


if __name__ == "__main__":
    main()
