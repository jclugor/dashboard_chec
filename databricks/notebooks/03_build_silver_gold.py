# Databricks notebook source
from __future__ import annotations

from functools import reduce

from pyspark.sql import functions as F

# COMMAND ----------
# MAGIC %run ./_shared_phase1

# COMMAND ----------
define_standard_widgets()
context = build_context()
manifest = load_manifest(context.manifest_path)


def add_literal(frame, target: str, value: str, data_type: str = "string"):
    return frame.withColumn(target, F.lit(value).cast(data_type))


def add_coalesced_string(frame, target: str, candidates: list[str]):
    exprs = [F.trim(F.col(column).cast("string")) for column in candidates if column in frame.columns]
    if exprs:
        return frame.withColumn(target, F.coalesce(*exprs))
    return frame.withColumn(target, F.lit(None).cast("string"))


def add_coalesced_double(frame, target: str, candidates: list[str]):
    exprs = [F.col(column).cast("double") for column in candidates if column in frame.columns]
    if exprs:
        return frame.withColumn(target, F.coalesce(*exprs))
    return frame.withColumn(target, F.lit(None).cast("double"))


def add_timestamp_column(frame, target: str, candidates: list[str]):
    exprs = [F.col(column).cast("timestamp") for column in candidates if column in frame.columns]
    if exprs:
        return frame.withColumn(target, F.coalesce(*exprs))
    return frame.withColumn(target, F.lit(None).cast("timestamp"))


def write_table(frame, schema_name: str, table_name_suffix: str) -> None:
    frame.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(
        table_name(context.catalog_name, schema_name, table_name_suffix)
    )


def union_frames(frames: list):
    if not frames:
        raise ValueError("No frames were provided for union.")
    return reduce(lambda left, right: left.unionByName(right, allowMissingColumns=True), frames)


asset_labels = {
    "trafos": "Transformers",
    "apoyos": "Supports",
    "switches": "Switches",
    "redmt": "LineSegments",
}

event_labels = {
    "super_eventos": "SuperEventos",
    "eventos_interruptor": "Eventos Interruptor",
    "eventos_tramo_linea": "Eventos Tramo",
    "eventos_transformador": "Eventos Transformador",
}

environment_labels = {
    "vegetacion": "Vegetacion",
    "rayos": "Rayos",
}

# COMMAND ----------
asset_frames: list = []
for entry in manifest.get("raw_sources", []):
    logical_name = entry["logical_name"]
    if logical_name not in asset_labels:
        continue

    bronze_name = table_name(context.catalog_name, "bronze", entry["bronze_table"])
    frame = spark.table(bronze_name)
    frame = add_literal(frame, "source_logical_name", logical_name)
    frame = add_literal(frame, "source_table", bronze_name)
    frame = add_literal(frame, "record_kind", "asset")
    frame = add_literal(frame, "asset_family", asset_labels[logical_name])
    frame = add_coalesced_string(frame, "equipo_ope", ["equipo_ope", "CODE"])
    frame = add_coalesced_string(frame, "circuito", ["FPARENT", "cto_equi_ope"])
    frame = add_coalesced_string(frame, "municipio", ["MUN"])
    frame = add_timestamp_column(frame, "fecha_registro", ["FECHA"])
    frame = add_coalesced_double(frame, "latitude", ["LATITUD"])
    frame = add_coalesced_double(frame, "longitude", ["LONGITUD"])
    frame = add_coalesced_double(frame, "latitude_end", ["LATITUD2"])
    frame = add_coalesced_double(frame, "longitude_end", ["LONGITUD2"])
    frame = add_literal(frame, "geometry_kind", "line" if logical_name == "redmt" else "point")
    frame = add_coalesced_string(frame, "display_label", ["equipo_ope", "CODE", "source_file_name", "asset_family"])
    frame = frame.withColumn(
        "popup_text",
        F.concat_ws(
            " | ",
            F.col("asset_family"),
            F.col("display_label"),
            F.col("circuito"),
            F.col("municipio"),
            F.col("source_file_name"),
        ),
    )
    asset_frames.append(frame)

