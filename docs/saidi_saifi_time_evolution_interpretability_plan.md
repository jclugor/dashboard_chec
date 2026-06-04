# Implementation Plan: Time-Evolution Interpretability for SAIDI/SAIFI

## 1. Purpose

Add an interpretability feature to the **time-evolution tab for SAIDI/SAIFI** so that the system can automatically identify critical moments in the indicator time series and explain them using:

1. The plotted SAIDI/SAIFI time series.
2. Relevant values from the event dataset.
3. Current corpus/RAG documents and technical context.
4. Optional external/environmental signals when available.

The feature should help users answer questions such as:

- Which dates in the SAIDI/SAIFI trend deserve attention?
- Was the date critical because of a spike, drop, sustained period, or divergence between SAIDI and SAIFI?
- Which events, causes, equipment, circuits, municipalities, or environmental signals explain the point?
- What does the corpus say that helps interpret the observed behavior?
- What evidence is missing before making a stronger operational or compliance conclusion?

The core principle is:

> **Compute criticality with transparent deterministic rules, then use the agent to explain those computed facts using structured event data and retrieved corpus evidence.**

The LLM should not be responsible for detecting anomalies from raw data. It should receive precomputed candidate dates, event attribution, metrics, and evidence flags.

---

## 2. Current project integration points

The uploaded project already has the core pieces needed for this feature.

### 2.1 Summary tab

The summary tab currently renders the daily SAIDI/SAIFI trend.

Relevant files:

```text
src/chec_dashboard/pages/summary_page.py
src/chec_dashboard/services/summary_service.py
src/chec_dashboard/services/databricks_data_service.py
src/chec_dashboard/dash_app/api_client.py
src/chec_dashboard/api/routes/data.py
src/chec_dashboard/api/schemas/requests.py
src/chec_dashboard/api/schemas/responses.py
```

Current flow:

```text
Dash summary page
  -> fetch_summary_data(...)
  -> POST /data mode="summary"
  -> get_summary_payload(...)
  -> daily_data: [{fecha_dia, SAIDI, SAIFI}, ...]
  -> Plotly line chart
```

In the Databricks path, `get_summary_payload` reads from:

```text
gold.gold_saidi_saifi_daily
```

and returns:

```json
{
  "start_date": "YYYY-MM-DD",
  "end_date": "YYYY-MM-DD",
  "circuit_label": "...",
  "metric_mode": "SAIDI | SAIFI | BOTH",
  "saidi_total": 0.0,
  "saifi_total": 0.0,
  "event_count": 0,
  "daily_data": [
    {"fecha_dia": "YYYY-MM-DD", "SAIDI": 0.0, "SAIFI": 0.0}
  ],
  "status_text": "..."
}
```

### 2.2 Existing gold and silver tables

Relevant tables/views already present or implied by the Databricks notebooks and scripts:

```text
silver.silver_events
gold.gold_saidi_saifi_daily
gold.gold_saidi_saifi_circuit_summary
gold.gold_map_event_days
gold.gold_map_points
gold.gold_map_line_segments
gold.gold_agent_view_context
gold.gold_agent_event_context
gold.gold_agent_circuit_history
```

Important limitation:

`gold_map_event_days` is useful for map/event context, but it filters events with non-null `LATITUD` and `LONGITUD`. For time-series interpretability, the system should not lose non-geocoded events. The preferred source for event attribution is therefore:

1. `silver.silver_events`, or
2. a new gold presentation table/view that preserves all relevant events regardless of geolocation.

### 2.3 Existing agent and retrieval flow

Relevant files:

```text
src/chec_dashboard/services/agent_context_service.py
src/chec_dashboard/services/agent_orchestrator.py
src/chec_dashboard/services/prompt_service.py
src/chec_dashboard/services/retrieval_service.py
src/chec_dashboard/services/skill_service.py
databricks/scripts/setup_phase4_context_tools.py
```

Current agent pattern:

```text
selected_context
  -> build_chatbot_context_package(...)
  -> retrieve_chatbot_chunks(...)
  -> build_prompt(...)
  -> LLM answer with citations and guardrails
```

The new feature should reuse this pattern by creating a new structured context kind for time-series critical points.

---

## 3. Feature scope

### 3.1 MVP scope

The MVP should support:

1. Detect the top critical dates in the selected summary window.
2. Classify each critical date by criticality type:
   - high outlier,
   - low outlier,
   - sharp increase,
   - sharp decrease,
   - top contributor,
   - sustained elevated period,
   - SAIDI/SAIFI divergence,
   - data-quality flag.
3. Enrich each critical date with daily event attribution:
   - event count,
   - total duration,
   - affected users,
   - top causes,
   - top event families,
   - top equipment,
   - top circuits/municipalities,
   - top individual events.
4. Retrieve relevant corpus chunks using the dominant cause/equipment/event family/circuit/municipality.
5. Generate a Spanish explanation for the selected time window or for one selected critical date.
6. Render chart markers and a summary panel in the SAIDI/SAIFI time-evolution tab.

### 3.2 Recommended non-goals for the MVP

Avoid these in the first release:

- Full causal inference.
- Forecasting future SAIDI/SAIFI values.
- Automatic regulatory compliance conclusions.
- Deep geospatial clustering.
- Model-based anomaly detection that cannot be explained easily.
- Agent-generated anomaly detection from raw time-series arrays.

The MVP should be rule-based, transparent, testable, and easy to explain to users.

---

## 4. Definition of “critical points”

A critical point is a date, or short date interval, in the SAIDI/SAIFI time series that deserves attention because it is statistically unusual, operationally important, or important for data quality.

### 4.1 Point-level criticality types

| Type | Meaning | Typical interpretation |
|---|---|---|
| `saidi_high_outlier` | SAIDI is unusually high compared with the selected window or baseline | Long duration or high user-duration impact |
| `saifi_high_outlier` | SAIFI is unusually high | Many interruptions or widespread frequency impact |
| `saidi_low_outlier` | SAIDI is unusually low after a non-zero baseline | Possible improvement, recovery, lower activity, filter effect, or missing data |
| `saifi_low_outlier` | SAIFI is unusually low after a non-zero baseline | Possible improvement, recovery, lower activity, filter effect, or missing data |
| `sharp_saidi_increase` | SAIDI jumps strongly versus the previous day or rolling baseline | Sudden reliability degradation |
| `sharp_saifi_increase` | SAIFI jumps strongly | Sudden increase in interruption frequency |
| `sharp_saidi_decrease` | SAIDI falls strongly after a previous high value | Recovery or normalization after incident |
| `sharp_saifi_decrease` | SAIFI falls strongly | Recovery or fewer interruptions |
| `top_saidi_contributor` | Date contributes a large share of total SAIDI in the window | Business-impact date, even if not statistically rare |
| `top_saifi_contributor` | Date contributes a large share of total SAIFI | Frequency-impact date |
| `local_peak` | Date is a visible local maximum | Useful for chart annotation |
| `saidi_saifi_divergence` | SAIDI and SAIFI behave differently | Helps distinguish long/focused events from frequent/short events |
| `data_quality_flag` | Missing dates, duplicated rows, negative values, suspicious zeros, null event causes, etc. | Prevents over-interpretation |

### 4.2 Interval-level criticality types

