#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TABLE_FILES = [
    "causas.parquet",
    "equipos_proteccion.parquet",
    "apoyos.parquet",
    "vanos.parquet",
    "transformador_profiles.parquet",
    "eventos.parquet",
    "evento_vano_trafo.parquet",
    "clima_vano_fecha.parquet",
]

AUDIT_FILES = [
    "municipio_lookup_manifest.json",
    "unresolved_vanos.csv",
    "unresolved_transformador_profiles.csv",
    "unresolved_evento_vano_trafo_sample.csv",
    "legacy_apoyos_municipio_conflicts.csv",
    "legacy_trafos_municipio_conflicts.csv",
    "legacy_apoyos_municipio_conflict_examples.csv",
    "legacy_trafos_municipio_conflict_examples.csv",
]


class MunicipioEnrichmentError(RuntimeError):
    """Raised when municipio enrichment cannot continue safely."""


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
            raise MunicipioEnrichmentError(
                f"Output directory is not empty: {output_dir}. Pass --overwrite to replace generated outputs."
            )
        for child in output_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
    output_dir.mkdir(parents=True, exist_ok=True)


def _clean_text(series: Any):
    pd = _load_pandas()
    return series.astype("string").fillna(pd.NA).str.strip().replace("", pd.NA)


def _coverage_summary(frame: Any, municipio_column: str) -> dict[str, Any]:
    total = int(len(frame))
    resolved = int(frame[municipio_column].notna().sum()) if municipio_column in frame.columns else 0
    return {
        "rows": total,
        "resolved_rows": resolved,
        "unresolved_rows": total - resolved,
        "coverage": round(resolved / total, 6) if total else 0.0,
    }


