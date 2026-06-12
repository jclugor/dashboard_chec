# Databricks notebook source
from __future__ import annotations

from pyspark.sql import functions as F
from pyspark.sql.types import DoubleType, StringType, StructField, StructType

# COMMAND ----------
# MAGIC %run ./_shared_phase1

# COMMAND ----------
define_standard_widgets()
context = build_context()
manifest = load_manifest(context.manifest_path)
entries_by_name = {
    entry["logical_name"]: entry
    for entry in manifest.get("raw_sources", [])
    if entry.get("bronze_table")
}

IMPACT_METRICS = ("UITI", "UITI_VANO", "EVENT_COUNT", "USERS", "DURATION_RAW")


def bronze_table(logical_name: str):
    entry = entries_by_name[logical_name]
    frame = spark.table(table_name(context.catalog_name, "bronze", entry["bronze_table"]))
    selected_columns = list(entry.get("required_columns", []))
    weather_variables = entry.get("weather_variables", [])
    weather_offsets = entry.get("weather_offsets", [])
    if weather_variables and weather_offsets:
        selected_columns.extend(
            f"{variable}_{offset}"
            for variable in weather_variables
            for offset in range(int(weather_offsets[0]), int(weather_offsets[1]) + 1)
        )
    selected_columns = [column for column in dict.fromkeys(selected_columns) if column in frame.columns]
    return frame.select(*[F.col(column) for column in selected_columns]) if selected_columns else frame


def write_table(frame, schema_name: str, table_name_suffix: str) -> None:
    frame.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(
        table_name(context.catalog_name, schema_name, table_name_suffix)
    )


def clean_string(column: str):
    value = F.trim(F.col(column).cast("string"))
    return F.when(value == "", F.lit(None).cast("string")).otherwise(value)


def num(column: str):
    value = F.regexp_replace(clean_string(column), ",", ".")
    return value.cast("double")


def metric_struct(
    *,
    uiti_col: str = "uiti_total",
    uiti_vano_col: str = "uiti_vano_total",
    event_count_col: str = "event_count",
    users_col: str = "users_affected_total",
    duration_col: str = "duration_raw_total",
):
    return F.create_map(
        F.lit("UITI"),
        F.coalesce(F.col(uiti_col).cast("double"), F.lit(0.0)),
        F.lit("UITI_VANO"),
        F.coalesce(F.col(uiti_vano_col).cast("double"), F.lit(0.0)),
        F.lit("EVENT_COUNT"),
        F.coalesce(F.col(event_count_col).cast("double"), F.lit(0.0)),
        F.lit("USERS"),
        F.coalesce(F.col(users_col).cast("double"), F.lit(0.0)),
        F.lit("DURATION_RAW"),
        F.coalesce(F.col(duration_col).cast("double"), F.lit(0.0)),
    )


def empty_frame(schema: StructType):
    return spark.createDataFrame([], schema)


def coordinates_are_lon_lat(vanos_frame) -> bool:
    stats = vanos_frame.select(
        F.count(F.lit(1)).alias("total"),
        F.sum(
            F.when(
                num("X1").between(-180.0, 180.0)
                & num("X2").between(-180.0, 180.0)
                & num("Y1").between(-90.0, 90.0)
                & num("Y2").between(-90.0, 90.0),
                F.lit(1),
            ).otherwise(F.lit(0))
        ).alias("valid"),
    ).collect()[0]
    total = int(stats["total"] or 0)
    valid = int(stats["valid"] or 0)
    return total > 0 and valid / total >= 0.95


def ensure_columns(frame, columns: list[str]):
    result = frame
    for column in columns:
        if column not in result.columns:
            result = result.withColumn(column, F.lit(None).cast("string"))
    return result


# COMMAND ----------
causas = bronze_table("causas")
equipos = bronze_table("equipos_proteccion")
apoyos = bronze_table("apoyos")
vanos = ensure_columns(bronze_table("vanos"), ["municipio", "municipio_source", "municipio_confidence"])
transformadores = ensure_columns(
    bronze_table("transformador_profiles"),
    ["municipio", "municipio_source", "municipio_confidence"],
)
eventos = bronze_table("eventos")
fact = bronze_table("evento_vano_trafo")
clima = bronze_table("clima_vano_fecha")

