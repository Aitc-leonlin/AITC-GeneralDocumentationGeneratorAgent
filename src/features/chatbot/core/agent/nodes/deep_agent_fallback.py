import json
from collections.abc import Callable
from typing import Any

from langchain_core.tools import tool

from src.features.chatbot.core.agent.nodes.semantic_retrieval import (
    build_final_answer_evidence,
    extract_semantic_plan,
    list_company_reports,
    resolve_company,
    retrieve_requirement_data,
)
from src.features.chatbot.core.providers.chat_openAI_provider import chat_model, get_message_text
from src.features.chatbot.models.langgraph_state_types import OverallState


DEEP_AGENT_SYSTEM_PROMPT = """
你是企業徵審報告團隊的補充研究 Agent，只處理無法歸入既有標準 Workflow 的徵審問題。

規則：
1. 財務數字只能引用 retrieve_financial_statement_evidence 工具回傳的 facts 與 computed_metrics。
2. read_approved_reference_context 的資料只能作為背景與判讀輔助，不得冒充財務報表數字。
3. 不得自行捏造公司、期間、財務數字、內部徵審紀錄或外部事件。
4. 資料不足時，明確列出缺少的資料與無法完成的判斷。
5. 問題若不屬於財報、企業徵審、信用風險或授信報告範圍，應說明無法處理。
6. 回答使用繁體中文，並區分「財務報表證據」「核准參考資料」「分析結論」「資料限制」。
""".strip()


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _build_controlled_tools(state: OverallState) -> list[Any]:
    @tool
    def retrieve_financial_statement_evidence(question: str) -> str:
        """依問題規劃並查詢本系統財報 DB，回傳可引用的標準化財務證據。"""
        try:
            plan = extract_semantic_plan(question)
            company = resolve_company(
                plan.get("company_identifiers") or plan.get("company_identifier", "")
            )
            if not company:
                return _json_text(
                    {
                        "error": "無法匹配公司",
                        "required_action": "請提供公司代碼或完整公司名稱",
                        "plan": plan,
                    }
                )

            retrieval_results = [
                retrieve_requirement_data(question, company, requirement)
                for requirement in plan.get("requirements", [])
            ]
            evidence = build_final_answer_evidence(
                question=question,
                plan=plan,
                company=company,
                retrieval_results=retrieval_results,
            )
            return _json_text(
                {
                    "plan": plan,
                    "available_reports": list_company_reports(company["companyCode"]),
                    "evidence": evidence,
                }
            )
        except Exception as exc:
            return _json_text({"error": "財報資料查詢失敗", "detail": str(exc)})

    @tool
    def read_approved_reference_context() -> str:
        """讀取本次請求已核准的專家知識、資料倉儲與外部資料，不會額外查詢外部來源。"""
        return _json_text(
            {
                "expert_knowledge": state.get("applied_expert_knowledge") or [],
                "warehouse_data": state.get("applied_warehouse_data") or [],
                "external_data": {
                    "query": state.get("external_data_query_text") or "",
                    "response": state.get("external_data_response") or "",
                    "decision": state.get("external_data_decision") or "",
                },
            }
        )

    return [retrieve_financial_statement_evidence, read_approved_reference_context]


def _load_create_deep_agent() -> Callable[..., Any]:
    try:
        from deepagents import create_deep_agent
    except ImportError as exc:
        raise RuntimeError(
            "Deep Agent fallback 尚未安裝；請安裝 pyproject.toml 內的 deepagents 依賴。"
        ) from exc
    return create_deep_agent


def deep_agent_fallback(state: OverallState) -> OverallState:
    """以受控資料工具處理 14 種標準分類以外的徵審問題。"""
    question = str(state.get("rephrased_question") or state.get("user_input") or "").strip()
    try:
        create_deep_agent = _load_create_deep_agent()
        agent = create_deep_agent(
            model=chat_model,
            tools=_build_controlled_tools(state),
            system_prompt=DEEP_AGENT_SYSTEM_PROMPT,
        )
        result = agent.invoke({"messages": [{"role": "user", "content": question}]})
        messages = result.get("messages") or []
        if not messages:
            raise RuntimeError("Deep Agent 未回傳任何訊息。")
        answer = get_message_text(messages[-1])
        if not answer:
            raise RuntimeError("Deep Agent 回傳空白答案。")
    except Exception as exc:
        answer = f"非標準徵審問題目前無法由 Deep Agent 完成。錯誤：{exc}"
        return {
            **state,
            "answer": answer,
            "final_answer": answer,
            "post_analysis_answer": answer,
            "semantic_workflow_node": "deep_agent_fallback",
            "semantic_workflow_status": "failed",
            "deep_agent_result": {"error": str(exc)},
        }

    return {
        **state,
        "answer": answer,
        "final_answer": answer,
        "post_analysis_answer": answer,
        "semantic_workflow_node": "deep_agent_fallback",
        "semantic_workflow_status": "completed",
        "deep_agent_result": {"answer": answer},
    }
