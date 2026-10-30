import json
import os
from time import perf_counter

from openai import OpenAI
from pydantic import BaseModel, Field
from langgraph.types import interrupt

from src.features.chatbot.core.providers.chat_openAI_provider import chat_model
from src.features.chatbot.core.structured_output import invoke_pydantic_structured
from src.features.chatbot.models.langgraph_state_types import OverallState


class ExternalDataDecisionSchema(BaseModel):
    needs_external_data: bool = Field(
        description="這個問題是否需要先查詢外部資料，才能更完整回答"
    )
    external_data_query_text: str = Field(
        default="",
        description="若需要外部資料，提供給前端查詢外部資訊的建議查詢句"
    )
    reason: str = Field(default="", description="簡短說明判斷原因")


def sanitize_llm_text(text: str) -> str:
    if not text:
        return ""
    sanitized_chars = []
    for char in str(text):
        codepoint = ord(char)
        if 0xD800 <= codepoint <= 0xDFFF:
            continue
        if char in "\n\r\t" or codepoint >= 32:
            sanitized_chars.append(char)
    return "".join(sanitized_chars)


def query_external_data_with_llm(state: OverallState, query_text: str) -> tuple[str, str]:
    question = sanitize_llm_text(state.get("rephrased_question") or state.get("user_input") or "")
    semantic_plan = state.get("semantic_plan") or {}
    workflow_template = state.get("semantic_workflow_template") or {}
    analysis_goal = sanitize_llm_text(semantic_plan.get("analysis_goal") or "")
    external_data_model = "gpt-5.5"
    prompt = f"""
你是信用徵審流程中的外部資料搜尋與摘要 Agent。

請使用網路搜尋查詢「外部資料查詢主題」，整理可供最終回答引用的外部背景資料。

重要規則：
1. 請聚焦公司、期間、新聞、重大事件、產業脈絡、訴訟、裁罰、政策、供應鏈或信用風險。
2. 不要把外部資料當成財務報表數字來源；外部資料只可作為事件背景、風險脈絡與判斷輔助。
3. 若無法確認具體事件或來源，請明確寫出「無法確認」與限制，不要捏造新聞、日期、來源或事件。
4. 請用繁體中文輸出，格式固定為：
   - 查詢主題：
   - 摘要重點：
   - 可能影響：
   - 資料限制：

使用者原始問題：
{question}

analysis_goal：
{analysis_goal}

標準 Workflow 的外部資料／RAG 重點：
{json.dumps(workflow_template.get("rag_focus") or [], ensure_ascii=False)}

外部資料查詢主題：
{query_text}
"""
    print("[use_external_data] external data llm prompt:\n" + prompt)
    client = OpenAI()
    response = client.responses.create(
        model=external_data_model,
        tools=[
            {"type": "web_search"},
        ],
        input=prompt,
    )
    response_text = sanitize_llm_text(response.output_text)
    print("[use_external_data] external data llm response:\n" + response_text)
    return response_text, prompt


def use_external_data(state: OverallState) -> OverallState:
    started_at = perf_counter()
    use_external_data_enabled = bool(state.get("use_external_data", True))

    if not use_external_data_enabled:
        result = {
            "needs_external_data": False,
            "external_data_query_text": "",
            "reason": "Skipped because referenceSettings.useExternalData is false.",
            "decision": "disabled",
        }
        print("[use_external_data] skipped: use_external_data is false")
        return {
            **state,
            "needs_external_data": False,
            "awaiting_external_data_confirmation": False,
            "external_data_query_text": "",
            "external_data_decision": "",
            "external_data_response": "",
            "external_data_response_prompt": "",
            "external_data_result": result,
        }

    question = sanitize_llm_text(state.get("rephrased_question") or state.get("user_input") or "")
    semantic_plan = state.get("semantic_plan") or {}
    workflow_template = state.get("semantic_workflow_template") or {}
    analysis_goal = sanitize_llm_text(semantic_plan.get("analysis_goal") or "")
    requirements = semantic_plan.get("requirements") or []
    requirement_lines = []
    for index, requirement in enumerate(requirements, start=1):
        requirement_lines.append(
            json.dumps(
                {
                    "index": index,
                    "field_query": requirement.get("field_query") or [],
                    "statement_type": requirement.get("statement_type") or "",
                    "periods": requirement.get("periods") or [],
                    "purpose": requirement.get("purpose") or "",
                },
                ensure_ascii=False,
            )
        )

    prompt = f"""
你是授信與財報分析流程中的外部資料判斷器。

你的任務是根據使用者問題、標準 Workflow 的 RAG 重點、analysis_goal 與各 requirement 的 purpose，
判斷這題是否需要先查詢「財務報表資料庫以外」的外部資訊，才能更完整回答。

請特別判斷下列情境是否需要外部資料：
1. 問題要求即時、最新、近期、目前、最近發展、最新消息、重大事件。
2. 問題涉及產業景氣、新聞事件、訴訟、裁罰、政策、供應鏈、經營策略、信用事件、違約風險、非財報資料背景。
3. 問題需要知道財報數字以外的外部原因、外部佐證、產業脈絡或事件背景。

請判斷下列情境通常不需要外部資料：
1. 單純查財務數字、比率、期間比較、趨勢分析，且只靠財報資料即可回答。
2. 問題雖然是分析，但核心仍只依賴財報欄位與期間資料即可完成。

輸出規則：
1. 若需要外部資料，needs_external_data = true。
2. 若需要外部資料，external_data_query_text 必須是一句可直接交給前端查詢外部資訊的繁體中文查詢句。
3. external_data_query_text 要具體包含公司、期間、主題或事件，不可只寫關鍵字。
4. 若不需要外部資料，needs_external_data = false，external_data_query_text = ""。
5. 只能輸出 JSON。

原始問題：
{question}

analysis_goal：
{analysis_goal}

標準 Workflow 的 RAG 重點：
{json.dumps(workflow_template.get("rag_focus") or [], ensure_ascii=False)}

requirements：
{chr(10).join(requirement_lines) if requirement_lines else "無"}
"""

    print("[use_external_data] prompt:\n" + prompt)
    result = invoke_pydantic_structured(
        model=chat_model,
        schema=ExternalDataDecisionSchema,
        prompt=prompt,
        operation="use_external_data",
        fallback_factory=lambda: ExternalDataDecisionSchema(
            needs_external_data=False,
            external_data_query_text="",
            reason="Pydantic structured output failed; skipped external data.",
        ),
    ).model_dump()
    print("[use_external_data] result:\n" + json.dumps(result, ensure_ascii=False, indent=2))

    needs_external_data = bool(result.get("needs_external_data"))
    external_data_query_text = sanitize_llm_text(result.get("external_data_query_text") or "")
    if needs_external_data and external_data_query_text:
        answer = (
            f"這個問題可能需要外部查詢「{external_data_query_text}」的資料，"
            "請前端確認是否要用這段話查詢外部的資訊。"
        )
        print(f"[timing] use_external_data took {perf_counter() - started_at:.3f}s")
        return {
            **state,
            "needs_external_data": True,
            "awaiting_external_data_confirmation": True,
            "external_data_query_text": external_data_query_text,
            "external_data_decision": "",
            "external_data_response": "",
            "external_data_response_prompt": "",
            "external_data_result": result,
            "answer": answer,
        }

    result["external_data_query_text"] = ""
    result["needs_external_data"] = False
    print(f"[timing] use_external_data took {perf_counter() - started_at:.3f}s")
    return {
        **state,
        "needs_external_data": False,
        "awaiting_external_data_confirmation": False,
        "external_data_query_text": "",
        "external_data_decision": "",
        "external_data_response": "",
        "external_data_response_prompt": "",
        "external_data_result": result,
    }


