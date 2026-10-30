"""依使用者需求和文件範本目錄辨識用途與參考類型。"""

import json
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from src.features.report_generator.services.domain_report_service import ReportLLMTrace
from .llm import _invoke_report_structured
from .schemas import (
    DocumentTypeTemplate, ReportOutlineRequest, ReportQuestionPlan,
)


def _classify_report_question(
    request: ReportOutlineRequest,
    document_templates: dict[str, DocumentTypeTemplate],
    model,
    traces: list[ReportLLMTrace],
) -> ReportQuestionPlan:
    prompt = (
        "你是文件需求分類器。請根據歷史訊息、目前文件種類與大綱，"
        "理解使用者最新問題中的省略、指代與修正；只分類，不寫文件內容或數值。"
        "請先從使用者實際需求分析一個或多個 purposes；每項 purposeId 依序用 P1、P2，"
        "description 寫使用者想完成的用途，planningMode 選 analysis、procedure、proposal、explanation 或 mixed。"
        "referenceTemplateIds 可列出零個或多個相關 D ID；範本 metadata 只是參考，不限制用途或章節。"
        "若還不清楚用途，purposes 可為空。修正既有文件時保留未被修改的用途。"
        "documentTypeId 有單一明確參考範本時填該 ID，否則填 null；"
        "任何領域的文件需求都可以處理，沒有適合的範本時仍可規劃用途。"
        "intent 為 create_report、revise_report、ask_question 或 out_of_scope；"
        "使用者要建立文件時選 create_report，要改動現有文件或回答前次追問時選 revise_report，"
        "只詢問文件、目前計畫或 Document Type 的資訊且沒有要求修改時選 ask_question；"
        "只有與文件工作無關時才選 out_of_scope。"
        "這個 intent 會決定後續回答問題、追問或規劃大綱，不要把單純提問當成修改文件。"
        "sourceMode：最新訊息明確要求預設 JSON 時選 default_json，"
        "明確要求只用使用者資料或停用預設 JSON 時選 user_data，"
        "未更改來源時選 keep。"
        "includeAllMetrics 只有使用者要求全部指標時才為 true。"
        "requestedMetrics 記錄使用者明確提到的指標，不限固定目錄。\n"
        f"文件種類目錄：{json.dumps([{'id': item.id, 'name': item.name, 'category': item.category, 'purpose': item.purpose} for item in document_templates.values()], ensure_ascii=False)}\n"
        f"目前文件種類：{request.currentDocumentTypeId or '無'}\n"
        f"目前多用途計畫：{request.currentPurposePlan.model_dump_json() if request.currentPurposePlan else 'null'}\n"
        f"待確認的問題：{request.pendingClarification.model_dump_json() if request.pendingClarification else 'null'}\n"
        f"目前用途大綱：{request.currentPurposeOutline.model_dump_json() if request.currentPurposeOutline else 'null'}\n"
        f"目前文件範本大綱：{request.currentGeneralOutline.model_dump_json() if request.currentGeneralOutline else 'null'}\n"
        f"對話：{json.dumps([message.model_dump() for message in request.messages], ensure_ascii=False)}"
    )
    return _invoke_report_structured(
        model=model,
        schema=ReportQuestionPlan,
        prompt=prompt,
        operation="report_outline.classify_question",
        traces=traces,
    )


class DocumentTypeGraphState(TypedDict, total=False):
    request: ReportOutlineRequest
    document_templates: dict[str, DocumentTypeTemplate]
    model: Any
    traces: list[ReportLLMTrace]
    plan: ReportQuestionPlan
    document_template: DocumentTypeTemplate | None


def _classify(state: DocumentTypeGraphState) -> DocumentTypeGraphState:
    traces = list(state["traces"])
    plan = _classify_report_question(
        state["request"], state["document_templates"],
        state["model"], traces,
    )
    return {"plan": plan, "traces": traces}


def _resolve_type(state: DocumentTypeGraphState) -> DocumentTypeGraphState:
    request = state["request"]
    plan = state["plan"]
    document_type_id = plan.documentTypeId
    if document_type_id is None and plan.intent in ("revise_report", "ask_question"):
        document_type_id = request.currentDocumentTypeId
    return {
        "document_template": state["document_templates"].get(document_type_id),
    }


_builder = StateGraph(DocumentTypeGraphState)
_builder.add_node("classify_question", _classify)
_builder.add_node("resolve_document_type", _resolve_type)
_builder.add_edge(START, "classify_question")
_builder.add_edge("classify_question", "resolve_document_type")
_builder.add_edge("resolve_document_type", END)
DOCUMENT_TYPE_GRAPH = _builder.compile()


def classify_document_type(
    request: ReportOutlineRequest,
    document_templates: dict[str, DocumentTypeTemplate],
    model: Any,
    traces: list[ReportLLMTrace],
) -> DocumentTypeGraphState:
    return DOCUMENT_TYPE_GRAPH.invoke({
        "request": request,
        "document_templates": document_templates,
        "model": model,
        "traces": traces,
    })
