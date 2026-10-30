"""Mirror every table and column in the configured SQL schema into Neo4j.

This is a separate, lossless-as-practical SQL layer. It does not delete graph
data or modify the curated financial graph and its manually added relations.
"""

from __future__ import annotations

import base64
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from uuid import UUID

from neo4j import Driver
from sqlalchemy import inspect

from src.shared.database.connection import SQLAlchemyConnectionAdapter


@dataclass(frozen=True)
class ForeignKeySpec:
    name: str
    source_columns: tuple[str, ...]
    target_table: str
    target_columns: tuple[str, ...]


@dataclass(frozen=True)
class TableSpec:
    name: str
    columns: tuple[str, ...]
    primary_key: tuple[str, ...]
    foreign_keys: tuple[ForeignKeySpec, ...]


def inspect_source(connection: SQLAlchemyConnectionAdapter) -> tuple[TableSpec, ...]:
    """Read actual tables/columns/keys, rather than a migration's expected schema."""
    inspector = inspect(connection._connection)
    schema = connection.settings.schema if connection.dialect_name == "postgresql" else None
    names = sorted(inspector.get_table_names(schema=schema))
    primary_keys = {
        name: tuple(inspector.get_pk_constraint(name, schema=schema)["constrained_columns"] or ())
        for name in names
    }
    specs = []
    for name in names:
        columns = tuple(column["name"] for column in inspector.get_columns(name, schema=schema))
        primary_key = primary_keys[name]
        if not primary_key:
            raise ValueError(f"{name}: a primary key is required for stable, repeatable sync")
        if any(column.startswith("__kg_") for column in columns):
            raise ValueError(f"{name}: SQL columns beginning with __kg_ are reserved")
        foreign_keys = []
        for foreign_key in inspector.get_foreign_keys(name, schema=schema):
            target_table = foreign_key["referred_table"]
            target_schema = foreign_key.get("referred_schema") or schema
            if target_schema != schema or target_table not in primary_keys:
                raise ValueError(f"{name}: foreign key targets a table outside the selected schema")
            target_columns = tuple(foreign_key["referred_columns"])
            if target_columns != primary_keys[target_table]:
                raise ValueError(
                    f"{name}: foreign key to {target_table} does not target its primary key"
                )
            source_columns = tuple(foreign_key["constrained_columns"])
            foreign_keys.append(
                ForeignKeySpec(
                    name=foreign_key.get("name") or f"{name}_{'_'.join(source_columns)}_fk",
                    source_columns=source_columns,
                    target_table=target_table,
                    target_columns=target_columns,
                )
            )
        specs.append(TableSpec(name, columns, primary_key, tuple(foreign_keys)))
    return tuple(specs)


def _source_id(connection: SQLAlchemyConnectionAdapter) -> str:
    settings = connection.settings
    if settings.mode == "postgresql":
        return f"postgresql://{settings.host}:{settings.port}/{settings.database}/{settings.schema}"
    return f"sqlite://{settings.sqlite_path}"


def _identity(source_id: str, table: str, values: list[Any]) -> str:
    return json.dumps([source_id, table, values], ensure_ascii=False, separators=(",", ":"), default=str)


def _property_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, (date, datetime, time, UUID, Decimal)):
        return str(value) if isinstance(value, (UUID, Decimal)) else value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode("ascii")
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    return str(value)


def _quoted(connection: SQLAlchemyConnectionAdapter, identifier: str) -> str:
    return connection._connection.dialect.identifier_preparer.quote(identifier)


def _cypher_label(table: str) -> str:
    return "`SQL_" + table.replace("`", "``") + "`"


def _rows(connection: SQLAlchemyConnectionAdapter, columns: tuple[str, ...], table: str, batch_size: int):
    names = ", ".join(_quoted(connection, column) for column in columns)
    table_name = _quoted(connection, table)
    result = connection._connection.execution_options(stream_results=True).exec_driver_sql(
        f"SELECT {names} FROM {table_name}"
    )
    try:
        while batch := result.fetchmany(batch_size):
            yield [dict(row._mapping) for row in batch]
    finally:
        result.close()


