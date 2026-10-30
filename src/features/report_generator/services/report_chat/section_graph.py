"""章節規劃 Graph：固定必要章節，從範本允許的可選章節中挑選。"""

import json
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from src.features.report_generator.services.domain_report_service import ReportLLMTrace
from .catalog import get_document_section_plan
from .llm import _invoke_report_structured
from .samples import DocumentTypeSample
from .schemas import (
    DocumentSectionPlan, GeneralDocumentPlan, PlannedSection, ReportChatMessage,
)


class OptionalSectionChoice(BaseModel):
    optionalSectionIds: list[str] = Field(default_factory=list)


class SectionGraphState(TypedDict, total=False):
    document_type_id: str
    messages: list[ReportChatMessage]
    source_sample: DocumentTypeSample | None
    current_plan: GeneralDocumentPlan | None
    model: Any
    traces: list[ReportLLMTrace]
    template_plan: DocumentSectionPlan
    selected_optional_ids: list[str]
    plan: GeneralDocumentPlan


def _load_sections(state: SectionGraphState) -> SectionGraphState:
    template_plan = get_document_section_plan(state["document_type_id"])
    if template_plan is None:
        raise ValueError("文件種類不存在，無法規劃章節")
    return {"template_plan": template_plan}


def _choose_optional(state: SectionGraphState) -> SectionGraphState:
    available = state["template_plan"].optionalSections
    if not available:
        return {"selected_optional_ids": []}
    current_plan = state.get("current_plan")
    current_optional_ids = (
        [section.sectionId for section in current_plan.sections if not section.isRequired]
        if current_plan and current_plan.documentTypeId == state["document_type_id"] else []
    )
    traces = list(state["traces"])
    choice = _invoke_report_structured(
        model=state["model"],
        schema=OptionalSectionChoice,
        operation="general_document.select_optional_sections",
        traces=traces,
        prompt=(
            "你是文件章節規劃器。必要章節由程式固定加入。"
            "只從下列可選章節 ID 選出使用者需求需要的章節；沒有必要補充時回傳空清單。"
            "沿用目前計畫中未被最新訊息修改的可選章節，不可新增清單外的 ID。\n"
            f"文件：{state['template_plan'].documentTemplate.model_dump_json(exclude={'suggestedSections'})}\n"
            f"可選章節：{json.dumps([item.model_dump() for item in available], ensure_ascii=False)}\n"
            f"目前可選章節：{json.dumps(current_optional_ids, ensure_ascii=False)}\n"
            f"明確選用的虛構測試資料：{state['source_sample'].model_dump_json() if state.get('source_sample') else '無'}\n"
            f"對話：{json.dumps([message.model_dump() for message in state['messages']], ensure_ascii=False)}"
        ),
    )
    selected = set(choice.optionalSectionIds)
    allowed = {section.id for section in available}
    if not selected <= allowed:
        raise ValueError("AI 選擇了範本以外的可選章節")
    return {
        "selected_optional_ids": [section.id for section in available if section.id in selected],
        "traces": traces,
    }


def _assemble_sections(state: SectionGraphState) -> SectionGraphState:
    template_plan = state["template_plan"]
    sections = [
        PlannedSection(sectionId=section.id, isRequired=True)
        for section in template_plan.requiredSections
    ]
    sections.extend(
        PlannedSection(sectionId=section.id, isRequired=False)
        for section in template_plan.optionalSections
        if section.id in state["selected_optional_ids"]
    )
    return {"plan": GeneralDocumentPlan(
        documentTypeId=state["document_type_id"],
        sections=sections,
    )}


_builder = StateGraph(SectionGraphState)
_builder.add_node("load_section_template", _load_sections)
_builder.add_node("choose_optional_sections", _choose_optional)
_builder.add_node("assemble_sections", _assemble_sections)
_builder.add_edge(START, "load_section_template")
_builder.add_edge("load_section_template", "choose_optional_sections")
_builder.add_edge("choose_optional_sections", "assemble_sections")
_builder.add_edge("assemble_sections", END)
SECTION_GRAPH = _builder.compile()


def plan_document_sections(
    document_type_id: str,
    messages: list[ReportChatMessage],
    model: Any,
    traces: list[ReportLLMTrace],
    current_plan: GeneralDocumentPlan | None = None,
    source_sample: DocumentTypeSample | None = None,
) -> tuple[GeneralDocumentPlan, list[ReportLLMTrace]]:
    result = SECTION_GRAPH.invoke({
        "document_type_id": document_type_id,
        "messages": messages,
        "current_plan": current_plan,
        "source_sample": source_sample,
        "model": model,
        "traces": traces,
    })
    return result["plan"], result["traces"]
