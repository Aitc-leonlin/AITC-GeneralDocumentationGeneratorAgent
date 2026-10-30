"""Regenerate output/table_relationships.mmd from the configured live SQL schema."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
from sqlalchemy import inspect

from src.shared.database.config import get_database_settings
from src.shared.database.connection import open_database_connection


# Application-level joins that are intentionally not declared as SQL FKs.
# Each entry is (parent table, parent column, child table, child column).
LOGICAL_RELATIONSHIPS = (
    ("company_profile", "company_code", "report_instance", "company_code"),
    ("company_profile", "company_code", "financial_metric_value", "company_code"),
    ("company_profile", "company_code", "report_generator_history", "company_code"),
    ("taxonomy_entry_point", "taxonomy_id", "taxonomy_concept", "taxonomy_id"),
    ("taxonomy_entry_point", "taxonomy_id", "taxonomy_presentation", "taxonomy_id"),
    ("taxonomy_entry_point", "taxonomy_id", "taxonomy_calculation", "taxonomy_id"),
    ("taxonomy_entry_point", "taxonomy_id", "field_concept_mapping", "taxonomy_id"),
    ("taxonomy_concept", "concept_id", "taxonomy_presentation", "parent_concept_id"),
    ("taxonomy_concept", "concept_id", "taxonomy_presentation", "child_concept_id"),
    ("taxonomy_concept", "concept_id", "taxonomy_calculation", "parent_concept_id"),
    ("taxonomy_concept", "concept_id", "taxonomy_calculation", "child_concept_id"),
    ("taxonomy_concept", "concept_id", "xbrl_fact", "concept_id"),
    ("taxonomy_concept", "concept_id", "financial_metric_value", "concept_id"),
    ("taxonomy_concept", "concept_id", "field_concept_mapping", "concept_id"),
    ("report_instance", "report_id", "xbrl_fact", "report_id"),
    ("report_instance", "report_id", "financial_metric_value", "report_id"),
    ("field_dictionary", "field_id", "field_concept_mapping", "field_id"),
    ("field_dictionary", "field_id", "financial_metric_value", "field_id"),
    ("xbrl_fact", "fact_id", "financial_metric_value", "fact_id"),
    ("membership_notification_template", "code", "membership_notification_outbox", "template_code"),
)


def _mermaid_type(sql_type: object) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", str(sql_type)).strip("_") or "UNKNOWN"


def _unique_sets(inspector: object, table: str, schema: str | None) -> set[frozenset[str]]:
    unique = {
        frozenset(item["column_names"])
        for item in inspector.get_unique_constraints(table, schema=schema)
        if item.get("column_names")
    }
    unique.update(
        frozenset(item["column_names"])
        for item in inspector.get_indexes(table, schema=schema)
        if item.get("unique") and item.get("column_names")
    )
    return unique


def generate() -> tuple[Path, int, int, int, int]:
    load_dotenv(PROJECT_ROOT / ".env")
    settings = get_database_settings()
    connection = open_database_connection()
    try:
        inspector = inspect(connection._connection)
        schema = settings.schema if settings.mode == "postgresql" else None
        tables = sorted(inspector.get_table_names(schema=schema))
        columns = {
            table: inspector.get_columns(table, schema=schema) for table in tables
        }
        names = {
            table: {column["name"] for column in columns[table]} for table in tables
        }
        primary_keys = {
            table: set(inspector.get_pk_constraint(table, schema=schema)["constrained_columns"] or ())
            for table in tables
        }
        foreign_keys = {
            table: sorted(
                inspector.get_foreign_keys(table, schema=schema),
                key=lambda item: item.get("name") or "",
            )
            for table in tables
        }
        unique_sets = {
            table: _unique_sets(inspector, table, schema) for table in tables
        }

        for parent, parent_column, child, child_column in LOGICAL_RELATIONSHIPS:
            if parent not in names or child not in names:
                raise ValueError(f"Logical relationship references a missing table: {parent}, {child}")
            if parent_column not in names[parent] or child_column not in names[child]:
                raise ValueError(
                    f"Logical relationship references a missing column: "
                    f"{parent}.{parent_column}, {child}.{child_column}"
                )

        database = settings.database if settings.mode == "postgresql" else str(settings.sqlite_path)
        lines = [
            "erDiagram",
            f"    %% Generated from live {settings.mode} database {database}, schema {schema or 'main'}.",
            f"    %% {len(tables)} tables; {sum(map(len, columns.values()))} columns; "
            f"{sum(map(len, foreign_keys.values()))} declared FKs.",
            "    %% Solid edges are declared SQL foreign keys. Dashed edges are selected",
            "    %% application-level joins, not enforced by the database.",
            "    %% NULLability and composite UNIQUE constraints are not shown as field badges.",
            "",
        ]
        for table in tables:
            fk_columns = {
                column for fk in foreign_keys[table] for column in fk["constrained_columns"]
            }
            single_unique = {
                next(iter(group)) for group in unique_sets[table] if len(group) == 1
            }
            for group in sorted(unique_sets[table], key=lambda value: tuple(sorted(value))):
                if len(group) > 1:
                    lines.append(f"    %% UNIQUE {table} ({', '.join(sorted(group))})")
            lines.append(f"    {table} {{")
            for column in columns[table]:
                name = column["name"]
                keys = []
                if name in primary_keys[table]:
                    keys.append("PK")
                if name in fk_columns:
                    keys.append("FK")
                if name in single_unique and name not in primary_keys[table]:
                    keys.append("UK")
                suffix = " " + ",".join(keys) if keys else ""
                lines.append(f"        {_mermaid_type(column['type'])} {name}{suffix}")
            lines.extend(("    }", ""))

        lines.extend(("    %% Declared SQL foreign keys", ""))
        for child in tables:
            nullable = {column["name"]: column["nullable"] for column in columns[child]}
            for foreign_key in foreign_keys[child]:
                parent = foreign_key["referred_table"]
                source_columns = foreign_key["constrained_columns"]
                target_columns = foreign_key["referred_columns"]
                if parent not in names:
                    raise ValueError(f"FK from {child} targets table outside selected schema: {parent}")
                parent_cardinality = "o|" if any(nullable[name] for name in source_columns) else "||"
                child_cardinality = (
                    "o|" if frozenset(source_columns) in unique_sets[child] else "o{"
                )
                label = f"{','.join(source_columns)} to {','.join(target_columns)}"
                lines.append(
                    f'    {parent} {parent_cardinality}--{child_cardinality} {child} : "{label}"'
                )

        lines.extend(("", "    %% Application-level joins (not declared SQL foreign keys)", ""))
        for parent, parent_column, child, child_column in LOGICAL_RELATIONSHIPS:
            lines.append(
                f'    {parent} o|..o{{ {child} : "{child_column} to {parent_column} logical"'
            )
        output = PROJECT_ROOT / "output" / "table_relationships.mmd"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return (
            output,
            len(tables),
            sum(map(len, columns.values())),
            sum(map(len, foreign_keys.values())),
            len(LOGICAL_RELATIONSHIPS),
        )
    finally:
        connection.close()


if __name__ == "__main__":
    path, tables, columns, foreign_keys, logical = generate()
    print(
        f"Updated {path}: {tables} tables, {columns} columns, "
        f"{foreign_keys} declared FKs, {logical} logical joins"
    )
