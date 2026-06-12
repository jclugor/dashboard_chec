# Codex Plan: Upgrade CHEC Databricks App to the Normalized Vano Dataset

## Purpose

Upgrade the current Databricks-deployed dashboard so it no longer depends on the old pickle/XLSX tabular sources and instead uses the new normalized Parquet dataset described by the Codex skill `chec-vano-normalized-dataset`.

The migration must:

1. Upload the new normalized dataset into the Databricks raw source volume.
2. Delete the current structured/tabular Databricks data generated from the old source files.
3. Preserve all PDF/unstructured assets and existing chatbot documents.
4. Rebuild the bronze, silver, and gold data products from the normalized Parquet tables.
5. Keep the currently implemented Databricks App functionality working: summary, map, probability explorer, time-series interpretability, and chatbot/context tools.
6. Add the boss/advisor’s cost-aware multi-agent idea only where it fits the app features that already exist.
7. Explicitly leave graph reasoning, real ML model outputs, scenario simulation, economic evaluation, and formal reports as future work until their upstream components are implemented.

---

## Important assumptions to confirm before execution

Codex should proceed with these assumptions unless the developer/user changes them:

1. **Canonical local source path** is:

   ```text
   /home/jclugor/unal/CHEC/data/Indicadores_vano_v3_normalized
   ```

2. **Databricks target source location** should be:

   ```text
   /Volumes/<catalog_name>/raw/<source_volume_name>/Indicadores_vano_v3_normalized
   ```

   Current defaults in the repo are:

   ```text
   catalog_name = chec_dbx_demo
   source_volume_name = source_files
   ```

3. **Do not delete PDFs or chatbot document volumes.** The cleanup must only remove old structured source files and old Delta tables/views generated from the pickle/XLSX pipeline.

4. The new normalized dataset does **not** expose direct `SAIDI` and `SAIFI` columns. It exposes `UITI`, `UITI_VANO`, `TOT_USUS`, `CNT_TRF`, and `DURACION`. Therefore, the app should be upgraded from hard-coded `SAIDI/SAIFI` language to a more general **impact metrics** model, with `UITI` as the primary current impact metric.

5. `DURACION` unit must be confirmed before labeling it as hours. Until confirmed, label it as `Duración fuente` or `duration_raw` in technical contexts. Do not silently call it hours unless the data owner confirms the unit.

---

## Source dataset rules from the skill

When implementing code, follow these rules strictly:

1. Read `normalization_manifest.json` first when validating row counts, table paths, source hash, or reconstruction guarantees.
2. Load the source tables from Parquet.
3. Preserve raw tables as lossless strings. Apply logical casting only in derived silver/gold/model frames.
4. Use `evento_vano_trafo` as the central fact table and safest ML/data-product grain:

   ```text
   one row per event + vano + transformer profile
   ```

5. Join outward from `evento_vano_trafo` to:

   ```text
   eventos
   vanos
   equipos_proteccion
   apoyos
   causas
   transformador_profiles
   clima_vano_fecha
   ```

6. Never reinterpret raw identifier strings as numeric values, even when they look numeric.
7. Convert numeric features only in derived frames using explicit casts.
8. Convert `eventos.FECHA` and `clima_vano_fecha.FECHA` to timestamps/dates in derived frames.
9. Treat `FECHA_OPERACION_VANO` and `FECHA_OPERACION_TRF` as nullable integer year fields, not event timestamps.
10. Keep `trafo_profile_id`; it is required because blank `FID_TRAFO` rows can represent distinct transformer-like profiles.
11. Avoid direct impact leakage for future modeling. Exclude `UITI`, `UITI_VANO`, `TOT_USUS`, `CNT_TRF`, and `DURACION` when they are the target or post-event consequences.

Expected normalized source tables:

```text
causas.parquet
  COD_CAUSA, DESC_CAUSA

equipos_proteccion.parquet
  FID_SW, COD_EQ_PROTEGE, CIRCUITO, T_USUS_EQ_PROT, CNT_VN_SW, TIPO

apoyos.parquet
  FID_APOYO_FIN, COD_APOYO_FIN, ALTURA, CANTIDAD_TIERRA, PROPIETARIO, CLASE, ELEMENTO, VAL_CRIT_APOYO

vanos.parquet
  FID_VANO, FID_SW, LVSW, CNT_VN, PORC_APORTE_VANO, LONGITUD, CNT_FASES, CONDUCTOR,
  CALIBRE_NEUTRO, NG_RED, FECHA_OPERACION_VANO, X1, Y1, X2, Y2, FID_APOYO_FIN, NORMA,
  TIPO_TAX, NR_T, LONG_CRUCETA, PROMEDIO_KWH_VANO, DDT

transformador_profiles.parquet
  trafo_profile_id, FID_TRAFO, CODIGO, CAPACIDAD_NOMINAL, CNT_USUS, FECHA_OPERACION_TRF,
  PROMEDIO_KWH_TRF

eventos.parquet
  event_id, FECHA, DURACION, UITI, TOT_USUS, CNT_TRF, COD_CAUSA

evento_vano_trafo.parquet
  row_id, event_id, FID_VANO, trafo_profile_id, UITI_VANO

clima_vano_fecha.parquet
  FID_VANO, FECHA, 225 weather columns: prep_0..clouds_24
```

Expected validation guarantees from the skill:

```text
source rows: 159,470
source columns: 273
causas rows: 25
equipos_proteccion rows: 2,208
apoyos rows: 26,746
vanos rows: 27,390
transformador_profiles rows: 8,398
eventos rows: 7,079
evento_vano_trafo rows: 159,470
clima_vano_fecha rows: 142,158
full reconstruction: normalized tables reconstruct the original 159,470 x 273 dataframe exactly
```

