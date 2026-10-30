"""對話階段：分類需求並產生可確認的大綱。"""

import json
import re
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from src.features.report_generator.services.domain_report_service import ReportLLMTrace
from .catalog import load_document_type_templates
from .document_type_graph import classify_document_type
from .llm import _invoke_report_structured
from .purpose_workflow import assess_purpose_readiness, pending_from_decision, plan_purpose_document
from .schemas import (
    DocumentPurpose, DocumentTypeTemplate, InvalidReportRequest, PendingClarification,
    ReportOutlineRequest, ReportOutlineResponse, ReportQuestionPlan,
)


def create_report_outline(request: ReportOutlineRequest) -> ReportOutlineResponse:
    response = None
    graph_nodes = []
    for namespace, update in _OUTLINE_GRAPH.stream(
        {"request": request}, stream_mode="updates", subgraphs=True
    ):
        for node_name, node_update in update.items():
            if node_name == "__interrupt__":
                continue
            parent_nodes = [part.split(":", 1)[0] for part in namespace]
            graph_nodes.append(" / ".join([*parent_nodes, node_name]))
            if not namespace and isinstance(node_update, dict):
                response = node_update.get("response", response)
    if response is None:
        raise RuntimeError("報告大綱流程未產生回應")
    response.graphNodes = graph_nodes
    return response


class OutlineGraphState(TypedDict, total=False):
    request: ReportOutlineRequest
    model: Any
    traces: list[ReportLLMTrace]
    document_templates: dict[str, DocumentTypeTemplate]
    plan: ReportQuestionPlan
    purposes: list[DocumentPurpose]
    pending_clarification: PendingClarification | None
    document_template: DocumentTypeTemplate | None
    source_mode: Literal["default_json", "user_data"] | None
    response: ReportOutlineResponse


class QuestionAnswer(BaseModel):
    answer: str = Field(min_length=1, max_length=1000)


def _outline_load_context(state: OutlineGraphState) -> OutlineGraphState:
    request = state["request"]
    if request.messages[-1].role != "user":
        raise InvalidReportRequest("最後一則訊息必須由使用者送出")
    from src.features.chatbot.core.providers.chat_openAI_provider import chat_model

    return {
        "model": chat_model,
        "traces": [],
        "document_templates": load_document_type_templates(),
    }


def _outline_classify(state: OutlineGraphState) -> OutlineGraphState:
    classified = classify_document_type(
        state["request"], state["document_templates"],
        state["model"], state["traces"],
    )
    return {
        "plan": classified["plan"],
        "document_template": classified["document_template"],
        "traces": classified["traces"],
    }


def _outline_assess(state: OutlineGraphState) -> OutlineGraphState:
    request = state["request"]
    known_templates = state["document_templates"]
    raw = state["plan"].purposes
    if not raw and state["plan"].intent == "revise_report" and request.pendingClarification:
        raw = request.pendingClarification.purposes
    if not raw and state["plan"].intent == "revise_report" and request.currentPurposePlan:
        raw = request.currentPurposePlan.purposes
    if not raw and state["document_template"] is not None:
        template = state["document_template"]
        raw = [DocumentPurpose(
            purposeId="P1", description=state["plan"].purpose or template.purpose,
            referenceTemplateIds=[template.id],
        )]
    purposes = [DocumentPurpose(
        purposeId=f"P{index}", description=item.description,
        planningMode=item.planningMode,
        referenceTemplateIds=list(dict.fromkeys(
            template_id for template_id in item.referenceTemplateIds if template_id in known_templates
        )),
    ) for index, item in enumerate(raw, start=1)]
    decision, traces = assess_purpose_readiness(request, state["plan"], purposes, state["model"], state["traces"])
    pending = pending_from_decision(decision, purposes) if not decision.ready else None
    source_mode = _general_source_mode(state)
    if pending is None and source_mode == "default_json":
        references = {item for purpose in purposes for item in purpose.referenceTemplateIds}
        if len(purposes) != 1 or len(references) != 1:
            pending = PendingClarification(
                question=(
                    "目前沒有對應這份文件的測試 JSON。請提供資料，或指定要使用哪一種 Document Type 的測試案例。"
                    if not references else
                    "目前的預設測試 JSON 各自對應一種範本。這份文件要改用你提供的資料，還是先只做其中一種範本的測試案例？"
                ),
                missingDecision="測試資料來源", purposes=purposes,
            )
    return {"purposes": purposes, "pending_clarification": pending, "traces": traces}


def _intent_route(state: OutlineGraphState) -> Literal["answer", "assess"]:
    return "answer" if state["plan"].intent in ("ask_question", "out_of_scope") else "assess"