| Type | Meaning | Typical interpretation |
|---|---|---|
| `sustained_saidi_elevated_period` | SAIDI stays above baseline for several consecutive days | Persistent reliability degradation |
| `sustained_saifi_elevated_period` | SAIFI stays above baseline for several consecutive days | Repeated/frequent interruptions |
| `multi_day_recovery` | Indicator declines for several days after a spike | Recovery pattern |
| `recurring_pattern` | Same cause/equipment/circuit appears repeatedly around critical dates | Maintenance or reliability pattern worth reviewing |

---

## 5. Relevant variables

### 5.1 Time-series variables

These are computed from the daily SAIDI/SAIFI series.

| Variable | Type | Purpose |
|---|---:|---|
| `fecha_dia` | date | Primary date key |
| `SAIDI` | float | Daily SAIDI value in the chart |
| `SAIFI` | float | Daily SAIFI value in the chart |
| `saidi_rolling_median_7d` | float | Short-term SAIDI baseline |
| `saifi_rolling_median_7d` | float | Short-term SAIFI baseline |
| `saidi_rolling_median_30d` | float | Longer SAIDI baseline |
| `saifi_rolling_median_30d` | float | Longer SAIFI baseline |
| `saidi_robust_z` | float | Robust SAIDI outlier score |
| `saifi_robust_z` | float | Robust SAIFI outlier score |
| `saidi_delta_1d` | float | Day-over-day SAIDI change |
| `saifi_delta_1d` | float | Day-over-day SAIFI change |
| `saidi_delta_pct` | float/null | Relative SAIDI change, guarded against zero division |
| `saifi_delta_pct` | float/null | Relative SAIFI change, guarded against zero division |
| `saidi_contribution_pct` | float | Share of selected-window SAIDI total |
| `saifi_contribution_pct` | float | Share of selected-window SAIFI total |
| `saidi_saifi_ratio` | float/null | Duration-vs-frequency signal |
| `rolling_7d_saidi_sum` | float | Sustained SAIDI impact |
| `rolling_7d_saifi_sum` | float | Sustained SAIFI impact |
| `is_zero_day` | bool | Identifies zero-value days |
| `data_quality_flags` | list[string] | Prevents false explanations |

### 5.2 Daily aggregate variables

From `gold_saidi_saifi_daily`:

| Variable | Purpose |
|---|---|
| `fecha_dia` | Join key with time series |
| `circuito` | Scope and attribution |
| `municipio` | Geographic context |
| `event_family` | Event source family |
| `saidi_total` | Daily SAIDI contribution |
| `saifi_total` | Daily SAIFI contribution |
| `event_count` | Number of events |
| `duration_total_h` | Total event duration in hours |
| `users_affected_total` | Affected users |
| `first_event_ts` | First event timestamp |
| `last_event_ts` | Last event timestamp |

### 5.3 Event-level variables

Use `silver_events` or a new gold detail table that preserves all events.

Highest-priority event variables:

| Variable | Purpose |
|---|---|
| `evento` or `event_id` | Traceability |
| `inicio_ts` / `inicio` | Event start |
| `fin_ts` / `fin` | Event end |
| `duration_hours` / `duracion_h` | Explains SAIDI-heavy points |
| `severity_saidi` / `SAIDI` | Event contribution to SAIDI |
| `severity_saifi` / `SAIFI` | Event contribution to SAIFI |
| `cnt_usus` | Users affected |
| `CNT_TRAFOS_AFEC` | Transformers affected, when present |
| `tipo_duracion` | Short/long interruption classification, when present |
| `causa` | Most important categorical explanation |
| `event_family` | Source family: interruptor, tramo, transformador, SuperEventos |
| `tipo_equi_ope` | Equipment type involved |
| `tipo_elemento` | Specific element type |
| `equipo_ope` | Specific operated equipment |
| `cto_equi_ope` / `circuito` | Circuit attribution |
| `FPARENT` | Parent feeder/circuit relationship, when present |
| `MUN` / `municipio` | Municipality |
| `DEP` | Department, when present |
| `LATITUD`, `LONGITUD` | Spatial context, optional |
| `PHASES` | Phases involved, optional |
| `event_hour` | Hour-of-day pattern |
| `day_of_week` | Day-of-week pattern |
| `event_month` | Month/seasonality context |

Recommended priority order for explanations:

1. `severity_saidi`, `severity_saifi`, `duration_hours`, `cnt_usus`, `CNT_TRAFOS_AFEC`
2. `causa`
3. `event_family`, `tipo_equi_ope`, `tipo_elemento`
4. `circuito`, `equipo_ope`, `municipio`
5. `inicio_ts`, `fin_ts`, `event_hour`, `day_of_week`, `event_month`
6. `LATITUD`, `LONGITUD`
7. Asset/electrical variables, when available

### 5.4 Asset/network variables

Use these when the critical point is concentrated in a specific asset or asset family.

#### Transformers

| Variable | Purpose |
|---|---|
| `KVA` | Transformer capacity |
| `KV1` | Voltage level |
| `TRFTYPE` | Transformer type |
| `IMPEDANCE` | Electrical characteristic |
| `DATE_FAB` | Manufacturing date / age proxy |
| `MARCA` | Manufacturer |
| `TIPO_SUB` | Subtype |
| `GRUPO015` | Regulatory/quality grouping if relevant |
| `OWNER1` | Ownership/responsibility context |

#### Switches/reclosers

| Variable | Purpose |
|---|---|
| `ASSEMBLY` | Equipment assembly/type |
| `KV` | Voltage |
| `STATE` | Normally open/closed status |
| `LINESECTIO` | Associated line section |
| `PHASES` | Phases |

#### Line segments

| Variable | Purpose |
|---|---|
| `LENGTH` | Segment length and exposure |
| `KVNOM` | Nominal voltage |
| `CONDUCTOR` | Conductor type/context |
| `MATERIALCONDUCTOR` | Conductor material |
| `TIPOCONDUCTOR` | Conductor category |
| `CALIBRECONDUCTOR` | Conductor gauge |
| `NEUTRAL` | Neutral configuration |
| `CALIBRENEUTRO` | Neutral gauge |
| `CAPACITY` | Capacity |
| `RESISTANCE` | Resistance |
| `LONGITUD2`, `LATITUD2` | Segment endpoint coordinates |

### 5.5 Environmental/external variables

The project includes environmental event sources for `vegetacion` and `rayos`. Use same-date and same-municipality joins for the MVP. Later, add geospatial proximity joins.

| Variable | Purpose |
|---|---|
| `environment_family` | Vegetación or Rayos |
| `fecha_dia` / `fecha_evento_ts` | Temporal coincidence |
| `municipio` | Simple spatial join |
| `LATITUD`, `LONGITUD` | Optional geospatial proximity |
| `precip_total_mm` | Rain signal, if available |
| `precip_max_mm_h` | Intense-rain signal, if available |
| `wind_gust_max` | Wind-gust signal, if available |
| `wind_speed_max` | Wind signal, if available |
| `humidity_avg` | Weather context, if available |
| `temperature_avg_c` | Weather context, if available |

---

## 6. Data model additions

### 6.1 New gold table/view: event detail for time-series attribution

Create a gold presentation view that preserves event details even without geolocation.

Suggested name:

```text
gold.gold_timeseries_event_details
```

Purpose:

- Provide event-level attribution for candidate critical dates.
- Avoid using `gold_map_event_days` as the only source because it filters out non-geocoded events.
- Keep the output stable and small enough for API use.

Suggested columns:

