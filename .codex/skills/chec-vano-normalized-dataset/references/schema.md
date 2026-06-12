# CHEC Normalized Vano Dataset Schema

## Overview

Canonical path: `/home/jclugor/unal/CHEC/data/Indicadores_vano_v3_normalized`

The dataset was generated from `/home/jclugor/unal/CHEC/data/Indicadores_vano_v3.csv` into Parquet tables with wide weather features. Source hash:
`7d4efade8c78a6d364ed68e0228439693a533626bde8a247c5e6e0b4ab89d354`.

Physical storage: all Parquet columns are `string` except `evento_vano_trafo.row_id`, which is `int64`. This is intentional so the normalized tables are lossless. Apply logical casting only in derived analysis/modeling frames.

## Validation Guarantees

The normalizer wrote `normalization_manifest.json` and completed these checks:

- Source shape: `159,470` rows and `273` original columns.
- `causas`: `COD_CAUSA` determines `DESC_CAUSA`.
- `equipos_proteccion`: `FID_SW` determines all table columns.
- `apoyos`: `FID_APOYO_FIN` determines all table columns.
- `vanos`: `FID_VANO` determines all table columns.
- `transformadores_nonblank`: nonblank `FID_TRAFO` determines transformer profile attributes.
- `clima_vano_fecha`: `FID_VANO + FECHA` determines all 225 weather values.
- `evento_vano_trafo`: natural key `event_id + FID_VANO + trafo_profile_id` is unique over `159,470` rows.
- `full_reconstruction`: all normalized tables reconstruct the original `159,470 x 273` source dataframe exactly.

## Join Graph

Use `evento_vano_trafo` as the central fact table.

```text
evento_vano_trafo.event_id          -> eventos.event_id
evento_vano_trafo.FID_VANO          -> vanos.FID_VANO
evento_vano_trafo.trafo_profile_id  -> transformador_profiles.trafo_profile_id
eventos.COD_CAUSA                   -> causas.COD_CAUSA
vanos.FID_SW                        -> equipos_proteccion.FID_SW
vanos.FID_APOYO_FIN                 -> apoyos.FID_APOYO_FIN
evento_vano_trafo.FID_VANO + eventos.FECHA -> clima_vano_fecha.FID_VANO + FECHA
```

`eventos.FECHA` and `clima_vano_fecha.FECHA` use the same timestamp strings and are intended to join through the fact table plus `FID_VANO`.

## Complete Physical Column Inventory

### `causas` columns

```text
COD_CAUSA, DESC_CAUSA
```

### `equipos_proteccion` columns

```text
FID_SW, COD_EQ_PROTEGE, CIRCUITO, T_USUS_EQ_PROT, CNT_VN_SW, TIPO
```

### `apoyos` columns

```text
FID_APOYO_FIN, COD_APOYO_FIN, ALTURA, CANTIDAD_TIERRA, PROPIETARIO, CLASE, ELEMENTO, VAL_CRIT_APOYO
```

### `vanos` columns

```text
FID_VANO, FID_SW, LVSW, CNT_VN, PORC_APORTE_VANO, LONGITUD, CNT_FASES, CONDUCTOR, CALIBRE_NEUTRO, NG_RED, FECHA_OPERACION_VANO, X1, Y1, X2, Y2, FID_APOYO_FIN, NORMA, TIPO_TAX, NR_T, LONG_CRUCETA, PROMEDIO_KWH_VANO, DDT
```

### `transformador_profiles` columns

```text
trafo_profile_id, FID_TRAFO, CODIGO, CAPACIDAD_NOMINAL, CNT_USUS, FECHA_OPERACION_TRF, PROMEDIO_KWH_TRF
```

### `eventos` columns

```text
event_id, FECHA, DURACION, UITI, TOT_USUS, CNT_TRF, COD_CAUSA
```

### `evento_vano_trafo` columns

```text
row_id, event_id, FID_VANO, trafo_profile_id, UITI_VANO
```

### `clima_vano_fecha` columns