---

## Current app functionality to preserve

The Databricks App currently has these implemented features and they must remain in scope:

```text
Summary page
Map page
Probability explorer page
Time-series interpretability panel
Chatbot page
Conversation/feedback storage
Context tools and agent context views
Optional RAG/AI Search over existing documents
Observability hooks
```

Do **not** add new product modules that depend on unavailable components. Specifically, do not implement these in this migration:

```text
full graph reasoning agent
real ML model scoring/masks/predictions
what-if scenario simulator
technical-economic evaluator
formal evidence report generator
regulatory auto-update workflow
```

Those are future work.

---

## Target architecture after this migration

```text
Local normalized Parquet dataset
  /home/jclugor/unal/CHEC/data/Indicadores_vano_v3_normalized
        |
        | upload script
        v
Unity Catalog raw volume
  /Volumes/<catalog>/raw/<source_volume>/Indicadores_vano_v3_normalized
        |
        | Databricks Jobs / notebooks
        v
Bronze Delta tables
  bronze_causas
  bronze_equipos_proteccion
  bronze_apoyos
  bronze_vanos
  bronze_transformador_profiles
  bronze_eventos
  bronze_evento_vano_trafo
  bronze_clima_vano_fecha
        |
        v
Silver canonical tables
  silver_vano_fact
  silver_events
  silver_assets
  silver_weather_daily
  silver_data_quality_results
        |
        v
Gold app-facing tables/views
  gold_impact_daily
  gold_impact_circuit_summary
  gold_timeseries_event_details
  gold_timeseries_daily_attribution
  gold_timeseries_environment_daily
  gold_probability_inputs
  gold_map_points
  gold_map_line_segments
  gold_map_filter_index
  gold_map_event_days
  gold_agent_view_context
  gold_agent_event_context
  gold_agent_asset_context
  gold_agent_circuit_history
        |
        v
Databricks App
  Dash UI
  Databricks SQL data service
  cost-aware bounded agent workflow
  existing RAG/document tools preserved
```

---

## Migration strategy

Use a two-layer approach:

1. **Canonical new tables** with correct semantics and names, such as `gold_impact_daily` and `silver_vano_fact`.
2. **Temporary compatibility views only where needed** while app code is being refactored away from old `SAIDI/SAIFI` assumptions.

Preferred end state: the app should use the new canonical impact tables and generic metric labels instead of treating `UITI` as fake `SAIDI`.

Allowed short-term compatibility tactic:

```text
Create compatibility views with old names only as a bridge during development,
but mark them clearly as deprecated and do not hide the fact that UITI is the available impact metric.
```

Do not silently map `UITI` to `SAIDI` in user-facing text.

---

## Implementation plan for Codex

### PR 1 — Add normalized dataset manifest and upload script

#### 1.1 Add a new Databricks manifest

Create:

```text
databricks/manifests/normalized_vano_assets.json
```

Suggested structure:

```json
{
  "bundle_name": "chec_phase1",
  "dataset_name": "Indicadores_vano_v3_normalized",
  "dataset_manifest": "Indicadores_vano_v3_normalized/normalization_manifest.json",
  "source_root_folder": "data",
  "raw_sources": [
    {
      "logical_name": "causas",
      "relative_path": "Indicadores_vano_v3_normalized/causas.parquet",
      "bronze_table": "bronze_causas",
      "load_mode": "parquet",
      "primary_key": ["COD_CAUSA"],
      "required_columns": ["COD_CAUSA", "DESC_CAUSA"],
      "date_columns": []
    },
    {
      "logical_name": "equipos_proteccion",
      "relative_path": "Indicadores_vano_v3_normalized/equipos_proteccion.parquet",
      "bronze_table": "bronze_equipos_proteccion",
      "load_mode": "parquet",
      "primary_key": ["FID_SW"],
      "required_columns": ["FID_SW", "COD_EQ_PROTEGE", "CIRCUITO"],
      "date_columns": []
    },
    {
      "logical_name": "apoyos",
      "relative_path": "Indicadores_vano_v3_normalized/apoyos.parquet",
      "bronze_table": "bronze_apoyos",
      "load_mode": "parquet",
      "primary_key": ["FID_APOYO_FIN"],
      "required_columns": ["FID_APOYO_FIN", "COD_APOYO_FIN"],
      "date_columns": []
    },
    {
      "logical_name": "vanos",
      "relative_path": "Indicadores_vano_v3_normalized/vanos.parquet",
      "bronze_table": "bronze_vanos",
      "load_mode": "parquet",
      "primary_key": ["FID_VANO"],
      "required_columns": ["FID_VANO", "FID_SW", "X1", "Y1", "X2", "Y2", "FID_APOYO_FIN"],
      "date_columns": []
    },
    {
      "logical_name": "transformador_profiles",
      "relative_path": "Indicadores_vano_v3_normalized/transformador_profiles.parquet",
      "bronze_table": "bronze_transformador_profiles",
      "load_mode": "parquet",
      "primary_key": ["trafo_profile_id"],
      "required_columns": ["trafo_profile_id", "FID_TRAFO"],
      "date_columns": []
    },
    {
      "logical_name": "eventos",
      "relative_path": "Indicadores_vano_v3_normalized/eventos.parquet",
      "bronze_table": "bronze_eventos",
      "load_mode": "parquet",
      "primary_key": ["event_id"],
      "required_columns": ["event_id", "FECHA", "DURACION", "UITI", "TOT_USUS", "CNT_TRF", "COD_CAUSA"],
      "date_columns": ["FECHA"]
    },
    {
      "logical_name": "evento_vano_trafo",
      "relative_path": "Indicadores_vano_v3_normalized/evento_vano_trafo.parquet",
      "bronze_table": "bronze_evento_vano_trafo",
      "load_mode": "parquet",
      "primary_key": ["row_id"],
      "natural_key": ["event_id", "FID_VANO", "trafo_profile_id"],
      "required_columns": ["row_id", "event_id", "FID_VANO", "trafo_profile_id", "UITI_VANO"],
      "date_columns": []
    },
    {
      "logical_name": "clima_vano_fecha",
      "relative_path": "Indicadores_vano_v3_normalized/clima_vano_fecha.parquet",
      "bronze_table": "bronze_clima_vano_fecha",
      "load_mode": "parquet",
      "primary_key": ["FID_VANO", "FECHA"],
      "required_columns": ["FID_VANO", "FECHA"],
      "date_columns": ["FECHA"]
    }
  ]
}
```

