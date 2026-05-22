# Databricks notebook source
from __future__ import annotations

from datetime import datetime
import gc

import pandas as pd
from pyspark.sql import functions as F

# COMMAND ----------
# MAGIC %run ./_shared_phase1

# COMMAND ----------
define_standard_widgets()
context = build_context()
manifest = load_manifest(context.manifest_path)
source_volume_root = Path(context.source_volume_root)

copy_log_rows: list[dict[str, object]] = []
ingest_log_rows: list[dict[str, object]] = []

# COMMAND ----------
for entry in manifest.get("raw_sources", []):
    relative_path = entry["relative_path"]
    staged_path = source_volume_root / relative_path
    if not staged_path.exists():
        raise FileNotFoundError(
            f"Required staged file {staged_path} was not found. Upload raw phase 1 assets to the source volume before running ingest."
        )

    copy_log_rows.append(
        {
            "logical_name": entry["logical_name"],
            "source_file_name": Path(relative_path).name,
            "relative_path": relative_path,
            "staged_path": str(staged_path),
            "bytes": int(staged_path.stat().st_size),
            "copy_status": "AVAILABLE_IN_VOLUME",
            "copied_at": datetime.utcnow(),
        }
    )

    if entry.get("load_mode") != "pickle" or not entry.get("bronze_table"):
        continue

    source_frame = load_source_frame(staged_path, "pickle")
    normalized_frame = normalize_pandas_frame(source_frame, entry.get("date_columns", []))
    normalized_frame["source_logical_name"] = entry["logical_name"]
    normalized_frame["source_relative_path"] = relative_path
    normalized_frame["source_file_name"] = Path(relative_path).name
    normalized_frame["ingested_at"] = pd.Timestamp.utcnow()

    bronze_table_name = table_name(context.catalog_name, "bronze", entry["bronze_table"])
    write_pandas_frame_to_delta(spark, normalized_frame, bronze_table_name)

    bounds = source_date_bounds(source_frame, entry.get("date_columns", []))
    ingest_log_rows.append(
        {
            "logical_name": entry["logical_name"],
            "bronze_table": entry["bronze_table"],
            "source_file_name": Path(relative_path).name,
            "relative_path": relative_path,
            "row_count": safe_count(source_frame),
            "column_count": len(source_frame.columns),
            "min_date": bounds["min_date"],
            "max_date": bounds["max_date"],
            "load_status": "STAGED",
            "ingested_at": datetime.utcnow(),
        }
    )

    del source_frame
    del normalized_frame
    gc.collect()

# COMMAND ----------
copy_log_df = spark.createDataFrame(copy_log_rows)
copy_log_df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    table_name(context.catalog_name, "raw", "phase1_copy_log")
)

if ingest_log_rows:
    ingest_log_df = spark.createDataFrame(ingest_log_rows)
    ingest_log_df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(
        table_name(context.catalog_name, "bronze", "phase1_ingest_log")
    )

# COMMAND ----------
print(f"Validated availability for {len(copy_log_rows)} raw files in Unity Catalog volumes.")
print(f"Staged {len(ingest_log_rows)} bronze Delta tables.")
