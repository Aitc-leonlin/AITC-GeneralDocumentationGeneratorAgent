"""DOCX 內容來源分流：metadata 命中讀 JSON，否則依大綱由 LLM 撰寫。"""

import json
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from .json_evidence import (
    JsonEvidence, SectionAnswer, draft_sections_from_json, retrieve_json_evidence,
)
from .llm import _invoke_report_structured
from .sample_matcher import match_document_type_sample
from .schemas import GeneralDocumentOutline, PurposeDocumentOutline, ReportChatMessage


class OutlineSectionDraft(BaseModel):
    sectionIndex: int = Field(ge=1)
    paragraphs: list[str] = Field(min_length=1, max_length=4)


class OutlineDocumentDraft(BaseModel):
    sections: list[OutlineSectionDraft] = Field(min_length=1)


class DocxContentState(TypedDict, total=False):
    outline: GeneralDocumentOutline | PurposeDocumentOutline
    messages: list[ReportChatMessage]
    classified_document_type_id: str | None
    sample_id: str | None
    mode: Literal["json", "outline_llm"]
    evidence: JsonEvidence | None
    answers: list[SectionAnswer]


def _match_metadata(state: DocxContentState) -> DocxContentState:
    sample_id = match_document_type_sample(
        state["outline"], state.get("classified_document_type_id")
    )
    return {"sample_id": sample_id}


def _route_content(state: DocxContentState) -> Literal["json", "outline_llm"]:
    return "json" if state.get("sample_id") else "outline_llm"


def _draft_from_json(state: DocxContentState) -> DocxContentState:
    sample_id = state.get("sample_id")
    if not sample_id:
        raise RuntimeError("metadata 比對未選出 JSON 案例")
    evidence = retrieve_json_evidence(sample_id)
    return {
        "mode": "json",
        "evidence": evidence,
        "answers": draft_sections_from_json(
            state["outline"], evidence, state["messages"]
        ),
    }


def _draft_from_outline(state: DocxContentState) -> DocxContentState:
    """一次 LLM 呼叫產出整份大綱的章節內容，完全不取用案例 JSON。"""
    from src.features.chatbot.core.providers.chat_openAI_provider import chat_model

    outline = state["outline"]
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
    draft = _invoke_report_structured(
        model=chat_model,
        schema=OutlineDocumentDraft,
        operation="general_document.draft_from_outline",
        traces=[],
        prompt=(
            "你是繁體中文 DOCX 文件撰稿者。預設測試案例的 metadata 與這份大綱"
            "沒有足夠關聯；請只根據下列大綱、使用者明確需求與通用知識撰寫各章內文。"
            "不要讀取、引用、猜測或提及任何預設 JSON 案例、案例標題或案例事實。"
            "大綱的主題、目的與各章重點優先；每章要有可直接放入 DOCX 的實質內容，"
            "不要重複章節標題，也不要輸出「待補」、空白佔位語或要求讀者另行補寫。"
            "若缺少特定數據或個案資料，改寫成適用的說明、操作方法、判斷準則或"
            "可執行的建議；不得捏造數值、已發生的事實、檢驗結果、引文、法規條文"
            "或已查閱的來源。必要時明確說明內容為一般性建議或示例。"
            "如需表格，使用完整 Markdown 表格，放在同一個 paragraphs 項目內。"
            "sections 必須依大綱順序，每章恰好一筆；sectionIndex 必須等於大綱序號。"
            "每章提供 1 至 4 段可直接呈現的文字，不要包在程式碼區塊中。\n"
            f"大綱：{json.dumps(outline_input, ensure_ascii=False)}\n"
            f"使用者需求：{json.dumps(user_requests[-15:], ensure_ascii=False)}"
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
    return {
        "mode": "outline_llm",
        "evidence": None,
        "answers": [
            SectionAnswer(paragraphs=section.paragraphs)
            for section in draft.sections
        ],
    }


_builder = StateGraph(DocxContentState)
_builder.add_node("match_metadata", _match_metadata)
_builder.add_node("draft_from_json", _draft_from_json)
_builder.add_node("draft_from_outline", _draft_from_outline)
_builder.add_edge(START, "match_metadata")
_builder.add_conditional_edges("match_metadata", _route_content, {
    "json": "draft_from_json",
    "outline_llm": "draft_from_outline",
})
_builder.add_edge("draft_from_json", END)
_builder.add_edge("draft_from_outline", END)
DOCX_CONTENT_GRAPH = _builder.compile()


def build_docx_content(
    outline: GeneralDocumentOutline | PurposeDocumentOutline,
    messages: list[ReportChatMessage],
    classified_document_type_id: str | None,
) -> DocxContentState:
    return DOCX_CONTENT_GRAPH.invoke({
        "outline": outline,
        "messages": messages,
        "classified_document_type_id": classified_document_type_id,
    })