Keep the old `phase1_assets.json` temporarily if tests/scripts still refer to it, but make the new manifest the one used by the migration jobs.

#### 1.2 Make the manifest filename configurable

Update:

```text
databricks/notebooks/_shared_phase1.py
```

Required changes:

```text
- Add a widget/env/variable for manifest_filename.
- Default to normalized_vano_assets.json for the upgraded pipeline.
- Keep backward compatibility only where tests require it.
```

Suggested default constant:

```python
DEFAULT_MANIFEST_FILENAME = "normalized_vano_assets.json"
```

But safer implementation:

```python
define_standard_widgets():
    ...
    dbutils.widgets.text("manifest_filename", DEFAULT_MANIFEST_FILENAME)
```

and in `build_context`, include `manifest_filename` in the context dataclass.

#### 1.3 Add upload script for the normalized dataset

Create:

```text
databricks/scripts/upload_normalized_vano_dataset.sh
```

Script behavior:

```text
- Read CHEC_NORMALIZED_DATASET_DIR, defaulting to /home/jclugor/unal/CHEC/data/Indicadores_vano_v3_normalized.
- Validate that normalization_manifest.json exists.
- Validate that all expected .parquet files exist.
- Upload the directory to dbfs:/Volumes/<catalog>/raw/<source_volume>/Indicadores_vano_v3_normalized.
- Do not upload/delete PDFs.
- Do not touch chatbot_documents, chatbot_corpus, or agent_config/skills.
- Verify uploaded file sizes or at least remote existence.
```

Suggested command shape:

```bash
CATALOG_NAME=chec_dbx_demo \
SOURCE_VOLUME_NAME=source_files \
CHEC_NORMALIZED_DATASET_DIR=/home/jclugor/unal/CHEC/data/Indicadores_vano_v3_normalized \
bash databricks/scripts/upload_normalized_vano_dataset.sh
```

Expected target:

```text
dbfs:/Volumes/chec_dbx_demo/raw/source_files/Indicadores_vano_v3_normalized/
```

---

### PR 2 — Add safe structured-data cleanup

Create:

```text
databricks/notebooks/00_cleanup_old_structured_data.py
```

This notebook must be idempotent and must support dry-run mode.

Widgets:

```text
catalog_name
source_volume_name
dry_run = true
cleanup_source_tabular_files = true
cleanup_delta_tables = true
preserve_pdfs = true
```

#### 2.1 Tables/views to drop or replace

Drop only old dashboard structured objects and app context views that will be rebuilt.

Recommended drop list:

```text
raw.phase1_manifest_json
raw.phase1_source_inventory
raw.phase1_secret_inventory
raw.phase1_copy_log

bronze.phase1_ingest_log
bronze.bronze_trafos
bronze.bronze_apoyos
bronze.bronze_switches
bronze.bronze_redmt
bronze.bronze_super_eventos
bronze.bronze_eventos_interruptor
bronze.bronze_eventos_tramo_linea
bronze.bronze_eventos_transformador
bronze.bronze_vegetacion
bronze.bronze_rayos

silver.phase1_validation_results
silver.silver_assets
silver.silver_events
silver.silver_environmental_events

gold.phase1_table_registry
gold.gold_saidi_saifi_daily
gold.gold_saidi_saifi_circuit_summary
gold.gold_timeseries_event_details
gold.gold_timeseries_daily_attribution
gold.gold_timeseries_environment_daily
gold.gold_probability_inputs
gold.gold_map_points
gold.gold_map_line_segments
gold.gold_map_filter_index
gold.gold_map_event_days
gold.gold_agent_view_context
gold.gold_agent_event_context
gold.gold_agent_asset_context
gold.gold_agent_circuit_history

ml.phase1_artifact_inventory
```

Do **not** drop these unless explicitly requested:

```text
silver.technical_doc_chunks
gold.technical_doc_chunks_current
agent conversation tables
agent_tools functions/schema
agent_observability tables
AI Search index resources
```

Reason: these belong to chatbot/RAG/observability, not the old structured source dataset. They can be rebuilt later if needed, but the dataset migration should not delete PDFs or the document corpus.

#### 2.2 Old source files to remove from raw volume

Delete only known old structured files under:

```text
/Volumes/<catalog>/raw/<source_volume>/
```

Explicit old source file list:

```text
TRAFOS.pkl
APOYOS.pkl
SWITCHES.pkl
REDMT.pkl
SuperEventos_Criticidad_AguasAbajo_CODEs.pkl
Eventos_interruptor.pkl
Eventos_tramo_linea.pkl
Eventos_transformador.pkl
Vegetacion.pkl
Rayos.pkl
arbol_decision_recomendaciones/*.xlsx
arbol_decision_recomendaciones/Temporal/*.xlsx
```

Do **not** delete:

```text
chatbot_documents/**/*.pdf
chatbot_corpus/**
Indicadores_vano_v3_normalized/**, once uploaded
any *.pdf anywhere
```

