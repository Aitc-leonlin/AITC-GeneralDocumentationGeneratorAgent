"""對話階段：分類需求並產生可確認的大綱。"""

import logging
import re
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from src.features.report_generator.services.domain_report_service import ReportLLMTrace
from .catalog import load_document_type_templates
from .document_type_graph import classify_document_type
from .open_sample_agent import choose_open_sample
from .purpose_workflow import assess_purpose_readiness, pending_from_decision, plan_purpose_document
from .question_agent import answer_report_question
from .schemas import (
    DocumentPurpose, DocumentTypeTemplate, InvalidReportRequest, PendingClarification,
    ReportOutlineRequest, ReportOutlineResponse, ReportQuestionPlan,
    ReportSampleSelection, ReportToolUsage, required_source_satisfied,
)


logger = logging.getLogger("uvicorn.error")


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
    sample_selection: ReportSampleSelection | None
    tool_usages: list[ReportToolUsage]
    response: ReportOutlineResponse


def _outline_load_context(state: OutlineGraphState) -> OutlineGraphState:
    request = state["request"]
    if request.messages[-1].role != "user":
        raise InvalidReportRequest("最後一則訊息必須由使用者送出")
    from src.features.chatbot.core.providers.chat_openAI_provider import chat_model

    return {
        "model": chat_model,
        "traces": [],
        "tool_usages": [],
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
    return {"purposes": purposes, "pending_clarification": pending, "traces": traces}


def _intent_route(state: OutlineGraphState) -> Literal["answer", "assess"]:
    intent = state["plan"].intent
    if intent in ("ask_question", "out_of_scope"):
        return "answer"
    logger.info(
        "report_question.decide_lookup.not_entered reason=intent_route intent=%s question=%s",
        intent, state["request"].messages[-1].content,
    )
    return "assess"


def _outline_answer_question(state: OutlineGraphState) -> OutlineGraphState:
    request = state["request"]
    plan = state["plan"]
    source_mode = _general_source_mode(state)
    answer, traces, tool_usages = answer_report_question(
        request=request, plan=plan, templates=state["document_templates"],
        model=state["model"], traces=state["traces"],
        allow_samples=plan.intent == "ask_question" and source_mode != "user_data",
        source_mode=source_mode,
    )
    return {"traces": traces, "response": ReportOutlineResponse(
        assistantMessage=answer,
        documentTemplate=state["document_templates"].get(request.currentDocumentTypeId),
        generalPlan=request.currentGeneralPlan,
        generalOutline=request.currentGeneralOutline,
        purposePlan=request.currentPurposePlan,
        purposeOutline=request.currentPurposeOutline,
        pendingClarification=request.pendingClarification,
        sourceMode=request.currentSourceMode,
        sampleSelection=request.currentSampleSelection,
        llmTraces=traces,
        toolUsages=tool_usages,
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


def _outline_route_sample(state: OutlineGraphState) -> OutlineGraphState:
    selection, traces, usages = choose_open_sample(
        request=state["request"], purposes=state["purposes"],
        model=state["model"], traces=state["traces"],
        fallback_document_type_id=(
            state["document_template"].id if state.get("document_template") else None
        ),
        allow_tools=state["source_mode"] != "user_data",
    )
    pending = None
    if not required_source_satisfied(selection):
        questions = {
            "case": "這份文件需要符合需求的案例資料，目前沒有找到可採用的案例。請提供案例內容，或明確告訴我改用一般性示例。",
            "user_data": "這份文件需要依據你提供的資料，但目前對話中還沒有足夠的資料內容。請貼上資料，或明確告訴我改用一般性示例。",
            "external": "這份文件需要外部真實資料查證，目前案例工具無法完成查證。請提供要引用的資料內容與來源，或明確告訴我改成一般性示例。",
            "any": "這份文件需要具體資料支撐，目前沒有足夠的可用來源。請提供資料內容與來源，或明確告訴我改用一般性示例。",
        }
        question = questions[selection.requiredSource]
        if selection.requiredSource in ("case", "any") and selection.outputMode != "single":
            covered_count = len(selection.outputCoverage)
            matched_subjects = {item.label for item in selection.outputCoverage}
            missing_subjects = [
                item for item in selection.comparisonSubjects
                if item not in matched_subjects
            ]
            missing_text = (
                f"；尚缺少「{'、'.join(missing_subjects)}」的對應資料"
                if missing_subjects else ""
            )
            question = (
                f"這份文件要求 {selection.requestedCount} 個有資料支撐的選項或比較對象，"
                f"目前只有 {covered_count} 個項目有案例資料支援{missing_text}。"
                "請提供缺少的資料，或明確告訴我改用一般性示例。"
            )
        pending = PendingClarification(
            question=question,
            missingDecision="必要參考資料", purposes=state["purposes"],
        )
    return {
        "sample_selection": selection,
        "pending_clarification": pending,
        "traces": traces,
        "tool_usages": [*state["tool_usages"], *usages],
    }


def _sample_source_route(state: OutlineGraphState) -> Literal["clarify", "classified"]:
    return "clarify" if state.get("pending_clarification") else "classified"


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
        sample_selection=state.get("sample_selection"),
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
        sampleSelection=state.get("sample_selection"),
        llmTraces=traces,
        toolUsages=state["tool_usages"],
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
        sourceMode=(state.get("source_mode") or _general_source_mode(state)) if pending else request.currentSourceMode,
        sampleSelection=state.get("sample_selection") or request.currentSampleSelection,
        llmTraces=state["traces"],
        toolUsages=state.get("tool_usages", []),
    )}


_outline_builder = StateGraph(OutlineGraphState)
_outline_builder.add_node("load_context", _outline_load_context)
_outline_builder.add_node("classify_question", _outline_classify)
_outline_builder.add_node("assess_readiness", _outline_assess)
_outline_builder.add_node("answer_question", _outline_answer_question)
_outline_builder.add_node("resolve_source_mode", _outline_resolve_source)
_outline_builder.add_node("route_open_sample", _outline_route_sample)
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
_outline_builder.add_edge("resolve_source_mode", "route_open_sample")
_outline_builder.add_conditional_edges("route_open_sample", _sample_source_route, {
    "clarify": "clarify", "classified": "classified",
})
_outline_builder.add_edge("classified", END)
_outline_builder.add_edge("clarify", END)
_outline_builder.add_edge("answer_question", END)
_OUTLINE_GRAPH = _outline_builder.compile()