```text
FID_VANO, FECHA
prep_0, prep_1, prep_2, prep_3, prep_4, prep_5, prep_6, prep_7, prep_8, prep_9, prep_10, prep_11, prep_12, prep_13, prep_14, prep_15, prep_16, prep_17, prep_18, prep_19, prep_20, prep_21, prep_22, prep_23, prep_24
pres_0, pres_1, pres_2, pres_3, pres_4, pres_5, pres_6, pres_7, pres_8, pres_9, pres_10, pres_11, pres_12, pres_13, pres_14, pres_15, pres_16, pres_17, pres_18, pres_19, pres_20, pres_21, pres_22, pres_23, pres_24
sp_0, sp_1, sp_2, sp_3, sp_4, sp_5, sp_6, sp_7, sp_8, sp_9, sp_10, sp_11, sp_12, sp_13, sp_14, sp_15, sp_16, sp_17, sp_18, sp_19, sp_20, sp_21, sp_22, sp_23, sp_24
rh_0, rh_1, rh_2, rh_3, rh_4, rh_5, rh_6, rh_7, rh_8, rh_9, rh_10, rh_11, rh_12, rh_13, rh_14, rh_15, rh_16, rh_17, rh_18, rh_19, rh_20, rh_21, rh_22, rh_23, rh_24
solar_rad_0, solar_rad_1, solar_rad_2, solar_rad_3, solar_rad_4, solar_rad_5, solar_rad_6, solar_rad_7, solar_rad_8, solar_rad_9, solar_rad_10, solar_rad_11, solar_rad_12, solar_rad_13, solar_rad_14, solar_rad_15, solar_rad_16, solar_rad_17, solar_rad_18, solar_rad_19, solar_rad_20, solar_rad_21, solar_rad_22, solar_rad_23, solar_rad_24
temp_0, temp_1, temp_2, temp_3, temp_4, temp_5, temp_6, temp_7, temp_8, temp_9, temp_10, temp_11, temp_12, temp_13, temp_14, temp_15, temp_16, temp_17, temp_18, temp_19, temp_20, temp_21, temp_22, temp_23, temp_24
wind_gust_spd_0, wind_gust_spd_1, wind_gust_spd_2, wind_gust_spd_3, wind_gust_spd_4, wind_gust_spd_5, wind_gust_spd_6, wind_gust_spd_7, wind_gust_spd_8, wind_gust_spd_9, wind_gust_spd_10, wind_gust_spd_11, wind_gust_spd_12, wind_gust_spd_13, wind_gust_spd_14, wind_gust_spd_15, wind_gust_spd_16, wind_gust_spd_17, wind_gust_spd_18, wind_gust_spd_19, wind_gust_spd_20, wind_gust_spd_21, wind_gust_spd_22, wind_gust_spd_23, wind_gust_spd_24
wind_spd_0, wind_spd_1, wind_spd_2, wind_spd_3, wind_spd_4, wind_spd_5, wind_spd_6, wind_spd_7, wind_spd_8, wind_spd_9, wind_spd_10, wind_spd_11, wind_spd_12, wind_spd_13, wind_spd_14, wind_spd_15, wind_spd_16, wind_spd_17, wind_spd_18, wind_spd_19, wind_spd_20, wind_spd_21, wind_spd_22, wind_spd_23, wind_spd_24
clouds_0, clouds_1, clouds_2, clouds_3, clouds_4, clouds_5, clouds_6, clouds_7, clouds_8, clouds_9, clouds_10, clouds_11, clouds_12, clouds_13, clouds_14, clouds_15, clouds_16, clouds_17, clouds_18, clouds_19, clouds_20, clouds_21, clouds_22, clouds_23, clouds_24
```

## Tables

### `causas`

Rows: `25`

Primary key: `COD_CAUSA`

| Column | Logical role |
| --- | --- |
| `COD_CAUSA` | Cause identifier; keep as string/category |
| `DESC_CAUSA` | Cause description; categorical label |

### `equipos_proteccion`

Rows: `2,208`

Primary key: `FID_SW`

| Column | Logical role |
| --- | --- |
| `FID_SW` | Protection switch/equipment id; string key |
| `COD_EQ_PROTEGE` | Protected equipment code; string id |
| `CIRCUITO` | Circuit code; categorical |
| `T_USUS_EQ_PROT` | Protected users count; numeric |
| `CNT_VN_SW` | Number of vanos under switch; numeric |
| `TIPO` | Interruption/type code; categorical |

### `apoyos`

Rows: `26,746`

Primary key: `FID_APOYO_FIN`

| Column | Logical role |
| --- | --- |
| `FID_APOYO_FIN` | Support/end-pole id; string key |
| `COD_APOYO_FIN` | Support/end-pole code; string id |
| `ALTURA` | Support height; numeric |
| `CANTIDAD_TIERRA` | Grounding count/indicator; numeric |
| `PROPIETARIO` | Owner; categorical. One observed value is a single space |
| `CLASE` | Support class; categorical |
| `ELEMENTO` | Support element type; categorical |
| `VAL_CRIT_APOYO` | Support criticality value; numeric |

### `vanos`

Rows: `27,390`

Primary key: `FID_VANO`