# COMMAND ----------
events_typed = (
    eventos.withColumn("event_ts", F.to_timestamp(clean_string("FECHA")))
    .withColumn("fecha_dia", F.to_date(F.col("event_ts")))
    .withColumn("duration_raw", num("DURACION"))
    .withColumn("uiti_event", num("UITI"))
    .withColumn("event_users", num("TOT_USUS"))
    .withColumn("event_transformer_count", num("CNT_TRF"))
    .withColumn("COD_CAUSA", clean_string("COD_CAUSA"))
)

vanos_typed = (
    vanos.withColumn("FID_VANO", clean_string("FID_VANO"))
    .withColumn("FID_SW", clean_string("FID_SW"))
    .withColumn("FID_APOYO_FIN", clean_string("FID_APOYO_FIN"))
    .withColumn("municipio_vano", clean_string("municipio"))
    .withColumn("municipio_vano_source", clean_string("municipio_source"))
    .withColumn("municipio_vano_confidence", clean_string("municipio_confidence"))
    .drop("municipio", "municipio_source", "municipio_confidence")
    .withColumn("longitude", num("X1"))
    .withColumn("latitude", num("Y1"))
    .withColumn("longitude_end", num("X2"))
    .withColumn("latitude_end", num("Y2"))
    .withColumn("span_length", num("LONGITUD"))
    .withColumn("average_kwh_vano", num("PROMEDIO_KWH_VANO"))
    .withColumn("ddt", num("DDT"))
)

transformadores_typed = (
    transformadores.withColumn("trafo_profile_id", clean_string("trafo_profile_id"))
    .withColumn("municipio_trafo", clean_string("municipio"))
    .withColumn("municipio_trafo_source", clean_string("municipio_source"))
    .withColumn("municipio_trafo_confidence", clean_string("municipio_confidence"))
    .drop("municipio", "municipio_source", "municipio_confidence")
    .withColumn("transformer_users", num("CNT_USUS"))
    .withColumn("transformer_capacity", num("CAPACIDAD_NOMINAL"))
    .withColumn("average_kwh_transformer", num("PROMEDIO_KWH_TRF"))
)

equipos_typed = (
    equipos.withColumn("FID_SW", clean_string("FID_SW"))
    .withColumn("circuito_raw", clean_string("CIRCUITO"))
    .withColumn("protected_users", num("T_USUS_EQ_PROT"))
    .withColumn("protected_vano_count", num("CNT_VN_SW"))
)

causas_typed = causas.withColumn("COD_CAUSA", clean_string("COD_CAUSA")).withColumn(
    "causa", F.coalesce(clean_string("DESC_CAUSA"), F.lit("Sin causa"))
)

clima_typed = (
    clima.withColumn("clima_FID_VANO", clean_string("FID_VANO"))
    .withColumn("weather_ts", F.to_timestamp(clean_string("FECHA")))
    .drop("FID_VANO", "FECHA")
)

# COMMAND ----------
silver_vano_fact = (
    fact.withColumn("row_id", F.col("row_id").cast("long"))
    .withColumn("event_id", clean_string("event_id"))
    .withColumn("FID_VANO", clean_string("FID_VANO"))
    .withColumn("trafo_profile_id", clean_string("trafo_profile_id"))
    .withColumn("uiti_vano", num("UITI_VANO"))
    .join(events_typed, on="event_id", how="left")
    .join(vanos_typed, on="FID_VANO", how="left")
    .join(equipos_typed, on="FID_SW", how="left")
    .join(apoyos, on="FID_APOYO_FIN", how="left")
    .join(causas_typed, on="COD_CAUSA", how="left")
    .join(transformadores_typed, on="trafo_profile_id", how="left")
    .join(
        clima_typed,
        (F.col("FID_VANO") == F.col("clima_FID_VANO")) & (F.col("event_ts") == F.col("weather_ts")),
        "left",
    )
    .drop("clima_FID_VANO")
    .withColumn("circuito", F.coalesce(F.col("circuito_raw"), F.lit("Sin circuito")))
    .withColumn("municipio", F.coalesce(F.col("municipio_vano"), F.col("municipio_trafo"), F.lit("Sin municipio")))
    .withColumn(
        "municipio_source",
        F.coalesce(F.col("municipio_vano_source"), F.col("municipio_trafo_source")),
    )
    .withColumn(
        "municipio_confidence",
        F.coalesce(F.col("municipio_vano_confidence"), F.col("municipio_trafo_confidence"), F.lit("unresolved")),
    )
    .withColumn("event_family", F.lit("Eventos Vano"))
    .withColumn("criteria_group", F.col("event_family"))
    .withColumn("equipo_ope", F.coalesce(F.col("FID_SW"), F.col("COD_EQ_PROTEGE"), F.lit("Sin equipo")))
    .withColumn("tipo_equi_ope", F.coalesce(clean_string("TIPO"), F.lit("Proteccion")))
    .withColumn("tipo_elemento", F.coalesce(clean_string("TIPO_TAX"), F.lit("Vano")))
    .withColumn("asset_id", F.col("FID_VANO"))
    .withColumn("users_affected", F.coalesce(F.col("transformer_users"), F.col("event_users"), F.lit(0.0)))
    .withColumn("impact_flag", F.when(F.coalesce(F.col("uiti_vano"), F.lit(0.0)) > 0, F.lit(1)).otherwise(F.lit(0)))
)
write_table(silver_vano_fact, "silver", "silver_vano_fact")