assets_silver = union_frames(asset_frames)
write_table(assets_silver, "silver", "silver_assets")

# COMMAND ----------
event_frames: list = []
for entry in manifest.get("raw_sources", []):
    logical_name = entry["logical_name"]
    if logical_name not in event_labels:
        continue

    bronze_name = table_name(context.catalog_name, "bronze", entry["bronze_table"])
    frame = spark.table(bronze_name)
    frame = add_literal(frame, "source_logical_name", logical_name)
    frame = add_literal(frame, "source_table", bronze_name)
    frame = add_literal(frame, "record_kind", "event")
    frame = add_literal(frame, "event_family", event_labels[logical_name])
    frame = add_coalesced_string(frame, "evento", ["evento", "source_file_name"])
    frame = add_coalesced_string(frame, "equipo_ope", ["equipo_ope", "CODE"])
    frame = add_coalesced_string(frame, "circuito", ["cto_equi_ope", "FPARENT"])
    frame = add_coalesced_string(frame, "municipio", ["MUN"])
    frame = add_coalesced_string(frame, "causa", ["causa"])
    frame = add_coalesced_string(frame, "tipo_equi_ope", ["tipo_equi_ope"])
    frame = add_coalesced_string(frame, "tipo_elemento", ["tipo_elemento"])
    frame = add_timestamp_column(frame, "inicio_ts", ["inicio"])
    frame = add_timestamp_column(frame, "fin_ts", ["fin"])
    frame = frame.withColumn("fecha_dia", F.to_date(F.col("inicio_ts")))
    frame = frame.withColumn("event_hour", F.hour(F.col("inicio_ts")))
    frame = frame.withColumn("event_month", F.month(F.col("inicio_ts")))
    frame = frame.withColumn("event_year", F.year(F.col("inicio_ts")))
    frame = frame.withColumn("day_of_week", F.date_format(F.col("inicio_ts"), "E"))
    frame = add_coalesced_double(frame, "duration_hours", ["duracion_h"])
    frame = add_coalesced_double(frame, "severity_saidi", ["SAIDI"])
    frame = add_coalesced_double(frame, "severity_saifi", ["SAIFI"])
    frame = add_coalesced_double(frame, "cnt_usus", ["cnt_usus"])
    frame = add_coalesced_double(frame, "latitude", ["LATITUD"])
    frame = add_coalesced_double(frame, "longitude", ["LONGITUD"])
    frame = frame.withColumn(
        "impact_flag",
        F.when(
            (F.coalesce(F.col("severity_saidi"), F.lit(0.0)) > 0)
            | (F.coalesce(F.col("severity_saifi"), F.lit(0.0)) > 0),
            F.lit(1),
        ).otherwise(F.lit(0)),
    )
    frame = add_coalesced_string(frame, "display_label", ["evento", "equipo_ope", "event_family", "source_file_name"])
    frame = frame.withColumn(
        "popup_text",
        F.concat_ws(
            " | ",
            F.col("event_family"),
            F.col("display_label"),
            F.col("circuito"),
            F.col("municipio"),
            F.col("severity_saidi").cast("string"),
            F.col("severity_saifi").cast("string"),
        ),
    )
    event_frames.append(frame)

events_silver = union_frames(event_frames)
write_table(events_silver, "silver", "silver_events")

