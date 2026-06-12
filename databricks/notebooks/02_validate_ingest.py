# Databricks notebook source
from __future__ import annotations

from datetime import datetime
from functools import reduce

from pyspark.sql import functions as F

# COMMAND ----------
# MAGIC %run ./_shared_phase1

# COMMAND ----------
define_standard_widgets()
context = build_context()
manifest = load_manifest(context.manifest_path)

validation_rows: list[dict[str, object]] = []
entries_by_name = {
    entry["logical_name"]: entry
    for entry in manifest.get("raw_sources", [])
    if entry.get("load_mode") in {"pickle", "parquet"} and entry.get("bronze_table")
}


def _record(
    *,
    logical_name: str,
    bronze_table: str | None,
    check_name: str,
    passed: bool,
    expected_value: object,
    observed_value: object,
    details: str,
) -> None:
    validation_rows.append(
        {
            "logical_name": logical_name,
            "bronze_table": bronze_table,
            "check_name": check_name,
            "check_status": "PASS" if passed else "FAIL",
            "expected_value": "" if expected_value is None else str(expected_value),
            "observed_value": "" if observed_value is None else str(observed_value),
            "details": details,
            "validated_at": datetime.utcnow(),
        }
    )


def _fq_table(entry: dict[str, object]) -> str:
    return table_name(context.catalog_name, "bronze", str(entry["bronze_table"]))


def _null_safe_key_condition(left_alias: str, right_alias: str, columns: list[str], reference_columns: list[str]) -> object:
    condition = None
    for column, reference_column in zip(columns, reference_columns):
        expr = F.col(f"{left_alias}.{column}").eqNullSafe(F.col(f"{right_alias}.{reference_column}"))
        condition = expr if condition is None else condition & expr
    return condition


# COMMAND ----------
for entry in entries_by_name.values():
    logical_name = entry["logical_name"]
    bronze_table = entry["bronze_table"]
    bronze_table_name = _fq_table(entry)
    required_columns = [str(column).strip() for column in entry.get("required_columns", [])]
    expected_rows = entry.get("expected_rows")
    primary_key = [str(column).strip() for column in entry.get("primary_key", [])]
    natural_key = [str(column).strip() for column in entry.get("natural_key", [])]

    try:
        frame = spark.table(bronze_table_name)
        observed_columns = frame.columns
        observed_row_count = frame.count()
        _record(
            logical_name=logical_name,
            bronze_table=bronze_table,
            check_name="row_count",
            passed=expected_rows is None or observed_row_count == int(expected_rows),
            expected_value=expected_rows,
            observed_value=observed_row_count,
            details="Bronze row count matches the normalized manifest.",
        )
        _record(
            logical_name=logical_name,
            bronze_table=bronze_table,
            check_name="required_columns",
            passed=set(required_columns).issubset(set(observed_columns)),
            expected_value=", ".join(required_columns),
            observed_value=", ".join(observed_columns),
            details="Required normalized columns are present in bronze.",
        )

        for key_name, key_columns in (("primary_key", primary_key), ("natural_key", natural_key)):
            if not key_columns:
                continue
            duplicate_count = (
                frame.groupBy(*[F.col(column) for column in key_columns])
                .count()
                .filter(F.col("count") > 1)
                .count()
            )
            null_condition = reduce(lambda left, right: left | right, [F.col(column).isNull() for column in key_columns])
            null_key_count = frame.filter(null_condition).count()
            _record(
                logical_name=logical_name,
                bronze_table=bronze_table,
                check_name=f"{key_name}_unique",
                passed=duplicate_count == 0,
                expected_value=0,
                observed_value=duplicate_count,
                details=f"{key_name} columns {', '.join(key_columns)} are unique.",
            )
            _record(
                logical_name=logical_name,
                bronze_table=bronze_table,
                check_name=f"{key_name}_not_null",
                passed=null_key_count == 0,
                expected_value=0,
                observed_value=null_key_count,
                details=f"{key_name} columns {', '.join(key_columns)} do not contain Spark nulls.",
            )

        weather_variables = entry.get("weather_variables", [])
        weather_offsets = entry.get("weather_offsets", [])
        if weather_variables and weather_offsets:
            offset_start = int(weather_offsets[0])
            offset_end = int(weather_offsets[1])
            expected_weather_columns = [
                f"{variable}_{offset}"
                for variable in weather_variables
                for offset in range(offset_start, offset_end + 1)
            ]
            missing_weather = sorted(set(expected_weather_columns).difference(observed_columns))
            _record(
                logical_name=logical_name,
                bronze_table=bronze_table,
                check_name="weather_feature_columns",
                passed=not missing_weather,
                expected_value=len(expected_weather_columns),
                observed_value=len(expected_weather_columns) - len(missing_weather),
                details="All wide weather feature columns are present."
                if not missing_weather
                else "Missing weather columns: " + ", ".join(missing_weather[:20]),
            )
    except Exception as exc:
        _record(
            logical_name=logical_name,
            bronze_table=bronze_table,
            check_name="table_read",
            passed=False,
            expected_value="bronze table available",
            observed_value="",
            details=str(exc),
        )