```text
event_id
fecha_dia
inicio_ts
fin_ts
duration_hours
severity_saidi
severity_saifi
cnt_usus
CNT_TRAFOS_AFEC
causa
event_family
tipo_equi_ope
tipo_elemento
equipo_ope
circuito
municipio
DEP
latitude
longitude
event_hour
day_of_week
event_month
source_logical_name
source_table
```

Suggested SQL/view logic:

```sql
CREATE OR REPLACE VIEW gold.gold_timeseries_event_details AS
SELECT
  CONCAT('event-', SUBSTR(SHA2(CONCAT_WS('|',
    COALESCE(CAST(fecha_dia AS STRING), ''),
    COALESCE(CAST(evento AS STRING), ''),
    COALESCE(CAST(circuito AS STRING), ''),
    COALESCE(CAST(equipo_ope AS STRING), ''),
    COALESCE(CAST(event_family AS STRING), ''),
    COALESCE(CAST(causa AS STRING), ''),
    COALESCE(CAST(severity_saidi AS STRING), ''),
    COALESCE(CAST(severity_saifi AS STRING), '')
  ), 256), 1, 16)) AS event_id,
  fecha_dia,
  inicio_ts,
  fin_ts,
  duration_hours,
  severity_saidi,
  severity_saifi,
  cnt_usus,
  CNT_TRAFOS_AFEC,
  causa,
  event_family,
  tipo_equi_ope,
  tipo_elemento,
  equipo_ope,
  circuito,
  municipio,
  DEP,
  latitude,
  longitude,
  event_hour,
  day_of_week,
  event_month,
  source_logical_name,
  source_table
FROM silver.silver_events
WHERE fecha_dia IS NOT NULL;
```

Use `allowMissingColumns` behavior upstream and tolerate columns that are absent in some raw sources.

### 6.2 New gold table/view: daily attribution

Suggested name:

```text
gold.gold_timeseries_daily_attribution
```

Purpose:

- Summarize the drivers for each candidate date.
- Support efficient “top causes”, “top event families”, “top equipment”, and “top circuits” lookups.

Suggested grain:

```text
fecha_dia, circuito, municipio, event_family, causa, tipo_equi_ope, tipo_elemento, equipo_ope
```

Suggested metrics:

```text
event_count
saidi_total
saifi_total
duration_total_h
users_affected_total
transformers_affected_total
first_event_ts
last_event_ts
```

Suggested SQL/view logic:

```sql
CREATE OR REPLACE VIEW gold.gold_timeseries_daily_attribution AS
SELECT
  fecha_dia,
  COALESCE(circuito, 'Sin circuito') AS circuito,
  COALESCE(municipio, 'Sin municipio') AS municipio,
  COALESCE(event_family, 'Sin criterio') AS event_family,
  COALESCE(causa, 'Sin causa') AS causa,
  COALESCE(tipo_equi_ope, 'Sin tipo equipo') AS tipo_equi_ope,
  COALESCE(tipo_elemento, 'Sin tipo elemento') AS tipo_elemento,
  COALESCE(equipo_ope, 'Sin equipo') AS equipo_ope,
  COUNT(*) AS event_count,
  COALESCE(SUM(severity_saidi), 0.0D) AS saidi_total,
  COALESCE(SUM(severity_saifi), 0.0D) AS saifi_total,
  COALESCE(SUM(duration_hours), 0.0D) AS duration_total_h,
  COALESCE(SUM(cnt_usus), 0.0D) AS users_affected_total,
  COALESCE(SUM(CNT_TRAFOS_AFEC), 0.0D) AS transformers_affected_total,
  MIN(inicio_ts) AS first_event_ts,
  MAX(fin_ts) AS last_event_ts
FROM gold.gold_timeseries_event_details
GROUP BY
  fecha_dia,
  COALESCE(circuito, 'Sin circuito'),
  COALESCE(municipio, 'Sin municipio'),
  COALESCE(event_family, 'Sin criterio'),
  COALESCE(causa, 'Sin causa'),
  COALESCE(tipo_equi_ope, 'Sin tipo equipo'),
  COALESCE(tipo_elemento, 'Sin tipo elemento'),
  COALESCE(equipo_ope, 'Sin equipo');
```

### 6.3 Optional gold table/view: environmental daily context

Suggested name:

```text
gold.gold_timeseries_environment_daily
```

Purpose:

- Attach environmental signals to critical dates.
- Use same-date/same-municipality joins for MVP.

Suggested grain:

```text
fecha_dia, municipio, environment_family
```

Suggested metrics:

```text
environment_event_count
first_environment_ts
last_environment_ts
```

---

## 7. API contract

There are two viable integration options.

### 7.1 Recommended option: dedicated interpretability endpoint/mode

Add a separate data mode so that the chart loads quickly and interpretability can load on demand.

Extend `DataRequest.mode`:

```python
Literal[
    "map",
    "map_metadata",
    "summary",
    "summary_interpretability",
    "probability",
    "probability_metadata",
]
```

Add request payload:

```python
class SummaryInterpretabilityPayload(APIRequestModel):
    start_date: str | None = None
    end_date: str | None = None
    circuito: str | None = None
    metric_mode: Literal["SAIDI", "SAIFI", "BOTH"] = "BOTH"
    max_points: int = Field(default=5, ge=1, le=12)
    include_agent_text: bool = True
    selected_date: str | None = None
```

Add response fields:

```python
class CriticalityReason(APIResponseModel):
    reason_type: str
    metric: Literal["SAIDI", "SAIFI", "BOTH", "DATA_QUALITY"]
    score: float
    value: float | None = None
    baseline: float | None = None
    threshold: float | None = None
    detail: str

class AttributionItem(APIResponseModel):
    label: str
    event_count: int = 0
    saidi_total: float = 0.0
    saifi_total: float = 0.0
    duration_total_h: float = 0.0
    users_affected_total: float = 0.0
    contribution_pct: float | None = None

class CriticalEvent(APIResponseModel):
    event_id: str | None = None
    evento: str | None = None
    inicio_ts: str | None = None
    fin_ts: str | None = None
    causa: str | None = None
    event_family: str | None = None
    circuito: str | None = None
    municipio: str | None = None
    equipo_ope: str | None = None
    tipo_equi_ope: str | None = None
    tipo_elemento: str | None = None
    duration_hours: float = 0.0
    severity_saidi: float = 0.0
    severity_saifi: float = 0.0
    cnt_usus: float = 0.0

class CriticalPoint(APIResponseModel):
    fecha_dia: str
    rank: int
    criticality_score: float
    criticality_types: list[str]
    metrics: dict[str, Any]
    reasons: list[CriticalityReason]
    daily_aggregates: dict[str, Any]
    top_causes: list[AttributionItem]
    top_event_families: list[AttributionItem]
    top_equipment: list[AttributionItem]
    top_circuits: list[AttributionItem]
    top_events: list[CriticalEvent]
    external_signals: dict[str, Any]
    data_quality_flags: list[str]
    confidence: Literal["high", "medium", "low"]

class CriticalPeriod(APIResponseModel):
    start_date: str
    end_date: str
    metric: Literal["SAIDI", "SAIFI"]
    period_type: str
    score: float
    days: int
    summary: str

class SummaryInterpretabilityResponse(APIResponseModel):
    start_date: str
    end_date: str
    circuit_label: str
    metric_mode: str
    generated_at: str
    critical_points: list[CriticalPoint]
    critical_periods: list[CriticalPeriod]
    insight_text: str | None = None
    corpus_citations: list[dict[str, Any]] = Field(default_factory=list)
    status_text: str
```