def _node_payload(source_id: str, spec: TableSpec, row: dict[str, Any]) -> dict[str, Any]:
    key = _identity(source_id, spec.name, [row[column] for column in spec.primary_key])
    props = {column: _property_value(row[column]) for column in spec.columns}
    props.update(
        __kg_source_key=key,
        __kg_source_id=source_id,
        __kg_source_table=spec.name,
        __kg_primary_key_columns=list(spec.primary_key),
        __kg_null_columns=[column for column in spec.columns if row[column] is None],
        __kg_binary_columns=[
            column for column in spec.columns
            if isinstance(row[column], (bytes, bytearray, memoryview))
        ],
        __kg_json_columns=[
            column for column in spec.columns if isinstance(row[column], (dict, list, tuple))
        ],
    )
    return {"key": key, "props": props}


def _fk_payload(
    source_id: str, spec: TableSpec, foreign_key: ForeignKeySpec, row: dict[str, Any],
) -> dict[str, str] | None:
    target_values = dict(zip(foreign_key.target_columns, (row[c] for c in foreign_key.source_columns)))
    if any(value is None for value in target_values.values()):
        return None
    target_order = foreign_key.target_columns
    return {
        "from_key": _identity(source_id, spec.name, [row[c] for c in spec.primary_key]),
        "to_key": _identity(
            source_id, foreign_key.target_table, [target_values[c] for c in target_order]
        ),
    }


def sync_full_database(
    connection: SQLAlchemyConnectionAdapter,
    driver: Driver | None,
    database: str,
    batch_size: int,
    dry_run: bool,
) -> None:
    specs = inspect_source(connection)
    source_id = _source_id(connection)
    print(
        f"SQL source: {source_id}; tables: {len(specs)}; "
        f"columns: {sum(len(spec.columns) for spec in specs)}; "
        f"foreign keys: {sum(len(spec.foreign_keys) for spec in specs)}",
        flush=True,
    )
    if dry_run:
        for spec in specs:
            print(
                f"{spec.name}: {len(spec.columns)} columns, "
                f"PK ({', '.join(spec.primary_key)}), {len(spec.foreign_keys)} FKs"
            )
        return
    if driver is None:
        raise ValueError("Neo4j driver is required unless --dry-run is used")

    driver.execute_query(
        "CREATE CONSTRAINT kg_sql_source_key IF NOT EXISTS "
        "FOR (n:SqlRow) REQUIRE n.__kg_source_key IS UNIQUE",
        database_=database,
    )
    for spec in specs:
        count = 0
        query = (
            "UNWIND $rows AS row "
            "MERGE (n:SqlRow {__kg_source_key: row.key}) "
            "SET n += row.props "
            f"SET n:{_cypher_label(spec.name)}"
        )
        for rows in _rows(connection, spec.columns, spec.name, batch_size):
            driver.execute_query(
                query,
                rows=[_node_payload(source_id, spec, row) for row in rows],
                database_=database,
            )
            count += len(rows)
        print(f"{spec.name}: {count} rows synchronized", flush=True)

    # All nodes exist before any FK relationship is written, so table order
    # and circular references do not matter.
    for spec in specs:
        for foreign_key in spec.foreign_keys:
            columns = tuple(dict.fromkeys((*spec.primary_key, *foreign_key.source_columns)))
            count = 0
            pending: list[dict[str, str]] = []
            query = (
                "UNWIND $rows AS row "
                "MATCH (child:SqlRow {__kg_source_key: row.from_key}) "
                "MATCH (parent:SqlRow {__kg_source_key: row.to_key}) "
                "MERGE (child)-[r:SQL_FOREIGN_KEY {__kg_constraint: $constraint}]->(parent) "
                "SET r.__kg_source_columns = $source_columns, "
                "r.__kg_target_columns = $target_columns"
            )
            for rows in _rows(connection, columns, spec.name, batch_size):
                pending = [payload for row in rows if (payload := _fk_payload(source_id, spec, foreign_key, row))]
                if pending:
                    driver.execute_query(
                        query,
                        rows=pending,
                        constraint=foreign_key.name,
                        source_columns=list(foreign_key.source_columns),
                        target_columns=list(foreign_key.target_columns),
                        database_=database,
                    )
                    count += len(pending)
            print(f"{spec.name}.{foreign_key.name}: {count} FK rows processed", flush=True)
