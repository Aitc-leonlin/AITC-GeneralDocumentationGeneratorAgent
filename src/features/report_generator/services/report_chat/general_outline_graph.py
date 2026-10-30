"""通用文件大綱 Graph：依已確認的 D→S→C 計畫撰寫大綱。"""

import json
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from src.features.report_generator.services.domain_report_service import ReportLLMTrace
from .catalog import load_content_type_templates, load_document_type_templates, load_section_type_templates
from .llm import _invoke_report_structured
from .samples import DocumentTypeSample
from .schemas import (
    ContentTypeTemplate, DocumentTypeTemplate, GeneralDocumentOutline,
    GeneralDocumentPlan, GeneralOutlineContent, GeneralOutlineSection,
    ReportChatMessage, SectionTypeTemplate,
)


class SectionFocusDraft(BaseModel):
    sectionId: str
    focus: str = Field(min_length=1, max_length=500)


class GeneralOutlineDraft(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    subject: str = Field(min_length=1, max_length=150)
    period: str = Field(min_length=1, max_length=100)
    objective: str = Field(min_length=1, max_length=800)
    sourcePlan: str = Field(min_length=1, max_length=1000)
    sectionFocuses: list[SectionFocusDraft] = Field(min_length=1)


class GeneralOutlineGraphState(TypedDict, total=False):
    plan: GeneralDocumentPlan
    messages: list[ReportChatMessage]
    source_sample: DocumentTypeSample | None
    current_outline: GeneralDocumentOutline | None
    model: Any
    traces: list[ReportLLMTrace]
    template: DocumentTypeTemplate
    sections: dict[str, SectionTypeTemplate]
    contents: dict[str, ContentTypeTemplate]
    draft: GeneralOutlineDraft
    outline: GeneralDocumentOutline


def _load_outline_context(state: GeneralOutlineGraphState) -> GeneralOutlineGraphState:
    plan = state["plan"]
    template = load_document_type_templates()[plan.documentTypeId]
    sections = load_section_type_templates()
    contents = load_content_type_templates()
    selected_ids = [section.sectionId for section in plan.sections]
    if (
        len(selected_ids) != len(set(selected_ids))
        or not set(template.requiredSectionIds) <= set(selected_ids)
        or not set(selected_ids) <= set(template.requiredSectionIds + template.optionalSectionIds)
    ):
        raise ValueError("大綱的章節計畫與文件範本不一致")
    for section in plan.sections:
        if section.isRequired != (section.sectionId in template.requiredSectionIds):
            raise ValueError(f"{section.sectionId} 的必要章節標記不正確")
        selected_contents = section.contentTypeIds
        allowed_contents = sections[section.sectionId].suggestedContentTypeIds
        if (
            not selected_contents
            or len(selected_contents) != len(set(selected_contents))
            or not set(selected_contents) <= set(allowed_contents)
        ):
            raise ValueError(f"{section.sectionId} 的內容種類與章節範本不一致")
    return {
        "template": template,
        "sections": {section_id: sections[section_id] for section_id in selected_ids},
        "contents": contents,
    }


def _draft_outline(state: GeneralOutlineGraphState) -> GeneralOutlineGraphState:
    plan = state["plan"]
    sections = state["sections"]
    contents = state["contents"]
    planned_sections = [
        {
            "sectionId": section.sectionId,
            "heading": sections[section.sectionId].name,
            "purpose": sections[section.sectionId].purpose,
            "isRequired": section.isRequired,
            "contents": [
                {
                    "id": content_id,
                    "name": contents[content_id].name,
                    "description": contents[content_id].description,
                }
                for content_id in section.contentTypeIds
            ],
        }
        for section in plan.sections
    ]
    current_outline = state.get("current_outline")
    if current_outline and current_outline.documentTypeId != plan.documentTypeId:
        current_outline = None
    traces = list(state["traces"])
    draft = _invoke_report_structured(
        model=state["model"],
        schema=GeneralOutlineDraft,
        operation="general_document.draft_outline",
        traces=traces,
        prompt=(
            "你是通用文件大綱編輯。文件種類、章節與內容種類已由前面的 Graph 決定。"
            "現在只撰寫可供使用者確認的大綱，不撰寫章節內文、結論或引用；"
            "可以在規劃重點中提及已明確提供的數值，但不可自行捏造。"
            "每個章節只需一段 focus，說明該章預計處理的重點；sectionId 必須與規劃一致，"
            "不得增刪或改名章節與內容種類。"
            "未提供的對象或期間可填「待提供」。若明確選用了虛構測試資料，"
            "請使用其中的對象、期間、事實與假設規劃大綱，sourcePlan 必須明示資料為虛構測試案例；"
            "不得把虛構案例當作使用者真實資料。若沒有選用測試資料，sourcePlan 說明後續將使用使用者資料，缺漏處需標示。"
            "延續目前大綱中未被最新訊息修改的需求。\n"
            f"文件範本：{state['template'].model_dump_json(exclude={'suggestedSections'})}\n"
            f"確定的章節與內容：{json.dumps(planned_sections, ensure_ascii=False)}\n"
            f"目前大綱：{current_outline.model_dump_json() if current_outline else 'null'}\n"
            f"明確選用的虛構測試資料：{state['source_sample'].model_dump_json() if state.get('source_sample') else '無'}\n"
            f"對話：{json.dumps([message.model_dump() for message in state['messages']], ensure_ascii=False)}"
        ),
    )
    return {"draft": draft, "traces": traces}


def _validate_outline(state: GeneralOutlineGraphState) -> GeneralOutlineGraphState:
    actual_ids = [section.sectionId for section in state["draft"].sectionFocuses]
    expected_ids = [section.sectionId for section in state["plan"].sections]
    if len(actual_ids) != len(set(actual_ids)) or set(actual_ids) != set(expected_ids):
        raise ValueError("AI 大綱未完整涵蓋確定的章節")
    return {"draft": state["draft"]}


def _assemble_outline(state: GeneralOutlineGraphState) -> GeneralOutlineGraphState:
    draft = state["draft"]
    focus_by_id = {section.sectionId: section.focus for section in draft.sectionFocuses}
    sections = []
    for planned in state["plan"].sections:
        template = state["sections"][planned.sectionId]
        sections.append(GeneralOutlineSection(
            sectionId=planned.sectionId,
            heading=template.name,
            focus=focus_by_id[planned.sectionId],
            isRequired=planned.isRequired,
            contents=[
                GeneralOutlineContent(
                    contentTypeId=content_id,
                    name=state["contents"][content_id].name,
                    description=state["contents"][content_id].description,
                )
                for content_id in planned.contentTypeIds
            ],
        ))
    return {"outline": GeneralDocumentOutline(
        documentTypeId=state["plan"].documentTypeId,
        documentTypeName=state["template"].name,
        title=draft.title,
        subject=draft.subject,
        period=draft.period,
        objective=draft.objective,
        sections=sections,
        sourcePlan=draft.sourcePlan,
    )}


_builder = StateGraph(GeneralOutlineGraphState)
_builder.add_node("load_outline_context", _load_outline_context)
_builder.add_node("draft_outline", _draft_outline)
_builder.add_node("validate_outline", _validate_outline)
_builder.add_node("assemble_outline", _assemble_outline)
_builder.add_edge(START, "load_outline_context")
_builder.add_edge("load_outline_context", "draft_outline")
_builder.add_edge("draft_outline", "validate_outline")
_builder.add_edge("validate_outline", "assemble_outline")
_builder.add_edge("assemble_outline", END)
GENERAL_OUTLINE_GRAPH = _builder.compile()


def draft_general_outline(
    plan: GeneralDocumentPlan,
    messages: list[ReportChatMessage],
    model: Any,
    traces: list[ReportLLMTrace],
    current_outline: GeneralDocumentOutline | None = None,
    source_sample: DocumentTypeSample | None = None,
) -> tuple[GeneralDocumentOutline, list[ReportLLMTrace]]:
    result = GENERAL_OUTLINE_GRAPH.invoke({
        "plan": plan,
        "messages": messages,
        "current_outline": current_outline,
        "source_sample": source_sample,
        "model": model,
        "traces": traces,
    })
    return result["outline"], result["traces"]
