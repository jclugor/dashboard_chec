# Databricks notebook source
from __future__ import annotations

import json
from datetime import datetime

# COMMAND ----------
# MAGIC %run ./_shared_phase1

# COMMAND ----------
define_standard_widgets()
context = build_context()
manifest = load_manifest(context.manifest_path)

# COMMAND ----------
catalog_exists = (
    spark.sql(f"SHOW CATALOGS LIKE '{context.catalog_name}'").limit(1).count() > 0
)

if not catalog_exists:
    spark.sql(f"CREATE CATALOG {context.catalog_name}")

for schema_name in DEFAULT_SCHEMA_NAMES:
    spark.sql(f"CREATE SCHEMA IF NOT EXISTS {context.catalog_name}.{schema_name}")

spark.sql(
    f"CREATE VOLUME IF NOT EXISTS {table_name(context.catalog_name, 'raw', context.source_volume_name)}"
)
spark.sql(
    f"CREATE VOLUME IF NOT EXISTS {table_name(context.catalog_name, 'ml', context.artifact_volume_name)}"
)

# COMMAND ----------
manifest_json = json.dumps(manifest, indent=2, ensure_ascii=False)

spark.sql(
    f"""
    CREATE TABLE IF NOT EXISTS {table_name(context.catalog_name, 'raw', 'phase1_manifest_json')} (
      manifest_name STRING,
      manifest_json STRING,
      loaded_at TIMESTAMP
    ) USING DELTA
    """
)
spark.sql(
    f"""
    CREATE TABLE IF NOT EXISTS {table_name(context.catalog_name, 'raw', 'phase1_source_inventory')} (
      logical_name STRING,
      source_file_name STRING,
      relative_path STRING,
      load_mode STRING,
      bronze_table STRING,
      required_columns ARRAY<STRING>,
      date_columns ARRAY<STRING>
    ) USING DELTA
    """
)
spark.sql(
    f"""
    CREATE TABLE IF NOT EXISTS {table_name(context.catalog_name, 'raw', 'phase1_secret_inventory')} (
      logical_name STRING,
      source_file_name STRING,
      relative_path STRING,
      disposition STRING,
      reason STRING
    ) USING DELTA
    """
)
spark.sql(
    f"""
    CREATE TABLE IF NOT EXISTS {table_name(context.catalog_name, 'raw', 'phase1_copy_log')} (
      logical_name STRING,
      source_file_name STRING,
      relative_path STRING,
      staged_path STRING,
      bytes BIGINT,
      copy_status STRING,
      copied_at TIMESTAMP
    ) USING DELTA
    """
)
spark.sql(
    f"""
    CREATE TABLE IF NOT EXISTS {table_name(context.catalog_name, 'bronze', 'phase1_ingest_log')} (
      logical_name STRING,
      bronze_table STRING,
      source_file_name STRING,
      relative_path STRING,
      row_count BIGINT,
      column_count INT,
      min_date TIMESTAMP,
      max_date TIMESTAMP,
      load_status STRING,
      ingested_at TIMESTAMP
    ) USING DELTA
    """
)
spark.sql(
    f"""
    CREATE TABLE IF NOT EXISTS {table_name(context.catalog_name, 'silver', 'phase1_validation_results')} (
      logical_name STRING,
      bronze_table STRING,
      check_name STRING,
      check_status STRING,
      expected_value STRING,
      observed_value STRING,
      details STRING,
      validated_at TIMESTAMP
    ) USING DELTA
    """
)
spark.sql(
    f"""
    CREATE TABLE IF NOT EXISTS {table_name(context.catalog_name, 'gold', 'phase1_table_registry')} (
      table_name STRING,
      description STRING,
      registered_at TIMESTAMP
    ) USING DELTA
    """
)
spark.sql(
    f"""
    CREATE TABLE IF NOT EXISTS {table_name(context.catalog_name, 'ml', 'phase1_artifact_inventory')} (
      logical_name STRING,
      source_file_name STRING,
      relative_path STRING,
      target_schema STRING,
      target_volume STRING,
      staged_path STRING,
      bytes BIGINT,
      copy_status STRING,
      staged_at TIMESTAMP
    ) USING DELTA
    """
)

# COMMAND ----------
manifest_row = spark.createDataFrame(
    [
        {
            "manifest_name": manifest.get("bundle_name", "chec_phase1"),
            "manifest_json": manifest_json,
            "loaded_at": datetime.utcnow(),
        }
    ]
)
manifest_row.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    table_name(context.catalog_name, "raw", "phase1_manifest_json")
)

source_inventory_df = spark.createDataFrame(manifest_source_rows(manifest))
source_inventory_df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    table_name(context.catalog_name, "raw", "phase1_source_inventory")
)

secret_inventory_df = spark.createDataFrame(manifest_secret_rows(manifest))
secret_inventory_df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    table_name(context.catalog_name, "raw", "phase1_secret_inventory")
)

table_registry_df = spark.createDataFrame(
    [
        {**row, "registered_at": datetime.utcnow()}
        for row in manifest_gold_rows(manifest)
    ]
)
table_registry_df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    table_name(context.catalog_name, "gold", "phase1_table_registry")
)

artifact_inventory_df = spark.createDataFrame(
    [
        {
            "logical_name": row["logical_name"],
            "source_file_name": row["source_file_name"],
            "relative_path": row["relative_path"],
            "target_schema": row["target_schema"],
            "target_volume": row["target_volume"],
            "staged_path": "",
            "bytes": 0,
            "copy_status": "PENDING",
            "staged_at": datetime.utcnow(),
        }
        for row in manifest_artifact_rows(manifest)
    ]
)
artifact_inventory_df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    table_name(context.catalog_name, "ml", "phase1_artifact_inventory")
)

# COMMAND ----------
print(f"Bootstrapped catalog {context.catalog_name} and phase 1 registry tables.")
