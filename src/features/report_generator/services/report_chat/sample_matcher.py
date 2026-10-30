"""先用分類與案例 metadata 比對大綱，再決定是否讀取完整測試 JSON。"""

import json
import logging

from pydantic import BaseModel, Field

from .catalog import load_document_type_templates
from .llm import _invoke_report_structured
from .samples import load_document_type_sample_metadata
from .schemas import GeneralDocumentOutline, PurposeDocumentOutline

logger = logging.getLogger(__name__)
MIN_SAMPLE_CONFIDENCE = 0.8


class MetadataMatchScore(BaseModel):
    sampleId: str
    confidence: float = Field(ge=0, le=1)
    sameSubject: bool
    reason: str = Field(min_length=1, max_length=300)


class MetadataMatchResult(BaseModel):
    matches: list[MetadataMatchScore] = Field(default_factory=list)


def _candidate_ids(
    outline: GeneralDocumentOutline | PurposeDocumentOutline,
    classified_document_type_id: str | None,
) -> list[str]:
    """D 範本分類是候選資料的預篩；日後可換成 DB 的分類欄位查詢。"""
    templates = load_document_type_templates()
    if isinstance(outline, GeneralDocumentOutline):
        reference_ids = [outline.documentTypeId]
    else:
        reference_ids = [
            template_id
            for purpose in outline.purposes
            for template_id in purpose.referenceTemplateIds
        ]
        if not reference_ids and classified_document_type_id:
            reference_ids = [classified_document_type_id]
    categories = {
        templates[template_id].category
        for template_id in reference_ids
        if template_id in templates
    }
    return [
        template_id
        for template_id, template in templates.items()
        if template.category in categories
    ]


def match_document_type_sample(
    outline: GeneralDocumentOutline | PurposeDocumentOutline,
    classified_document_type_id: str | None = None,
) -> str | None:
    """回傳最相關且達門檻的案例 ID；無法確認時不使用虛構資料。"""
    outline_summary = {
        "title": outline.title,
        "subject": outline.subject,
        "objective": outline.objective,
        "sections": [
            {"heading": section.heading, "focus": section.focus}
            for section in outline.sections
        ],
    }
    try:
        metadata = load_document_type_sample_metadata(
            _candidate_ids(outline, classified_document_type_id)
        )
        if not metadata:
            return None
        from src.features.chatbot.core.providers.chat_openAI_provider import chat_model

        result = _invoke_report_structured(
            model=chat_model,
            schema=MetadataMatchResult,
            operation="general_document.match_sample_metadata",
            traces=[],
            prompt=(
                "你是文件來源 metadata 比對器。請只根據大綱與候選案例的"
                " title、description，為每個候選案例給出 0 到 1 的相關信心分數。"
                "sameSubject 只有在案例的具體主題、對象及主要內容可以直接支援"
                "整份大綱時才是 true；僅文件種類或分類相同不算相關。"
                "例如其他菜色的食譜不能因同屬美食食譜而當成番茄炒蛋的資料。"
                "大綱只有泛稱而沒有可核對的具體主題時，所有 sameSubject 都應為 false。"
                "若大綱結合多個不同主題，單一案例只涵蓋一部分也不得標為 true。"
                "不得依候選 metadata 推測未列出的食材、數字或內容。"
                "請依候選清單逐一回傳 sampleId、confidence、sameSubject、reason。\n"
                f"大綱：{json.dumps(outline_summary, ensure_ascii=False)}\n"
                f"候選 metadata：{json.dumps([item.model_dump() for item in metadata], ensure_ascii=False)}"
            ),
        )
    except Exception:
        logger.exception("document sample metadata matching failed; skip sample data")
        return None

    known_ids = {item.sampleId for item in metadata}
    returned_ids = [item.sampleId for item in result.matches]
    if set(returned_ids) != known_ids or len(returned_ids) != len(known_ids):
        logger.warning("document sample matcher did not score each candidate exactly once")
        return None
    relevant = [
        item for item in result.matches
        if item.sameSubject and item.confidence >= MIN_SAMPLE_CONFIDENCE
    ]
    if not relevant:
        return None
    best = max(relevant, key=lambda item: item.confidence)
    return best.sampleId
