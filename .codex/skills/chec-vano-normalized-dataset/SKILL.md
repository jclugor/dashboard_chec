---
name: chec-vano-normalized-dataset
description: Use when working with the CHEC normalized vano dataset, Indicadores_vano_v3_normalized, including schema questions, table joins, validation checks, logical typing/casting, ML-ready feature assembly, leakage review, or troubleshooting the normalized Parquet outputs.
---

# CHEC Normalized Vano Dataset

## Core Workflow

1. Treat `/home/jclugor/unal/CHEC/data/Indicadores_vano_v3_normalized` as the canonical normalized dataset unless the user gives another path.
2. Read `normalization_manifest.json` first when verifying row counts, table paths, source hash, or reconstruction guarantees.
3. Load Parquet tables with pandas or PyArrow. Preserve the raw tables as lossless strings; create typed copies for analysis or modeling.
4. Use `evento_vano_trafo` as the central fact table and safest ML grain: one row per event, vano, and transformer profile.
5. Join outward from the fact table to `eventos`, `vanos`, `equipos_proteccion`, `apoyos`, `causas`, `transformador_profiles`, and `clima_vano_fecha`.

## References

- Read `references/schema.md` for table schemas, primary keys, foreign keys, row counts, blank-value notes, and validation guarantees.
- Read `references/ml_usage.md` before building modeling dataframes, casting columns, selecting targets, or deciding whether a field is leakage-prone.

## Handling Rules

- Never reinterpret raw identifier strings as numeric values, even when they look numeric.
- Convert numeric feature columns only in derived frames with `pd.to_numeric(errors="coerce")`.
- Convert `eventos.FECHA` and `clima_vano_fecha.FECHA` with `pd.to_datetime(errors="coerce")`.
- Treat `FECHA_OPERACION_VANO` and `FECHA_OPERACION_TRF` as nullable integer year fields, not event timestamps.
- Keep `trafo_profile_id`; it is required because blank `FID_TRAFO` rows have multiple distinct transformer-like profiles.
- Avoid direct impact leakage when modeling outage outcomes. Exclude fields such as `UITI`, `UITI_VANO`, `TOT_USUS`, `CNT_TRF`, and `DURACION` when they are the target or post-event consequences.