Foreign keys: `FID_SW -> equipos_proteccion.FID_SW`, `FID_APOYO_FIN -> apoyos.FID_APOYO_FIN`

Known blanks: `NORMA` has `938`; `LONG_CRUCETA` has `3,131`.

| Column | Logical role |
| --- | --- |
| `FID_VANO` | Vano/span id; string key |
| `FID_SW` | Protection equipment id; string foreign key |
| `LVSW` | Span contribution/length-like value; numeric |
| `CNT_VN` | Vano count; numeric |
| `PORC_APORTE_VANO` | Span contribution percentage/share; numeric |
| `LONGITUD` | Span length; numeric |
| `CNT_FASES` | Phase count; numeric or ordered categorical |
| `CONDUCTOR` | Conductor type; categorical |
| `CALIBRE_NEUTRO` | Neutral gauge; categorical |
| `NG_RED` | Network indicator; categorical |
| `FECHA_OPERACION_VANO` | Vano operation year; nullable integer year |
| `X1`, `Y1`, `X2`, `Y2` | Endpoint coordinates; numeric |
| `FID_APOYO_FIN` | End support id; string foreign key |
| `NORMA` | Construction/asset standard; categorical with blanks |
| `TIPO_TAX` | Taxonomy/type; categorical |
| `NR_T` | Numeric topology/transformer-related field |
| `LONG_CRUCETA` | Crossarm length; numeric with blanks |
| `PROMEDIO_KWH_VANO` | Average kWh for span; numeric |
| `DDT` | Numeric distance/derived metric |

### `transformador_profiles`

Rows: `8,398`

Primary key: `trafo_profile_id`

`FID_TRAFO` is blank in `62` profiles. Keep `trafo_profile_id` for joins because blank `FID_TRAFO` rows preserve multiple distinct source profiles.

| Column | Logical role |
| --- | --- |
| `trafo_profile_id` | Surrogate transformer-profile id; string key |
| `FID_TRAFO` | Transformer id when present; string id, may be blank |
| `CODIGO` | Transformer/support code when present; string id, may be blank |
| `CAPACIDAD_NOMINAL` | Nominal capacity; numeric |
| `CNT_USUS` | Users served by transformer/profile; numeric |
| `FECHA_OPERACION_TRF` | Transformer operation year; nullable integer year |
| `PROMEDIO_KWH_TRF` | Average kWh for transformer/profile; numeric |

### `eventos`

Rows: `7,079`

Primary key: `event_id`

Foreign key: `COD_CAUSA -> causas.COD_CAUSA`

| Column | Logical role |
| --- | --- |
| `event_id` | Surrogate event id; string key |
| `FECHA` | Event timestamp; parse with `pd.to_datetime` |
| `DURACION` | Event duration; numeric |
| `UITI` | Event-level interruption impact; numeric |
| `TOT_USUS` | Total affected users; numeric |
| `CNT_TRF` | Affected transformer count; numeric |
| `COD_CAUSA` | Cause id; string foreign key |

### `evento_vano_trafo`

Rows: `159,470`

Primary key: `row_id`

Natural key: `event_id + FID_VANO + trafo_profile_id`

Foreign keys: `event_id -> eventos.event_id`, `FID_VANO -> vanos.FID_VANO`, `trafo_profile_id -> transformador_profiles.trafo_profile_id`

This is the central fact table and the safest ML training grain.

| Column | Logical role |
| --- | --- |
| `row_id` | Original row order id; int64 key |
| `event_id` | Event id; string foreign key |
| `FID_VANO` | Vano/span id; string foreign key |
| `trafo_profile_id` | Transformer-profile id; string foreign key |
| `UITI_VANO` | Vano-level impact allocation; numeric |

### `clima_vano_fecha`

Rows: `142,158`

Primary key: `FID_VANO + FECHA`

Foreign key: `FID_VANO -> vanos.FID_VANO`

| Column group | Logical role |
| --- | --- |
| `FID_VANO` | Vano/span id; string key |
| `FECHA` | Weather timestamp aligned to event timestamp; parse with `pd.to_datetime` |
| `{variable}_{offset}` | Numeric weather feature |

Weather variables: `prep`, `pres`, `sp`, `rh`, `solar_rad`, `temp`, `wind_gust_spd`, `wind_spd`, `clouds`.

Offsets: `0..24`, giving `225` weather columns. The wide column pattern is:

```text
prep_0..prep_24
pres_0..pres_24
sp_0..sp_24
rh_0..rh_24
solar_rad_0..solar_rad_24
temp_0..temp_24
wind_gust_spd_0..wind_gust_spd_24
wind_spd_0..wind_spd_24
clouds_0..clouds_24
```