### 7.2 Alternative option: extend summary payload

Add an optional `interpretability` object to `SummaryDataResponse`.

This is simpler for the frontend but can slow the initial chart load. If this option is chosen, add:

```python
class SummaryDataPayload(APIRequestModel):
    start_date: str | None = None
    end_date: str | None = None
    circuito: str | None = None
    metric_mode: Literal["SAIDI", "SAIFI", "BOTH"] = "BOTH"
    include_interpretability: bool = False
```

Recommended behavior:

- `include_interpretability=False` for initial chart render.
- `include_interpretability=True` only when user opens the interpretability panel or clicks “Analizar evolución”.

---

## 8. Detection algorithm

Implement the detection as a pure Python/pandas service first. Keep it independent of Dash, API, Databricks, and the LLM.

Suggested new file:

```text
src/chec_dashboard/services/time_series_interpretability_service.py
```

### 8.1 Main service functions

```python
def compute_time_series_features(daily_data: pd.DataFrame) -> pd.DataFrame:
    ...


def detect_critical_points(
    feature_frame: pd.DataFrame,
    *,
    metric_mode: str = "BOTH",
    max_points: int = 5,
    thresholds: CriticalityThresholds | None = None,
) -> list[dict[str, Any]]:
    ...


def detect_critical_periods(
    feature_frame: pd.DataFrame,
    *,
    metric_mode: str = "BOTH",
    thresholds: CriticalityThresholds | None = None,
) -> list[dict[str, Any]]:
    ...


def enrich_critical_points_with_attribution(
    critical_points: list[dict[str, Any]],
    attribution_frame: pd.DataFrame,
    event_frame: pd.DataFrame,
    environment_frame: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    ...
```

### 8.2 Robust statistics

For each metric `m` in `SAIDI`, `SAIFI`:

```text
median_m = median(m)
mad_m = median(abs(m - median_m))
robust_scale_m = 1.4826 * mad_m
robust_z_m = (m - median_m) / robust_scale_m
```

Fallbacks:

1. If `mad_m > 0`, use MAD.
2. Else if standard deviation is positive, use standard z-score.
3. Else use percentile/top-contributor rules only.
4. If the selected window is very short, avoid strong anomaly language.

Recommended minimum window logic:

| Window length | Behavior |
|---:|---|
| `< 7 days` | Use top contributor and day-over-day changes only; avoid outlier language |
| `7–13 days` | Use top contributor, local peaks, and deltas; use weak anomaly confidence |
| `>= 14 days` | Enable robust z-score and percentile rules |
| `>= 30 days` | Enable stronger rolling-baseline interpretation |

### 8.3 Feature computation

For each daily row:

```python
features["saidi_delta_1d"] = features["SAIDI"].diff()
features["saifi_delta_1d"] = features["SAIFI"].diff()
features["saidi_delta_abs"] = features["saidi_delta_1d"].abs()
features["saifi_delta_abs"] = features["saifi_delta_1d"].abs()
features["saidi_contribution_pct"] = features["SAIDI"] / features["SAIDI"].sum()
features["saifi_contribution_pct"] = features["SAIFI"] / features["SAIFI"].sum()
features["saidi_rolling_median_7d"] = features["SAIDI"].rolling(7, min_periods=3).median()
features["saifi_rolling_median_7d"] = features["SAIFI"].rolling(7, min_periods=3).median()
features["rolling_7d_saidi_sum"] = features["SAIDI"].rolling(7, min_periods=1).sum()
features["rolling_7d_saifi_sum"] = features["SAIFI"].rolling(7, min_periods=1).sum()
```

Relative deltas need zero guards:

```python
saidi_delta_pct = delta / previous_value if previous_value > epsilon else None
```

Use `epsilon = 1e-9` or a configurable value.

### 8.4 Criticality rules

#### Rule A: high outlier

Flag if either condition is true:

```text
robust_z >= 3.0
value >= p95 of selected window
```

Suggested labels:

```text
saidi_high_outlier
saifi_high_outlier
```

#### Rule B: low outlier

Flag if:

```text
robust_z <= -2.5
or value <= p05 of selected window
```

but only when:

```text
rolling/recent baseline is meaningfully above zero
```

Do not overstate low values. The explanation should say:

> “El valor fue inusualmente bajo frente a la línea base observada; esto puede reflejar recuperación, menor actividad, efecto de filtros o datos faltantes.”

#### Rule C: sharp increase/decrease

Compute robust scores for day-over-day deltas.

Flag sharp increase if:

```text
delta_1d > 0
and delta_abs >= p95(delta_abs)
```

or:

```text
robust_z_delta >= 3.0
```

Flag sharp decrease if:

```text
delta_1d < 0
and delta_abs >= p95(delta_abs)
```

or:

```text
robust_z_delta <= -3.0
```

#### Rule D: top contributor

Flag if:

```text
rank(value) <= top_n_per_metric
```

or:

```text
contribution_pct >= 0.10
```

Recommended defaults:

```text
top_n_per_metric = 3
contribution_threshold = 10%
```

#### Rule E: sustained elevated period

Flag intervals where:

```text
value >= p80 or value >= rolling_median_30d + robust_margin
```

for at least:

```text
min_consecutive_days = 3
```

Return the interval, not only individual dates.

#### Rule F: local peak

Flag if:

```text
value_today > value_yesterday
and value_today >= value_tomorrow
and value_today >= rolling_median_7d * local_peak_multiplier
```

Suggested default:

```text
local_peak_multiplier = 1.5
```

Guard against near-zero baselines.

#### Rule G: SAIDI/SAIFI divergence

Flag when one metric is critical and the other is not.

Examples:

```text
SAIDI high + SAIFI normal
  -> fewer interruptions but longer duration or higher duration impact

SAIFI high + SAIDI normal
  -> more frequent interruptions but shorter duration

Both high
  -> broad and/or long-impact reliability issue
```

Suggested implementation:

```text
saidi_is_high = saidi_robust_z >= 3 or saidi_contribution_pct >= 0.10
saifi_is_high = saifi_robust_z >= 3 or saifi_contribution_pct >= 0.10

if saidi_is_high != saifi_is_high:
    flag divergence
```

#### Rule H: data-quality critical points

Flag suspicious rows before explanation.

Examples:

```text
negative_saidi
negative_saifi
missing_date_after_reindex
zero_after_nonzero_period
duplicated_date_in_raw_daily
null_or_unknown_cause_dominates
no_event_rows_for_nonzero_indicator
event_rows_exist_but_indicator_zero
missing_duration_for_saidi_driver
missing_user_count_for_saifi_driver
```

Data-quality flags should reduce confidence and change the agent’s wording.

---

## 9. Criticality scoring

Each date can receive multiple reasons. Merge them into one `CriticalPoint` per date.

Suggested scoring components:

```text
outlier_score      = min(abs(robust_z) / 5, 1)
delta_score        = percentile_rank(abs(delta_1d))
contribution_score = min(contribution_pct / 0.20, 1)
sustained_score    = 1 if date belongs to sustained period else 0
local_peak_score   = 0.6 if local peak else 0
divergence_score   = 0.7 if divergence else 0
data_quality_score = 0.5 if data-quality issue else 0
```

Recommended weighted score:

```text
criticality_score = max(
  0.35 * outlier_score + 0.25 * delta_score + 0.30 * contribution_score + 0.10 * sustained_score,
  local_peak_score,
  divergence_score,
  data_quality_score
)
```

