# Databricks notebook source
from __future__ import annotations

from datetime import datetime

import pandas as pd
from pyspark.sql import functions as F

# COMMAND ----------
# MAGIC %run ./_shared_phase1

# COMMAND ----------
define_standard_widgets()
context = build_context()
manifest = load_manifest(context.manifest_path)

validation_rows: list[dict[str, object]] = []

# COMMAND ----------
for entry in manifest.get("raw_sources", []):
    if entry.get("load_mode") != "pickle" or not entry.get("bronze_table"):
        continue

    logical_name = entry["logical_name"]
    bronze_table_name = table_name(context.catalog_name, "bronze", entry["bronze_table"])
    source_path = source_file_path(context, entry["relative_path"])
    source_frame = load_source_frame(source_path, "pickle")
    expected_row_count = safe_count(source_frame)
    expected_columns = [str(column).strip() for column in source_frame.columns]
    required_columns = [str(column).strip() for column in entry.get("required_columns", [])]
    date_columns = [str(column).strip() for column in entry.get("date_columns", [])]

    try:
        bronze_frame = spark.table(bronze_table_name)
        observed_row_count = bronze_frame.count()
        observed_columns = bronze_frame.columns
        row_count_status = "PASS" if observed_row_count == expected_row_count else "FAIL"
        column_status = "PASS" if set(required_columns).issubset(set(observed_columns)) else "FAIL"

        validation_rows.append(
            {
                "logical_name": logical_name,
                "bronze_table": entry["bronze_table"],
                "check_name": "row_count",
                "check_status": row_count_status,
                "expected_value": str(expected_row_count),
                "observed_value": str(observed_row_count),
                "details": "Bronze row count matches the staged source file.",
                "validated_at": datetime.utcnow(),
            }
        )
        validation_rows.append(
            {
                "logical_name": logical_name,
                "bronze_table": entry["bronze_table"],
                "check_name": "required_columns",
                "check_status": column_status,
                "expected_value": ", ".join(required_columns) if required_columns else "",
                "observed_value": ", ".join(observed_columns),
                "details": "Required source columns are present in bronze.",
                "validated_at": datetime.utcnow(),
            }
        )

        source_bounds = source_date_bounds(source_frame, date_columns)
        observed_date_columns = [column for column in date_columns if column in observed_columns]
        if observed_date_columns:
            min_expressions = [F.min(F.col(column)).alias(f"{column}_min") for column in observed_date_columns]
            max_expressions = [F.max(F.col(column)).alias(f"{column}_max") for column in observed_date_columns]
            observed_bounds_row = bronze_frame.select(*min_expressions, *max_expressions).collect()[0]
            observed_mins = [
                observed_bounds_row[f"{column}_min"]
                for column in observed_date_columns
                if observed_bounds_row[f"{column}_min"] is not None
            ]
            observed_maxes = [
                observed_bounds_row[f"{column}_max"]
                for column in observed_date_columns
                if observed_bounds_row[f"{column}_max"] is not None
            ]
            expected_min = (
                pd.Timestamp(source_bounds["min_date"]).isoformat()
                if source_bounds["min_date"] is not None
                else ""
            )
            expected_max = (
                pd.Timestamp(source_bounds["max_date"]).isoformat()
                if source_bounds["max_date"] is not None
                else ""
            )
            observed_min = pd.Timestamp(min(observed_mins)).isoformat() if observed_mins else ""
            observed_max = pd.Timestamp(max(observed_maxes)).isoformat() if observed_maxes else ""
            validation_rows.append(
                {
                    "logical_name": logical_name,
                    "bronze_table": entry["bronze_table"],
                    "check_name": "date_bounds",
                    "check_status": "PASS"
                    if expected_min == observed_min and expected_max == observed_max
                    else "FAIL",
                    "expected_value": f"{expected_min} -> {expected_max}",
                    "observed_value": f"{observed_min} -> {observed_max}",
                    "details": (
                        "Combined date bounds across "
                        + ", ".join(observed_date_columns)
                        + " match the staged source bounds."
                    ),
                    "validated_at": datetime.utcnow(),
                }
            )
    except Exception as exc:
        validation_rows.append(
            {
                "logical_name": logical_name,
                "bronze_table": entry["bronze_table"],
                "check_name": "table_read",
                "check_status": "FAIL",
                "expected_value": "bronze table available",
                "observed_value": "",
                "details": str(exc),
                "validated_at": datetime.utcnow(),
            }
        )

# COMMAND ----------
validation_df = spark.createDataFrame(validation_rows)
validation_df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    table_name(context.catalog_name, "silver", "phase1_validation_results")
)

failed_checks = [row for row in validation_rows if row["check_status"] != "PASS"]
if failed_checks:
    raise AssertionError(f"Phase 1 validation found {len(failed_checks)} failing checks.")

print(f"Validated {len(validation_rows)} checks across bronze tables.")
