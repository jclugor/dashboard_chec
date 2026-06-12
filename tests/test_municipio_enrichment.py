from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str) -> ModuleType:
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_normalized_fixture(normalized_dir: Path) -> None:
    normalized_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"COD_CAUSA": ["1"], "DESC_CAUSA": ["Viento"]}).to_parquet(
        normalized_dir / "causas.parquet",
        index=False,
    )
    pd.DataFrame(
        {
            "FID_SW": ["SW1"],
            "COD_EQ_PROTEGE": ["EQ1"],
            "CIRCUITO": ["CIR1"],
            "T_USUS_EQ_PROT": ["10"],
            "CNT_VN_SW": ["3"],
            "TIPO": ["S"],
        }
    ).to_parquet(normalized_dir / "equipos_proteccion.parquet", index=False)
    pd.DataFrame(
        {
            "FID_APOYO_FIN": ["A1", "A2", "A3"],
            "COD_APOYO_FIN": ["P1", "P2", "P_MISSING"],
            "ALTURA": ["", "", ""],
            "CANTIDAD_TIERRA": ["", "", ""],
            "PROPIETARIO": ["", "", ""],
            "CLASE": ["", "", ""],
            "ELEMENTO": ["", "", ""],
            "VAL_CRIT_APOYO": ["", "", ""],
        }
    ).to_parquet(normalized_dir / "apoyos.parquet", index=False)
    pd.DataFrame(
        {
            "FID_VANO": ["V1", "V2", "V3"],
            "FID_SW": ["SW1", "SW1", "SW1"],
            "LVSW": ["", "", ""],
            "CNT_VN": ["", "", ""],
            "PORC_APORTE_VANO": ["", "", ""],
            "LONGITUD": ["1", "1", "1"],
            "CNT_FASES": ["", "", ""],
            "CONDUCTOR": ["", "", ""],
            "CALIBRE_NEUTRO": ["", "", ""],
            "NG_RED": ["", "", ""],
            "FECHA_OPERACION_VANO": ["", "", ""],
            "X1": ["-75.0", "-75.1", "-75.2"],
            "Y1": ["5.0", "5.1", "5.2"],
            "X2": ["-75.0", "-75.1", "-75.2"],
            "Y2": ["5.0", "5.1", "5.2"],
            "FID_APOYO_FIN": ["A1", "A2", "A3"],
            "NORMA": ["", "", ""],
            "TIPO_TAX": ["", "", ""],
            "NR_T": ["", "", ""],
            "LONG_CRUCETA": ["", "", ""],
            "PROMEDIO_KWH_VANO": ["", "", ""],
            "DDT": ["", "", ""],
        }
    ).to_parquet(normalized_dir / "vanos.parquet", index=False)
    pd.DataFrame(
        {
            "trafo_profile_id": ["T1", "T2"],
            "FID_TRAFO": ["F1", ""],
            "CODIGO": ["TR1", "TR_MISSING"],
            "CAPACIDAD_NOMINAL": ["", ""],
            "CNT_USUS": ["", ""],
            "FECHA_OPERACION_TRF": ["", ""],
            "PROMEDIO_KWH_TRF": ["", ""],
        }
    ).to_parquet(normalized_dir / "transformador_profiles.parquet", index=False)
    pd.DataFrame(
        {
            "event_id": ["E1", "E2"],
            "FECHA": ["2024-01-01", "2024-01-02"],
            "DURACION": ["1", "1"],
            "UITI": ["1", "1"],
            "TOT_USUS": ["1", "1"],
            "CNT_TRF": ["1", "1"],
            "COD_CAUSA": ["1", "1"],
        }
    ).to_parquet(normalized_dir / "eventos.parquet", index=False)
    pd.DataFrame(
        {
            "row_id": [0, 1, 2],
            "event_id": ["E1", "E1", "E2"],
            "FID_VANO": ["V1", "V2", "V3"],
            "trafo_profile_id": ["T1", "T2", "T2"],
            "UITI_VANO": ["1", "1", "1"],
        }
    ).to_parquet(normalized_dir / "evento_vano_trafo.parquet", index=False)
    pd.DataFrame({"FID_VANO": ["V1"], "FECHA": ["2024-01-01"]}).to_parquet(
        normalized_dir / "clima_vano_fecha.parquet",
        index=False,
    )
    (normalized_dir / "normalization_manifest.json").write_text(
        """{
  "tables": {
    "vanos": {"rows": 3, "columns": [], "path": ""},
    "transformador_profiles": {"rows": 2, "columns": [], "path": ""}
  }
}
""",
        encoding="utf-8",
    )