Then apply a confidence adjustment:

```text
confidence = high
  if window >= 30 days and event attribution coverage is strong

confidence = medium
  if window >= 14 days or partial event attribution is available

confidence = low
  if window < 14 days, many missing fields, or nonzero indicators lack event rows
```

Recommended ranking:

1. Sort by `criticality_score` descending.
2. Keep at most `max_points` dates.
3. Deduplicate adjacent dates if they are part of the same sustained episode, unless the user selected “show all markers”.

---

## 10. Event attribution rules

For every candidate date, fetch event-level and daily-attribution rows.

### 10.1 Candidate-first query pattern

Avoid loading all event rows in large windows.

Recommended flow:

```text
1. Fetch daily SAIDI/SAIFI series for selected filters.
2. Detect candidate critical dates.
3. Fetch event attribution only for candidate dates.
4. Fetch top event rows only for candidate dates.
5. Build agent context from compact summaries.
```

### 10.2 Top attribution groups

For each critical date, compute top groups by:

```text
cause
event_family
equipment
circuit
municipality
equipment type
element type
```

For each group, compute:

```text
event_count
saidi_total
saifi_total
duration_total_h
users_affected_total
contribution_pct_to_day_saidi
contribution_pct_to_day_saifi
```

### 10.3 Top individual events

For each date, fetch top events ordered by impact.

Suggested ordering:

```sql
ORDER BY
  COALESCE(severity_saidi, 0.0) + COALESCE(severity_saifi, 0.0) DESC,
  COALESCE(duration_hours, 0.0) DESC,
  COALESCE(cnt_usus, 0.0) DESC
LIMIT 10
```

### 10.4 Concentration flags

Add concentration flags when a group dominates the day.

Examples:

```text
dominant_cause
  if one cause contributes >= 50% of daily SAIDI or SAIFI

dominant_equipment
  if one equipment contributes >= 50% of daily SAIDI or SAIFI

dominant_event_family
  if one family contributes >= 50% of daily SAIDI or SAIFI

fragmented_impact
  if many events each contribute small shares
```

Interpretation examples:

```text
One dominant event/cause
  -> likely a focused incident or asset-related issue

Many small events
  -> distributed reliability issue or repeated interruptions

High SAIDI with few events
  -> long-duration/high-duration-impact events

High SAIFI with many events
  -> high frequency/repetition, possibly short interruptions
```

---

## 11. Corpus/RAG usage

The corpus should support interpretation. It should not decide which dates are critical.

### 11.1 Retrieval query construction

For each critical point, build a retrieval query from:

```text
SAIDI SAIFI confiabilidad calidad servicio
{criticality_types}
{dominant_cause}
{dominant_event_family}
{dominant_equipment_type}
{dominant_element_type}
{circuito}
{municipio}
vegetacion rayos viento lluvia mantenimiento
```

Example query:

```text
SAIDI SAIFI confiabilidad calidad servicio pico SAIDI cambio brusco transformador causa falla equipo circuito X municipio Y mantenimiento duración usuarios afectados
```

### 11.2 Structured context passed to retriever

Use the existing `retrieve_chatbot_chunks` pattern by passing a compact context object:

```json
{
  "kind": "timeseries_criticality",
  "nombre_analisis": "Confiabilidad",
  "summary": {
    "text": "Puntos críticos SAIDI/SAIFI para circuito X entre 2024-01-01 y 2024-06-30."
  },
  "selected_context": {
    "circuito": "X",
    "start_date": "2024-01-01",
    "end_date": "2024-06-30",
    "metric_mode": "BOTH"
  },
  "critical_points": [
    {
      "fecha_dia": "2024-06-10",
      "criticality_types": ["saidi_high_outlier", "top_saidi_contributor"],
      "top_causes": ["..."],
      "top_event_families": ["..."],
      "top_equipment": ["..."]
    }
  ],
  "metrics": {
    "saidi_total": 0.0,
    "saifi_total": 0.0,
    "event_count": 0
  }
}
```

### 11.3 Agent prompt instructions

Add or reuse a reliability skill instruction specialized for time-series interpretation.

Suggested prompt rules:

```text
- Responde en español.
- Explica primero qué punto o periodo fue marcado como crítico y por qué.
- Usa los tipos de criticidad calculados; no inventes nuevos tipos.
- Distingue entre evidencia observada, hipótesis y datos faltantes.
- Usa valores concretos de SAIDI, SAIFI, eventos, duración y usuarios afectados.
- Si una causa, equipo o familia domina el día, dilo con su porcentaje de contribución.
- Si hay señales ambientales, usa lenguaje de coincidencia temporal/espacial, no de causalidad confirmada.
- Si el corpus no aporta evidencia suficiente, dilo claramente.
- No afirmes cumplimiento/incumplimiento legal definitivo.
- Cita documentos recuperados usando [1], [2], etc.
```

### 11.4 Recommended answer structure

For the interpretability panel, the agent should produce a compact version:

```text
## Resumen de puntos críticos
## Punto más relevante
## Posibles explicaciones desde eventos
## Señales del corpus
## Datos faltantes
## Recomendaciones
## Limitaciones
```

For a selected point, use:

```text
## Estado observado
## Por qué se marcó como crítico
## Eventos que explican el punto
## Variables relevantes
## Evidencia del corpus
## Datos faltantes
## Recomendaciones
## Limitaciones
```

---

## 12. Frontend design

### 12.1 Summary tab additions

Modify:

```text
src/chec_dashboard/pages/summary_page.py
```

Add:

1. A button or toggle:

```text
Analizar evolución
```

2. A side/bottom panel:

```text
Interpretación de puntos críticos
```

3. A list of critical points:

```text
Fecha | Tipo | SAIDI | SAIFI | Principal explicación | Confianza
```

4. Optional click behavior:

- Click a marker on the chart.
- Select the corresponding critical point in the panel.
- Show detailed explanation for that date.

### 12.2 Chart markers

Extend `_build_line_figure` to receive optional `critical_points`.

Recommended signature:

```python
def _build_line_figure(
    daily_data: pd.DataFrame,
    metric_mode: str,
    critical_points: list[dict[str, Any]] | None = None,
) -> go.Figure:
    ...
```

For markers:

```python
fig.add_trace(
    go.Scatter(
        x=marker_dates,
        y=marker_values,
        mode="markers+text",
        name="Puntos críticos",
        text=marker_labels,
        hovertext=marker_hover,
        hoverinfo="text",
    )
)
```

Recommended labels:

| Criticality type | UI label |
|---|---|
| `saidi_high_outlier` | `Pico SAIDI` |
| `saifi_high_outlier` | `Pico SAIFI` |
| `sharp_saidi_increase` | `Subida SAIDI` |
| `sharp_saifi_increase` | `Subida SAIFI` |
| `sharp_saidi_decrease` | `Bajada SAIDI` |
| `sharp_saifi_decrease` | `Bajada SAIFI` |
| `top_saidi_contributor` | `Alto aporte SAIDI` |
| `top_saifi_contributor` | `Alto aporte SAIFI` |
| `sustained_saidi_elevated_period` | `Periodo SAIDI` |
| `sustained_saifi_elevated_period` | `Periodo SAIFI` |
| `saidi_saifi_divergence` | `Divergencia` |
| `data_quality_flag` | `Revisar datos` |