def _read_manifest(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise MunicipioEnrichmentError(f"Missing manifest: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _copy_unmodified_tables(normalized_dir: Path, output_dir: Path) -> None:
    for file_name in TABLE_FILES:
        source = normalized_dir / file_name
        if not source.exists():
            raise MunicipioEnrichmentError(f"Missing normalized table: {source}")
        if file_name in {"vanos.parquet", "transformador_profiles.parquet"}:
            continue
        shutil.copy2(source, output_dir / file_name)


def _copy_audit_files(lookup_dir: Path, output_dir: Path) -> dict[str, str]:
    audit_dir = output_dir / "municipio_enrichment"
    audit_dir.mkdir(parents=True, exist_ok=True)
    copied: dict[str, str] = {}
    for file_name in AUDIT_FILES:
        source = lookup_dir / file_name
        if not source.exists():
            continue
        target = audit_dir / file_name
        shutil.copy2(source, target)
        copied[file_name] = str(target)
    return copied


def enrich_normalized_dataset(
    *,
    normalized_dir: Path,
    lookup_dir: Path,
    output_dir: Path,
    min_vano_coverage: float,
    min_fact_coverage: float,
    overwrite: bool,
) -> dict[str, Any]:
    pd = _load_pandas()
    _prepare_output_dir(output_dir, overwrite=overwrite)
    _copy_unmodified_tables(normalized_dir, output_dir)
    copied_audit_files = _copy_audit_files(lookup_dir, output_dir)

    manifest = _read_manifest(normalized_dir / "normalization_manifest.json")
    lookup_manifest = _read_manifest(lookup_dir / "municipio_lookup_manifest.json")

    vanos = pd.read_parquet(normalized_dir / "vanos.parquet")
    transformador_profiles = pd.read_parquet(normalized_dir / "transformador_profiles.parquet")
    evento_vano_trafo = pd.read_parquet(normalized_dir / "evento_vano_trafo.parquet")
    span_lookup = pd.read_parquet(lookup_dir / "span_municipio_lookup.parquet")
    transformer_lookup = pd.read_parquet(lookup_dir / "transformer_municipio_lookup.parquet")

    enriched_vanos = (
        vanos.assign(FID_VANO=lambda df: _clean_text(df["FID_VANO"]))
        .merge(
            span_lookup.assign(FID_VANO=lambda df: _clean_text(df["FID_VANO"]))[
                ["FID_VANO", "municipio_vano", "municipio_source", "municipio_confidence"]
            ],
            on="FID_VANO",
            how="left",
            validate="one_to_one",
        )
        .rename(
            columns={
                "municipio_vano": "municipio",
                "municipio_source": "municipio_source",
                "municipio_confidence": "municipio_confidence",
            }
        )
    )
    enriched_vanos["municipio"] = _clean_text(enriched_vanos["municipio"])
    enriched_vanos["municipio_source"] = _clean_text(enriched_vanos["municipio_source"])
    enriched_vanos["municipio_confidence"] = _clean_text(enriched_vanos["municipio_confidence"]).fillna("unresolved")

    enriched_transformers = (
        transformador_profiles.assign(trafo_profile_id=lambda df: _clean_text(df["trafo_profile_id"]))
        .merge(
            transformer_lookup.assign(trafo_profile_id=lambda df: _clean_text(df["trafo_profile_id"]))[
                ["trafo_profile_id", "municipio_trafo", "municipio_source", "municipio_confidence"]
            ],
            on="trafo_profile_id",
            how="left",
            validate="one_to_one",
        )
        .rename(
            columns={
                "municipio_trafo": "municipio",
                "municipio_source": "municipio_source",
                "municipio_confidence": "municipio_confidence",
            }
        )
    )
    enriched_transformers["municipio"] = _clean_text(enriched_transformers["municipio"])
    enriched_transformers["municipio_source"] = _clean_text(enriched_transformers["municipio_source"])
    enriched_transformers["municipio_confidence"] = _clean_text(enriched_transformers["municipio_confidence"]).fillna("unresolved")

    fact_coverage = (
        evento_vano_trafo.assign(
            FID_VANO=lambda df: _clean_text(df["FID_VANO"]),
            trafo_profile_id=lambda df: _clean_text(df["trafo_profile_id"]),
        )[["row_id", "FID_VANO", "trafo_profile_id"]]
        .merge(enriched_vanos[["FID_VANO", "municipio"]].rename(columns={"municipio": "municipio_vano"}), on="FID_VANO", how="left", validate="many_to_one")
        .merge(
            enriched_transformers[["trafo_profile_id", "municipio"]].rename(columns={"municipio": "municipio_trafo"}),
            on="trafo_profile_id",
            how="left",
            validate="many_to_one",
        )
    )
    fact_coverage["municipio"] = fact_coverage["municipio_vano"].combine_first(fact_coverage["municipio_trafo"])

    vano_coverage = _coverage_summary(enriched_vanos, "municipio")
    fact_summary = _coverage_summary(fact_coverage, "municipio")
    if vano_coverage["coverage"] < min_vano_coverage:
        raise MunicipioEnrichmentError(
            f"Vano municipio coverage {vano_coverage['coverage']:.2%} is below required {min_vano_coverage:.2%}."
        )
    if fact_summary["coverage"] < min_fact_coverage:
        raise MunicipioEnrichmentError(
            f"Fact municipio coverage {fact_summary['coverage']:.2%} is below required {min_fact_coverage:.2%}."
        )

    enriched_vanos.to_parquet(output_dir / "vanos.parquet", index=False)
    enriched_transformers.to_parquet(output_dir / "transformador_profiles.parquet", index=False)

    enrichment = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_lookup_manifest": str(lookup_dir / "municipio_lookup_manifest.json"),
        "policy": lookup_manifest.get("direct_join_policy", {}),
        "source_files": lookup_manifest.get("source_files", {}),
        "coverage": {
            "vanos": vano_coverage,
            "transformador_profiles": _coverage_summary(enriched_transformers, "municipio"),
            "evento_vano_trafo": fact_summary,
        },
        "legacy_conflicts": lookup_manifest.get("legacy_conflicts", {}),
        "unresolved_outputs": {
            "unresolved_vanos": str(lookup_dir / "unresolved_vanos.csv"),
            "unresolved_transformador_profiles": str(lookup_dir / "unresolved_transformador_profiles.csv"),
            "unresolved_evento_vano_trafo_sample": str(lookup_dir / "unresolved_evento_vano_trafo_sample.csv"),
        },
        "uploaded_audit_files": copied_audit_files,
    }
    manifest["output_dir"] = str(output_dir)
    manifest["municipio_enrichment"] = enrichment
    for table_name, frame in {
        "vanos": enriched_vanos,
        "transformador_profiles": enriched_transformers,
    }.items():
        manifest["tables"][table_name]["rows"] = int(len(frame))
        manifest["tables"][table_name]["columns"] = list(frame.columns)
        manifest["tables"][table_name]["path"] = str(output_dir / f"{table_name}.parquet")

    (output_dir / "normalization_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create an enriched normalized CHEC dataset with municipio columns."
    )
    parser.add_argument("--normalized-dir", type=Path, required=True)
    parser.add_argument("--lookup-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--min-vano-coverage", type=float, default=0.95)
    parser.add_argument("--min-fact-coverage", type=float, default=0.92)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        manifest = enrich_normalized_dataset(
            normalized_dir=args.normalized_dir,
            lookup_dir=args.lookup_dir,
            output_dir=args.output_dir,
            min_vano_coverage=args.min_vano_coverage,
            min_fact_coverage=args.min_fact_coverage,
            overwrite=args.overwrite,
        )
    except MunicipioEnrichmentError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc

    enrichment = manifest["municipio_enrichment"]
    print("Municipio enrichment completed.")
    print(f"Output directory: {manifest['output_dir']}")
    for name in ("vanos", "transformador_profiles", "evento_vano_trafo"):
        item = enrichment["coverage"][name]
        print(f"  {name}: {item['resolved_rows']}/{item['rows']} resolved ({item['coverage']:.2%})")


if __name__ == "__main__":
    main()