def _outline_answer_question(state: OutlineGraphState) -> OutlineGraphState:
    request = state["request"]
    plan = state["plan"]
    traces = list(state["traces"])
    answer = _invoke_report_structured(
        model=state["model"], schema=QuestionAnswer,
        operation="report_outline.answer_question", traces=traces,
        prompt=(
            "你是通用文件助手。請直接回答使用者最新的問題，不修改既有文件或大綱。"
            "參考完整對話、目前文件狀態及 Document Type 目錄；目錄只供參考，"
            "不能據此宣稱任何領域都必須套用特定範本。"
            "若問題與文件工作無關，簡短說明你能協助規劃、修訂或解釋文件。"
            "若缺乏資料，明確說明尚未提供，不要臆造事實。回答請使用繁體中文。\n"
            f"分類結果：{plan.model_dump_json()}\n"
            f"文件種類目錄：{json.dumps([{'id': item.id, 'name': item.name, 'category': item.category, 'purpose': item.purpose} for item in state['document_templates'].values()], ensure_ascii=False)}\n"
            f"目前用途計畫：{request.currentPurposePlan.model_dump_json() if request.currentPurposePlan else 'null'}\n"
            f"目前用途大綱：{request.currentPurposeOutline.model_dump_json() if request.currentPurposeOutline else 'null'}\n"
            f"目前文件範本大綱：{request.currentGeneralOutline.model_dump_json() if request.currentGeneralOutline else 'null'}\n"
            f"對話：{json.dumps([message.model_dump() for message in request.messages], ensure_ascii=False)}"
        ),
    )
    return {"traces": traces, "response": ReportOutlineResponse(
        assistantMessage=answer.answer,
        documentTemplate=state["document_templates"].get(request.currentDocumentTypeId),
        generalPlan=request.currentGeneralPlan,
        generalOutline=request.currentGeneralOutline,
        purposePlan=request.currentPurposePlan,
        purposeOutline=request.currentPurposeOutline,
        pendingClarification=request.pendingClarification,
        sourceMode=request.currentSourceMode,
        llmTraces=traces,
    )}


def _assessed_route(state: OutlineGraphState) -> Literal["clarify", "classified"]:
    return "clarify" if state["pending_clarification"] is not None else "classified"


def _general_source_mode(state: OutlineGraphState) -> Literal["default_json", "user_data"] | None:
    latest = state["request"].messages[-1].content
    if re.search(
        r"(?:不使用|不要使用|停用|不要用).{0,8}(?:預設|測試|範例)"
        r"|(?:只用|改用|使用|用).{0,6}(?:我提供|使用者提供|自己的|使用者).{0,6}資料",
        latest,
    ):
        return "user_data"
    if re.search(r"(?:預設|測試|範例).{0,12}(?:json|資料)", latest, re.IGNORECASE):
        return "default_json"
    selected = state["plan"].sourceMode
    return state["request"].currentSourceMode if selected == "keep" else selected


def _outline_resolve_source(state: OutlineGraphState) -> OutlineGraphState:
    """決定通用文件來源；此節點不呼叫 LLM。"""
    return {"source_mode": _general_source_mode(state)}


def _outline_classified(state: OutlineGraphState) -> OutlineGraphState:
    purposes = state["purposes"]
    if not purposes:
        raise InvalidReportRequest("尚未辨識文件用途，請補充需求")
    request = state["request"]
    purpose_plan, purpose_outline, traces = plan_purpose_document(
        purposes=purposes,
        messages=request.messages,
        model=state["model"],
        traces=state["traces"],
        current_plan=request.currentPurposePlan,
        current_outline=request.currentPurposeOutline,
        source_mode=state["source_mode"],
    )
    names = "、".join(item.description for item in purpose_plan.purposes)
    return {"traces": traces, "response": ReportOutlineResponse(
        assistantMessage=(
            f"已依「{names}」整理成一份「{purpose_outline.title}」大綱，"
            f"共 {len(purpose_outline.sections)} 個章節。可繼續告訴我想調整的地方。"
        )[:1000],
        purposePlan=purpose_plan,
        purposeOutline=purpose_outline,
        documentTemplate=state["document_template"],
        sourceMode=state["source_mode"],
        llmTraces=traces,
    )}


def _outline_clarify(state: OutlineGraphState) -> OutlineGraphState:
    request = state["request"]
    pending = state.get("pending_clarification")
    return {"response": ReportOutlineResponse(
        assistantMessage=pending.question if pending else "請說明想製作的文件種類或用途，以及希望包含的內容。",
        documentTemplate=state["document_templates"].get(request.currentDocumentTypeId),
        generalPlan=request.currentGeneralPlan,
        generalOutline=request.currentGeneralOutline,
        purposePlan=request.currentPurposePlan,
        purposeOutline=request.currentPurposeOutline,
        pendingClarification=pending,
        sourceMode=_general_source_mode(state) if pending else request.currentSourceMode,
        llmTraces=state["traces"],
    )}


_outline_builder = StateGraph(OutlineGraphState)
_outline_builder.add_node("load_context", _outline_load_context)
_outline_builder.add_node("classify_question", _outline_classify)
_outline_builder.add_node("assess_readiness", _outline_assess)
_outline_builder.add_node("answer_question", _outline_answer_question)
_outline_builder.add_node("resolve_source_mode", _outline_resolve_source)
_outline_builder.add_node("classified", _outline_classified)
_outline_builder.add_node("clarify", _outline_clarify)
_outline_builder.add_edge(START, "load_context")
_outline_builder.add_edge("load_context", "classify_question")
_outline_builder.add_conditional_edges("classify_question", _intent_route, {
    "answer": "answer_question", "assess": "assess_readiness",
})
_outline_builder.add_conditional_edges("assess_readiness", _assessed_route, {
    "classified": "resolve_source_mode", "clarify": "clarify",
})
_outline_builder.add_edge("resolve_source_mode", "classified")
_outline_builder.add_edge("classified", END)
_outline_builder.add_edge("clarify", END)
_outline_builder.add_edge("answer_question", END)
_OUTLINE_GRAPH = _outline_builder.compile()
