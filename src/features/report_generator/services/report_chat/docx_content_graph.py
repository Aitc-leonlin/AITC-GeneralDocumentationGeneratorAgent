"""DOCX 內容來源分流：metadata 命中讀 JSON，否則依大綱由 LLM 撰寫。"""

import json
import logging
import os
from typing import Callable, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from src.features.report_generator.services.domain_report_service import ReportLLMTrace

from .json_evidence import (
    JsonEvidence, SectionAnswer, draft_sections_from_json, evidence_from_samples,
)
from .llm import _invoke_report_structured
from .markdown_tables import TABLE_FORMAT_FEW_SHOT
from .question_agent import list_document_samples, read_document_sample
from .sample_matcher import candidate_document_type_ids, match_document_type_sample
from .samples import DocumentSampleMetadata, DocumentTypeSample
from .schemas import (
    GeneralDocumentOutline, PurposeDocumentOutline, ReportChatMessage,
    ReportSampleSelection, ReportToolUsage, required_source_satisfied,
)


logger = logging.getLogger(__name__)


class OutlineSectionDraft(BaseModel):
    sectionIndex: int = Field(ge=1)
    paragraphs: list[str] = Field(min_length=1, max_length=8)


class OutlineDocumentDraft(BaseModel):
    sections: list[OutlineSectionDraft] = Field(min_length=1)


class GeneratedOutputItem(BaseModel):
    label: str = Field(min_length=1, max_length=150)
    sectionIndex: int = Field(ge=1)
    excerpt: str = Field(min_length=1, max_length=200)


class GeneratedOutputReview(BaseModel):
    items: list[GeneratedOutputItem] = Field(default_factory=list)
    comparable: bool
    reason: str = Field(min_length=1, max_length=500)


class DocxContentState(TypedDict, total=False):
    outline: GeneralDocumentOutline | PurposeDocumentOutline
    messages: list[ReportChatMessage]
    classified_document_type_id: str | None
    source_mode: Literal["default_json", "user_data"] | None
    candidate_ids: list[str]
    metadata: list[DocumentSampleMetadata]
    sample: DocumentTypeSample | None
    sample_id: str | None
    sample_ids: list[str]
    samples: list[tuple[str, DocumentTypeSample]]
    sample_selection: ReportSampleSelection | None
    lookup_reason: str
    mode: Literal["json", "outline_llm", "user_data"]
    evidence: JsonEvidence | None
    answers: list[SectionAnswer]
    traces: list[ReportLLMTrace]
    tool_usages: list[ReportToolUsage]
    progress_callback: Callable[[int, str], None] | None
    coverage_feedback: str
    coverage_reviews: int
    coverage_valid: bool


def _list_metadata(state: DocxContentState) -> DocxContentState:
    candidate_ids = candidate_document_type_ids(
        state["outline"], state.get("classified_document_type_id"),
    )
    if not candidate_ids:
        return {"candidate_ids": [], "metadata": [], "lookup_reason": "大綱沒有可查詢的 D 類型；未呼叫案例 Tool。"}
    callback = state.get("progress_callback")
    if callback:
        callback(15, "查詢候選測試案例清單")
    request = {"document_type_ids": candidate_ids}
    status: Literal["success", "error"] = "success"
    try:
        response = list_document_samples.invoke(request)
        metadata = [DocumentSampleMetadata.model_validate(item) for item in json.loads(response)]
    except Exception as error:
        logger.exception("DOCX list_document_samples failed")
        status = "error"
        response = json.dumps({"error": str(error)}, ensure_ascii=False)
        metadata = []
    usage = ReportToolUsage(
        toolName="list_document_samples", documentTypeIds=candidate_ids,
        resultCount=len(metadata), status=status,
        requestJson=json.dumps(request, ensure_ascii=False), responseJson=response,
    )
    reason = (
        "案例清單查詢失敗；未執行案例判斷。" if status == "error"
        else "指定 D 類型沒有候選案例；未執行案例判斷。" if not metadata
        else ""
    )
    return {
        "candidate_ids": candidate_ids, "metadata": metadata,
        "tool_usages": [*state.get("tool_usages", []), usage],
        "lookup_reason": reason,
    }


def _metadata_route(state: DocxContentState) -> Literal["decide", "outline_llm"]:
    return "decide" if state.get("metadata") else "outline_llm"


