# Databricks notebook source
from __future__ import annotations

import os

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
from pyspark.sql import functions as F

# COMMAND ----------
# MAGIC %run ./_shared_phase1

# COMMAND ----------
define_probability_widgets()
context = build_context()
manifest = load_manifest(context.manifest_path)

criteria_value = widget_value("criteria", "Todos")
start_date_value = widget_value("start_date", "")
end_date_value = widget_value("end_date", "")
selected_circuit_value = widget_value("selected_circuit", "Todos")
selected_municipio_value = widget_value("selected_municipio", "Todos")
target_column_value = widget_value("target_column", "SAIDI")

frame = spark.table(table_name(context.catalog_name, "gold", "gold_probability_inputs"))

if criteria_value != "Todos" and "criteria_group" in frame.columns:
    frame = frame.filter(F.trim(F.col("criteria_group")) == F.lit(criteria_value))

if start_date_value:
    frame = frame.filter(F.to_date(F.col("inicio_ts")) >= F.to_date(F.lit(start_date_value)))
if end_date_value:
    frame = frame.filter(F.to_date(F.col("inicio_ts")) <= F.to_date(F.lit(end_date_value)))
if selected_circuit_value and selected_circuit_value != "Todos" and "circuito" in frame.columns:
    frame = frame.filter(F.trim(F.col("circuito")) == F.lit(selected_circuit_value))
if selected_municipio_value and selected_municipio_value != "Todos" and "municipio" in frame.columns:
    frame = frame.filter(F.trim(F.col("municipio")) == F.lit(selected_municipio_value))

resolved_target = resolve_column_name(frame.columns, target_column_value)
if resolved_target is None:
    resolved_target = resolve_column_name(frame.columns, "SAIDI") or frame.columns[0]

target_field = next((field for field in frame.schema.fields if field.name == resolved_target), None)
target_type = target_field.dataType.simpleString() if target_field is not None else "string"

if not start_date_value or not end_date_value:
    bounds = frame.select(
        F.min(F.to_date(F.col("inicio_ts"))).alias("min_date"),
        F.max(F.to_date(F.col("inicio_ts"))).alias("max_date"),
    ).collect()[0]
    start_date_value = start_date_value or (str(bounds["min_date"]) if bounds["min_date"] else "")
    end_date_value = end_date_value or (str(bounds["max_date"]) if bounds["max_date"] else "")

filtered_count = frame.count()

# COMMAND ----------
print(
    "Filters:",
    {
        "criteria": criteria_value,
        "start_date": start_date_value,
        "end_date": end_date_value,
        "circuito": selected_circuit_value,
        "municipio": selected_municipio_value,
        "target_column": resolved_target,
        "target_type": target_type,
        "rows": filtered_count,
    },
)

if filtered_count == 0:
    print("No rows matched the selected filters.")
else:
    sample_pdf = frame.select(resolved_target).dropna().limit(50000).toPandas()
    if sample_pdf.empty:
        print(f"No values available in target column {resolved_target}.")
    else:
        series = sample_pdf[resolved_target]
        plt.figure(figsize=(11, 6))
        if target_type in {"double", "float", "int", "bigint", "long"} or target_type.startswith("decimal"):
            sns.histplot(series, kde=True, bins=30, stat="probability", color="#0b5d25")
            plt.ylabel("Probability")
            plt.xlabel(resolved_target)
            plt.title(f"Probability view for {resolved_target}")
        else:
            counts = series.astype(str).value_counts().head(30)
            sns.barplot(x=counts.values, y=counts.index, color="#0b5d25")
            plt.xlabel("Count")
            plt.ylabel(resolved_target)
            plt.title(f"Top values for {resolved_target}")
        plt.tight_layout()
        plt.show()

        summary_pdf = series.describe(include="all").to_frame(name="value")
        print(summary_pdf.to_string())