# COMMAND ----------
for entry in entries_by_name.values():
    logical_name = entry["logical_name"]
    bronze_table = entry["bronze_table"]
    source_frame = spark.table(_fq_table(entry)).alias("source")
    for foreign_key in entry.get("foreign_keys", []):
        reference_name = foreign_key["references"]
        reference_entry = entries_by_name[reference_name]
        reference_frame = spark.table(_fq_table(reference_entry)).alias("reference")
        key_columns = [str(column) for column in foreign_key["columns"]]
        reference_columns = [str(column) for column in foreign_key["reference_columns"]]
        condition = _null_safe_key_condition("source", "reference", key_columns, reference_columns)
        missing_count = (
            source_frame.join(reference_frame, condition, "left_anti")
            .select(*[F.col(f"source.{column}") for column in key_columns])
            .dropDuplicates()
            .count()
        )
        _record(
            logical_name=logical_name,
            bronze_table=bronze_table,
            check_name=f"foreign_key_{reference_name}",
            passed=missing_count == 0,
            expected_value=0,
            observed_value=missing_count,
            details=(
                f"{logical_name}.{', '.join(key_columns)} joins to "
                f"{reference_name}.{', '.join(reference_columns)} without missing matches."
            ),
        )

# COMMAND ----------
fact_entry = entries_by_name.get("evento_vano_trafo")
if fact_entry:
    fact_count = spark.table(_fq_table(fact_entry)).count()
    _record(
        logical_name="evento_vano_trafo",
        bronze_table=fact_entry["bronze_table"],
        check_name="central_fact_row_count",
        passed=fact_count == int(manifest.get("source_rows", 0)),
        expected_value=manifest.get("source_rows"),
        observed_value=fact_count,
        details="Central fact table preserves the original source row count.",
    )

_record(
    logical_name="manifest",
    bronze_table=None,
    check_name="source_hash",
    passed=manifest.get("source_sha256") == "7d4efade8c78a6d364ed68e0228439693a533626bde8a247c5e6e0b4ab89d354",
    expected_value="7d4efade8c78a6d364ed68e0228439693a533626bde8a247c5e6e0b4ab89d354",
    observed_value=manifest.get("source_sha256"),
    details="Manifest source hash matches the canonical normalized dataset.",
)
_record(
    logical_name="manifest",
    bronze_table=None,
    check_name="full_reconstruction",
    passed="full_reconstruction ok" in str(manifest.get("reconstruction_guarantee", "")),
    expected_value="full_reconstruction ok",
    observed_value=manifest.get("reconstruction_guarantee"),
    details="Normalizer reconstruction guarantee is recorded in the manifest.",
)

# COMMAND ----------
validation_df = spark.createDataFrame(validation_rows)
validation_df.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable(
    table_name(context.catalog_name, "silver", "phase1_validation_results")
)

failed_checks = [row for row in validation_rows if row["check_status"] != "PASS"]
if failed_checks:
    raise AssertionError(f"Phase 1 validation found {len(failed_checks)} failing checks.")

print(f"Validated {len(validation_rows)} normalized dataset checks across bronze tables.")