def _decide_lookup(state: DocxContentState) -> DocxContentState:
    traces = list(state.get("traces", []))
    callback = state.get("progress_callback")
    if callback:
        callback(15, "比對測試案例與報告大綱")
    sample_id = match_document_type_sample(
        state["outline"], state.get("classified_document_type_id"),
        metadata=state["metadata"], traces=traces,
        operation="general_document.decide_sample_lookup",
    )
    if callback:
        callback(20, "完成測試案例比對")
    return {
        "sample_id": sample_id,
        "sample_ids": [sample_id] if sample_id else [],
        "traces": traces,
        "lookup_reason": "已選取對大綱具有參考價值的案例。" if sample_id
        else "候選案例未通過相關性判斷，或判斷呼叫失敗；未讀取完整案例。",
    }


def _route_content(state: DocxContentState) -> Literal["json", "outline_llm"]:
    return "json" if state.get("sample_id") else "outline_llm"


def _read_sample(state: DocxContentState) -> DocxContentState:
    samples: list[tuple[str, DocumentTypeSample]] = []
    usages = list(state.get("tool_usages", []))
    for sample_id in state.get("sample_ids") or ([state["sample_id"]] if state.get("sample_id") else []):
        request = {"sample_id": sample_id}
        status: Literal["success", "error"] = "success"
        try:
            response = read_document_sample.invoke(request)
            samples.append((sample_id, DocumentTypeSample.model_validate_json(response)))
        except Exception as error:
            logger.exception("DOCX read_document_sample failed sample_id=%s", sample_id)
            status = "error"
            response = json.dumps({"error": str(error)}, ensure_ascii=False)
        usages.append(ReportToolUsage(
            toolName="read_document_sample", sampleId=sample_id, status=status,
            requestJson=json.dumps(request, ensure_ascii=False), responseJson=response,
        ))
    selection = state.get("sample_selection")
    if selection and samples:
        loaded_ids = {sample_id for sample_id, _ in samples}
        adopted = [item for item in selection.adoptedSampleIds if item in loaded_ids]
        if selection.mode == "adopt" and not selection.adoptedSampleIds:
            adopted = [selection.sampleId] if selection.sampleId in loaded_ids else []
        selection = selection.model_copy(update={
            "mode": "adopt" if adopted else "reference",
            "sampleId": adopted[0] if adopted else samples[0][0],
            "sampleIds": [sample_id for sample_id, _ in samples],
            "adoptedSampleIds": adopted,
            "outputCoverage": [
                item for item in selection.outputCoverage
                if item.sampleId in adopted
            ],
            "chosenSubjects": [sample.subject for sample_id, sample in samples if sample_id in adopted],
            "chosenSubject": "、".join(
                sample.subject for sample_id, sample in samples if sample_id in adopted
            )[:150],
        })
    return {
        "sample": samples[0][1] if samples else None,
        "samples": samples, "sample_selection": selection,
        "tool_usages": usages,
        "lookup_reason": f"已讀取 {len(samples)} 份完整案例。" if samples else "完整案例讀取失敗；改由大綱撰寫。",
    }


def _sample_route(state: DocxContentState) -> Literal["json", "outline_llm"]:
    selection = state.get("sample_selection")
    if selection and not required_source_satisfied(selection):
        return "outline_llm"
    return "json" if state.get("samples") else "outline_llm"


def _start_route(state: DocxContentState) -> Literal["read", "list", "outline_llm", "user_data"]:
    if state.get("source_mode") == "user_data":
        return "user_data"
    selection = state.get("sample_selection")
    if selection:
        if selection.mode != "none" and (selection.sampleIds or selection.sampleId):
            return "read"
        return "outline_llm"
    return "list"


def _draft_from_json(state: DocxContentState) -> DocxContentState:
    samples = state.get("samples") or []
    if not samples:
        raise RuntimeError("案例 Tool 未回傳 JSON 案例")
    evidence = evidence_from_samples(samples)
    selection = state.get("sample_selection")
    use_mode: Literal["adopt", "reference"] = (
        "adopt" if selection and selection.mode == "adopt" else "reference"
    )
    traces = list(state.get("traces", []))
    callback = state.get("progress_callback") if not state.get("coverage_reviews") else None
    return {
        "mode": "json",
        "evidence": evidence,
        "answers": draft_sections_from_json(
            state["outline"], evidence, state["messages"], traces=traces,
            use_mode=use_mode, sample_selection=selection,
            progress_callback=callback,
            coverage_feedback=state.get("coverage_feedback", ""),
        ),
        "traces": traces,
    }