silver_events = (
    silver_vano_fact.groupBy("event_id", "fecha_dia", "event_ts", "circuito", "municipio", "causa", "event_family")
    .agg(
        F.sum(F.coalesce(F.col("uiti_vano"), F.lit(0.0))).alias("uiti_total"),
        F.sum(F.coalesce(F.col("uiti_vano"), F.lit(0.0))).alias("uiti_vano_total"),
        F.max(F.coalesce(F.col("uiti_event"), F.lit(0.0))).alias("uiti_event_total"),
        F.max(F.coalesce(F.col("duration_raw"), F.lit(0.0))).alias("duration_raw"),
        F.sum(F.coalesce(F.col("users_affected"), F.lit(0.0))).alias("users_affected"),
        F.max(F.coalesce(F.col("event_transformer_count"), F.lit(0.0))).alias("transformer_count"),
        F.count(F.lit(1)).alias("fact_row_count"),
        F.first("equipo_ope", ignorenulls=True).alias("equipo_ope"),
        F.first("tipo_equi_ope", ignorenulls=True).alias("tipo_equi_ope"),
        F.first("tipo_elemento", ignorenulls=True).alias("tipo_elemento"),
        F.avg("latitude").alias("latitude"),
        F.avg("longitude").alias("longitude"),
    )
)
write_table(silver_events, "silver", "silver_events")

silver_assets = (
    vanos_typed.join(equipos_typed.select("FID_SW", "circuito_raw"), on="FID_SW", how="left")
    .withColumn("asset_family", F.lit("LineSegments"))
    .withColumn("display_label", F.coalesce(F.col("FID_VANO"), F.lit("Vano")))
    .withColumn("circuito", F.coalesce(F.col("circuito_raw"), F.lit("Sin circuito")))
    .withColumn("municipio", F.coalesce(F.col("municipio_vano"), F.lit("Sin municipio")))
    .withColumn("municipio_source", F.col("municipio_vano_source"))
    .withColumn("municipio_confidence", F.coalesce(F.col("municipio_vano_confidence"), F.lit("unresolved")))
    .withColumn("geometry_kind", F.lit("line"))
    .withColumn("map_date", F.current_date())
    .withColumn("map_period", F.date_format(F.col("map_date"), "yyyy-MM"))
    .withColumn("map_day", F.dayofmonth(F.col("map_date")))
    .withColumn(
        "popup_text",
        F.concat_ws(" | ", F.col("display_label"), F.col("circuito"), F.col("CONDUCTOR"), F.col("span_length").cast("string")),
    )
)
write_table(silver_assets, "silver", "silver_assets")

# COMMAND ----------
event_grouped = (
    silver_events.groupBy("fecha_dia", "circuito", "municipio", "event_family")
    .agg(
        F.sum("uiti_total").alias("uiti_total"),
        F.sum("uiti_vano_total").alias("uiti_vano_total"),
        F.countDistinct("event_id").alias("event_count"),
        F.sum("duration_raw").alias("duration_raw_total"),
        F.sum("users_affected").alias("users_affected_total"),
        F.sum("transformer_count").alias("transformer_count_total"),
        F.min("event_ts").alias("first_event_ts"),
        F.max("event_ts").alias("last_event_ts"),
    )
    .withColumn("metrics", metric_struct())
    .withColumn("primary_metric_key", F.lit("UITI"))
    .withColumn("primary_metric_value", F.col("uiti_total"))
)
write_table(event_grouped, "gold", "gold_impact_daily")

