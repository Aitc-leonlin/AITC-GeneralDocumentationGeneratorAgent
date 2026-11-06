"""以使用者用途為主、範本 metadata 為參考的統一大綱流程。"""

import json
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from src.features.report_generator.services.domain_report_service import ReportLLMTrace
from .catalog import load_content_type_templates, load_document_type_templates, load_section_type_templates
from .llm import _invoke_report_structured
from .schemas import (
    DocumentPurpose, GeneralOutlineContent, PendingClarification,
    PurposeDocumentOutline, PurposeDocumentPlan, PurposeOutlineSection,
    PurposePlannedSection, ReportChatMessage, ReportOutlineRequest, ReportQuestionPlan,
    ReportSampleSelection,
)


class ReadinessDecision(BaseModel):
    ready: bool
    reason: str = Field(min_length=1, max_length=500)
    missingDecision: str = Field(default="", max_length=300)
    question: str = Field(default="", max_length=1000)


def assess_purpose_readiness(
    request: ReportOutlineRequest,
    question_plan: ReportQuestionPlan,
    purposes: list[DocumentPurpose],
    model: Any,
    traces: list[ReportLLMTrace],
) -> tuple[ReadinessDecision, list[ReportLLMTrace]]:
    """只判斷能否規劃；缺少數值、日期或資料不必阻止大綱。"""
    recorded = list(traces)
    decision = _invoke_report_structured(
        model=model,
        schema=ReadinessDecision,
        operation="general_document.assess_readiness",
        traces=recorded,
        prompt=(
            "你是文件需求追問判斷器。請根據完整對話、目前用途及待確認問題，判斷資訊是否足夠"
            "規劃下一份大綱。只有文件用途、範圍、要整合或只做其中一種等決策不明確，"
            "而且不同選擇會實質改變大綱時，才回傳 ready=false。"
            "缺少數值、資料來源、對象或期間可在大綱標待提供，不要因此追問。"
            "若使用者已清楚要求複合文件，直接繼續；若已回答前次追問，不要重問。"
            "若使用者要求開放式推薦、任選菜色或地點等，這是授權系統選具體方案；"
            "不得僅因未指定菜色、目的地或其他可選主題而追問。"
            "ready=false 時只問一個最關鍵、具體且可回答的問題，並填 missingDecision；"
            "ready=true 時 question 與 missingDecision 留空。\n"
            f"分類結果：{question_plan.model_dump_json()}\n"
            f"實際規劃用途：{json.dumps([item.model_dump() for item in purposes], ensure_ascii=False)}\n"
            f"待確認：{request.pendingClarification.model_dump_json() if request.pendingClarification else 'null'}\n"
            f"目前計畫：{request.currentPurposePlan.model_dump_json() if request.currentPurposePlan else 'null'}\n"
            f"對話：{json.dumps([message.model_dump() for message in request.messages], ensure_ascii=False)}"
        ),
    )
    if not purposes:
        decision = ReadinessDecision(
            ready=False, reason="尚未辨識文件用途",
            missingDecision="文件用途", question=decision.question or "請說明這份文件要達成什麼目的？",
        )
    if not decision.ready and not decision.question.strip():
        decision.question = "請確認這次要整合哪些用途，以及希望完成一份文件還是先處理其中一種？"
    if not decision.ready and not decision.missingDecision.strip():
        decision.missingDecision = "文件範圍"
    return decision, recorded


def pending_from_decision(
    decision: ReadinessDecision, purposes: list[DocumentPurpose],
) -> PendingClarification:
    return PendingClarification(
        question=decision.question, missingDecision=decision.missingDecision,
        purposes=purposes,
    )


class SuggestedSection(BaseModel):
    heading: str = Field(min_length=1, max_length=100)
    focusHint: str = Field(min_length=1, max_length=500)
    referenceSectionIds: list[str] = Field(default_factory=list)
    contentTypeIds: list[str] = Field(default_factory=list)


class PurposeSectionsDraft(BaseModel):
    sections: list[SuggestedSection] = Field(min_length=1)


class MergedSectionDraft(SuggestedSection):
    purposeIds: list[str] = Field(min_length=1)


class MergedSectionsDraft(BaseModel):
    sections: list[MergedSectionDraft] = Field(min_length=1)