def _draft_without_json(state: DocxContentState, *, user_data_only: bool) -> DocxContentState:
    """依大綱撰寫章節；使用者資料模式只根據使用者實際提供的內容。"""
    outline = state["outline"]
    sample_selection = state.get("sample_selection")
    if sample_selection and sample_selection.sourceRequirement == "required" and (
        sample_selection.requiredSource in ("case", "external")
        or (sample_selection.requiredSource == "any" and not sample_selection.sourceProvided)
        or (sample_selection.requiredSource == "user_data" and not sample_selection.sourceProvided)
    ):
        raise ValueError("必要參考資料未取得或讀取失敗，請提供可用資料後再產生 DOCX")
    from src.features.chatbot.core.providers.chat_openAI_provider import chat_model
    outline_input = {
        "title": outline.title,
        "subject": outline.subject,
        "period": outline.period,
        "objective": outline.objective,
        "sections": [
            {
                "sectionIndex": index,
                "heading": section.heading,
                "focus": section.focus,
                "contents": [
                    {"name": item.name, "description": item.description}
                    for item in section.contents
                ],
            }
            for index, section in enumerate(outline.sections, start=1)
        ],
    }
    user_requests = [
        message.content for message in state["messages"] if message.role == "user"
    ]
    source_messages = user_requests if user_data_only else user_requests[-15:]
    if user_data_only and sum(len(message) for message in source_messages) > 40000:
        raise ValueError("此對話的使用者資料超過本次 DOCX 撰寫可處理的長度，請在新對話提供精簡資料後重試")
    selection_context = (
        json.dumps(sample_selection.model_dump(include={
            "outputMode", "requestedCount", "comparisonSubjects",
            "sourceRequirement", "requiredSource", "sourceProvided",
        }), ensure_ascii=False)
        if sample_selection else "未指定"
    )
    traces = list(state.get("traces", []))
    callback = state.get("progress_callback") if not state.get("coverage_reviews") else None
    if callback:
        callback(25, "依使用者資料撰寫報告章節" if user_data_only else "依大綱撰寫報告章節")
    if os.getenv("LLM_PROVIDER", "openai").strip().lower() == "local":
        table_instruction = (
            "不要產生 Markdown 表格或其他表格格式；即使大綱列出比較矩陣或數據表格，"
            "也請改用一般段落或條列清單逐項說明。"
        )
        table_example = ""
    else:
        table_instruction = "如需表格，使用完整 Markdown 表格，放在同一個 paragraphs 項目內。"
        table_example = "" if user_data_only else f"{TABLE_FORMAT_FEW_SHOT}\n"
    if user_data_only:
        source_guidance = (
            "本次來源模式為 user_data。只使用使用者訊息中實際提供的資料及明確條件，"
            "可以整理、改寫和組織章節，但不得使用預設 JSON、外部資料或通用知識"
            "補出未提供的個案事實、數值、地點、人物、事件或結論。"
            "使用者的問題與指令是撰寫要求，不代表其中描述的事件已獲證實。"
            "大綱是規劃，不能將大綱中的待提供內容當成已提供的資料。"
            "當某個章節缺乏所需資料時，寫明目前資料可確認的範圍與無法判定的部分；"
            "若完全沒有資料可支撐該章，明確說明缺少哪類資料及因此無法完成的內容。"
            "仍須提供可直接放入文件的段落，不要輸出空白或『待補』佔位語。"
        )
    else:
        source_guidance = (
            "本次沒有可用的完整案例；請根據大綱、使用者明確需求與通用知識撰寫各章內文。"
            "若缺少特定數據或個案資料，改寫成適用的說明、操作方法、判斷準則或"
            "可執行的建議；不得捏造數值、已發生的事實、檢驗結果、引文、法規條文"
            "或已查閱的來源。必要時明確說明內容為一般性建議或示例。"
        )
    draft = _invoke_report_structured(
        model=chat_model,
        schema=OutlineDocumentDraft,
        operation="general_document.draft_from_user_data" if user_data_only else "general_document.draft_from_outline",
        traces=traces,
        prompt=(
            "你是繁體中文 DOCX 文件撰稿者。"
            f"{source_guidance}"
            "不要讀取、引用、猜測或提及任何預設 JSON 案例、案例標題或案例事實。"
            "大綱的主題、目的與各章重點優先；每章要有可直接放入 DOCX 的實質內容，"
            "不要重複章節標題，也不要輸出「待補」、空白佔位語或要求讀者另行補寫。"
            "若 sourceRequirement=required 且 sourceProvided=true，個案事實只依"
            "使用者實際提供的資料撰寫；資料不足的具體結論須說明無法判定。"
            "若輸出需求為 multiple，提供要求數量的不同選項；若為 compare，"
            "按相同面向比較指定對象，資料不足的具體差異只說明比較方法。"
            "若提供全文件輸出缺漏回饋，請在相關章節補足；不得因此捏造"
            "使用者資料中不存在的個案事實。"
            f"{table_instruction}"
            "sections 必須依大綱順序，每章恰好一筆；sectionIndex 必須等於大綱序號。"
            "每章提供 1 至 8 段可直接呈現的文字，不要包在程式碼區塊中。\n"
            f"{table_example}"
            f"大綱：{json.dumps(outline_input, ensure_ascii=False)}\n"
            f"輸出需求：{selection_context}\n"
            f"全文件輸出缺漏回饋：{state.get('coverage_feedback') or '無'}\n"
            f"使用者訊息（僅這些訊息可能包含使用者資料）：{json.dumps(source_messages, ensure_ascii=False)}"
        ),
    )
    expected_indices = list(range(1, len(outline.sections) + 1))
    if [section.sectionIndex for section in draft.sections] != expected_indices:
        raise RuntimeError("LLM 回傳的章節數量或順序與大綱不一致")
    if any(
        "待補" in paragraph or not paragraph.strip()
        for section in draft.sections for paragraph in section.paragraphs
    ):
        raise RuntimeError("LLM 回傳了空白或待補內容，無法產生完整 DOCX")
    if callback:
        callback(70, "整理章節內容")
    answers: list[SectionAnswer] = []
    for section_draft in draft.sections:
        answers.append(SectionAnswer(paragraphs=section_draft.paragraphs))
        if callback:
            callback(70 + 10 * len(answers) // len(draft.sections), f"已整理 {len(answers)}/{len(draft.sections)} 個章節")
    return {
        "mode": "user_data" if user_data_only else "outline_llm",
        "evidence": None,
        "traces": traces,
        "answers": answers,
        "lookup_reason": "只使用使用者資料；未呼叫案例 Tool。" if user_data_only else state.get("lookup_reason", ""),
    }


def _draft_from_outline(state: DocxContentState) -> DocxContentState:
    return _draft_without_json(state, user_data_only=False)


def _draft_from_user_data(state: DocxContentState) -> DocxContentState:
    return _draft_without_json(state, user_data_only=True)


def _review_output_coverage(state: DocxContentState) -> DocxContentState:
    selection = state.get("sample_selection")
    if not selection or selection.outputMode == "single":
        return {"coverage_valid": True}
    callback = state.get("progress_callback")
    if callback and not state.get("coverage_reviews"):
        callback(81, "核對選項與比較對象")
    answers = state["answers"]
    traces = list(state.get("traces", []))
    from src.features.chatbot.core.providers.chat_openAI_provider import chat_model

    review = _invoke_report_structured(
        model=chat_model, schema=GeneratedOutputReview,
        operation="general_document.review_generated_output_coverage",
        traces=traces,
        prompt=(
            "你是 DOCX 章節成品的輸出覆蓋核對器，只根據下列實際章節內文判斷。"
            "items 逐一列出已在內文中獲得實質說明的不同選項或比較對象；"
            "每項附上所在章節序號及一段從該章某一段內文連續、逐字擷取的 excerpt，"
            "不要加省略號或原文沒有的引號。"
            "只有標題、清單名稱、來源資料章節或一句『稍後比較』，都不算實質說明。"
            "多選項必須是不同方案，不能把同一方案的步驟或優缺點拆成多項。"
            "比較需求的 label 請使用 comparisonSubjects 中的原字串；"
            "若有未指定的比較對象，可以用內文中的名稱。"
            "comparable=true 只有在內文用共同面向討論不同對象，或明確說明"
            "缺少資料時應如何按共同面向比較時才成立。"
            "使用者資料不足時，對某對象具體說明可確認範圍與無法判定的地方，"
            "仍算有處理該對象；單純重複名稱或虛構結論不算。"
            "可跨章節辨識選項；不要要求每章都包含所有選項。"
            "reason 簡述缺少哪些選項、對象或共同比較面向；全部具備時說明已涵蓋。\n"
            f"輸出需求：{selection.model_dump(include={'outputMode', 'requestedCount', 'comparisonSubjects'}, mode='json')}\n"
            f"章節內文：{json.dumps([{'sectionIndex': index, 'heading': section.heading, 'paragraphs': answer.paragraphs} for index, (section, answer) in enumerate(zip(state['outline'].sections, answers), start=1)], ensure_ascii=False)}"
        ),
    )
    labels: set[str] = set()
    for item in review.items:
        if item.sectionIndex > len(answers):
            continue
        if item.excerpt.strip() not in "\n".join(answers[item.sectionIndex - 1].paragraphs):
            continue
        labels.add(item.label.strip().casefold())
    required_subjects = {
        item.strip().casefold() for item in selection.comparisonSubjects if item.strip()
    }
    complete = (
        len(labels) >= selection.requestedCount
        and (selection.outputMode != "compare" or (
            review.comparable and required_subjects.issubset(labels)
        ))
    )
    if complete:
        return {"coverage_valid": True, "traces": traces}
    missing_subjects = [
        item for item in selection.comparisonSubjects
        if item.strip().casefold() not in labels
    ]
    feedback = (
        f"目前確認 {len(labels)}/{selection.requestedCount} 個實質選項或對象；"
        f"未涵蓋的指定對象：{'、'.join(missing_subjects) if missing_subjects else '無'}；"
        f"共同面向比較：{'已具備' if review.comparable else '尚不足'}；"
        f"核對說明：{review.reason}"
    )
    if state.get("coverage_reviews", 0) >= 1:
        raise ValueError(f"DOCX 章節未涵蓋要求的輸出項目：{feedback}")
    if callback:
        callback(82, "補足章節缺漏並重新核對")
    return {
        "coverage_valid": False,
        "coverage_feedback": feedback,
        "coverage_reviews": 1,
        "traces": traces,
    }


def _coverage_route(state: DocxContentState) -> Literal["end", "json", "outline_llm", "user_data"]:
    if state.get("coverage_valid"):
        return "end"
    mode = state["mode"]
    return "json" if mode == "json" else "user_data" if mode == "user_data" else "outline_llm"


_builder = StateGraph(DocxContentState)
_builder.add_node("list_document_samples", _list_metadata)
_builder.add_node("decide_sample_lookup", _decide_lookup)
_builder.add_node("read_document_sample", _read_sample)
_builder.add_node("draft_from_json", _draft_from_json)
_builder.add_node("draft_from_outline", _draft_from_outline)
_builder.add_node("draft_from_user_data", _draft_from_user_data)
_builder.add_node("review_output_coverage", _review_output_coverage)
_builder.add_conditional_edges(START, _start_route, {
    "read": "read_document_sample", "list": "list_document_samples",
    "outline_llm": "draft_from_outline", "user_data": "draft_from_user_data",
})
_builder.add_conditional_edges("list_document_samples", _metadata_route, {
    "decide": "decide_sample_lookup",
    "outline_llm": "draft_from_outline",
})
_builder.add_conditional_edges("decide_sample_lookup", _route_content, {
    "json": "read_document_sample",
    "outline_llm": "draft_from_outline",
})
_builder.add_conditional_edges("read_document_sample", _sample_route, {
    "json": "draft_from_json",
    "outline_llm": "draft_from_outline",
})
_builder.add_edge("draft_from_json", "review_output_coverage")
_builder.add_edge("draft_from_outline", "review_output_coverage")
_builder.add_edge("draft_from_user_data", "review_output_coverage")
_builder.add_conditional_edges("review_output_coverage", _coverage_route, {
    "end": END,
    "json": "draft_from_json",
    "outline_llm": "draft_from_outline",
    "user_data": "draft_from_user_data",
})
DOCX_CONTENT_GRAPH = _builder.compile()


def build_docx_content(
    outline: GeneralDocumentOutline | PurposeDocumentOutline,
    messages: list[ReportChatMessage],
    classified_document_type_id: str | None,
    *,
    sample_selection: ReportSampleSelection | None = None,
    source_mode: Literal["default_json", "user_data"] | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> DocxContentState:
    return DOCX_CONTENT_GRAPH.invoke({
        "outline": outline,
        "messages": messages,
        "classified_document_type_id": classified_document_type_id,
        "source_mode": source_mode,
        "sample_selection": sample_selection,
        "sample_id": sample_selection.sampleId if sample_selection else None,
        "sample_ids": (
            sample_selection.sampleIds or ([sample_selection.sampleId] if sample_selection.sampleId else [])
            if sample_selection else []
        ),
        "traces": [],
        "tool_usages": [],
        "progress_callback": progress_callback,
    })