# COMMAND ----------
environment_frames: list = []
for entry in manifest.get("raw_sources", []):
    logical_name = entry["logical_name"]
    if logical_name not in environment_labels:
        continue

    bronze_name = table_name(context.catalog_name, "bronze", entry["bronze_table"])
    frame = spark.table(bronze_name)
    frame = add_literal(frame, "source_logical_name", logical_name)
    frame = add_literal(frame, "source_table", bronze_name)
    frame = add_literal(frame, "record_kind", "environment")
    frame = add_literal(frame, "environment_family", environment_labels[logical_name])
    frame = add_coalesced_string(frame, "municipio", ["MUN"])
    frame = add_timestamp_column(frame, "fecha_evento_ts", ["FECHA"])
    frame = frame.withColumn("fecha_dia", F.to_date(F.col("fecha_evento_ts")))
    frame = add_coalesced_double(frame, "latitude", ["LATITUD"])
    frame = add_coalesced_double(frame, "longitude", ["LONGITUD"])
    frame = add_coalesced_string(frame, "display_label", ["source_file_name", "environment_family"])
    frame = frame.withColumn(
        "popup_text",
        F.concat_ws(
            " | ",
            F.col("environment_family"),
            F.col("display_label"),
            F.col("municipio"),
            F.col("fecha_dia").cast("string"),
        ),
    )
    environment_frames.append(frame)

environment_silver = union_frames(environment_frames)
write_table(environment_silver, "silver", "silver_environmental_events")

# COMMAND ----------
daily_gold = (
    events_silver.withColumn("circuito", F.coalesce(F.col("circuito"), F.lit("Sin circuito")))
    .withColumn("municipio", F.coalesce(F.col("municipio"), F.lit("Sin municipio")))
    .withColumn("event_family", F.coalesce(F.col("event_family"), F.lit("Sin criterio")))
    .groupBy("fecha_dia", "circuito", "municipio", "event_family")
    .agg(
        F.sum(F.coalesce(F.col("severity_saidi"), F.lit(0.0))).alias("saidi_total"),
        F.sum(F.coalesce(F.col("severity_saifi"), F.lit(0.0))).alias("saifi_total"),
        F.count(F.lit(1)).alias("event_count"),
        F.sum(F.coalesce(F.col("duration_hours"), F.lit(0.0))).alias("duration_total_h"),
        F.sum(F.coalesce(F.col("cnt_usus"), F.lit(0.0))).alias("users_affected_total"),
        F.min(F.col("inicio_ts")).alias("first_event_ts"),
        F.max(F.col("fin_ts")).alias("last_event_ts"),
    )
)
write_table(daily_gold, "gold", "gold_saidi_saifi_daily")

circuit_summary_gold = (
    events_silver.withColumn("circuito", F.coalesce(F.col("circuito"), F.lit("Sin circuito")))
    .withColumn("municipio", F.coalesce(F.col("municipio"), F.lit("Sin municipio")))
    .withColumn("event_family", F.coalesce(F.col("event_family"), F.lit("Sin criterio")))
    .groupBy("circuito", "municipio", "event_family")
    .agg(
        F.sum(F.coalesce(F.col("severity_saidi"), F.lit(0.0))).alias("saidi_total"),
        F.sum(F.coalesce(F.col("severity_saifi"), F.lit(0.0))).alias("saifi_total"),
        F.count(F.lit(1)).alias("event_count"),
        F.avg(F.coalesce(F.col("duration_hours"), F.lit(0.0))).alias("duration_avg_h"),
        F.sum(F.coalesce(F.col("cnt_usus"), F.lit(0.0))).alias("users_affected_total"),
        F.min(F.col("inicio_ts")).alias("first_event_ts"),
        F.max(F.col("fin_ts")).alias("last_event_ts"),
    )
)
write_table(circuit_summary_gold, "gold", "gold_saidi_saifi_circuit_summary")