Add an explicit safety check:

```python
if path.lower().endswith(".pdf"):
    raise ValueError("Cleanup attempted to remove a PDF; aborting.")
```

#### 2.3 Optional low-cost rollback guard

Before dropping tables in staging/prod, optionally create shallow clones in a temporary backup schema:

```text
backup_structured_migration_YYYYMMDD
```

Use only for old Delta tables, not source files. Drop the backup after validation/sign-off. This provides safety without copying all data.

---

### PR 3 — Update Databricks bootstrap and bronze ingest for Parquet

#### 3.1 Bootstrap schemas

Update:

```text
databricks/notebooks/00_bootstrap_uc.py
```

Required changes:

```text
- Keep raw/bronze/silver/gold/ml schemas.
- Add schemas if missing and useful now: agent, agent_tools, agent_observability only if not already handled elsewhere.
- Create source/artifact volumes as before.
- Store the normalized manifest JSON in raw.normalized_manifest_json or raw.phase1_manifest_json with dataset_name included.
- Store source inventory from normalized_vano_assets.json.
- Keep table registry updated to the new gold tables.
```

Recommended new registry entries:

```text
gold_impact_daily
gold_impact_circuit_summary
gold_timeseries_event_details
gold_timeseries_daily_attribution
gold_timeseries_environment_daily
gold_probability_inputs
gold_map_points
gold_map_line_segments
gold_map_filter_index
gold_map_event_days
```

#### 3.2 Bronze ingest

Update:

```text
databricks/notebooks/01_stage_bronze_tables.py
```

Required changes:

```text
- Support load_mode = parquet.
- Continue supporting pickle only if needed by tests, but do not use pickle in the normalized migration path.
- Read Parquet from /Volumes/<catalog>/raw/<source_volume>/<relative_path>.
- Preserve raw string columns as loaded.
- Add metadata columns:
  source_logical_name
  source_relative_path
  source_dataset_name
  source_loaded_at
- Do not infer numeric identifiers.
- Write each bronze table using Delta overwriteSchema.
```

Expected bronze tables:

```text
bronze.bronze_causas
bronze.bronze_equipos_proteccion
bronze.bronze_apoyos
bronze.bronze_vanos
bronze.bronze_transformador_profiles
bronze.bronze_eventos
bronze.bronze_evento_vano_trafo
bronze.bronze_clima_vano_fecha
```

---

### PR 4 — Validation notebook for normalized dataset

Update or replace:

```text
databricks/notebooks/02_validate_ingest.py
```

Validation must include the checks from the skill.

#### 4.1 Manifest checks

Check:

```text
normalization_manifest.json exists in the uploaded source directory
source_hash matches expected value when available:
7d4efade8c78a6d364ed68e0228439693a533626bde8a247c5e6e0b4ab89d354
expected source shape is 159,470 x 273
all expected table paths exist
```

Do not fail if source hash is absent from a future manifest version, but warn.

#### 4.2 Row count checks

Expected counts:

```text
causas: 25
equipos_proteccion: 2,208
apoyos: 26,746
vanos: 27,390
transformador_profiles: 8,398
eventos: 7,079
evento_vano_trafo: 159,470
clima_vano_fecha: 142,158
```

#### 4.3 Primary key checks

Check uniqueness:

```text
causas.COD_CAUSA
equipos_proteccion.FID_SW
apoyos.FID_APOYO_FIN
vanos.FID_VANO
transformador_profiles.trafo_profile_id
eventos.event_id
evento_vano_trafo.row_id
evento_vano_trafo event_id + FID_VANO + trafo_profile_id
clima_vano_fecha FID_VANO + FECHA
```

#### 4.4 Foreign key checks

Check:

```text
eventos.COD_CAUSA -> causas.COD_CAUSA
vanos.FID_SW -> equipos_proteccion.FID_SW
vanos.FID_APOYO_FIN -> apoyos.FID_APOYO_FIN
evento_vano_trafo.event_id -> eventos.event_id
evento_vano_trafo.FID_VANO -> vanos.FID_VANO
evento_vano_trafo.trafo_profile_id -> transformador_profiles.trafo_profile_id
clima_vano_fecha.FID_VANO -> vanos.FID_VANO
```

#### 4.5 Casting smoke checks

In derived validation frames only:

```text
eventos.FECHA parses as timestamp
clima_vano_fecha.FECHA parses as timestamp/date
weather columns cast to numeric
FECHA_OPERACION_VANO casts to nullable integer year
FECHA_OPERACION_TRF casts to nullable integer year
X1, Y1, X2, Y2 cast to numeric for map features
```

#### 4.6 Store validation results

Write to:

```text
silver.normalized_validation_results
```

Suggested columns:

```text
validation_name
validation_type
status
expected_value
observed_value
details
severity
validated_at
```

Fail the job if any `severity = error` validation fails.

---

### PR 5 — Rebuild silver/gold from normalized source

Update:

```text
databricks/notebooks/03_build_silver_gold.py
```

The old script is centered on separate asset/event pickle files. Replace that logic with normalized joins.

#### 5.1 Build `silver_vano_fact`

Create one central enriched fact table from the canonical join:

```text
evento_vano_trafo
  -> eventos
  -> vanos
  -> equipos_proteccion
  -> apoyos
  -> causas
  -> transformador_profiles
  -> clima_vano_fecha
```

Required behavior:

```text
- The joined row count must remain 159,470.
- The natural key event_id + FID_VANO + trafo_profile_id must remain unique.
- ID columns remain string/category fields.
- Numeric/date columns are explicitly cast in the silver table.
```

Recommended important columns:

```text
row_id
event_id
FID_VANO
trafo_profile_id
FID_SW
FID_APOYO_FIN
FID_TRAFO
COD_CAUSA
DESC_CAUSA
CIRCUITO
FECHA
fecha_dia
event_year
event_month
event_hour
day_of_week
DURACION as duration_raw
UITI
UITI_VANO
TOT_USUS
CNT_TRF
X1, Y1, X2, Y2
span_mid_x
span_mid_y
LONGITUD
CONDUCTOR
CALIBRE_NEUTRO
NG_RED
TIPO_TAX
CAPACIDAD_NOMINAL
CNT_USUS
weather columns, or selected weather aggregates
```

#### 5.2 Build `silver_events`

Grain: one row per `evento_vano_trafo` record, because that is the safest available current grain.

Columns should align with current app needs but use correct semantics:

```text
event_id
row_id
FID_VANO
trafo_profile_id
fecha_dia
inicio_ts = FECHA
fin_ts = NULL unless duration unit can be converted safely
evento = event_id
causa = DESC_CAUSA
cause_code = COD_CAUSA
event_family = 'Evento Vano/Trafo'
circuito = CIRCUITO
municipio = 'Sin municipio' until municipality mapping is available
equipo_ope = FID_VANO or FID_SW depending on selected context
tipo_equi_ope = TIPO
tipo_elemento = TIPO_TAX
impact_uiti = UITI
impact_uiti_vano = UITI_VANO
duration_raw = DURACION
users_affected_total = TOT_USUS
transformer_count = CNT_TRF
latitude = span_mid_y if coordinates are lat/lon, or Y midpoint by current mapping
longitude = span_mid_x if coordinates are lat/lon, or X midpoint by current mapping
coordinate_quality = 'span_midpoint_from_vano'
source_logical_name = 'evento_vano_trafo'
```

Coordinate note: confirm whether `X/Y` are longitude/latitude or projected coordinates. If they are projected coordinates, the map needs a transformation step before rendering with Folium. Until confirmed, keep coordinate quality metadata and add a validation that the values fall into valid latitude/longitude ranges before using them on the map.

#### 5.3 Build `silver_assets`

Use normalized asset data to support the current map and chatbot context.

Recommended rows:

```text
LineSegments from vanos:
  asset_family = 'LineSegments'
  asset_id = FID_VANO
  circuito = CIRCUITO
  latitude/longitude from X1/Y1 after validation/transform
  latitude_end/longitude_end from X2/Y2 after validation/transform

Supports from vanos + apoyos:
  asset_family = 'Supports'
  asset_id = FID_APOYO_FIN
  coordinates from the most common or latest X2/Y2 associated with the support
  support attributes from apoyos

Switches from equipos_proteccion + vanos:
  asset_family = 'Switches'
  asset_id = FID_SW
  coordinates derived from associated vano start/midpoint
  coordinate_quality = 'derived_from_associated_vano'

Transformer profiles from transformador_profiles + fact + vanos:
  asset_family = 'Transformers'
  asset_id = trafo_profile_id
  coordinates derived from the most frequent associated vano midpoint
  coordinate_quality = 'derived_from_vano_midpoint'
```

If a coordinate type is invalid for Folium, do not put it in `gold_map_points`; keep it in silver with a warning and exclude it from the gold map until a transformation is available.

#### 5.4 Build weather/environment table

The old app had `Vegetacion` and `Rayos` source event tables. The new normalized dataset has weather features by `FID_VANO + FECHA`.

Create:

```text
silver_weather_daily
```

Suggested grain:

```text
fecha_dia + circuito
```

Metrics:

```text
avg/max prep_0..prep_24 summary
avg/max wind_spd_0..wind_spd_24 summary
avg/max wind_gust_spd_0..wind_gust_spd_24 summary
avg temp summary
avg rh summary
avg clouds summary
record_count
```

Then create:

```text
gold_timeseries_environment_daily
```

with current app-compatible fields:

```text
fecha_dia
municipio = 'Sin municipio'
environment_family = weather variable group
first_environment_ts
last_environment_ts
geocoded_event_count or record_count
summary_value
```

#### 5.5 Build new gold impact tables

Create canonical tables:

```text
gold_impact_daily
gold_impact_circuit_summary
```

`gold_impact_daily` grain:

```text
fecha_dia + circuito + municipio + event_family
```

Columns:

```text
fecha_dia
circuito
municipio
event_family
uiti_total
uiti_vano_total
event_count
duration_total_raw
users_affected_total
transformer_count_total
first_event_ts
last_event_ts
```

`gold_impact_circuit_summary` grain:

```text
circuito + municipio + event_family
```

Columns:

```text
circuito
municipio
event_family
uiti_total
uiti_vano_total
event_count
duration_avg_raw
users_affected_total
transformer_count_total
first_event_ts
last_event_ts
```

#### 5.6 Rebuild app-compatible gold tables

The current app expects these tables. Either refactor the app to use the canonical names or create views during transition.

Required app-facing objects:

```text
gold_timeseries_event_details
gold_timeseries_daily_attribution
gold_timeseries_environment_daily
gold_probability_inputs
gold_map_points
gold_map_line_segments
gold_map_filter_index
gold_map_event_days
```

Preferred: update services to read `gold_impact_daily` and `gold_impact_circuit_summary`.

Temporary compatibility option: create deprecated views:

```text
gold_saidi_saifi_daily
gold_saidi_saifi_circuit_summary
```

with `saidi_total`/`saifi_total` only for old code compatibility. If used, include comments in the code and table description:

```text
This is a temporary compatibility view. It does not mean the new source contains SAIDI/SAIFI.
```

Do not show those labels to users after the UI refactor.

---