def _write_legacy_fixture(legacy_dir: Path) -> None:
    legacy_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "CODE": ["P1", "P2", "P2", "UNUSED"],
            "MUN": ["MANIZALES", "NEIRA", "CHINCHINA", "MARMATO"],
            "FECHA": ["2020-01-01", "2020-01-01", "2021-01-01", "2020-01-01"],
        }
    ).to_pickle(legacy_dir / "APOYOS.pkl")
    pd.DataFrame(
        {
            "CODE": ["TR1", "TR_CONFLICT", "TR_CONFLICT"],
            "MUN": ["MANIZALES", "NEIRA", "MANIZALES"],
            "FECHA": ["2020-01-01", "2020-01-01", "2021-01-01"],
        }
    ).to_pickle(legacy_dir / "TRAFOS.pkl")


def test_extract_municipio_lookups_records_conflicts_and_unresolved_rows(tmp_path: Path) -> None:
    extract_module = _load_script("extract_municipio_lookups")
    normalized_dir = tmp_path / "normalized"
    legacy_dir = tmp_path / "legacy"
    output_dir = tmp_path / "lookups"
    _write_normalized_fixture(normalized_dir)
    _write_legacy_fixture(legacy_dir)

    manifest = extract_module.extract_municipio_lookups(
        legacy_data_dir=legacy_dir,
        normalized_dir=normalized_dir,
        output_dir=output_dir,
        overwrite=True,
    )

    assert manifest["coverage"]["vanos"]["resolved_rows"] == 2
    assert manifest["coverage"]["transformador_profiles"]["resolved_rows"] == 1
    assert manifest["coverage"]["evento_vano_trafo"]["resolved_rows"] == 2
    assert manifest["legacy_conflicts"]["apoyos_conflicting_codes"] == 1
    assert manifest["legacy_conflicts"]["trafos_conflicting_codes"] == 1
    assert (output_dir / "unresolved_vanos.csv").read_text(encoding="utf-8").count("\n") == 2


def test_enrich_normalized_dataset_preserves_rows_and_adds_only_asset_municipio_columns(tmp_path: Path) -> None:
    extract_module = _load_script("extract_municipio_lookups")
    enrich_module = _load_script("enrich_normalized_vano_municipios")
    normalized_dir = tmp_path / "normalized"
    legacy_dir = tmp_path / "legacy"
    lookup_dir = tmp_path / "lookups"
    output_dir = tmp_path / "enriched"
    _write_normalized_fixture(normalized_dir)
    _write_legacy_fixture(legacy_dir)
    extract_module.extract_municipio_lookups(
        legacy_data_dir=legacy_dir,
        normalized_dir=normalized_dir,
        output_dir=lookup_dir,
        overwrite=True,
    )

    manifest = enrich_module.enrich_normalized_dataset(
        normalized_dir=normalized_dir,
        lookup_dir=lookup_dir,
        output_dir=output_dir,
        min_vano_coverage=0.60,
        min_fact_coverage=0.60,
        overwrite=True,
    )

    vanos = pd.read_parquet(output_dir / "vanos.parquet")
    transformers = pd.read_parquet(output_dir / "transformador_profiles.parquet")
    eventos = pd.read_parquet(output_dir / "eventos.parquet")
    assert len(vanos) == 3
    assert len(transformers) == 2
    assert {"municipio", "municipio_source", "municipio_confidence"}.issubset(vanos.columns)
    assert {"municipio", "municipio_source", "municipio_confidence"}.issubset(transformers.columns)
    assert "municipio" not in eventos.columns
    assert manifest["municipio_enrichment"]["coverage"]["vanos"]["resolved_rows"] == 2
    assert (output_dir / "municipio_enrichment" / "municipio_lookup_manifest.json").exists()