Avoid too many labels. Show labels for the top 3 points and markers for the rest.

### 12.3 Panel content

Each critical point card should show:

```text
Fecha: 2024-06-10
Tipo: Pico SAIDI + alto aporte
SAIDI: 12.40 | SAIFI: 0.80
Eventos: 14 | Duración total: 38.2 h | Usuarios afectados: 3,200
Principal causa: ...
Familia dominante: ...
Equipo dominante: ...
Confianza: media
```

Detail expansion:

```text
Por qué se marcó:
- SAIDI está por encima del percentil 95.
- El día aporta 18.5% del SAIDI de la ventana.
- El incremento frente al día anterior fue de 9.1.

Eventos que más aportan:
- Evento A: SAIDI 6.2, SAIFI 0.3, duración 12.1 h, causa ...
- Evento B: ...

Datos faltantes:
- No se encontró causa en 30% de los eventos.
- No hay señal ambiental georreferenciada para el municipio.
```

### 12.4 Loading and error states

Recommended UI messages:

```text
Analizando puntos críticos de la evolución...
No se detectaron puntos críticos con los umbrales actuales.
No hay suficientes datos para análisis estadístico robusto; se muestran principales contribuyentes.
Se detectaron valores críticos, pero faltan eventos detallados para explicar algunos puntos.
```

---

## 13. Backend implementation plan

### Step 1: Add pure interpretability service

Create:

```text
src/chec_dashboard/services/time_series_interpretability_service.py
```

Include:

```python
@dataclass(frozen=True)
class CriticalityThresholds:
    high_robust_z: float = 3.0
    low_robust_z: float = -2.5
    delta_robust_z: float = 3.0
    high_percentile: float = 0.95
    low_percentile: float = 0.05
    top_contributor_pct: float = 0.10
    sustained_percentile: float = 0.80
    sustained_min_days: int = 3
    max_points: int = 5
```

Core functions:

```python
normalize_daily_frame(...)
compute_time_series_features(...)
detect_point_reasons(...)
detect_critical_periods(...)
rank_and_merge_critical_points(...)
compute_data_quality_flags(...)
build_critical_point_payload(...)
```

Keep functions deterministic and unit-testable.

### Step 2: Add local fallback enrichment

Modify:

```text
src/chec_dashboard/services/summary_service.py
```

Add a function that can use the local `SummaryDataset.frame` to enrich candidate points.

Suggested function:

```python
def get_summary_interpretability_payload(
    dataset: SummaryDataset,
    start_date_raw: str | None,
    end_date_raw: str | None,
    circuito: str | None,
    metric_mode: str | None,
    max_points: int = 5,
) -> dict[str, Any]:
    ...
```

Local caveat:

The local pickle may not include all event variables. The function should gracefully return available fields and add data-quality flags for missing variables.

### Step 3: Add Databricks enrichment

Modify:

```text
src/chec_dashboard/services/databricks_data_service.py
```

Add:

```python
def get_summary_interpretability_payload(
    settings: Settings,
    start_date_raw: str | None,
    end_date_raw: str | None,
    circuito: str | None,
    metric_mode: str | None,
    max_points: int = 5,
    include_agent_text: bool = True,
    selected_date: str | None = None,
) -> dict[str, Any]:
    ...
```

Recommended query pattern:

1. Fetch daily time series with totals.
2. Compute candidate critical dates in Python.
3. Fetch attribution only for candidate dates.
4. Fetch top event details only for candidate dates.
5. Fetch environmental signals only for candidate dates and municipalities.
6. Build compact response.
7. Optionally call RAG/LLM for `insight_text`.

Daily query should include more than current `daily_data`:

```sql
SELECT
  CAST(fecha_dia AS DATE) AS fecha_dia,
  COALESCE(SUM(saidi_total), 0.0) AS SAIDI,
  COALESCE(SUM(saifi_total), 0.0) AS SAIFI,
  COALESCE(SUM(event_count), 0) AS event_count,
  COALESCE(SUM(duration_total_h), 0.0) AS duration_total_h,
  COALESCE(SUM(users_affected_total), 0.0) AS users_affected_total
FROM gold.gold_saidi_saifi_daily
WHERE ...
GROUP BY CAST(fecha_dia AS DATE)
ORDER BY CAST(fecha_dia AS DATE)
```

Attribution query should use candidate dates:

```sql
SELECT *
FROM gold.gold_timeseries_daily_attribution
WHERE fecha_dia IN (...candidate dates...)
  AND (...same circuit filter...)
ORDER BY fecha_dia, saidi_total + saifi_total DESC
```

Top events query:

```sql
SELECT *
FROM gold.gold_timeseries_event_details
WHERE fecha_dia IN (...candidate dates...)
  AND (...same circuit filter...)
ORDER BY
  fecha_dia,
  COALESCE(severity_saidi, 0.0) + COALESCE(severity_saifi, 0.0) DESC,
  COALESCE(duration_hours, 0.0) DESC,
  COALESCE(cnt_usus, 0.0) DESC
```

### Step 4: Add schemas

Modify:

```text
src/chec_dashboard/api/schemas/requests.py
src/chec_dashboard/api/schemas/responses.py
```

Add the request/response models described in section 7.

### Step 5: Add API routing

Modify:

```text
src/chec_dashboard/api/routes/data.py
```

Add route handling:

```python
if request.mode == "summary_interpretability":
    if request.summary_interpretability is None:
        raise ValueError("summary_interpretability payload is required")
    payload = get_summary_interpretability_payload(...)
    return DataResponse(mode="summary_interpretability", summary_interpretability=payload)
```

### Step 6: Add API client function

Modify:

```text
src/chec_dashboard/dash_app/api_client.py
```

Add:

```python
def fetch_summary_interpretability(
    start_date_raw: str | None,
    end_date_raw: str | None,
    circuito: str | None,
    metric_mode: str | None,
    *,
    max_points: int = 5,
    include_agent_text: bool = True,
    selected_date: str | None = None,
) -> dict[str, Any]:
    ...
```

Support both `inproc` and HTTP transport.

### Step 7: Update summary page layout and callbacks

Modify:

```text
src/chec_dashboard/pages/summary_page.py
```

Add components:

```text
html.Button(id="summary-interpretability-button", children="Analizar evolución")
dcc.Store(id="summary-interpretability-store")
html.Div(id="summary-interpretability-panel")
```

Add callback:

```text
Inputs:
- button click
- date range
- circuit
- metric mode

Outputs:
- interpretability store
- interpretability panel children
- updated chart figure with markers
```

Keep chart rendering functional even if interpretability fails.

### Step 8: Add Databricks setup script changes

Modify or create:

```text
databricks/scripts/setup_phase4_context_tools.py
```

or create a new setup script:

```text
databricks/scripts/setup_timeseries_interpretability_context.py
```

Add views:

```text
gold_timeseries_event_details
gold_timeseries_daily_attribution
gold_timeseries_environment_daily
```

Optionally add SQL function:

```text
agent_tools.get_timeseries_interpretability_context(
  circuit_arg STRING,
  start_date_arg STRING,
  end_date_arg STRING,
  dates_arg STRING
)
```

This function can return compact JSON for agent tools, similar to existing `get_circuit_history`.

---

## 14. Agent integration plan

### 14.1 New context kind

Add support for:

```text
timeseries_criticality
```

Potential modifications:

```text
src/chec_dashboard/services/agent_context_service.py
src/chec_dashboard/services/agent_orchestrator.py
src/chec_dashboard/services/prompt_service.py
```

