#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class MunicipioLookupError(RuntimeError):
    """Raised when municipio lookup extraction cannot continue safely."""


def _load_pandas():
    try:
        import pandas as pd
    except ImportError as exc:
        raise SystemExit(
            "This script requires pandas and pyarrow. Install them in the execution "
            "environment, for example with `pip install pandas pyarrow`."
        ) from exc
    return pd


def _prepare_output_dir(output_dir: Path, *, overwrite: bool) -> None:
    if output_dir.exists() and any(output_dir.iterdir()):
        if not overwrite:
            raise MunicipioLookupError(
                f"Output directory is not empty: {output_dir}. Pass --overwrite to replace generated outputs."
            )
        for child in output_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)


def _read_parquet_table(path: Path):
    if not path.exists():
        raise MunicipioLookupError(f"Missing normalized table: {path}")
    return _load_pandas().read_parquet(path)


def _read_pickle_table(path: Path):
    if not path.exists():
        raise MunicipioLookupError(f"Missing legacy pickle: {path}")
    return _load_pandas().read_pickle(path)


def _clean_text(series: Any):
    pd = _load_pandas()
    return series.astype("string").fillna(pd.NA).str.strip().replace("", pd.NA)


def _latest_legacy_code_municipio(frame: Any, *, source_file: str):
    pd = _load_pandas()
    required_columns = {"CODE", "MUN"}
    missing = sorted(required_columns.difference(frame.columns))
    if missing:
        raise MunicipioLookupError(f"{source_file} is missing required columns: {missing}")

    legacy = frame.copy()
    legacy["legacy_code"] = _clean_text(legacy["CODE"])
    legacy["municipio"] = _clean_text(legacy["MUN"])
    if "FECHA" in legacy.columns:
        legacy["_sort_fecha"] = pd.to_datetime(legacy["FECHA"], errors="coerce")
    else:
        legacy["_sort_fecha"] = pd.NaT
    legacy["_source_order"] = range(len(legacy))
    legacy = legacy.dropna(subset=["legacy_code", "municipio"]).copy()

    conflict_counts = legacy.groupby("legacy_code", dropna=False)["municipio"].nunique(dropna=True)
    conflicts = conflict_counts[conflict_counts > 1].reset_index(name="distinct_municipio_count")
    if not conflicts.empty:
        examples = (
            legacy.loc[legacy["legacy_code"].isin(conflicts["legacy_code"])]
            .groupby(["legacy_code", "municipio"], dropna=False)
            .size()
            .reset_index(name="row_count")
            .sort_values(["legacy_code", "row_count"], ascending=[True, False])
        )
    else:
        examples = pd.DataFrame(columns=["legacy_code", "municipio", "row_count"])

    latest = (
        legacy.sort_values(["_sort_fecha", "_source_order"], kind="stable")
        .drop_duplicates("legacy_code", keep="last")[["legacy_code", "municipio"]]
        .reset_index(drop=True)
    )
    return latest, conflicts, examples


def _coverage_summary(frame: Any, municipio_column: str) -> dict[str, Any]:
    total = int(len(frame))
    resolved = int(frame[municipio_column].notna().sum()) if municipio_column in frame.columns else 0
    unresolved = total - resolved
    return {
        "rows": total,
        "resolved_rows": resolved,
        "unresolved_rows": unresolved,
        "coverage": round(resolved / total, 6) if total else 0.0,
    }