timeseries_event_details_gold = (
    events_silver.withColumn("fecha_dia", F.to_date(F.col("inicio_ts")))
    .withColumn(
        "event_id",
        F.concat(
            F.lit("timeseries-event-"),
            F.substring(
                F.sha2(
                    F.concat_ws(
                        "|",
                        F.coalesce(F.col("source_logical_name").cast("string"), F.lit("")),
                        F.coalesce(F.col("evento").cast("string"), F.lit("")),
                        F.coalesce(F.col("circuito").cast("string"), F.lit("")),
                        F.coalesce(F.col("equipo_ope").cast("string"), F.lit("")),
                        F.coalesce(F.col("inicio_ts").cast("string"), F.lit("")),
                        F.coalesce(F.col("severity_saidi").cast("string"), F.lit("")),
                        F.coalesce(F.col("severity_saifi").cast("string"), F.lit("")),
                    ),
                    256,
                ),
                1,
                16,
            ),
        ),
    )
    .select(
        "event_id",
        "fecha_dia",
        "evento",
        "inicio_ts",
        "fin_ts",
        "causa",
        "event_family",
        "circuito",
        "municipio",
        "equipo_ope",
        "tipo_equi_ope",
        "tipo_elemento",
        "duration_hours",
        "severity_saidi",
        "severity_saifi",
        "cnt_usus",
        "latitude",
        "longitude",
        "source_logical_name",
        "source_table",
        "display_label",
    )
)
write_table(timeseries_event_details_gold, "gold", "gold_timeseries_event_details")

timeseries_daily_attribution_gold = (
    timeseries_event_details_gold.withColumn("circuito", F.coalesce(F.col("circuito"), F.lit("Sin circuito")))
    .withColumn("municipio", F.coalesce(F.col("municipio"), F.lit("Sin municipio")))
    .withColumn("causa", F.coalesce(F.col("causa"), F.lit("Sin causa")))
    .withColumn("event_family", F.coalesce(F.col("event_family"), F.lit("Sin criterio")))
    .withColumn("equipo_ope", F.coalesce(F.col("equipo_ope"), F.lit("Sin equipo")))
    .withColumn("tipo_equi_ope", F.coalesce(F.col("tipo_equi_ope"), F.lit("Sin tipo equipo")))
    .groupBy("fecha_dia", "circuito", "municipio", "causa", "event_family", "equipo_ope", "tipo_equi_ope")
    .agg(
        F.count(F.lit(1)).alias("event_count"),
        F.sum(F.coalesce(F.col("severity_saidi"), F.lit(0.0))).alias("saidi_total"),
        F.sum(F.coalesce(F.col("severity_saifi"), F.lit(0.0))).alias("saifi_total"),
        F.sum(F.coalesce(F.col("duration_hours"), F.lit(0.0))).alias("duration_total_h"),
        F.sum(F.coalesce(F.col("cnt_usus"), F.lit(0.0))).alias("users_affected_total"),
        F.min(F.col("inicio_ts")).alias("first_event_ts"),
        F.max(F.col("fin_ts")).alias("last_event_ts"),
    )
)
write_table(timeseries_daily_attribution_gold, "gold", "gold_timeseries_daily_attribution")

timeseries_environment_daily_gold = (
    environment_silver.withColumn("municipio", F.coalesce(F.col("municipio"), F.lit("Sin municipio")))
    .withColumn("environment_family", F.coalesce(F.col("environment_family"), F.lit("Sin senal")))
    .groupBy("fecha_dia", "municipio", "environment_family")
    .agg(
        F.count(F.lit(1)).alias("environment_event_count"),
        F.min(F.col("fecha_evento_ts")).alias("first_environment_ts"),
        F.max(F.col("fecha_evento_ts")).alias("last_environment_ts"),
        F.count(F.when(F.col("latitude").isNotNull() & F.col("longitude").isNotNull(), F.lit(1))).alias("geocoded_event_count"),
    )
)
write_table(timeseries_environment_daily_gold, "gold", "gold_timeseries_environment_daily")

probability_inputs_gold = (
    events_silver.filter(F.col("event_family") != F.lit("SuperEventos"))
    .withColumn("criteria_group", F.col("event_family"))
    .withColumn("source_date", F.to_date(F.col("inicio_ts")))
    .withColumn("target_flag", F.col("impact_flag"))
    .withColumn("has_geo", F.when(F.col("latitude").isNotNull() & F.col("longitude").isNotNull(), F.lit(1)).otherwise(F.lit(0)))
)
write_table(probability_inputs_gold, "gold", "gold_probability_inputs")