### 14.2 Context package shape

```json
{
  "tipo_analisis": "reliability",
  "nombre_analisis": "Confiabilidad",
  "context_kind": "timeseries_criticality",
  "selected_context": {
    "circuito": "TODOS or selected circuit",
    "start_date": "YYYY-MM-DD",
    "end_date": "YYYY-MM-DD",
    "metric_mode": "BOTH"
  },
  "metrics": {
    "saidi_total": 0.0,
    "saifi_total": 0.0,
    "event_count": 0
  },
  "critical_points": [],
  "critical_periods": [],
  "external_signals": {},
  "data_source_scope": "Datos internos CHEC disponibles en el dashboard...",
  "response_guardrails": {
    "causality": "Do not state causal claims unless supported by explicit event cause fields or documents.",
    "citations": "Cite retrieved documents with [1], [2]."
  }
}
```

### 14.3 Agent wording rules

The agent should use careful language:

Use:

```text
- “El punto fue marcado porque…”
- “La evidencia disponible muestra…”
- “La causa registrada más relevante fue…”
- “La señal ambiental coincide temporalmente con…”
- “Esto es consistente con…”
- “Se recomienda verificar…”
```

Avoid:

```text
- “Esto demuestra que…”
- “La causa fue definitivamente…”
- “Hay incumplimiento confirmado…”
- “La empresa es responsable de…”
```

### 14.4 Generated explanation examples

Window-level explanation:

```text
Entre 2024-01-01 y 2024-06-30 se identificaron 5 fechas críticas. El punto más relevante fue 2024-06-10 porque SAIDI superó el percentil 95 de la ventana y aportó 18.5% del SAIDI total. La diferencia entre SAIDI alto y SAIFI moderado sugiere que el impacto estuvo más asociado a duración que a frecuencia. Los eventos del día se concentraron en la familia Transformador y en la causa registrada “...”.
```

Point-level explanation:

```text
El 2024-06-10 fue marcado como crítico por tres razones: pico de SAIDI, incremento brusco frente al día anterior y alto aporte al total de la ventana. Los eventos del día acumularon 38.2 horas de duración y 3,200 usuarios afectados. La causa dominante explica 62% del SAIDI diario, por lo que la evidencia apunta a un impacto concentrado. Sin embargo, faltan datos ambientales georreferenciados para confirmar si hubo una condición externa asociada.
```

---

## 15. Configuration

Add settings with safe defaults.

Suggested additions in:

```text
src/chec_dashboard/core/config.py
```

```python
summary_interpretability_enabled: bool = True
summary_interpretability_max_points: int = 5
summary_interpretability_high_robust_z: float = 3.0
summary_interpretability_low_robust_z: float = -2.5
summary_interpretability_delta_robust_z: float = 3.0
summary_interpretability_top_contributor_pct: float = 0.10
summary_interpretability_sustained_min_days: int = 3
summary_interpretability_include_agent_text_default: bool = True
summary_interpretability_cache_seconds: int = 300
```

Add corresponding `.env.example` values:

```text
SUMMARY_INTERPRETABILITY_ENABLED=true
SUMMARY_INTERPRETABILITY_MAX_POINTS=5
SUMMARY_INTERPRETABILITY_HIGH_ROBUST_Z=3.0
SUMMARY_INTERPRETABILITY_LOW_ROBUST_Z=-2.5
SUMMARY_INTERPRETABILITY_DELTA_ROBUST_Z=3.0
SUMMARY_INTERPRETABILITY_TOP_CONTRIBUTOR_PCT=0.10
SUMMARY_INTERPRETABILITY_SUSTAINED_MIN_DAYS=3
SUMMARY_INTERPRETABILITY_INCLUDE_AGENT_TEXT_DEFAULT=true
SUMMARY_INTERPRETABILITY_CACHE_SECONDS=300
```

---

## 16. Caching and performance

### 16.1 Cache key

Use filters and thresholds in the cache key:

```text
summary_interpretability:{circuit}:{metric_mode}:{start_date}:{end_date}:{max_points}:{threshold_hash}:{include_agent_text}
```

### 16.2 Recommended cache TTL

```text
300 seconds
```

This matches dashboard interaction patterns and avoids repeated LLM/RAG calls.

### 16.3 Performance safeguards

- Compute candidate dates from daily aggregates first.
- Fetch event details only for candidate dates.
- Limit event rows per critical date.
- Limit markers on chart.
- Limit corpus chunks.
- Truncate structured context before sending to LLM.
- Fall back to deterministic summary if LLM/RAG is unavailable.

---

## 17. Data-quality handling

Data-quality flags are part of interpretability, not just errors.

### 17.1 Time-series quality checks

Check:

```text
missing_dates
raw_duplicate_dates
negative_values
all_zero_window
zero_heavy_window
short_window
flat_series
extreme_single_day_dominance
```

### 17.2 Event-attribution quality checks

Check:

```text
nonzero_indicator_without_event_rows
event_rows_without_indicator_impact
missing_cause_share_high
missing_duration_share_high
missing_user_count_share_high
missing_equipment_share_high
missing_coordinates_share_high
```

### 17.3 Explanation impact

If data quality is poor, the agent must say so.

Examples:

```text
La fecha se marca como crítica por el valor del indicador, pero la atribución por causa tiene confianza baja porque 70% de los eventos no tiene causa registrada.
```

```text
El valor SAIDI es distinto de cero, pero no se encontraron eventos detallados asociados al mismo filtro. Se recomienda revisar la consistencia entre la tabla diaria y la tabla de eventos.
```

---

## 18. Testing plan

### 18.1 Unit tests for pure analytics

Create:

```text
tests/test_time_series_interpretability_service.py
```

Test cases:

1. High SAIDI spike is detected.
2. High SAIFI spike is detected.
3. Sharp increase is detected.
4. Sharp decrease is detected.
5. Top contributor is detected even when robust z-score is not available.
6. Sustained elevated period is detected.
7. SAIDI/SAIFI divergence is detected.
8. Short windows do not produce overconfident outlier language.
9. Flat all-zero windows produce no critical points, but return a clear status.
10. Negative values create data-quality flags.
11. Missing event attribution lowers confidence.
12. Adjacent critical dates are merged or grouped correctly.

### 18.2 API tests

Update:

```text
tests/test_api.py
tests/test_services.py
```

Add tests for:

```text
POST /data mode="summary_interpretability"
valid response shape
empty-data response
short-window response
candidate dates with attribution
agent text disabled
agent text enabled but retriever unavailable
```

### 18.3 Frontend callback tests

Update or add:

```text
tests/test_summary_callbacks.py
```

Test:

```text
clicking "Analizar evolución" calls fetch_summary_interpretability
chart receives critical markers
panel renders critical point cards
empty critical point response shows empty-state message
API failure does not break existing summary chart
```

### 18.4 Databricks scaffold tests

Update:

```text
tests/test_databricks_phase1_scaffold.py
tests/test_databricks_parity_runtime.py
```

Test that new views/functions are declared:

```text
gold_timeseries_event_details
gold_timeseries_daily_attribution
gold_timeseries_environment_daily
get_timeseries_interpretability_context, if added
```

### 18.5 Golden example tests

Create small synthetic daily data:

```text
Date        SAIDI  SAIFI
2024-01-01  0.1    0.02
2024-01-02  0.2    0.03
2024-01-03  9.5    0.05
2024-01-04  0.3    0.04
```

