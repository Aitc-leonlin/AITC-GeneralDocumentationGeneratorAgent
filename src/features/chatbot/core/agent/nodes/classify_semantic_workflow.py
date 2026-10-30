from time import perf_counter
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.features.chatbot.core.providers.chat_openAI_provider import chat_model
from src.features.chatbot.core.structured_output import invoke_pydantic_structured
from src.features.chatbot.models.langgraph_state_types import OverallState


SemanticWorkflowCategory = Literal[
    "FINANCIAL_STATEMENT_VALUE_QUERY",
    "FINANCIAL_CONCEPT_EXPLANATION",
    "FINANCIAL_TREND_CHANGE_ANALYSIS",
    "PROFITABILITY_ANALYSIS",
    "SOLVENCY_ANALYSIS",
    "DEBT_CAPITAL_STRUCTURE_ANALYSIS",
    "CASH_FLOW_EARNINGS_QUALITY_ANALYSIS",
    "OPERATING_EFFICIENCY_ANALYSIS",
    "FINANCIAL_ANOMALY_CAUSE_ANALYSIS",
    "PEER_INDUSTRY_COMPARISON_ANALYSIS",
    "INDUSTRY_EXTERNAL_RISK_ANALYSIS",
    "COMPANY_EVENT_MAJOR_RISK_ANALYSIS",
    "HISTORICAL_CREDIT_REVIEW_QUERY",
    "COMPREHENSIVE_CREDIT_RISK_DECISION",
    "OTHER",
]


class SemanticWorkflowClassification(BaseModel):
    category: SemanticWorkflowCategory = Field(description="最適合的徵審問題分類")
    confidence: float = Field(ge=0.0, le=1.0, description="分類信心分數")
    reason: str = Field(description="簡短說明分類理由")


def _classify_from_static_categories(question: str) -> dict[str, Any]:
    """Use the existing 14-category LLM classifier for routing."""

    prompt = f"""
你是企業徵審報告系統的語意問題分類器。

請將問題分類成下列其中一個 category：
1. FINANCIAL_STATEMENT_VALUE_QUERY：查詢單一或明確的財報數值。
2. FINANCIAL_CONCEPT_EXPLANATION：解釋財務名詞、指標或財務現象的意義。
3. FINANCIAL_TREND_CHANGE_ANALYSIS：比較多期財務資料、趨勢、增減或變化。
4. PROFITABILITY_ANALYSIS：分析毛利、營業利益、淨利、報酬率等獲利能力。
5. SOLVENCY_ANALYSIS：分析短期或長期償債能力與流動性。
6. DEBT_CAPITAL_STRUCTURE_ANALYSIS：分析負債組成、槓桿及資本結構。
7. CASH_FLOW_EARNINGS_QUALITY_ANALYSIS：交叉分析現金流、淨利及盈餘品質。
8. OPERATING_EFFICIENCY_ANALYSIS：分析應收帳款、存貨、週轉率及營運效率。
9. FINANCIAL_ANOMALY_CAUSE_ANALYSIS：追查跨報表異常、矛盾現象或可能原因。
10. PEER_INDUSTRY_COMPARISON_ANALYSIS：公司與同業、產業平均或其他公司的比較。
11. INDUSTRY_EXTERNAL_RISK_ANALYSIS：分析景氣、政策、供應鏈等產業及外部風險。
12. COMPANY_EVENT_MAJOR_RISK_ANALYSIS：分析訴訟、裁罰、違約、新聞等公司重大事件。
13. HISTORICAL_CREDIT_REVIEW_QUERY：查詢過去徵審報告、額度調整或內部授信紀錄。
14. COMPREHENSIVE_CREDIT_RISK_DECISION：要求綜合授信風險、准駁、額度或條件建議。
15. OTHER：仍屬徵審相關，但無法合理歸入以上任何一類。

規則：
- 只選一個最主要分類。
- 問題同時包含多個分析面向，但最終要求授信判斷時，選 COMPREHENSIVE_CREDIT_RISK_DECISION。
- 問題要求追查特定訴訟、裁罰或負面新聞時，選 COMPANY_EVENT_MAJOR_RISK_ANALYSIS。
- 問題要求一般產業環境影響時，選 INDUSTRY_EXTERNAL_RISK_ANALYSIS。
- 只有真的無法歸類時才選 OTHER，不要因資料可能不足就選 OTHER。

使用者問題：
{question}
"""

    classification = invoke_pydantic_structured(
        model=chat_model,
        schema=SemanticWorkflowClassification,
        prompt=prompt,
        operation="classify_semantic_workflow",
        fallback_factory=lambda: SemanticWorkflowClassification(
            category="OTHER",
            confidence=0.0,
            reason="結構化分類失敗，交由 Deep Agent fallback。",
        ),
    ).model_dump()
    return classification


def classify_semantic_workflow(state: OverallState) -> OverallState:
    """Route with the built-in category classifier and Python workflow templates."""
    started_at = perf_counter()
    question = str(state.get("rephrased_question") or state.get("user_input") or "").strip()
    classification = _classify_from_static_categories(question)
    classification["routing_source"] = "static"

    print("[classify_semantic_workflow] result:", classification)
    print(f"[timing] classify_semantic_workflow took {perf_counter() - started_at:.3f}s")
    return {
        **state,
        "semantic_workflow_category": classification["category"],
        "semantic_workflow_category_confidence": classification["confidence"],
        "semantic_workflow_category_reason": classification["reason"],
        "semantic_workflow_category_result": classification,
        # Python 模板會提供各分類的分析與輸出指引，無須外部圖資料庫。
        "semantic_workflow_guidance": {},
    }
