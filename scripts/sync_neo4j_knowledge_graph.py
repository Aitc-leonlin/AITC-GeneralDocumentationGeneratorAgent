"""Copy curated financial knowledge or the full SQL schema into Neo4j.

The SQL database remains the source of truth. This importer reads it in bounded
batches and upserts graph nodes and relationships using stable source keys.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
from neo4j import GraphDatabase

from src.shared.database.config import get_database_settings
from src.shared.database.connection import get_table_names, open_database_connection


@dataclass(frozen=True)
class GraphStage:
    table: str
    columns: tuple[str, ...]
    key_column: str
    cypher: str
    active_only: bool = False


STAGES = (
    GraphStage(
        "company_profile",
        ("company_code", "company_name", "company_short_name", "industry_code",
         "tax_id", "publication_date", "incorporation_date", "listing_date",
         "paid_in_capital", "financial_statement_type", "created_at", "updated_at"),
        "company_code",
        "UNWIND $rows AS row MERGE (n:Company {code: row.key}) SET n += row.props",
    ),
    GraphStage(
        "taxonomy_entry_point",
        ("taxonomy_id", "taxonomy_version", "module", "entry_point"),
        "taxonomy_id",
        "UNWIND $rows AS row MERGE (n:Taxonomy {id: row.key}) SET n += row.props",
    ),
    GraphStage(
        "taxonomy_concept",
        ("concept_id", "taxonomy_id", "namespace", "local_name", "zh_label",
         "en_label", "terse_code", "period_type", "balance_type", "data_type",
         "is_abstract"),
        "concept_id",
        """UNWIND $rows AS row
           MERGE (n:Concept {id: row.key}) SET n += row.props
           WITH n, row MATCH (t:Taxonomy {id: row.taxonomy_id})
           MERGE (t)-[:HAS_CONCEPT]->(n)""",
    ),
    GraphStage(
        "field_dictionary",
        ("field_id", "canonical_name", "zh_name", "en_name", "module",
         "statement_type", "value_type", "description"),
        "field_id",
        "UNWIND $rows AS row MERGE (n:FinancialField {id: row.key}) SET n += row.props",
    ),
    GraphStage(
        "report_instance",
        ("report_id", "company_code", "year", "quarter", "industry_type",
         "report_scope", "taxonomy_version", "module", "file_name",
         "source_type", "period_start", "period_end"),
        "report_id",
        """UNWIND $rows AS row
           MERGE (n:Report {id: row.key}) SET n += row.props
           WITH n, row MERGE (c:Company {code: row.company_code})
           MERGE (c)-[:FILED]->(n)""",
    ),
    GraphStage(
        "taxonomy_presentation",
        ("id", "taxonomy_id", "role_uri", "parent_concept_id",
         "child_concept_id", "order_no", "preferred_label", "depth"),
        "id",
        """UNWIND $rows AS row
           MATCH (parent:Concept {id: row.parent_concept_id})
           MATCH (child:Concept {id: row.child_concept_id})
           MERGE (parent)-[r:PRESENTS {source_id: row.key}]->(child)
           SET r += row.props""",
    ),
    GraphStage(
        "taxonomy_calculation",
        ("id", "taxonomy_id", "role_uri", "parent_concept_id",
         "child_concept_id", "weight", "order_no"),
        "id",
        """UNWIND $rows AS row
           MATCH (parent:Concept {id: row.parent_concept_id})
           MATCH (child:Concept {id: row.child_concept_id})
           MERGE (parent)-[r:CALCULATES {source_id: row.key}]->(child)
           SET r += row.props""",
    ),
    GraphStage(
        "field_concept_mapping",
        ("id", "field_id", "concept_id", "taxonomy_id", "industry_type",
         "priority", "effective_from", "effective_to"),
        "id",
        """UNWIND $rows AS row
           MATCH (field:FinancialField {id: row.field_id})
           MATCH (concept:Concept {id: row.concept_id})
           MERGE (field)-[r:MAPS_TO {source_id: row.key}]->(concept)
           SET r += row.props""",
    ),
    GraphStage(
        "xbrl_fact",
        ("fact_id", "report_id", "concept_id", "context_id", "unit_id",
         "value_numeric", "value_text", "decimals", "scale", "instant_date",
         "period_start", "period_end", "segment_json"),
        "fact_id",
        """UNWIND $rows AS row
           MATCH (report:Report {id: row.report_id})
           MATCH (concept:Concept {id: row.concept_id})
           MERGE (fact:Fact {id: row.key}) SET fact += row.props
           MERGE (report)-[:HAS_FACT]->(fact)
           MERGE (fact)-[:INSTANCE_OF]->(concept)""",
    ),
    GraphStage(
        "financial_metric_value",
        ("company_code", "year", "quarter", "report_scope", "industry_type",
         "field_id", "concept_id", "value", "report_id", "fact_id",
         "period_start", "period_end"),
        "field_id,fact_id",
        """UNWIND $rows AS row
           MATCH (fact:Fact {id: row.fact_id})
           MATCH (field:FinancialField {id: row.field_id})
           MERGE (metric:MetricValue {key: row.key}) SET metric += row.props
           MERGE (fact)-[:HAS_METRIC]->(metric)
           MERGE (metric)-[:MEASURES_FIELD]->(field)""",
    ),
    GraphStage(
        "expert_knowledge_entry",
        ("id", "title", "data_source", "industry", "company_label",
         "company_prompt_value", "source_schema_key", "anchor_description",
         "system_prompt", "created_at", "updated_at"),
        "id",
        """UNWIND $rows AS row
           MERGE (n:ExpertKnowledge {id: row.key}) SET n += row.props
           WITH n, row MERGE (topic:IndustryTopic {name: row.industry_topic})
           MERGE (n)-[:ABOUT_INDUSTRY]->(topic)
           WITH n, row OPTIONAL MATCH (c:Company {code: row.company_code})
           FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END |
             MERGE (c)-[:HAS_EXPERT_KNOWLEDGE]->(n))""",
        active_only=True,
    ),
    GraphStage(
        "warehouse_data_entry",
        ("id", "category", "title", "industry", "company_label",
         "company_prompt_value", "summary", "source", "url",
         "record_updated_at", "created_at", "updated_at"),
        "id",
        """UNWIND $rows AS row
           MERGE (n:WarehouseKnowledge {id: row.key}) SET n += row.props
           WITH n, row MERGE (topic:IndustryTopic {name: row.industry_topic})
           MERGE (n)-[:ABOUT_INDUSTRY]->(topic)
           WITH n, row MERGE (category:KnowledgeCategory {name: row.category_topic})
           MERGE (n)-[:IN_CATEGORY]->(category)
           WITH n, row OPTIONAL MATCH (c:Company {code: row.company_code})
           FOREACH (_ IN CASE WHEN c IS NULL THEN [] ELSE [1] END |
             MERGE (c)-[:HAS_WAREHOUSE_KNOWLEDGE]->(n))""",
        active_only=True,
    ),
)

CONSTRAINTS = (
    ("company_code", "Company", "code"),
    ("taxonomy_id", "Taxonomy", "id"),
    ("concept_id", "Concept", "id"),
    ("financial_field_id", "FinancialField", "id"),
    ("report_id", "Report", "id"),
    ("fact_id", "Fact", "id"),
    ("metric_key", "MetricValue", "key"),
    ("expert_knowledge_id", "ExpertKnowledge", "id"),
    ("warehouse_knowledge_id", "WarehouseKnowledge", "id"),
    ("industry_topic_name", "IndustryTopic", "name"),
    ("knowledge_category_name", "KnowledgeCategory", "name"),
)


def _neo4j_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _company_code(value: Any) -> str:
    label = str(value or "").strip()
    if label.isdigit():
        return label
    match = re.search(r"\(([0-9]{4,6})(?:\.[A-Za-z]+)?\)$", label)
    return match.group(1) if match else ""


def _payload(stage: GraphStage, row: dict[str, Any]) -> dict[str, Any]:
    if stage.table == "financial_metric_value":
        key = json.dumps([row["field_id"], row["fact_id"]], separators=(",", ":"))
    else:
        key = row[stage.key_column]
    properties = {name: _neo4j_value(value) for name, value in row.items()}
    payload = {"key": key, "props": properties}
    payload.update(properties)
    if stage.table in {"expert_knowledge_entry", "warehouse_data_entry"}:
        payload["company_code"] = _company_code(row.get("company_prompt_value"))
        payload["industry_topic"] = row.get("industry") or "未分類"
    if stage.table == "warehouse_data_entry":
        payload["category_topic"] = row.get("category") or "未分類"
    return payload


def _source_rows(connection: Any, stage: GraphStage, batch_size: int):
    columns = ", ".join(stage.columns)
    where = " WHERE deleted_at IS NULL" if stage.active_only else ""
    # Stage definitions are constants, not user-supplied SQL identifiers.
    result = connection._connection.execution_options(stream_results=True).exec_driver_sql(
        f"SELECT {columns} FROM {stage.table}{where}"
    )
    try:
        while batch := result.fetchmany(batch_size):
            yield [_payload(stage, dict(row._mapping)) for row in batch]
    finally:
        result.close()


def sync(batch_size: int, dry_run: bool, full_database: bool = False) -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(PROJECT_ROOT / ".env.neo4j")
    settings = get_database_settings()
    print(f"SQL source: {settings.mode}", flush=True)

    source = open_database_connection()
    try:
        if full_database:
            from scripts.sync_neo4j_full_database import sync_full_database

            if dry_run:
                sync_full_database(source, None, "neo4j", batch_size, True)
                return
            password = os.getenv("NEO4J_PASSWORD", "")
            if not password:
                raise RuntimeError("NEO4J_PASSWORD must be set in .env.neo4j or the environment.")
            uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
            user = os.getenv("NEO4J_USER", "neo4j")
            database = os.getenv("NEO4J_DATABASE", "neo4j")
            with GraphDatabase.driver(uri, auth=(user, password)) as driver:
                driver.verify_connectivity()
                sync_full_database(source, driver, database, batch_size, False)
            return

        available = set(get_table_names(source))
        missing = [stage.table for stage in STAGES if stage.table not in available]
        if missing:
            raise RuntimeError("Missing source tables: " + ", ".join(missing))

        if dry_run:
            for stage in STAGES:
                where = " WHERE deleted_at IS NULL" if stage.active_only else ""
                count = source.execute(
                    f"SELECT COUNT(*) FROM {stage.table}{where}"
                ).fetchone()[0]
                print(f"{stage.table}: {count}")
            return

        password = os.getenv("NEO4J_PASSWORD", "")
        if not password:
            raise RuntimeError("NEO4J_PASSWORD must be set in .env.neo4j or the environment.")
        uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        database = os.getenv("NEO4J_DATABASE", "neo4j")
        with GraphDatabase.driver(uri, auth=(user, password)) as driver:
            driver.verify_connectivity()
            for name, label, property_name in CONSTRAINTS:
                driver.execute_query(
                    f"CREATE CONSTRAINT kg_{name} IF NOT EXISTS "
                    f"FOR (n:{label}) REQUIRE n.{property_name} IS UNIQUE",
                    database_=database,
                )
            for stage in STAGES:
                imported = 0
                for rows in _source_rows(source, stage, batch_size):
                    driver.execute_query(stage.cypher, rows=rows, database_=database)
                    imported += len(rows)
                print(f"{stage.table}: {imported} rows synchronized", flush=True)
    finally:
        source.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=1000)
    parser.add_argument("--dry-run", action="store_true", help="Inspect the SQL source without writing Neo4j")
    parser.add_argument(
        "--full-database", action="store_true",
        help="Mirror every table and column into a separate SQL graph layer",
    )
    parser.add_argument(
        "--acknowledge-sensitive-data", action="store_true",
        help="Required for --full-database writes: includes credentials, tokens and chat data",
    )
    args = parser.parse_args()
    if args.batch_size < 1:
        parser.error("--batch-size must be greater than zero")
    if args.full_database and not args.dry_run and not args.acknowledge_sensitive_data:
        parser.error("--full-database imports credentials, tokens and private chat data; "
                     "add --acknowledge-sensitive-data to proceed")
    if args.acknowledge_sensitive_data and not args.full_database:
        parser.error("--acknowledge-sensitive-data is only valid with --full-database")
    sync(args.batch_size, args.dry_run, args.full_database)


if __name__ == "__main__":
    main()