Expected:

```text
2024-01-03 has:
- saidi_high_outlier
- sharp_saidi_increase
- top_saidi_contributor
- saidi_saifi_divergence
```

---

## 19. Acceptance criteria

### 19.1 Functional criteria

The feature is accepted when:

1. The summary tab still loads the SAIDI/SAIFI line chart as before.
2. Users can request an interpretability analysis for the selected window/circuit/metric.
3. The backend returns a ranked list of critical dates.
4. Each critical date has at least one clear reason.
5. Each critical date includes available event attribution.
6. Chart markers appear for the top critical dates.
7. The panel explains why each date was marked.
8. The agent explanation uses structured context and corpus chunks.
9. Missing evidence is explicitly identified.
10. The feature gracefully handles empty, zero, flat, or short time windows.

### 19.2 Quality criteria

The feature is accepted when:

1. Detection is deterministic and testable.
2. Thresholds are configurable.
3. The agent does not invent causes or requirements.
4. Corpus citations appear when documents support claims.
5. Causal language is careful and evidence-bound.
6. API payloads are compact.
7. Large windows do not fetch all event details unnecessarily.
8. Interpretability failure does not break the normal summary chart.

---

## 20. Rollout plan

### Phase 1: Deterministic analytics only

- Add pure time-series interpretability service.
- Detect critical dates and periods.
- Return reasons and scores.
- Add tests.
- No UI changes yet.

### Phase 2: Backend API and event attribution

- Add `summary_interpretability` API mode.
- Add Databricks event attribution queries.
- Add local fallback enrichment.
- Add data-quality flags.
- Add tests.

### Phase 3: Summary tab UI

- Add “Analizar evolución” button.
- Add chart markers.
- Add interpretability panel.
- Add empty/error/loading states.
- Add callback tests.

### Phase 4: Corpus/RAG explanation

- Build `timeseries_criticality` context package.
- Retrieve corpus chunks using dominant causes/equipment/families.
- Generate Spanish explanation.
- Add citations and limitations.
- Add fallback deterministic explanation if RAG/LLM unavailable.

### Phase 5: Databricks optimization

- Add gold detail/attribution/environment views.
- Add optional SQL context function.
- Add cache keys and TTL.
- Add deployment scripts/tests.

### Phase 6: UX and tuning

- Tune thresholds with real historical data.
- Compare detected dates with domain expert expectations.
- Add threshold configuration in environment.
- Add “why this point?” drill-down interactions.
- Add feedback capture for useful/not useful explanations.

---

## 21. Recommended MVP payload example

```json
{
  "start_date": "2024-01-01",
  "end_date": "2024-06-30",
  "circuit_label": "CIRCUITO_1",
  "metric_mode": "BOTH",
  "generated_at": "2026-06-04T00:00:00Z",
  "critical_points": [
    {
      "fecha_dia": "2024-06-10",
      "rank": 1,
      "criticality_score": 0.91,
      "criticality_types": [
        "saidi_high_outlier",
        "sharp_saidi_increase",
        "top_saidi_contributor",
        "saidi_saifi_divergence"
      ],
      "metrics": {
        "SAIDI": 12.4,
        "SAIFI": 0.8,
        "saidi_robust_z": 3.7,
        "saifi_robust_z": 1.2,
        "saidi_delta_1d": 9.1,
        "saidi_contribution_pct": 0.185,
        "saifi_contribution_pct": 0.032
      },
      "reasons": [
        {
          "reason_type": "saidi_high_outlier",
          "metric": "SAIDI",
          "score": 0.74,
          "value": 12.4,
          "baseline": 1.1,
          "threshold": 3.0,
          "detail": "SAIDI superó el umbral robusto de valores altos."
        }
      ],
      "daily_aggregates": {
        "event_count": 14,
        "duration_total_h": 38.2,
        "users_affected_total": 3200
      },
      "top_causes": [],
      "top_event_families": [],
      "top_equipment": [],
      "top_circuits": [],
      "top_events": [],
      "external_signals": {
        "rayos_count": 0,
        "vegetacion_count": 2
      },
      "data_quality_flags": [],
      "confidence": "medium"
    }
  ],
  "critical_periods": [],
  "insight_text": "...",
  "corpus_citations": [],
  "status_text": "Se detectaron 5 puntos críticos para la ventana seleccionada."
}
```

---

## 22. Suggested deterministic fallback explanation

When the LLM or corpus is unavailable, return a deterministic explanation generated from structured data.

Template:

```text
Se detectaron {n} puntos críticos entre {start_date} y {end_date}. El punto principal fue {fecha_dia}, con SAIDI={saidi} y SAIFI={saifi}. Se marcó por: {criticality_types}. En ese día se registraron {event_count} eventos, {duration_total_h} horas acumuladas de duración y {users_affected_total} usuarios afectados. La principal agrupación observada fue {dominant_group}. {data_quality_sentence}
```

This ensures the feature remains useful even without RAG.

---

## 23. Important implementation notes

1. Use deterministic analytics for criticality.
2. Use the agent for explanation, synthesis, and corpus-grounded recommendations.
3. Never rely only on `gold_map_event_days` for event attribution because it may exclude events without coordinates.
4. Use `silver_events` or a new gold event-detail view for complete event attribution.
5. Keep chart loading separate from interpretability loading if latency becomes noticeable.
6. Treat low outliers carefully; they can mean improvement, filtering, seasonality, missing events, or zero-heavy data.
7. Treat environmental variables as coincident signals unless explicit evidence supports causality.
8. Keep API payloads compact by sending only top critical dates and top events.
9. Always include data-quality flags in the response.
10. Use Spanish labels and explanations in the UI because the dashboard and agent are Spanish-oriented.

---

## 24. File-by-file checklist

### New files

```text
src/chec_dashboard/services/time_series_interpretability_service.py
tests/test_time_series_interpretability_service.py
```

Optional:

```text
databricks/scripts/setup_timeseries_interpretability_context.py
tests/test_summary_interpretability_api.py
tests/test_summary_interpretability_callbacks.py
```

### Files to modify

```text
src/chec_dashboard/core/config.py
.env.example
src/chec_dashboard/api/schemas/requests.py
src/chec_dashboard/api/schemas/responses.py
src/chec_dashboard/api/routes/data.py
src/chec_dashboard/dash_app/api_client.py
src/chec_dashboard/pages/summary_page.py
src/chec_dashboard/services/summary_service.py
src/chec_dashboard/services/databricks_data_service.py
src/chec_dashboard/services/agent_context_service.py
src/chec_dashboard/services/prompt_service.py
src/chec_dashboard/services/retrieval_service.py
databricks/notebooks/03_build_silver_gold.py
databricks/scripts/setup_phase4_context_tools.py
```

### Documentation to update

```text
README.md
docs/phase2_databricks_consumption_pilot.md
docs/phase35_databricks_app_parity.md
databricks/README.md
```

---

## 25. Final recommendation

Implement this feature in two layers:

1. **Analytics layer:** deterministic criticality detection and event attribution.
2. **Agent layer:** narrative explanation, corpus-grounded interpretation, and recommendations.

The most important early decision is to create a complete event-detail source for time-series attribution, because `gold_map_event_days` is map-oriented and may exclude non-geocoded events. Once the backend can produce reliable `CriticalPoint` objects, the UI and agent can be added safely without making the LLM responsible for raw anomaly detection.
