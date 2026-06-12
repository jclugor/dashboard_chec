# ML-Safe Use of the CHEC Normalized Vano Dataset

## Recommended Grain

Use one row per `evento_vano_trafo` record for supervised learning unless the user explicitly requests event-level or asset-level modeling. This grain has `159,470` rows and a unique natural key:

```text
event_id + FID_VANO + trafo_profile_id
```

## Canonical Load

```python
from pathlib import Path
import pandas as pd

DATASET_DIR = Path("/home/jclugor/unal/CHEC/data/Indicadores_vano_v3_normalized")

tables = {
    name: pd.read_parquet(DATASET_DIR / f"{name}.parquet")
    for name in [
        "causas",
        "equipos_proteccion",
        "apoyos",
        "vanos",
        "transformador_profiles",
        "eventos",
        "evento_vano_trafo",
        "clima_vano_fecha",
    ]
}
```

Keep `tables` raw and lossless. Build typed modeling frames separately.

## Canonical Join

```python
fact = tables["evento_vano_trafo"]

df = (
    fact
    .merge(tables["eventos"], on="event_id", how="left", validate="many_to_one")
    .merge(tables["vanos"], on="FID_VANO", how="left", validate="many_to_one")
    .merge(tables["equipos_proteccion"], on="FID_SW", how="left", validate="many_to_one")
    .merge(tables["apoyos"], on="FID_APOYO_FIN", how="left", validate="many_to_one")
    .merge(tables["causas"], on="COD_CAUSA", how="left", validate="many_to_one")
    .merge(tables["transformador_profiles"], on="trafo_profile_id", how="left", validate="many_to_one")
    .merge(tables["clima_vano_fecha"], on=["FID_VANO", "FECHA"], how="left", validate="many_to_one")
)

assert len(df) == len(fact) == 159_470
```

If the joined frame grows beyond `159,470` rows, a key is no longer unique or an incorrect join path was used.

## Logical Casting

Prefer explicit column groups instead of broad type inference.

```python
id_columns = [
    "event_id",
    "FID_VANO",
    "trafo_profile_id",
    "FID_SW",
    "COD_EQ_PROTEGE",
    "FID_APOYO_FIN",
    "COD_APOYO_FIN",
    "FID_TRAFO",
    "CODIGO",
    "COD_CAUSA",
]

categorical_columns = [
    "CIRCUITO",
    "TIPO",
    "DESC_CAUSA",
    "CONDUCTOR",
    "CALIBRE_NEUTRO",
    "NG_RED",
    "PROPIETARIO",
    "CLASE",
    "ELEMENTO",
    "NORMA",
    "TIPO_TAX",
]

year_columns = ["FECHA_OPERACION_VANO", "FECHA_OPERACION_TRF"]
weather_variables = ["prep", "pres", "sp", "rh", "solar_rad", "temp", "wind_gust_spd", "wind_spd", "clouds"]
weather_columns = [f"{variable}_{offset}" for variable in weather_variables for offset in range(25)]
```

Apply casting to a copy:

```python
model = df.copy()

model["FECHA"] = pd.to_datetime(model["FECHA"], errors="coerce")

for column in year_columns:
    model[column] = pd.to_numeric(model[column].replace("", pd.NA), errors="coerce").astype("Int64")

for column in categorical_columns:
    model[column] = model[column].replace("", pd.NA).astype("category")

numeric_columns = [
    column
    for column in model.columns
    if column not in id_columns + categorical_columns + ["row_id", "FECHA"] + year_columns
]

for column in numeric_columns:
    model[column] = pd.to_numeric(model[column].replace("", pd.NA), errors="coerce")
```

Do not cast raw ids to numbers. Numeric-looking ids such as `FID_VANO`, `FID_SW`, `FID_TRAFO`, and `COD_CAUSA` are identifiers/categories, not continuous features.

## Feature Design

- Use event timestamp features from `FECHA`: month, day of week, hour, weekend/holiday indicators if available.
- Use weather columns as numeric lag/window features. Preserve the `variable_offset` naming unless reshaping is required by the model.
- Use asset topology and condition features from `vanos`, `apoyos`, `equipos_proteccion`, and `transformador_profiles`.
- Encode high-cardinality ids carefully. Prefer target-safe encoders, hashing, grouped rare levels, or leave ids out for first baselines.
- Keep geographic coordinates numeric, and consider derived span midpoint/length features if the modeling task benefits from location.

## Leakage Rules

Before training, define the prediction target and remove fields that would not be known at prediction time.

Examples:

- Predicting `UITI_VANO`: exclude `UITI_VANO`, event-level `UITI`, and usually `DURACION`, `TOT_USUS`, `CNT_TRF` if they are post-event outcomes.
- Predicting event duration: exclude `DURACION` and any fields derived from interruption duration or realized impact.
- Predicting cause (`COD_CAUSA`): exclude `DESC_CAUSA` and any downstream field generated from the cause.

When in doubt, start with a pre-event feature set: asset tables, topology, historical aggregates available before `FECHA`, and weather/context fields available at prediction time.

## Validation Snippets

Primary key checks:

```python
assert tables["causas"]["COD_CAUSA"].is_unique
assert tables["equipos_proteccion"]["FID_SW"].is_unique
assert tables["apoyos"]["FID_APOYO_FIN"].is_unique
assert tables["vanos"]["FID_VANO"].is_unique
assert tables["transformador_profiles"]["trafo_profile_id"].is_unique
assert tables["eventos"]["event_id"].is_unique
assert tables["evento_vano_trafo"]["row_id"].is_unique
assert not tables["evento_vano_trafo"][["event_id", "FID_VANO", "trafo_profile_id"]].duplicated().any()
assert not tables["clima_vano_fecha"][["FID_VANO", "FECHA"]].duplicated().any()
```

Foreign key checks:

```python
assert tables["eventos"]["COD_CAUSA"].isin(tables["causas"]["COD_CAUSA"]).all()
assert tables["vanos"]["FID_SW"].isin(tables["equipos_proteccion"]["FID_SW"]).all()
assert tables["vanos"]["FID_APOYO_FIN"].isin(tables["apoyos"]["FID_APOYO_FIN"]).all()
assert tables["evento_vano_trafo"]["event_id"].isin(tables["eventos"]["event_id"]).all()
assert tables["evento_vano_trafo"]["FID_VANO"].isin(tables["vanos"]["FID_VANO"]).all()
assert tables["evento_vano_trafo"]["trafo_profile_id"].isin(tables["transformador_profiles"]["trafo_profile_id"]).all()
assert tables["clima_vano_fecha"]["FID_VANO"].isin(tables["vanos"]["FID_VANO"]).all()
```

Casting smoke checks:

```python
assert model["FECHA"].notna().all()
assert model[weather_columns].notna().all().all()
assert model["FECHA_OPERACION_VANO"].notna().all()
```

`FECHA_OPERACION_TRF` can be nullable after casting if a future dataset version introduces blank operation years.