def extract_municipio_lookups(
    *,
    legacy_data_dir: Path,
    normalized_dir: Path,
    output_dir: Path,
    overwrite: bool,
) -> dict[str, Any]:
    pd = _load_pandas()
    _prepare_output_dir(output_dir, overwrite=overwrite)

    vanos = _read_parquet_table(normalized_dir / "vanos.parquet")
    apoyos = _read_parquet_table(normalized_dir / "apoyos.parquet")
    transformador_profiles = _read_parquet_table(normalized_dir / "transformador_profiles.parquet")
    evento_vano_trafo = _read_parquet_table(normalized_dir / "evento_vano_trafo.parquet")

    legacy_apoyos = _read_pickle_table(legacy_data_dir / "APOYOS.pkl")
    legacy_trafos = _read_pickle_table(legacy_data_dir / "TRAFOS.pkl")

    apoyo_mun, apoyo_conflicts, apoyo_conflict_examples = _latest_legacy_code_municipio(
        legacy_apoyos,
        source_file="APOYOS.pkl",
    )
    trafo_mun, trafo_conflicts, trafo_conflict_examples = _latest_legacy_code_municipio(
        legacy_trafos,
        source_file="TRAFOS.pkl",
    )

    span_lookup = (
        vanos.assign(
            FID_VANO=lambda df: _clean_text(df["FID_VANO"]),
            FID_APOYO_FIN=lambda df: _clean_text(df["FID_APOYO_FIN"]),
        )[["FID_VANO", "FID_APOYO_FIN"]]
        .merge(
            apoyos.assign(
                FID_APOYO_FIN=lambda df: _clean_text(df["FID_APOYO_FIN"]),
                COD_APOYO_FIN=lambda df: _clean_text(df["COD_APOYO_FIN"]),
            )[["FID_APOYO_FIN", "COD_APOYO_FIN"]],
            on="FID_APOYO_FIN",
            how="left",
            validate="many_to_one",
        )
        .merge(
            apoyo_mun,
            left_on="COD_APOYO_FIN",
            right_on="legacy_code",
            how="left",
            validate="many_to_one",
        )
        .drop(columns=["legacy_code"])
        .rename(columns={"municipio": "municipio_vano"})
    )
    span_lookup["municipio_source"] = span_lookup["municipio_vano"].where(
        span_lookup["municipio_vano"].isna(),
        "APOYOS.pkl:CODE",
    )
    span_lookup["municipio_confidence"] = span_lookup["municipio_vano"].notna().map(
        {True: "direct_code", False: "unresolved"}
    )

    transformer_lookup = (
        transformador_profiles.assign(
            trafo_profile_id=lambda df: _clean_text(df["trafo_profile_id"]),
            CODIGO=lambda df: _clean_text(df["CODIGO"]),
        )[["trafo_profile_id", "CODIGO"]]
        .merge(
            trafo_mun,
            left_on="CODIGO",
            right_on="legacy_code",
            how="left",
            validate="many_to_one",
        )
        .drop(columns=["legacy_code"])
        .rename(columns={"municipio": "municipio_trafo"})
    )
    transformer_lookup["municipio_source"] = transformer_lookup["municipio_trafo"].where(
        transformer_lookup["municipio_trafo"].isna(),
        "TRAFOS.pkl:CODE",
    )
    transformer_lookup["municipio_confidence"] = transformer_lookup["municipio_trafo"].notna().map(
        {True: "direct_code", False: "unresolved"}
    )

    fact_coverage = (
        evento_vano_trafo.assign(
            FID_VANO=lambda df: _clean_text(df["FID_VANO"]),
            trafo_profile_id=lambda df: _clean_text(df["trafo_profile_id"]),
        )[["row_id", "FID_VANO", "trafo_profile_id"]]
        .merge(span_lookup[["FID_VANO", "municipio_vano"]], on="FID_VANO", how="left", validate="many_to_one")
        .merge(
            transformer_lookup[["trafo_profile_id", "municipio_trafo"]],
            on="trafo_profile_id",
            how="left",
            validate="many_to_one",
        )
    )
    fact_coverage["municipio"] = fact_coverage["municipio_vano"].combine_first(fact_coverage["municipio_trafo"])

    unresolved_spans = span_lookup.loc[span_lookup["municipio_vano"].isna()].copy()
    unresolved_transformers = transformer_lookup.loc[transformer_lookup["municipio_trafo"].isna()].copy()
    unresolved_facts = fact_coverage.loc[fact_coverage["municipio"].isna()].copy()

    span_lookup.to_parquet(output_dir / "span_municipio_lookup.parquet", index=False)
    transformer_lookup.to_parquet(output_dir / "transformer_municipio_lookup.parquet", index=False)
    unresolved_spans.to_csv(output_dir / "unresolved_vanos.csv", index=False, lineterminator="\n")
    unresolved_transformers.to_csv(output_dir / "unresolved_transformador_profiles.csv", index=False, lineterminator="\n")
    unresolved_facts.head(5000).to_csv(output_dir / "unresolved_evento_vano_trafo_sample.csv", index=False, lineterminator="\n")
    apoyo_conflicts.to_csv(output_dir / "legacy_apoyos_municipio_conflicts.csv", index=False, lineterminator="\n")
    trafo_conflicts.to_csv(output_dir / "legacy_trafos_municipio_conflicts.csv", index=False, lineterminator="\n")
    apoyo_conflict_examples.to_csv(
        output_dir / "legacy_apoyos_municipio_conflict_examples.csv",
        index=False,
        lineterminator="\n",
    )
    trafo_conflict_examples.to_csv(
        output_dir / "legacy_trafos_municipio_conflict_examples.csv",
        index=False,
        lineterminator="\n",
    )

    manifest = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "legacy_data_dir": str(legacy_data_dir),
        "normalized_dir": str(normalized_dir),
        "output_dir": str(output_dir),
        "source_files": {
            "apoyos": str(legacy_data_dir / "APOYOS.pkl"),
            "trafos": str(legacy_data_dir / "TRAFOS.pkl"),
        },
        "direct_join_policy": {
            "vanos": "vanos.FID_APOYO_FIN -> apoyos.COD_APOYO_FIN -> APOYOS.pkl.CODE -> MUN",
            "transformador_profiles": "transformador_profiles.CODIGO -> TRAFOS.pkl.CODE -> MUN",
            "fallbacks": "none; unresolved rows are audited only",
        },
        "coverage": {
            "vanos": _coverage_summary(span_lookup, "municipio_vano"),
            "transformador_profiles": _coverage_summary(transformer_lookup, "municipio_trafo"),
            "evento_vano_trafo": _coverage_summary(fact_coverage, "municipio"),
        },
        "legacy_conflicts": {
            "apoyos_conflicting_codes": int(len(apoyo_conflicts)),
            "trafos_conflicting_codes": int(len(trafo_conflicts)),
        },
        "outputs": {
            "span_lookup": str(output_dir / "span_municipio_lookup.parquet"),
            "transformer_lookup": str(output_dir / "transformer_municipio_lookup.parquet"),
            "unresolved_vanos": str(output_dir / "unresolved_vanos.csv"),
            "unresolved_transformador_profiles": str(output_dir / "unresolved_transformador_profiles.csv"),
            "unresolved_evento_vano_trafo_sample": str(output_dir / "unresolved_evento_vano_trafo_sample.csv"),
        },
    }
    (output_dir / "municipio_lookup_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract municipio lookup tables from legacy CHEC dashboard pickle files."
    )
    parser.add_argument("--legacy-data-dir", type=Path, required=True)
    parser.add_argument("--normalized-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        manifest = extract_municipio_lookups(
            legacy_data_dir=args.legacy_data_dir,
            normalized_dir=args.normalized_dir,
            output_dir=args.output_dir,
            overwrite=args.overwrite,
        )
    except MunicipioLookupError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc

    coverage = manifest["coverage"]
    print("Municipio lookup extraction completed.")
    print(f"Output directory: {manifest['output_dir']}")
    for name in ("vanos", "transformador_profiles", "evento_vano_trafo"):
        item = coverage[name]
        print(f"  {name}: {item['resolved_rows']}/{item['rows']} resolved ({item['coverage']:.2%})")


if __name__ == "__main__":
    main()
