"""Upsert SemanticWorkflow and their WorkflowGuidance into Neo4j."""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.features.chatbot.core.agent.nodes.semantic_workflow_templates import (
    STANDARD_SEMANTIC_WORKFLOW_TEMPLATES,
)
from src.features.chatbot.services.semantic_workflow_knowledge_graph import (
    GUIDANCE_RELATIONSHIPS,
)


CLASSIFICATION_DESCRIPTIONS = {
    "FINANCIAL_STATEMENT_VALUE_QUERY": "查詢單一或明確的財報數值",
    "FINANCIAL_CONCEPT_EXPLANATION": "解釋財務名詞、指標或財務現象的意義",
    "FINANCIAL_TREND_CHANGE_ANALYSIS": "比較多期財務資料、趨勢、增減或變化",
    "PROFITABILITY_ANALYSIS": "分析毛利、營業利益、淨利、報酬率等獲利能力",
    "SOLVENCY_ANALYSIS": "分析短期或長期償債能力與流動性",
    "DEBT_CAPITAL_STRUCTURE_ANALYSIS": "分析負債組成、槓桿及資本結構",
    "CASH_FLOW_EARNINGS_QUALITY_ANALYSIS": "交叉分析現金流、淨利及盈餘品質",
    "OPERATING_EFFICIENCY_ANALYSIS": "分析應收帳款、存貨、週轉率及營運效率",
    "FINANCIAL_ANOMALY_CAUSE_ANALYSIS": "追查跨報表異常、矛盾現象或可能原因",
    "PEER_INDUSTRY_COMPARISON_ANALYSIS": "公司與同業、產業平均或其他公司的比較",
    "INDUSTRY_EXTERNAL_RISK_ANALYSIS": "分析景氣、政策、供應鏈等產業及外部風險",
    "COMPANY_EVENT_MAJOR_RISK_ANALYSIS": "分析訴訟、裁罰、違約、新聞等公司重大事件",
    "HISTORICAL_CREDIT_REVIEW_QUERY": "查詢過去徵審報告、額度調整或內部授信紀錄",
    "COMPREHENSIVE_CREDIT_RISK_DECISION": "要求綜合授信風險、准駁、額度或條件建議",
}


def sync() -> None:
    load_dotenv(PROJECT_ROOT / ".env.neo4j")
    password = os.getenv("NEO4J_PASSWORD", "")
    if not password:
        raise RuntimeError("NEO4J_PASSWORD must be set in .env.neo4j or the environment.")

    uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    database = os.getenv("NEO4J_DATABASE", "neo4j")

    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        driver.verify_connectivity()
        for name, label, property_name in (
            ("semantic_workflow_category", "SemanticWorkflow", "category"),
            ("workflow_guidance_id", "WorkflowGuidance", "id"),
        ):
            driver.execute_query(
                f"CREATE CONSTRAINT kg_{name} IF NOT EXISTS "
                f"FOR (node:{label}) REQUIRE node.{property_name} IS UNIQUE",
                database_=database,
            )

        for category, template in STANDARD_SEMANTIC_WORKFLOW_TEMPLATES.items():
            driver.execute_query(
                """
                MERGE (workflow:SemanticWorkflow {category: $category})
                SET workflow.label = $label,
                    workflow.classification_description = $classification_description
                """,
                category=category,
                label=template["label"],
                classification_description=CLASSIFICATION_DESCRIPTIONS[category],
                database_=database,
            )

            for kind, relationship_type in GUIDANCE_RELATIONSHIPS.items():
                for item_order, guidance_text in enumerate(template[kind], start=1):
                    driver.execute_query(
                        f"""
                        MATCH (workflow:SemanticWorkflow {{category: $category}})
                        MERGE (guidance:WorkflowGuidance {{id: $guidance_id}})
                        SET guidance.kind = $kind,
                            guidance.text = $guidance_text,
                            guidance.managed_by = 'sync_semantic_workflow_knowledge_graph'
                        MERGE (workflow)-[link:{relationship_type}]->(guidance)
                        SET link.order = $item_order
                        """,
                        category=category,
                        guidance_id=f"{category}:{kind}:{item_order}",
                        kind=kind,
                        guidance_text=guidance_text,
                        item_order=item_order,
                        database_=database,
                    )

    print(
        f"Semantic workflow knowledge graph synchronized: "
        f"{len(STANDARD_SEMANTIC_WORKFLOW_TEMPLATES)} workflows"
    )


if __name__ == "__main__":
    sync()