def review_external_data(state: OverallState) -> OverallState:
    """Pause the graph until a human adopts, edits, or rejects the external query."""
    suggested_query = sanitize_llm_text(state.get("external_data_query_text") or "").strip()
    result = state.get("external_data_result") or {}
    resume_value = interrupt(
        {
            "type": "external_data_approval",
            "externalDataQueryText": suggested_query,
            "reason": sanitize_llm_text(result.get("reason") or ""),
        }
    )
    if not isinstance(resume_value, dict):
        raise ValueError("External data approval must be a JSON object.")

    decision = sanitize_llm_text(resume_value.get("decision") or "").strip().lower()
    reviewed_query = sanitize_llm_text(
        resume_value.get("externalDataQueryText") or suggested_query
    ).strip()
    if decision not in {"adopted", "rejected"}:
        raise ValueError("External data decision must be adopted or rejected.")
    if decision == "adopted" and not reviewed_query:
        raise ValueError("External data query text is required when the decision is adopted.")

    if decision == "rejected":
        print("[review_external_data] rejected external data query text")
        return {
            **state,
            "needs_external_data": False,
            "awaiting_external_data_confirmation": False,
            "external_data_decision": decision,
            "external_data_query_text": "",
            "external_data_response": "",
            "external_data_response_prompt": "",
            "external_data_result": {
                "needs_external_data": False,
                "external_data_query_text": reviewed_query,
                "reason": "User rejected the suggested external data query text.",
                "decision": decision,
            },
        }

    print("[review_external_data] adopted external data query text:\n" + reviewed_query)
    return {
        **state,
        "needs_external_data": True,
        "awaiting_external_data_confirmation": False,
        "external_data_decision": decision,
        "external_data_query_text": reviewed_query,
        "external_data_response": "",
        "external_data_response_prompt": "",
        "external_data_result": {
            "needs_external_data": True,
            "external_data_query_text": reviewed_query,
            "reason": "User adopted the reviewed external data query text.",
            "decision": decision,
        },
    }


def query_approved_external_data(state: OverallState) -> OverallState:
    """Run web search only after the interrupt has been resumed with approval."""
    started_at = perf_counter()
    query_text = sanitize_llm_text(state.get("external_data_query_text") or "").strip()
    external_data_response = ""
    external_data_response_prompt = ""
    try:
        external_data_response, external_data_response_prompt = query_external_data_with_llm(
            state,
            query_text,
        )
    except Exception as exc:
        external_data_response = f"外部資料查詢失敗：{exc}"
        print("[query_approved_external_data] external data llm failed:", exc)

    print(f"[timing] query_approved_external_data took {perf_counter() - started_at:.3f}s")
    return {
        **state,
        "external_data_response": external_data_response,
        "external_data_response_prompt": external_data_response_prompt,
        "external_data_result": {
            "needs_external_data": True,
            "external_data_query_text": query_text,
            "external_data_response": external_data_response,
            "reason": "User approved the external data query text.",
            "decision": "adopted",
        },
    }