map_points_gold = (
    assets_silver.withColumn("point_kind", F.lit("asset"))
    .withColumn("geometry_kind", F.coalesce(F.col("geometry_kind"), F.lit("point")))
    .withColumn("latitude_end", F.coalesce(F.col("latitude_end"), F.lit(None).cast("double")))
    .withColumn("longitude_end", F.coalesce(F.col("longitude_end"), F.lit(None).cast("double")))
    .unionByName(
        events_silver.withColumn("point_kind", F.lit("event"))
        .withColumn("geometry_kind", F.lit("point"))
        .withColumn("latitude_end", F.lit(None).cast("double"))
        .withColumn("longitude_end", F.lit(None).cast("double")),
        allowMissingColumns=True,
    )
    .withColumn("display_label", F.coalesce(F.col("display_label"), F.col("source_file_name")))
    .withColumn("popup_text", F.coalesce(F.col("popup_text"), F.col("display_label")))
    .withColumn(
        "map_date",
        F.coalesce(
            F.to_date(F.col("inicio_ts")),
            F.to_date(F.col("fecha_registro")),
        ),
    )
    .withColumn("map_period", F.date_format(F.col("map_date"), "yyyy-MM"))
    .withColumn("map_day", F.dayofmonth(F.col("map_date")))
    .filter(F.col("latitude").isNotNull() & F.col("longitude").isNotNull())
)
write_table(map_points_gold, "gold", "gold_map_points")

map_line_segments_gold = (
    assets_silver.filter(F.col("asset_family") == F.lit("LineSegments"))
    .withColumn("map_date", F.to_date(F.col("fecha_registro")))
    .withColumn("map_period", F.date_format(F.col("map_date"), "yyyy-MM"))
    .withColumn("map_day", F.dayofmonth(F.col("map_date")))
    .filter(
        F.col("latitude").isNotNull()
        & F.col("longitude").isNotNull()
        & F.col("latitude_end").isNotNull()
        & F.col("longitude_end").isNotNull()
    )
)
write_table(map_line_segments_gold, "gold", "gold_map_line_segments")

map_filter_index_gold = (
    map_points_gold.select(
        "map_period",
        F.coalesce(F.col("municipio"), F.lit("Sin municipio")).alias("municipio"),
        F.coalesce(F.col("circuito"), F.lit("Sin circuito")).alias("circuito"),
    )
    .unionByName(
        map_line_segments_gold.select(
            "map_period",
            F.coalesce(F.col("municipio"), F.lit("Sin municipio")).alias("municipio"),
            F.coalesce(F.col("circuito"), F.lit("Sin circuito")).alias("circuito"),
        ),
        allowMissingColumns=True,
    )
    .filter(F.col("map_period").isNotNull())
    .dropDuplicates(["map_period", "municipio", "circuito"])
)
write_table(map_filter_index_gold, "gold", "gold_map_filter_index")

map_event_days_gold = (
    events_silver.withColumn("map_date", F.to_date(F.col("inicio_ts")))
    .withColumn("map_period", F.date_format(F.col("map_date"), "yyyy-MM"))
    .withColumn("map_day", F.dayofmonth(F.col("map_date")))
    .withColumn("LATITUD", F.col("latitude"))
    .withColumn("LONGITUD", F.col("longitude"))
    .withColumn("MUN", F.col("municipio"))
    .withColumn("cto_equi_ope", F.col("circuito"))
    .withColumn("SAIDI", F.col("severity_saidi"))
    .withColumn("SAIFI", F.col("severity_saifi"))
    .withColumn("duracion_h", F.col("duration_hours"))
    .filter(F.col("LATITUD").isNotNull() & F.col("LONGITUD").isNotNull())
)
write_table(map_event_days_gold, "gold", "gold_map_event_days")

# COMMAND ----------
print("Built silver normalization tables and the Databricks gold presentation tables.")