circuit_summary_gold = (
    silver_events.groupBy("circuito", "municipio", "event_family")
    .agg(
        F.sum("uiti_total").alias("uiti_total"),
        F.sum("uiti_vano_total").alias("uiti_vano_total"),
        F.countDistinct("event_id").alias("event_count"),
        F.avg("duration_raw").alias("duration_raw_avg"),
        F.sum("duration_raw").alias("duration_raw_total"),
        F.sum("users_affected").alias("users_affected_total"),
        F.sum("transformer_count").alias("transformer_count_total"),
        F.min("event_ts").alias("first_event_ts"),
        F.max("event_ts").alias("last_event_ts"),
    )
    .withColumn("metrics", metric_struct(duration_col="duration_raw_total"))
    .withColumn("primary_metric_key", F.lit("UITI"))
    .withColumn("primary_metric_value", F.col("uiti_total"))
)
write_table(circuit_summary_gold, "gold", "gold_impact_circuit_summary")

timeseries_event_details_gold = (
    silver_vano_fact.withColumn("event_detail_id", F.concat(F.lit("fact-"), F.col("row_id").cast("string")))
    .withColumn("inicio_ts", F.col("event_ts"))
    .withColumn("fin_ts", F.lit(None).cast("timestamp"))
    .withColumn("UITI", F.col("uiti_event"))
    .withColumn("UITI_VANO", F.col("uiti_vano"))
    .withColumn("DURATION_RAW", F.col("duration_raw"))
    .withColumn("USERS", F.col("users_affected"))
    .select(
        "event_detail_id",
        "event_id",
        "row_id",
        "fecha_dia",
        "inicio_ts",
        "fin_ts",
        "causa",
        "event_family",
        "circuito",
        "municipio",
        "equipo_ope",
        "tipo_equi_ope",
        "tipo_elemento",
        "asset_id",
        "FID_VANO",
        "trafo_profile_id",
        "DURATION_RAW",
        "UITI",
        "UITI_VANO",
        "USERS",
        "latitude",
        "longitude",
        "longitude_end",
        "latitude_end",
        "criteria_group",
    )
)
write_table(timeseries_event_details_gold, "gold", "gold_timeseries_event_details")

timeseries_daily_attribution_gold = (
    timeseries_event_details_gold.groupBy(
        "fecha_dia",
        "circuito",
        "municipio",
        "causa",
        "event_family",
        "equipo_ope",
        "tipo_equi_ope",
    )
    .agg(
        F.countDistinct("event_id").alias("event_count"),
        F.sum(F.coalesce(F.col("UITI_VANO"), F.lit(0.0))).alias("uiti_total"),
        F.sum(F.coalesce(F.col("UITI_VANO"), F.lit(0.0))).alias("uiti_vano_total"),
        F.sum(F.coalesce(F.col("DURATION_RAW"), F.lit(0.0))).alias("duration_raw_total"),
        F.sum(F.coalesce(F.col("USERS"), F.lit(0.0))).alias("users_affected_total"),
        F.min("inicio_ts").alias("first_event_ts"),
        F.max("inicio_ts").alias("last_event_ts"),
    )
    .withColumn("metrics", metric_struct())
)
write_table(timeseries_daily_attribution_gold, "gold", "gold_timeseries_daily_attribution")

# COMMAND ----------
weather_columns = [
    f"{variable}_{offset}"
    for variable in entries_by_name["clima_vano_fecha"].get("weather_variables", [])
    for offset in range(
        int(entries_by_name["clima_vano_fecha"].get("weather_offsets", [0, 24])[0]),
        int(entries_by_name["clima_vano_fecha"].get("weather_offsets", [0, 24])[1]) + 1,
    )
]
weather_agg_exprs = [
    F.avg(F.regexp_replace(clean_string(column), ",", ".").cast("double")).alias(f"{column}_avg")
    for column in weather_columns
    if column in clima.columns
]
weather_with_municipio = clima.withColumn("FID_VANO", clean_string("FID_VANO")).join(
    vanos_typed.select("FID_VANO", "municipio_vano"),
    on="FID_VANO",
    how="left",
)
timeseries_environment_daily_gold = (
    weather_with_municipio.withColumn("fecha_dia", F.to_date(F.to_timestamp(clean_string("FECHA"))))
    .withColumn("municipio", F.coalesce(F.col("municipio_vano"), F.lit("Sin municipio")))
    .groupBy("fecha_dia", "municipio")
    .agg(*weather_agg_exprs)
    .withColumn("environment_family", F.lit("Clima"))
)
write_table(timeseries_environment_daily_gold, "gold", "gold_timeseries_environment_daily")

