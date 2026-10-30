"""Read WorkflowGuidance routing candidates and their linked SemanticWorkflows."""

from __future__ import annotations

import os
import json
from typing import Any

from dotenv import load_dotenv
from neo4j import GraphDatabase, RoutingControl

from src.shared.database.config import PROJECT_ROOT


GUIDANCE_RELATIONSHIPS = {
    "analysis_purposes": "HAS_PURPOSE",
    "financial_data_requirements": "REQUIRES_FINANCIAL_DATA",
    "rag_focus": "USES_RAG_FOCUS",
    "analysis_steps": "HAS_ANALYSIS_STEP",
    "output_requirements": "HAS_OUTPUT_REQUIREMENT",
}


def _execute_logged_read(
    cypher: str,
    parameters: dict[str, Any],
    *,
    request_label: str,
    response_label: str,
) -> list[dict[str, Any]]:
    load_dotenv(PROJECT_ROOT / ".env.neo4j")
    password = os.getenv("NEO4J_PASSWORD", "")
    if not password:
        raise RuntimeError("NEO4J_PASSWORD is not configured")

    uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    database = os.getenv("NEO4J_DATABASE", "neo4j")
    print(
        f"[{request_label}] "
        + json.dumps(
            {
                "uri": uri,
                "database": database,
                "cypher": cypher.strip(),
                "parameters": parameters,
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    try:
        with GraphDatabase.driver(
            uri,
            auth=(user, password),
            connection_timeout=3.0,
            max_transaction_retry_time=2.0,
        ) as driver:
            records, _, _ = driver.execute_query(
                cypher,
                **parameters,
                database_=database,
                routing_=RoutingControl.READ,
            )
    except Exception as exc:
        print(
            f"[{response_label}] "
            + json.dumps({"error": str(exc)}, ensure_ascii=False),
            flush=True,
        )
        raise
    rows = [dict(record) for record in records]
    print(
        f"[{response_label}] "
        + json.dumps(rows, ensure_ascii=False, indent=2, default=str),
        flush=True,
    )
    return rows


def fetch_workflow_guidance_catalog(kind: str) -> list[dict[str, Any]]:
    """List guidance linked through the relationship for the selected kind."""
    relationship_type = GUIDANCE_RELATIONSHIPS.get(kind)
    if relationship_type is None:
        return []
    cypher = """
        MATCH (workflow:SemanticWorkflow)-[link]->(guidance:WorkflowGuidance {kind: $kind})
        WHERE type(link) = $relationship_type
        RETURN coalesce(toString(guidance.id), elementId(guidance)) AS id,
               guidance.kind AS kind,
               guidance.text AS text,
               workflow.category AS category,
               workflow.label AS label,
               workflow.classification_description AS classification_description
        ORDER BY category, link.order, id
    """
    return _execute_logged_read(
        cypher,
        {"kind": kind, "relationship_type": relationship_type},
        request_label="NEO4J GUIDANCE CATALOG REQUEST",
        response_label="NEO4J GUIDANCE CATALOG RESPONSE",
    )


def fetch_workflow_guidance_for_category(category: str) -> list[dict[str, Any]]:
    """Read every guidance item linked to a selected workflow."""
    cypher = """
        MATCH (workflow:SemanticWorkflow {category: $category})-[link]->(guidance:WorkflowGuidance)
        RETURN coalesce(toString(guidance.id), elementId(guidance)) AS id,
               guidance.kind AS kind,
               guidance.text AS text,
               type(link) AS relationship_type,
               link.order AS position
        ORDER BY kind, position, id
    """
    rows = _execute_logged_read(
        cypher,
        {"category": category},
        request_label="NEO4J SELECTED WORKFLOW GUIDANCE REQUEST",
        response_label="NEO4J SELECTED WORKFLOW GUIDANCE RESPONSE",
    )
    return [
        row for row in rows
        if GUIDANCE_RELATIONSHIPS.get(str(row.get("kind") or ""))
        == row.get("relationship_type")
        and row.get("text")
    ]
