from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

import pandas as pd

from chec_dashboard.core.config import Settings


INTEGER_TYPES = {"tinyint", "smallint", "int", "integer", "bigint", "long"}
NUMERIC_TYPES = INTEGER_TYPES | {"float", "double", "real", "decimal"}
TEMPORAL_TYPES = {"date", "timestamp", "datetime"}


def sql_identifier(name: str) -> str:
    return f"`{name.replace('`', '``')}`"


def sql_table_name(*parts: str) -> str:
    return ".".join(sql_identifier(part) for part in parts)


def sql_literal(value: Any) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError("NaN and infinity are not valid SQL literals.")
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


@dataclass(frozen=True)
class TableSchema:
    columns: list[str]
    types: dict[str, str]


class DatabricksSQLWarehouseClient:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._http_path = settings.databricks_sql_http_path or self._default_http_path()

    def _default_http_path(self) -> str:
        warehouse_id = self._settings.databricks_sql_warehouse_id
        if not warehouse_id:
            raise ValueError(
                "DATABRICKS_SQL_WAREHOUSE_ID is required when DATA_BACKEND=databricks_sql."
            )
        return f"/sql/1.0/warehouses/{warehouse_id}"

    def _connect(self):
        try:
            from databricks import sql
            from databricks.sdk.core import Config
        except ImportError as exc:  # pragma: no cover - exercised in runtime environments
            raise RuntimeError(
                "Databricks SQL dependencies are missing. Install "
                "'databricks-sdk' and 'databricks-sql-connector'."
            ) from exc

        cfg = Config()
        return sql.connect(
            server_hostname=cfg.host,
            http_path=self._http_path,
            credentials_provider=lambda: cfg.authenticate,
        )

    def fetch_dataframe(self, statement: str) -> pd.DataFrame:
        with self._connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(statement)
                description = cursor.description or []
                if not description:
                    return pd.DataFrame()
                rows = cursor.fetchall()

        columns = [column[0] for column in description]
        normalized_rows: list[list[Any]] = []
        for row in rows:
            if isinstance(row, (list, tuple)):
                normalized_rows.append(list(row))
            else:
                normalized_rows.append([getattr(row, column) for column in columns])
        return pd.DataFrame(normalized_rows, columns=columns)

    def fetch_scalar(self, statement: str, default: Any = None) -> Any:
        frame = self.fetch_dataframe(statement)
        if frame.empty:
            return default
        return frame.iloc[0, 0]

    def describe_table(self, table_name: str) -> TableSchema:
        frame = self.fetch_dataframe(f"DESCRIBE TABLE {table_name}")
        columns: list[str] = []
        types: dict[str, str] = {}
        if frame.empty:
            return TableSchema(columns=columns, types=types)

        for _, row in frame.iterrows():
            column_name = str(row.get("col_name") or "").strip()
            data_type = str(row.get("data_type") or "").strip().lower()
            if not column_name or column_name.startswith("#"):
                continue
            columns.append(column_name)
            types[column_name] = data_type
        return TableSchema(columns=columns, types=types)

    def ping(self) -> None:
        result = self.fetch_scalar("SELECT 1 AS ok", default=None)
        if result != 1:
            raise RuntimeError("Databricks SQL warehouse ping returned an unexpected result.")
