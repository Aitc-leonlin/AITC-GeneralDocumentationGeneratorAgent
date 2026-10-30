"""Read one document type's JSON evidence and draft cited section text."""

import json
from dataclasses import dataclass

from pydantic import BaseModel, Field

from .llm import _invoke_report_structured
from .samples import DocumentTypeSample, load_document_type_sample
from .schemas import GeneralDocumentOutline, PurposeDocumentOutline, ReportChatMessage


@dataclass(frozen=True)
class EvidenceItem:
    id: str
    field: str
    text: str


@dataclass(frozen=True)
class JsonEvidence:
    sample: DocumentTypeSample
    items: tuple[EvidenceItem, ...]


class SectionAnswer(BaseModel):
    paragraphs: list[str] = Field(min_length=1, max_length=4)
    evidenceIds: list[str] = Field(default_factory=list)


def retrieve_json_evidence(sample_id: str) -> JsonEvidence:
    """The storage boundary: replace this function when evidence moves to a DB."""
    sample = load_document_type_sample(sample_id)
    items = [EvidenceItem("CTX", "context", sample.context)]
    items.extend(
        EvidenceItem(f"F{index}", f"facts[{index - 1}]", f"{fact.label}：{fact.value}")
        for index, fact in enumerate(sample.facts, start=1)
    )
    items.extend(
        EvidenceItem(f"M{index}", f"sourceMaterials[{index - 1}]", f"{source.title}：{source.content}")
        for index, source in enumerate(sample.sourceMaterials, start=1)
    )
    items.extend(
        EvidenceItem(f"A{index}", f"assumptions[{index - 1}]", assumption)
        for index, assumption in enumerate(sample.assumptions, start=1)
    )
    return JsonEvidence(sample=sample, items=tuple(items))


def draft_sections_from_json(
    outline: PurposeDocumentOutline | GeneralDocumentOutline,
    evidence: JsonEvidence,
    messages: list[ReportChatMessage],
) -> list[SectionAnswer]:
    """Generate each outlined section from the retrieved JSON, with evidence IDs."""
    from src.features.chatbot.core.providers.chat_openAI_provider import chat_model

    known_ids = {item.id for item in evidence.items}
    source = json.dumps(
        [{"id": item.id, "field": item.field, "text": item.text} for item in evidence.items],
        ensure_ascii=False,
    )
    user_requests = [message.content for message in messages if message.role == "user"]
    answers = []
    for section in outline.sections:
        answer = _invoke_report_structured(
            model=chat_model,
            schema=SectionAnswer,
            operation=f"general_document.json_answer.{section.heading}",
            traces=[],
            prompt=(
                "你正在撰寫繁體中文 DOCX 的單一章節。只可把下列虛構 JSON 案例當作事實來源，"
                "使用者需求只決定寫作方向，不可把需求中的未驗證敘述寫成事實。"
                "根據章節標題與重點挑選相關資料，不要把所有資料硬塞進每章。"
                "M 開頭資料只是模擬來源的描述，不代表已查閱真實文件，也不能推導其未列出的數字。"
                "不要捏造數值、比較、結論、法規、建議或真實來源。"
                "資訊不足的部分請明寫『待補』，不要臆測。"
                "所有案例事實都要明確以『虛構測試案例』表述；若文件對象或期間與案例不同，"
                "不得把案例事實說成文件對象的真實狀況。"
                "每段應是可直接放入文件的內文，不要重複章節標題。"
                "需要表格時請使用完整的 Markdown 表格語法（表頭、分隔列、資料列），"
                "放在同一個 paragraphs 項目內，不要包在程式碼區塊中。"
                "evidenceIds 只列實際支撐內文的 ID；若只能寫待補，回傳空陣列。\n"
                f"文件：{outline.title}；對象：{outline.subject}；期間：{outline.period}；目的：{outline.objective}\n"
                f"章節：{section.heading}\n重點：{section.focus}\n"
                f"預計內容：{json.dumps([item.name for item in section.contents], ensure_ascii=False)}\n"
                f"使用者需求：{json.dumps(user_requests[-15:], ensure_ascii=False)}\n"
                f"案例：{evidence.sample.title}；對象：{evidence.sample.subject}；期間：{evidence.sample.period}\n"
                f"來源資料：{source}\n"
            ),
        )
        if not set(answer.evidenceIds) <= known_ids:
            raise ValueError(f"章節「{section.heading}」引用了不存在的 JSON 資料 ID")
        if not answer.evidenceIds and not any("待補" in paragraph for paragraph in answer.paragraphs):
            answer = SectionAnswer(paragraphs=["本章所需資料尚未提供，待補。"])
        answers.append(answer)
    return answers