probability_inputs_gold = (
    silver_vano_fact.withColumn("source_date", F.col("fecha_dia"))
    .withColumn("target_flag", F.col("impact_flag"))
    .withColumn("UITI", F.col("uiti_event"))
    .withColumn("UITI_VANO", F.col("uiti_vano"))
    .withColumn("DURATION_RAW", F.col("duration_raw"))
    .withColumn("USERS", F.col("users_affected"))
    .withColumn("EVENT_COUNT", F.lit(1.0))
)
write_table(probability_inputs_gold, "gold", "gold_probability_inputs")

# COMMAND ----------
coordinates_ok = coordinates_are_lon_lat(vanos)

map_point_schema = StructType(
    [
        StructField("point_kind", StringType(), True),
        StructField("asset_family", StringType(), True),
        StructField("display_label", StringType(), True),
        StructField("CODE", StringType(), True),
        StructField("equipo_ope", StringType(), True),
        StructField("circuito", StringType(), True),
        StructField("municipio", StringType(), True),
        StructField("map_period", StringType(), True),
        StructField("map_day", DoubleType(), True),
        StructField("map_date", StringType(), True),
        StructField("LATITUD", DoubleType(), True),
        StructField("LONGITUD", DoubleType(), True),
        StructField("latitude", DoubleType(), True),
        StructField("longitude", DoubleType(), True),
        StructField("latitude_end", DoubleType(), True),
        StructField("longitude_end", DoubleType(), True),
        StructField("geometry_kind", StringType(), True),
        StructField("popup_text", StringType(), True),
        StructField("source_logical_name", StringType(), True),
        StructField("source_table", StringType(), True),
    ]
)

if coordinates_ok:
    map_points_gold = (
        silver_vano_fact.withColumn("point_kind", F.lit("event"))
        .withColumn("asset_family", F.lit("Eventos Vano"))
        .withColumn("display_label", F.concat_ws(" | ", F.col("event_id"), F.col("causa"), F.col("FID_VANO")))
        .withColumn("CODE", F.col("FID_VANO"))
        .withColumn("map_date", F.col("fecha_dia").cast("string"))
        .withColumn("map_period", F.date_format(F.col("fecha_dia"), "yyyy-MM"))
        .withColumn("map_day", F.dayofmonth(F.col("fecha_dia")).cast("double"))
        .withColumn("LATITUD", F.col("latitude"))
        .withColumn("LONGITUD", F.col("longitude"))
        .withColumn("geometry_kind", F.lit("point"))
        .withColumn("popup_text", F.concat_ws(" | ", F.col("event_id"), F.col("circuito"), F.col("causa"), F.col("uiti_vano").cast("string")))
        .withColumn("source_logical_name", F.lit("evento_vano_trafo"))
        .withColumn("source_table", F.lit(table_name(context.catalog_name, "silver", "silver_vano_fact")))
        .select([field.name for field in map_point_schema.fields])
        .unionByName(
            silver_assets.withColumn("point_kind", F.lit("asset"))
            .withColumn("asset_family", F.lit("Switches"))
            .withColumn("CODE", F.col("FID_SW"))
            .withColumn("equipo_ope", F.col("FID_SW"))
            .withColumn("map_date", F.col("map_date").cast("string"))
            .withColumn("map_day", F.col("map_day").cast("double"))
            .withColumn("LATITUD", ((F.col("latitude") + F.col("latitude_end")) / 2.0).cast("double"))
            .withColumn("LONGITUD", ((F.col("longitude") + F.col("longitude_end")) / 2.0).cast("double"))
            .withColumn("latitude", F.col("LATITUD"))
            .withColumn("longitude", F.col("LONGITUD"))
            .withColumn("latitude_end", F.lit(None).cast("double"))
            .withColumn("longitude_end", F.lit(None).cast("double"))
            .withColumn("popup_text", F.concat_ws(" | ", F.col("FID_SW"), F.col("circuito"), F.col("display_label")))
            .withColumn("source_logical_name", F.lit("vanos"))
            .withColumn("source_table", F.lit(table_name(context.catalog_name, "silver", "silver_assets")))
            .select([field.name for field in map_point_schema.fields]),
            allowMissingColumns=True,
        )
        .filter(F.col("LATITUD").isNotNull() & F.col("LONGITUD").isNotNull())
    )
else:
    map_points_gold = empty_frame(map_point_schema)

write_table(map_points_gold, "gold", "gold_map_points")

