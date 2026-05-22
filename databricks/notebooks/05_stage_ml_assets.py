# Databricks notebook source
from __future__ import annotations

from datetime import datetime
from pathlib import Path

# COMMAND ----------
# MAGIC %run ./_shared_phase1

# COMMAND ----------
define_standard_widgets()
context = build_context()
manifest = load_manifest(context.manifest_path)
artifact_volume_root = Path(context.artifact_volume_root)

artifact_rows: list[dict[str, object]] = []

# COMMAND ----------
for entry in manifest.get("ml_artifacts", []):
    relative_path = entry["relative_path"]
    staged_path = artifact_volume_root / relative_path
    if not staged_path.exists():
        raise FileNotFoundError(
            f"Required ML artifact {staged_path} was not found. Upload the phase 1 artifacts to the ML volume before running validation."
        )
    artifact_rows.append(
        {
            "logical_name": entry["logical_name"],
            "source_file_name": Path(relative_path).name,
            "relative_path": relative_path,
            "target_schema": entry.get("target_schema", "ml"),
            "target_volume": entry.get("target_volume", context.artifact_volume_name),
            "staged_path": str(staged_path),
            "bytes": int(staged_path.stat().st_size),
            "copy_status": "AVAILABLE_IN_VOLUME",
            "staged_at": datetime.utcnow(),
        }
    )

artifact_df = spark.createDataFrame(artifact_rows)
artifact_df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    table_name(context.catalog_name, "ml", "phase1_artifact_inventory")
)

secret_rows = []
for entry in manifest.get("sensitive_files", []):
    relative_path = entry["relative_path"]
    secret_rows.append(
        {
            "logical_name": Path(relative_path).stem,
            "source_file_name": Path(relative_path).name,
            "relative_path": relative_path,
            "disposition": entry.get("disposition", "review"),
            "reason": entry.get("reason", ""),
            "sync_status": "excluded_from_sync",
            "recommended_target": "databricks-secret-scope",
            "discovered_at": datetime.utcnow(),
        }
    )

spark.sql(
    f"""
    CREATE TABLE IF NOT EXISTS {table_name(context.catalog_name, 'raw', 'phase1_secret_guardrail')} (
      logical_name STRING,
      source_file_name STRING,
      relative_path STRING,
      disposition STRING,
      reason STRING,
      sync_status STRING,
      recommended_target STRING,
      discovered_at TIMESTAMP
    ) USING DELTA
    """
)
secret_df = spark.createDataFrame(secret_rows)
secret_df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    table_name(context.catalog_name, "raw", "phase1_secret_guardrail")
)

# COMMAND ----------
print(f"Registered {len(artifact_rows)} ML artifacts from {context.artifact_volume_root}.")
print(f"Recorded {len(secret_rows)} secret guardrail entries.")
