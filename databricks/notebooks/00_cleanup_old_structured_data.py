# Databricks notebook source
from __future__ import annotations

from datetime import datetime

from pyspark.sql import functions as F

# COMMAND ----------
# MAGIC %run ./_shared_phase1

# COMMAND ----------
define_standard_widgets()
dbutils.widgets.dropdown("dry_run", "true", ["true", "false"])
context = build_context()
dry_run = widget_value("dry_run", "true").strip().lower() != "false"

OLD_STRUCTURED_RELATIVE_PATHS = [
    "TRAFOS.pkl",
    "APOYOS.pkl",
    "SWITCHES.pkl",
    "REDMT.pkl",
    "SuperEventos_Criticidad_AguasAbajo_CODEs.pkl",
    "Eventos_interruptor.pkl",
    "Eventos_tramo_linea.pkl",
    "Eventos_transformador.pkl",
    "Vegetacion.pkl",
    "Rayos.pkl",
    "arbol_decision_recomendaciones/variables_apoyo.xlsx",
    "arbol_decision_recomendaciones/variables_interruptor.xlsx",
    "arbol_decision_recomendaciones/variables_transformador.xlsx",
    "arbol_decision_recomendaciones/variables_tramo de linea.xlsx",
    "arbol_decision_recomendaciones/Temporal/variables_apoyos.xlsx",
    "arbol_decision_recomendaciones/Temporal/variables_interruptores.xlsx",
    "arbol_decision_recomendaciones/Temporal/variables_transformadores.xlsx",
]

OLD_STRUCTURED_TABLES = [
    ("bronze", "bronze_trafos"),
    ("bronze", "bronze_apoyos"),
    ("bronze", "bronze_switches"),
    ("bronze", "bronze_redmt"),
    ("bronze", "bronze_super_eventos"),
    ("bronze", "bronze_eventos_interruptor"),
    ("bronze", "bronze_eventos_tramo_linea"),
    ("bronze", "bronze_eventos_transformador"),
    ("bronze", "bronze_vegetacion"),
    ("bronze", "bronze_rayos"),
    ("gold", "gold_saidi_saifi_daily"),
    ("gold", "gold_saidi_saifi_circuit_summary"),
]

PRESERVED_PATH_TOKENS = ("pdf", "chatbot", "technical_doc", "corpus", "skills")


def _dbutils_obj():
    obj = globals().get("dbutils")
    if obj is None:
        raise RuntimeError("dbutils is required for cleanup.")
    return obj


def _path_exists(path: str) -> bool:
    try:
        _dbutils_obj().fs.ls(path)
        return True
    except Exception:
        return False


def _is_preserved_path(path: str) -> bool:
    lowered = path.lower()
    return any(token in lowered for token in PRESERVED_PATH_TOKENS)


cleanup_rows: list[dict[str, object]] = []

# COMMAND ----------
for relative_path in OLD_STRUCTURED_RELATIVE_PATHS:
    target = f"dbfs:{context.source_volume_root.rstrip('/')}/{relative_path}"
    preserved = _is_preserved_path(relative_path)
    exists = _path_exists(target)
    status = "PRESERVED_BLOCKED" if preserved else "MISSING" if not exists else "DRY_RUN"
    if exists and not dry_run and not preserved:
        _dbutils_obj().fs.rm(target, recurse=False)
        status = "DELETED"
    cleanup_rows.append(
        {
            "object_kind": "volume_file",
            "object_name": relative_path,
            "target": target,
            "exists_before": exists,
            "dry_run": dry_run,
            "status": status,
            "cleaned_at": datetime.utcnow(),
        }
    )

for schema_name, object_name in OLD_STRUCTURED_TABLES:
    fq_name = table_name(context.catalog_name, schema_name, object_name)
    exists = False
    try:
        exists = spark.catalog.tableExists(fq_name)
    except Exception:
        exists = False
    status = "MISSING" if not exists else "DRY_RUN"
    if exists and not dry_run:
        spark.sql(f"DROP TABLE IF EXISTS {fq_name}")
        status = "DROPPED"
    cleanup_rows.append(
        {
            "object_kind": "delta_table",
            "object_name": object_name,
            "target": fq_name,
            "exists_before": exists,
            "dry_run": dry_run,
            "status": status,
            "cleaned_at": datetime.utcnow(),
        }
    )

# COMMAND ----------
cleanup_df = spark.createDataFrame(cleanup_rows)
cleanup_df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    table_name(context.catalog_name, "silver", "old_structured_cleanup_log")
)

blocked = [row for row in cleanup_rows if row["status"] == "PRESERVED_BLOCKED"]
if blocked:
    raise AssertionError(f"Cleanup allowlist attempted to touch preserved paths: {blocked}")

print(f"Cleanup {'dry run' if dry_run else 'apply'} complete for {len(cleanup_rows)} old structured objects.")