if coordinates_ok:
    map_line_segments_gold = (
        silver_assets.withColumn("point_kind", F.lit("asset"))
        .withColumn("LATITUD", F.col("latitude"))
        .withColumn("LONGITUD", F.col("longitude"))
        .withColumn("LATITUD2", F.col("latitude_end"))
        .withColumn("LONGITUD2", F.col("longitude_end"))
        .withColumn("MATERIALCONDUCTOR", F.col("CONDUCTOR"))
        .withColumn("TIPOCONDUCTOR", F.col("TIPO_TAX"))
        .withColumn("LENGTH", F.col("span_length"))
        .withColumn("CODE", F.col("FID_VANO"))
        .withColumn("equipo_ope", F.col("FID_SW"))
        .withColumn("CALIBRECONDUCTOR", F.col("CALIBRE_NEUTRO"))
        .withColumn("GUARDACONDUCTOR", F.lit(None).cast("string"))
        .withColumn("NEUTROCONDUCTOR", F.col("NG_RED"))
        .withColumn("CALIBRENEUTRO", F.col("CALIBRE_NEUTRO"))
        .withColumn("CAPACITY", F.lit(None).cast("double"))
        .withColumn("RESISTANCE", F.lit(None).cast("double"))
        .withColumn("ACOMETIDACONDUCTOR", F.lit(None).cast("string"))
        .withColumn("source_logical_name", F.lit("vanos"))
        .withColumn("source_table", F.lit(table_name(context.catalog_name, "silver", "silver_assets")))
        .filter(
            F.col("LATITUD").isNotNull()
            & F.col("LONGITUD").isNotNull()
            & F.col("LATITUD2").isNotNull()
            & F.col("LONGITUD2").isNotNull()
        )
    )
else:
    map_line_segments_gold = empty_frame(
        StructType(
            [
                StructField("point_kind", StringType(), True),
                StructField("asset_family", StringType(), True),
                StructField("display_label", StringType(), True),
                StructField("CODE", StringType(), True),
                StructField("equipo_ope", StringType(), True),
                StructField("circuito", StringType(), True),
                StructField("municipio", StringType(), True),
                StructField("map_period", StringType(), True),
                StructField("map_day", DoubleType(), True),
                StructField("map_date", StringType(), True),
                StructField("latitude", DoubleType(), True),
                StructField("longitude", DoubleType(), True),
                StructField("latitude_end", DoubleType(), True),
                StructField("longitude_end", DoubleType(), True),
                StructField("geometry_kind", StringType(), True),
                StructField("popup_text", StringType(), True),
                StructField("source_logical_name", StringType(), True),
                StructField("source_table", StringType(), True),
                StructField("LATITUD", DoubleType(), True),
                StructField("LONGITUD", DoubleType(), True),
                StructField("LATITUD2", DoubleType(), True),
                StructField("LONGITUD2", DoubleType(), True),
            ]
        )
    )
write_table(map_line_segments_gold, "gold", "gold_map_line_segments")

map_filter_index_gold = (
    map_points_gold.select("map_period", "municipio", "circuito")
    .unionByName(map_line_segments_gold.select("map_period", "municipio", "circuito"), allowMissingColumns=True)
    .filter(F.col("map_period").isNotNull())
    .dropDuplicates(["map_period", "municipio", "circuito"])
)
write_table(map_filter_index_gold, "gold", "gold_map_filter_index")

map_event_days_gold = (
    timeseries_event_details_gold.withColumn("map_date", F.col("fecha_dia"))
    .withColumn("map_period", F.date_format(F.col("fecha_dia"), "yyyy-MM"))
    .withColumn("map_day", F.dayofmonth(F.col("fecha_dia")))
    .withColumn("LATITUD", F.col("latitude"))
    .withColumn("LONGITUD", F.col("longitude"))
    .withColumn("MUN", F.col("municipio"))
    .withColumn("cto_equi_ope", F.col("circuito"))
    .withColumn("DURACION_RAW", F.col("DURATION_RAW"))
    .withColumn("cnt_usus", F.col("USERS"))
    .filter(F.col("LATITUD").isNotNull() & F.col("LONGITUD").isNotNull())
)
write_table(map_event_days_gold, "gold", "gold_map_event_days")

# COMMAND ----------
print(
    "Built normalized silver/gold tables using evento_vano_trafo as the central fact grain. "
    f"Coordinate validation status: {'lon_lat_ok' if coordinates_ok else 'invalid_coordinates_empty_map'}."
)
