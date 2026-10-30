"""內容規劃 Graph：逐章從 S 範本建議的 C 類型中選擇。"""

import json
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from src.features.report_generator.services.domain_report_service import ReportLLMTrace
from .catalog import load_content_type_templates, load_document_type_templates, load_section_type_templates
from .llm import _invoke_report_structured
from .samples import DocumentTypeSample
from .schemas import (
    ContentTypeTemplate, GeneralDocumentPlan, PlannedSection, ReportChatMessage,
    SectionTypeTemplate,
)


class SectionContentChoice(BaseModel):
    sectionId: str
    contentTypeIds: list[str] = Field(min_length=1)


class ContentChoices(BaseModel):
    sections: list[SectionContentChoice] = Field(min_length=1)


class ContentGraphState(TypedDict, total=False):
    plan: GeneralDocumentPlan
    messages: list[ReportChatMessage]
    source_sample: DocumentTypeSample | None
    model: Any
    traces: list[ReportLLMTrace]
    section_templates: dict[str, SectionTypeTemplate]
    content_templates: dict[str, ContentTypeTemplate]
    choices: ContentChoices
    completed_plan: GeneralDocumentPlan


def _load_content_catalog(state: ContentGraphState) -> ContentGraphState:
    plan = state["plan"]
    template = load_document_type_templates()[plan.documentTypeId]
    sections = load_section_type_templates()
    selected_ids = [section.sectionId for section in plan.sections]
    allowed_ids = set(template.requiredSectionIds + template.optionalSectionIds)
    if (
        len(selected_ids) != len(set(selected_ids))
        or not set(template.requiredSectionIds) <= set(selected_ids)
        or not set(selected_ids) <= allowed_ids
        or any(
            section.isRequired != (section.sectionId in template.requiredSectionIds)
            for section in plan.sections
        )
    ):
        raise ValueError("章節計畫與文件範本不一致")
    return {
        "section_templates": {section_id: sections[section_id] for section_id in selected_ids},
        "content_templates": load_content_type_templates(),
    }


def _choose_content_types(state: ContentGraphState) -> ContentGraphState:
    sections = state["section_templates"]
    contents = state["content_templates"]
    allowed = [
        {
            "sectionId": section_id,
            "sectionName": section.name,
            "purpose": section.purpose,
            "suggestedContents": [contents[content_id].model_dump() for content_id in section.suggestedContentTypeIds],
        }
        for section_id, section in sections.items()
    ]
    traces = list(state["traces"])
    choices = _invoke_report_structured(
        model=state["model"],
        schema=ContentChoices,
        operation="general_document.select_content_types",
        traces=traces,
        prompt=(
            "你是文件內容規劃器。請針對每個章節選一個或多個內容種類 ID。"
            "只能選該章節 suggestedContents 中的 C ID，每個章節都要回傳一次；"
            "只規劃內容形式，不撰寫內文、不宣稱已執行工具或查到資料。"
            "延續目前計畫中未被最新訊息修改的內容選擇。\n"
            f"目前計畫：{state['plan'].model_dump_json()}\n"
            f"章節與可選內容：{json.dumps(allowed, ensure_ascii=False)}\n"
            f"明確選用的虛構測試資料：{state['source_sample'].model_dump_json() if state.get('source_sample') else '無'}\n"
            f"對話：{json.dumps([message.model_dump() for message in state['messages']], ensure_ascii=False)}"
        ),
    )
    return {"choices": choices, "traces": traces}


def _validate_content_plan(state: ContentGraphState) -> ContentGraphState:
    plan = state["plan"]
    choices = state["choices"].sections
    selected_ids = [choice.sectionId for choice in choices]
    expected_ids = [section.sectionId for section in plan.sections]
    if len(selected_ids) != len(set(selected_ids)) or set(selected_ids) != set(expected_ids):
        raise ValueError("AI 未完整規劃每個章節的內容")
    chosen_by_section = {choice.sectionId: choice.contentTypeIds for choice in choices}
    completed = []
    for section in plan.sections:
        selected = chosen_by_section[section.sectionId]
        allowed = state["section_templates"][section.sectionId].suggestedContentTypeIds
        if len(selected) != len(set(selected)) or not set(selected) <= set(allowed):
            raise ValueError(f"{section.sectionId} 的內容種類超出章節範本")
        completed.append(PlannedSection(
            sectionId=section.sectionId,
            isRequired=section.isRequired,
            contentTypeIds=[content_id for content_id in allowed if content_id in selected],
        ))
    return {"completed_plan": GeneralDocumentPlan(
        documentTypeId=plan.documentTypeId,
        sections=completed,
    )}


_builder = StateGraph(ContentGraphState)
_builder.add_node("load_content_catalog", _load_content_catalog)
_builder.add_node("choose_content_types", _choose_content_types)
_builder.add_node("validate_content_plan", _validate_content_plan)
_builder.add_edge(START, "load_content_catalog")
_builder.add_edge("load_content_catalog", "choose_content_types")
_builder.add_edge("choose_content_types", "validate_content_plan")
_builder.add_edge("validate_content_plan", END)
CONTENT_GRAPH = _builder.compile()


def plan_section_contents(
    plan: GeneralDocumentPlan,
    messages: list[ReportChatMessage],
    model: Any,
    traces: list[ReportLLMTrace],
    source_sample: DocumentTypeSample | None = None,
) -> tuple[GeneralDocumentPlan, list[ReportLLMTrace]]:
    result = CONTENT_GRAPH.invoke({
        "plan": plan,
        "messages": messages,
        "model": model,
        "traces": traces,
        "source_sample": source_sample,
    })
    return result["completed_plan"], result["traces"]