### PR 6 — Update the app data service for generic impact metrics

Current service to update:

```text
src/chec_dashboard/services/databricks_data_service.py
```

The current service is hard-coded to:

```text
gold_saidi_saifi_daily
saidi_total
saifi_total
SAIDI
SAIFI
```

Refactor to support a metric registry.

Suggested internal registry:

```python
IMPACT_METRICS = {
    "UITI": {
        "label": "UITI",
        "daily_column": "uiti_total",
        "display_digits": 3,
    },
    "UITI_VANO": {
        "label": "UITI vano",
        "daily_column": "uiti_vano_total",
        "display_digits": 3,
    },
    "EVENT_COUNT": {
        "label": "Eventos",
        "daily_column": "event_count",
        "display_digits": 0,
    },
    "USERS": {
        "label": "Usuarios afectados",
        "daily_column": "users_affected_total",
        "display_digits": 0,
    },
    "DURATION_RAW": {
        "label": "Duración fuente",
        "daily_column": "duration_total_raw",
        "display_digits": 3,
    },
}
```

Required app behavior:

```text
- Summary metadata loads circuits from gold_impact_circuit_summary.
- Summary payload supports one selected metric or a small set of selected metrics.
- Time-series interpretability works on the selected metric, defaulting to UITI.
- Status text no longer says SAIDI/SAIFI unless legacy compatibility mode is enabled.
- Readiness checks require the new impact tables and map/probability tables.
```

Short-term fallback:

```text
If the UI refactor is too large, create compatibility views first, then refactor the labels in a second commit.
```

---

### PR 7 — Update Summary page and time-series interpretability

Files:

```text
src/chec_dashboard/pages/summary_page.py
src/chec_dashboard/services/time_series_interpretability_service.py
src/chec_dashboard/services/time_series_interpretability_agent.py
```

Required changes:

```text
- Replace fixed SAIDI/SAIFI options with dynamic impact metric options.
- Default metric: UITI.
- Keep the same chart behavior and critical point detection.
- Interpret critical dates using current data only: UITI, event count, affected users, duration, cause, circuit, weather context.
- Avoid claiming causal explanation.
- Add limitation text when graph/model/scenario data is not available.
```

Example user-facing limitation:

```text
Este análisis usa los eventos, vanos, transformadores, clima y variables de impacto disponibles en la fuente normalizada. Todavía no incorpora modelo predictivo productivo, grafo topológico validado ni simulación de intervención.
```

---

### PR 8 — Update Map page data products only, not UX unless necessary

Files:

```text
src/chec_dashboard/services/map_service.py
src/chec_dashboard/services/databricks_data_service.py
src/chec_dashboard/pages/map_page.py
```

The current map UI can remain mostly the same, but the data source changes.

Required data changes:

```text
- `gold_map_line_segments` comes from `vanos`.
- `gold_map_points` comes from derived Supports, Switches, Transformers, and event points.
- `gold_map_event_days` comes from `silver_events` / `silver_vano_fact`.
- `gold_map_filter_index` comes from map points + lines.
```

Important coordinate safety:

```text
- Add validation for lat/lon ranges before sending data to Folium.
- If X/Y are not lat/lon, exclude from map gold tables and return a clear readiness/status error.
- Add coordinate_quality field to gold_map_points and gold_map_line_segments.
```

If municipality is unavailable:

```text
- Set municipio = 'Sin municipio'.
- Keep the existing municipio dropdown working with this single value.
- Add future work to derive municipality via spatial join when boundary data is available.
```

---

### PR 9 — Update Probability Explorer for normalized data

Files:

```text
src/chec_dashboard/services/probability_service.py
src/chec_dashboard/services/databricks_data_service.py
src/chec_dashboard/pages/probability_page.py
```

Data source:

```text
gold_probability_inputs
```

Build `gold_probability_inputs` from `silver_vano_fact` with useful current columns:

```text
criteria_group = event_family or cause/category group
source_date = fecha_dia
target_flag = UITI_VANO > 0 or UITI > 0
impact_uiti
impact_uiti_vano
duration_raw
users_affected_total
transformer_count
cause_code
cause_description
circuito
FID_VANO
FID_SW
trafo_profile_id
asset/weather/topology columns available today
```

Leakage-aware improvement:

```text
- Add metadata that flags fields as pre-event, event-descriptive, or post-event impact.
- For probability exploration, allow user exploration but label post-event fields clearly.
- For future ML feature assembly, do not use post-event impact fields as predictors.
```

Do not implement a new ML training pipeline in this migration.

---

### PR 10 — Preserve RAG/PDFs and update context tools

Files/scripts:

```text
databricks/scripts/setup_phase4_context_tools.py
databricks/scripts/setup_phase5_ai_search.py
src/chec_dashboard/services/agent_context_service.py
src/chec_dashboard/services/retrieval_service.py
```

Rules:

```text
- Do not delete or re-upload PDFs as part of the dataset migration.
- Keep chatbot_documents and chatbot_corpus as-is unless the user explicitly provides new documents.
- Keep AI Search resources as-is unless the corpus must be rebuilt.
- Rebuild only the app context views/functions because their source gold tables changed.
```

Update these views to use the new gold tables:

```text
gold_agent_view_context       -> gold_impact_daily
gold_agent_event_context      -> gold_map_event_days or gold_timeseries_event_details
gold_agent_asset_context      -> gold_map_points + gold_map_line_segments
gold_agent_circuit_history    -> gold_impact_daily
```

Update context payload language from `SAIDI/SAIFI` to current impact metrics:

```text
UITI
UITI vano
event count
affected users
duration_raw
weather context when available
```

---

### PR 11 — Implement cost-aware bounded multi-agent behavior using existing app features

