# Databricks notebook source
from __future__ import annotations

import pandas as pd
from pyspark.sql import functions as F

# COMMAND ----------
# MAGIC %run ./_shared_phase1

# COMMAND ----------
define_map_widgets()
context = build_context()

point_kind_value = widget_value("point_kind", "Todos")
geometry_kind_value = widget_value("geometry_kind", "Todos")
start_date_value = widget_value("start_date", "")
end_date_value = widget_value("end_date", "")
selected_circuit_value = widget_value("selected_circuit", "Todos")
selected_municipio_value = widget_value("selected_municipio", "Todos")
selected_family_value = widget_value("selected_family", "Todos")

frame = spark.table(table_name(context.catalog_name, "gold", "gold_map_points"))
frame = (
    frame.withColumn(
        "family_group",
        F.coalesce(
            F.col("event_family").cast("string"),
            F.col("asset_family").cast("string"),
            F.col("source_logical_name").cast("string"),
        ),
    )
    .withColumn(
        "map_date",
        F.coalesce(
            F.to_date(F.col("map_date")),
            F.to_date(F.col("inicio_ts")),
            F.to_date(F.col("fecha_registro")),
            F.to_date(F.col("fecha_evento_ts")),
        ),
    )
)

if point_kind_value != "Todos" and "point_kind" in frame.columns:
    frame = frame.filter(F.trim(F.col("point_kind")) == F.lit(point_kind_value))
if geometry_kind_value != "Todos" and "geometry_kind" in frame.columns:
    frame = frame.filter(F.trim(F.col("geometry_kind")) == F.lit(geometry_kind_value))
if start_date_value:
    frame = frame.filter(F.col("map_date") >= F.to_date(F.lit(start_date_value)))
if end_date_value:
    frame = frame.filter(F.col("map_date") <= F.to_date(F.lit(end_date_value)))
if selected_circuit_value and selected_circuit_value != "Todos" and "circuito" in frame.columns:
    frame = frame.filter(F.trim(F.col("circuito")) == F.lit(selected_circuit_value))
if selected_municipio_value and selected_municipio_value != "Todos" and "municipio" in frame.columns:
    frame = frame.filter(F.trim(F.col("municipio")) == F.lit(selected_municipio_value))
if selected_family_value and selected_family_value != "Todos" and "family_group" in frame.columns:
    frame = frame.filter(F.trim(F.col("family_group")) == F.lit(selected_family_value))

bounds = frame.select(
    F.min(F.col("map_date")).alias("min_date"),
    F.max(F.col("map_date")).alias("max_date"),
).collect()[0]
filtered_count = frame.count()

print(
    "Filters:",
    {
        "point_kind": point_kind_value,
        "geometry_kind": geometry_kind_value,
        "start_date": start_date_value or (str(bounds["min_date"]) if bounds["min_date"] else ""),
        "end_date": end_date_value or (str(bounds["max_date"]) if bounds["max_date"] else ""),
        "circuito": selected_circuit_value,
        "municipio": selected_municipio_value,
        "family_group": selected_family_value,
        "rows": filtered_count,
    },
)

if filtered_count == 0:
    print("No rows matched the selected filters.")
else:
    summary = frame.groupBy("point_kind", "geometry_kind", "family_group").count().orderBy(F.col("count").desc())
    display(summary)

    preview_pdf = (
        frame.select(
            "point_kind",
            "geometry_kind",
            "family_group",
            "display_label",
            "circuito",
            "municipio",
            "map_date",
            "latitude",
            "longitude",
            "popup_text",
        )
        .limit(5000)
        .toPandas()
    )

    display(preview_pdf.head(100))

    try:
        import plotly.express as px

        plot_pdf = preview_pdf.dropna(subset=["latitude", "longitude"]).copy()
        if not plot_pdf.empty:
            fig = px.scatter_geo(
                plot_pdf,
                lat="latitude",
                lon="longitude",
                color="point_kind",
                hover_name="display_label",
                hover_data={
                    "family_group": True,
                    "circuito": True,
                    "municipio": True,
                    "map_date": True,
                    "latitude": False,
                    "longitude": False,
                },
                title="CHEC Map Pilot",
                height=650,
            )
            fig.update_geos(
                showcountries=False,
                showsubunits=False,
                fitbounds="locations",
                visible=False,
            )
            fig.show()
        else:
            print("Filtered rows did not include usable latitude/longitude values.")
    except Exception as exc:
        print(f"Plot rendering fallback: {exc}")