class OutlineFocusDraft(BaseModel):
    sectionKey: str
    focus: str = Field(min_length=1, max_length=500)


class UnifiedOutlineDraft(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    subject: str = Field(min_length=1, max_length=150)
    period: str = Field(min_length=1, max_length=100)
    objective: str = Field(min_length=1, max_length=800)
    sourcePlan: str = Field(min_length=1, max_length=1000)
    sectionFocuses: list[OutlineFocusDraft] = Field(min_length=1)


MODE_GUIDANCE = {
    "analysis": "安排分析依據、分析過程、結果與限制。",
    "procedure": "安排前提、步驟、驗證方式與注意事項。",
    "proposal": "安排現況、選項、建議、執行方式與風險。",
    "explanation": "安排背景、核心概念、例子與適用限制。",
    "mixed": "依用途選擇合適章節，不套固定文件結構。",
}


class PurposeWorkflowState(TypedDict, total=False):
    purposes: list[DocumentPurpose]
    messages: list[ReportChatMessage]
    current_plan: PurposeDocumentPlan | None
    current_outline: PurposeDocumentOutline | None
    source_mode: Literal["default_json", "user_data"] | None
    sample_selection: ReportSampleSelection | None
    model: Any
    traces: list[ReportLLMTrace]
    strategy_guidance: dict[str, str]
    per_purpose: dict[str, list[SuggestedSection]]
    plan: PurposeDocumentPlan
    outline: PurposeDocumentOutline


def _route_purpose_strategy(state: PurposeWorkflowState) -> PurposeWorkflowState:
    """按每個用途選擇規劃策略，供後續用途節點逐一執行。"""
    return {"strategy_guidance": {
        purpose.purposeId: MODE_GUIDANCE[purpose.planningMode]
        for purpose in state["purposes"]
    }}


def _plan_each_purpose(state: PurposeWorkflowState) -> PurposeWorkflowState:
    templates = load_document_type_templates()
    sections = load_section_type_templates()
    contents = load_content_type_templates()
    traces = list(state["traces"])
    drafts: dict[str, list[SuggestedSection]] = {}
    for purpose in state["purposes"]:
        references = [templates[item] for item in purpose.referenceTemplateIds if item in templates]
        draft = _invoke_report_structured(
            model=state["model"], schema=PurposeSectionsDraft,
            operation=f"general_document.plan_purpose.{purpose.purposeId}", traces=traces,
            prompt=(
                "你是文件用途規劃器。只為這個用途提出需要的章節。"
                "範本與 S/C 目錄是參考，不是必選或限制；允許自訂章節標題。"
                "referenceSectionIds 與 contentTypeIds 只填確實相關的目錄 ID，可留空。"
                "不要為了範本的必要章節硬加入不需要的內容。"
                "先規劃大綱，不撰寫內文或捏造資料。"
                "若案例已採用為具體方案，章節應圍繞選定主題；"
                "若案例僅供參考，仍以使用者要求的主題為準。"
                "若 outputMode=multiple，須規劃要求數量的不同選項，案例不足時"
                "仍保留其餘選項的位置；若 outputMode=compare，須涵蓋所有指定"
                "比較對象及共同的比較面向，不得把兩個對象合併成一個。"
                f"此用途的規劃方式：{state['strategy_guidance'][purpose.purposeId]}\n"
                f"用途：{purpose.model_dump_json()}\n"
                f"參考文件範本：{json.dumps([item.model_dump(exclude={'suggestedSections'}) for item in references], ensure_ascii=False)}\n"
                f"章節目錄：{json.dumps([{'id': item.id, 'name': item.name, 'purpose': item.purpose} for item in sections.values()], ensure_ascii=False)}\n"
                f"內容種類目錄：{json.dumps([{'id': item.id, 'name': item.name, 'description': item.description} for item in contents.values()], ensure_ascii=False)}\n"
                f"目前計畫：{state['current_plan'].model_dump_json() if state.get('current_plan') else 'null'}\n"
                f"來源模式：{state.get('source_mode') or '尚未指定'}。\n"
                f"案例選擇：{state['sample_selection'].model_dump_json() if state.get('sample_selection') else 'null'}\n"
                f"對話：{json.dumps([message.model_dump() for message in state['messages']], ensure_ascii=False)}"
            ),
        )
        drafts[purpose.purposeId] = draft.sections
    return {"per_purpose": drafts, "traces": traces}


def _merge_purpose_sections(state: PurposeWorkflowState) -> PurposeWorkflowState:
    per_purpose = state["per_purpose"]
    traces = list(state["traces"])
    if len(state["purposes"]) == 1:
        purpose_id = state["purposes"][0].purposeId
        candidates = [MergedSectionDraft(**section.model_dump(), purposeIds=[purpose_id])
                      for section in per_purpose[purpose_id]]
    else:
        merged = _invoke_report_structured(
            model=state["model"], schema=MergedSectionsDraft,
            operation="general_document.merge_purposes", traces=traces,
            prompt=(
                "你是整份文件的章節整合編輯。把各用途的章節整理成一份有順序的大綱。"
                "合併重複的背景、摘要、結論與來源章節，保留每個用途的實質內容。"
                "purposeIds 必須使用已給的 ID，所有用途至少出現在一個章節；"
                "referenceSectionIds、contentTypeIds 只是可選參考。"
                "不要把多份範本的章節機械串接，也不要寫完整內文。\n"
                f"用途：{json.dumps([item.model_dump() for item in state['purposes']], ensure_ascii=False)}\n"
                f"各用途草案：{json.dumps({key: [item.model_dump() for item in value] for key, value in per_purpose.items()}, ensure_ascii=False)}\n"
                f"目前計畫：{state['current_plan'].model_dump_json() if state.get('current_plan') else 'null'}\n"
                f"對話：{json.dumps([message.model_dump() for message in state['messages']], ensure_ascii=False)}"
            ),
        )
        candidates = merged.sections
    known_purposes = {item.purposeId for item in state["purposes"]}
    known_sections = set(load_section_type_templates())
    known_contents = set(load_content_type_templates())
    result: list[PurposePlannedSection] = []
    seen_headings: set[str] = set()
    for candidate in candidates:
        heading_key = candidate.heading.strip().casefold()
        if heading_key in seen_headings:
            continue
        assigned = list(dict.fromkeys(item for item in candidate.purposeIds if item in known_purposes))
        if not assigned:
            continue
        seen_headings.add(heading_key)
        result.append(PurposePlannedSection(
            sectionKey=f"section-{len(result) + 1}", heading=candidate.heading,
            focusHint=candidate.focusHint, purposeIds=assigned,
            referenceSectionIds=list(dict.fromkeys(item for item in candidate.referenceSectionIds if item in known_sections)),
            contentTypeIds=list(dict.fromkeys(item for item in candidate.contentTypeIds if item in known_contents)),
        ))
    covered = {item for section in result for item in section.purposeIds}
    for purpose in state["purposes"]:
        if purpose.purposeId in covered:
            continue
        fallback = per_purpose[purpose.purposeId][0]
        result.append(PurposePlannedSection(
            sectionKey=f"section-{len(result) + 1}", heading=fallback.heading,
            focusHint=fallback.focusHint, purposeIds=[purpose.purposeId],
            referenceSectionIds=[item for item in fallback.referenceSectionIds if item in known_sections],
            contentTypeIds=[item for item in fallback.contentTypeIds if item in known_contents],
        ))
    return {"plan": PurposeDocumentPlan(purposes=state["purposes"], sections=result), "traces": traces}


def _draft_unified_outline(state: PurposeWorkflowState) -> PurposeWorkflowState:
    plan = state["plan"]
    traces = list(state["traces"])
    draft = _invoke_report_structured(
        model=state["model"], schema=UnifiedOutlineDraft,
        operation="general_document.draft_unified_outline", traces=traces,
        prompt=(
            "你是統一文件大綱編輯。針對已整合的計畫產出一份大綱。"
            "sectionFocuses 每個 sectionKey 都要有一筆，不能新增章節；"
            "只寫各章將處理的重點，不寫完整內文、結論或虛構事實。"
            "使用者未提供的對象、期間填待提供。"
            "若案例選擇 mode=adopt，title、subject、objective 與章節重點應明確呈現"
            "該案例作為本文件選定的示例主題；使用者未指定的日期、金額、人數或偏好"
            "不可因案例而變成使用者的真實條件。"
            "若 mode=reference，只在來源規劃說明其參考用途，不改寫文件核心主題。"
            "sourcePlan 要說明所選案例為參考／測試資料，具體事實仍須核對；"
            "若沒有選案例，說明依大綱與使用者需求撰寫。"
            "若 sourceRequirement=required，sourcePlan 須指出本文件依據哪種已提供資料；"
            "使用者貼上的內容不可說成系統已獨立查證。"
            "outputMode=multiple 時，大綱須清楚呈現 requestedCount 個選項；"
            "outputMode=compare 時，須明確列出 comparisonSubjects 中每個對象"
            "及共同比較面向，即使只有部分案例可用也要保留所有對象；"
            "outputCoverage 指出每個輸出項目由哪份案例支援，不能互換。"
            "若來源模式為 user_data，只使用使用者資料。"
            "延續目前大綱中未被最新訊息更改的要求。\n"
            f"統一計畫：{plan.model_dump_json()}\n"
            f"目前大綱：{state['current_outline'].model_dump_json() if state.get('current_outline') else 'null'}\n"
            f"來源模式：{state.get('source_mode') or '尚未指定'}。\n"
            f"案例選擇：{state['sample_selection'].model_dump_json() if state.get('sample_selection') else 'null'}\n"
            f"對話：{json.dumps([message.model_dump() for message in state['messages']], ensure_ascii=False)}"
        ),
    )
    focuses = {item.sectionKey: item.focus for item in draft.sectionFocuses}
    contents = load_content_type_templates()
    sections = [PurposeOutlineSection(
        **section.model_dump(), focus=focuses.get(section.sectionKey, section.focusHint),
        contents=[GeneralOutlineContent(
            contentTypeId=item, name=contents[item].name, description=contents[item].description,
        ) for item in section.contentTypeIds],
    ) for section in plan.sections]
    selection = state.get("sample_selection")
    chosen_subject = ""
    if selection:
        if selection.outputMode == "single" and selection.mode == "adopt":
            chosen_subject = selection.chosenSubject
        elif selection.outputMode == "compare" and selection.comparisonSubjects:
            chosen_subject = "、".join(selection.comparisonSubjects)[:150]
        elif (
            selection.outputMode == "multiple"
            and len(selection.chosenSubjects) == selection.requestedCount
        ):
            chosen_subject = "、".join(selection.chosenSubjects)[:150]
    title = draft.title
    if chosen_subject and selection and selection.outputMode == "single" and chosen_subject not in title:
        title = f"{chosen_subject}｜{title}"[:150]
    return {"outline": PurposeDocumentOutline(
        title=title, subject=chosen_subject or draft.subject, period=draft.period,
        objective=draft.objective, purposes=plan.purposes, sections=sections,
        sourcePlan=draft.sourcePlan,
    ), "traces": traces}


_builder = StateGraph(PurposeWorkflowState)
_builder.add_node("route_purpose_strategy", _route_purpose_strategy)
_builder.add_node("plan_each_purpose", _plan_each_purpose)
_builder.add_node("merge_purpose_sections", _merge_purpose_sections)
_builder.add_node("draft_unified_outline", _draft_unified_outline)
_builder.add_edge(START, "route_purpose_strategy")
_builder.add_edge("route_purpose_strategy", "plan_each_purpose")
_builder.add_edge("plan_each_purpose", "merge_purpose_sections")
_builder.add_edge("merge_purpose_sections", "draft_unified_outline")
_builder.add_edge("draft_unified_outline", END)
PURPOSE_WORKFLOW_GRAPH = _builder.compile()


def plan_purpose_document(
    *, purposes: list[DocumentPurpose], messages: list[ReportChatMessage], model: Any,
    traces: list[ReportLLMTrace], current_plan: PurposeDocumentPlan | None = None,
    current_outline: PurposeDocumentOutline | None = None,
    source_mode: Literal["default_json", "user_data"] | None = None,
    sample_selection: ReportSampleSelection | None = None,
) -> tuple[PurposeDocumentPlan, PurposeDocumentOutline, list[ReportLLMTrace]]:
    result = PURPOSE_WORKFLOW_GRAPH.invoke({
        "purposes": purposes, "messages": messages, "model": model, "traces": traces,
        "current_plan": current_plan, "current_outline": current_outline,
        "source_mode": source_mode,
        "sample_selection": sample_selection,
    })
    return result["plan"], result["outline"], result["traces"]