This incorporates the boss/advisor suggestion without building features that are not available yet.

Files:

```text
src/chec_dashboard/services/agent_orchestrator.py
src/chec_dashboard/services/agent_routing_service.py
src/chec_dashboard/services/llm_service.py
src/chec_dashboard/services/agent_trace_service.py
src/chec_dashboard/services/chatbot_service.py
src/chec_dashboard/core/config.py
databricks/apps/chec_dash_parity/app.yaml
databricks/scripts/stage_phase35_databricks_app.py
```

#### 11.1 Define agent roles that exist now

Active now:

```text
Router Agent
  - model: none or cheap
  - purpose: classify question and choose tools/model tier

Context Agent
  - model: none
  - purpose: fetch selected context from SQL/context tools

Historical/Impact Analyst Agent
  - model: none for metrics; cheap/medium only for wording if needed
  - purpose: summarize 12-month/current-window behavior using gold impact tables

RAG Agent
  - model: medium only when retrieval is enabled and the question asks for documents/compliance/methodology
  - purpose: retrieve/cite existing PDFs/corpus

Synthesis Agent
  - model: medium for normal answers; best model only for complex synthesis or explicit deep analysis
  - purpose: write the final technical explanation with evidence and limitations
```

Future, not implemented now:

```text
ML Evidence Agent
Graph Agent
Scenario Agent
Economic Evaluation Agent
Report Agent
```

#### 11.2 Add model tier configuration

Add env/settings:

```text
LLM_ROUTING_ENABLED=true
LLM_DEFAULT_TIER=medium
LLM_CHEAP_ENDPOINT_NAME
LLM_MEDIUM_ENDPOINT_NAME
LLM_BEST_ENDPOINT_NAME
LLM_MAX_EXPENSIVE_CALLS_PER_REQUEST=1
LLM_ALLOW_BEST_MODEL=false by default in dev
LLM_ROUTE_SIMPLE_TASKS_TO_CHEAP=true
```

Current single endpoint behavior should remain as fallback:

```text
If tiered endpoints are not configured, use LLM_ENDPOINT_NAME.
```

#### 11.3 Add routing policy

Implement a routing policy similar to:

```text
simple metric/table lookup:
  agents = context/historical only
  model = none

event explanation:
  agents = context + historical + synthesis
  model = medium

document/compliance question:
  agents = context + rag + synthesis
  model = medium

complex multi-source question:
  agents = context + historical + rag + synthesis
  model = best only if LLM_ALLOW_BEST_MODEL=true

follow-up question:
  agents = previous context + selected needed tools
  model = cheap or medium depending on complexity
```

#### 11.4 Add hard guardrails

```text
- LLMs do not calculate impact metrics.
- LLMs do not invent unavailable graph/model/scenario evidence.
- LLMs do not invent citations.
- Expensive model calls require route justification.
- Every answer states missing components when relevant.
- Every tool/model call is traced.
```

#### 11.5 Observability additions

Log per agent step:

```text
request_id
conversation_id
agent_name
tool_name
model_tier
endpoint_name
latency_ms
tokens_in
tokens_out, if available
estimated_cost, if available
route_reason
prompt_version
context_hash
citations_count
error
```

Use existing observability services/tables; do not introduce external infrastructure.

---

### PR 12 — Bundle, jobs, and deployment updates

Files:

```text
databricks/databricks.yml
databricks/resources/phase1_jobs.yml
databricks/resources/phase2_pilot_resources.yml
```

Required changes:

```text
- Add manifest_filename variable.
- Add a cleanup job/task that can run in dry-run or apply mode.
- Add normalized upload instructions to README/scripts, not as a Databricks job because upload runs from local/CI where the data exists.
- In ingest jobs, use the normalized manifest filename.
- Remove or disable `stage_ml_assets` from the default refresh job until a real governed model path is implemented.
```

Recommended job order:

```text
chec_normalized_bootstrap
  00_bootstrap_uc.py

chec_normalized_cleanup_old_structured_data
  00_cleanup_old_structured_data.py with dry_run=false, when intentionally invoked

chec_normalized_ingest_validation
  01_stage_bronze_tables.py
  02_validate_ingest.py
  03_build_silver_gold.py

chec_context_tools_refresh
  setup_phase4_context_tools.py
```

Do not schedule destructive cleanup. It should be manual/on-demand only.

---

## Migration runbook

### Step 0 — Deploy code to dev

```bash
cd databricks

databricks bundle validate -t dev
databricks bundle deploy -t dev
```

### Step 1 — Bootstrap schemas and volumes

Run the bootstrap job/notebook with:

```text
catalog_name = chec_dbx_demo
source_volume_name = source_files
manifest_filename = normalized_vano_assets.json
```

### Step 2 — Upload normalized dataset

From a machine that has the dataset:

```bash
CATALOG_NAME=chec_dbx_demo \
SOURCE_VOLUME_NAME=source_files \
CHEC_NORMALIZED_DATASET_DIR=/home/jclugor/unal/CHEC/data/Indicadores_vano_v3_normalized \
bash databricks/scripts/upload_normalized_vano_dataset.sh
```

Verify remote files:

```bash
databricks fs ls dbfs:/Volumes/chec_dbx_demo/raw/source_files/Indicadores_vano_v3_normalized
```

### Step 3 — Dry-run cleanup

Run:

```text
00_cleanup_old_structured_data.py
  dry_run = true
  preserve_pdfs = true
```

Confirm the dry-run output does **not** include any `.pdf`, `chatbot_documents`, or `chatbot_corpus` paths.

### Step 4 — Apply cleanup

Run:

```text
00_cleanup_old_structured_data.py
  dry_run = false
  cleanup_delta_tables = true
  cleanup_source_tabular_files = true
  preserve_pdfs = true
```

### Step 5 — Ingest and validate normalized data

Run:

```text
01_stage_bronze_tables.py
02_validate_ingest.py
03_build_silver_gold.py
```

Hard pass criteria:

```text
bronze_evento_vano_trafo count = 159,470
silver_vano_fact count = 159,470
natural key unique
primary/foreign key checks pass
no invalid map coordinates reach gold_map_points/gold_map_line_segments
```

### Step 6 — Rebuild context tools

Run:

```bash
APP_CATALOG_NAME=chec_dbx_demo \
APP_WAREHOUSE_ID=<warehouse_id> \
python databricks/scripts/setup_phase4_context_tools.py
```

### Step 7 — Smoke-test app data backend

Check readiness endpoint or local tests with Databricks app settings.

Required tables/views:

```text
gold_impact_daily
gold_impact_circuit_summary
gold_timeseries_event_details
gold_timeseries_daily_attribution
gold_timeseries_environment_daily
gold_probability_inputs
gold_map_points, if coordinates valid
gold_map_line_segments, if coordinates valid
gold_map_filter_index
gold_map_event_days
gold_agent_view_context
gold_agent_event_context
gold_agent_asset_context
gold_agent_circuit_history
```

### Step 8 — Deploy/stage Databricks App

```bash
APP_CATALOG_NAME=chec_dbx_demo \
APP_WAREHOUSE_ID=<warehouse_id> \
APP_CHATBOT_ENABLED=true \
APP_LLM_ROUTING_ENABLED=true \
python databricks/scripts/stage_phase35_databricks_app.py
```

Then deploy the app using the existing deployment script.

---

## Required tests

### Unit tests

Add/update tests for:

```text
tests/test_normalized_manifest.py
tests/test_normalized_validation.py
tests/test_databricks_phase1_scaffold.py
tests/test_databricks_parity_runtime.py
tests/test_services.py
tests/test_chatbot_service.py
tests/test_time_series_interpretability_service.py
```

Minimum expectations:

```text
- normalized manifest parses
- upload script references expected files
- cleanup script never deletes PDF paths
- bronze source names match the normalized tables
- metric registry contains UITI and EVENT_COUNT
- summary service no longer requires SAIDI/SAIFI labels
- readiness check uses new required tables
- router selects no/cheap model for simple metric requests
- router selects medium/best only for synthesis tasks based on configuration
```

### Databricks validation tests

The validation notebook must fail on:

```text
wrong row count
missing normalized source table
duplicate primary key
duplicate fact natural key
foreign key violation
unparseable FECHA
joined fact row count different from 159,470
invalid map coordinates in gold map tables
```

### App smoke tests

In dev, manually check:

```text
Summary page loads default UITI trend
Summary interpretability identifies critical dates
Map page either renders normalized coordinates or shows a clear coordinate readiness message
Probability explorer loads normalized columns and generates a graph
Chatbot context search works
Chatbot answer states current evidence and limitations
No PDF/RAG assets were deleted
```

---

## Future work explicitly out of scope for this migration

These items are part of the advisor’s broader product vision, but should not be implemented until their data/model dependencies exist:

### Future 1 — Full graph/topology reasoning

The normalized dataset includes useful network identifiers and span geometry, but a full graph product still needs validated topology semantics.

Future work:

```text
graph_node
graph_edge
protection-zone traversal
upstream/downstream customer exposure
asset neighborhood tools
graph criticality metrics
graph agent
```

Current migration only uses `vanos`, `FID_SW`, and `FID_APOYO_FIN` for map/context data products.

### Future 2 — Real ML model outputs

Do not treat the old staged `model.pth`/`mask.npy` path as production-ready.

Future work:

```text
MLflow experiment
Unity Catalog registered model
model aliases: dev/staging/production
batch prediction table
feature relevance table
model evidence agent
model monitoring
```

Current migration only prepares clean normalized `ml`/feature-ready tables; it does not implement model scoring.

### Future 3 — Scenario simulator

Future work:

```text
intervention catalog
scenario feature snapshot
scenario validation rules
model scoring for baseline vs scenario
scenario result table
uncertainty/sensitivity
economic calculation
scenario agent
```

Current migration does not add scenario UI or scenario tables unless empty placeholders are explicitly requested.

### Future 4 — Technical-economic report generation

Future work:

```text
report template
report generation service
report artifact storage
citation appendix
model/scenario version appendix
review workflow
```

Current migration only improves the chatbot’s evidence answer and limitations language.

### Future 5 — Regulatory/document lifecycle automation

Existing PDFs/RAG assets are preserved. Future work can add:

```text
document approval workflow
version/effective-date lifecycle
corpus promotion from draft to active
RAG evaluation gates
AI Search sync policies
```

---

## Definition of done

The migration is complete when:

1. The normalized dataset is uploaded to the raw Unity Catalog volume.
2. Old structured Delta tables/views and old structured source files are removed without deleting PDFs.
3. Bronze tables are created from normalized Parquet files.
4. Validation confirms the skill’s row counts, uniqueness, foreign keys, and joined fact grain.
5. Silver/gold tables are rebuilt from `evento_vano_trafo` and related normalized tables.
6. The app no longer depends on old pickle/XLSX tables.
7. The app no longer presents `UITI` as if it were `SAIDI/SAIFI`.
8. Summary, map, probability explorer, time-series interpretability, chatbot, conversation/feedback, and context tools are functional with the new data.
9. The multi-agent behavior is cost-aware and bounded, using deterministic SQL/Python for simple tasks and stronger models only for synthesis when configured.
10. Graph, ML scoring, scenario simulation, economics, and formal reports are clearly documented as future work.
