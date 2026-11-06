"""先用分類與案例 metadata 比對大綱，再決定是否讀取完整測試 JSON。"""

import json
import logging

from pydantic import BaseModel, Field

from src.features.report_generator.services.domain_report_service import ReportLLMTrace

from .catalog import load_document_type_templates
from .llm import _invoke_report_structured
from .samples import DocumentSampleMetadata, load_document_type_sample_metadata
from .schemas import GeneralDocumentOutline, PurposeDocumentOutline

logger = logging.getLogger(__name__)
MIN_SAMPLE_CONFIDENCE = 0.55


class MetadataMatchScore(BaseModel):
    sampleId: str
    confidence: float = Field(ge=0, le=1)
    sameSubject: bool
    reason: str = Field(min_length=1, max_length=300)


class MetadataMatchResult(BaseModel):
    matches: list[MetadataMatchScore] = Field(default_factory=list)


def candidate_document_type_ids(
    outline: GeneralDocumentOutline | PurposeDocumentOutline,
    classified_document_type_id: str | None,
) -> list[str]:
    """只使用先前大綱規劃選出的 D 類型，不擴展到同分類的其他 D 類型。"""
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
    return [
        template_id for template_id in dict.fromkeys(reference_ids)
        if template_id in templates
    ]


def match_document_type_sample(
    outline: GeneralDocumentOutline | PurposeDocumentOutline,
    classified_document_type_id: str | None = None,
    *,
    metadata: list[DocumentSampleMetadata] | None = None,
    traces: list[ReportLLMTrace] | None = None,
    operation: str = "general_document.match_sample_metadata",
) -> str | None:
    """回傳最有參考價值且達門檻的案例 ID；無法確認時不使用案例。"""
    if traces is None:
        traces = []
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
        candidate_ids = candidate_document_type_ids(
            outline, classified_document_type_id
        )
        if metadata is None:
            metadata = load_document_type_sample_metadata(candidate_ids)
        if not metadata:
            return None
        logger.info(
            "document sample metadata candidates document_type_ids=%s count=%d",
            candidate_ids, len(metadata),
        )
        from src.features.chatbot.core.providers.chat_openAI_provider import chat_model

        result = _invoke_report_structured(
            model=chat_model,
            schema=MetadataMatchResult,
            operation=operation,
            traces=traces,
            prompt=(
                "你是文件生成系統的參考資料相關性評估器。只根據大綱與候選案例的"
                " title、description，評估每個案例對文件生成的參考價值；"
                "此步只決定是否值得讀取完整案例，不要求案例能直接支援整份大綱。\n"
                "判斷原則：以核心目的、語意相關性、內容可借鑑程度與文件用途為主，"
                "不要求文字完全一致。案例能支援一個或多個重要章節、規劃方式或分析方法，"
                "即具有參考價值；單一案例不必涵蓋整份多主題大綱。"
                "description 是內容摘要，候選案例額外提及的地點、人數、預算、偏好或情境，"
                "在大綱未指定時不得視為衝突。若使用者明確指定不可替換的核心主題、"
                "對象或條件，而案例與之衝突，應降低分數；若仍有實質可借鑑內容，"
                "不必直接排除。僅文件分類相同、沒有具體內容交集時，不算相關。\n"
                "依需求具體程度評估：開放型需求可從語意相近案例取得主題、內容或規劃方向；"
                "指定型需求應優先符合明確指定的核心主題或對象。"
                "大綱未指定的條件不能從候選案例反推為使用者需求。\n"
                "confidence 表示參考適用程度，不是內容完全一致的機率："
                "0.90～1.00 為核心需求高度相關，可提供主要內容及結構；"
                "0.75～0.89 為高度相關，局部條件不同仍有明顯價值；"
                "0.55～0.74 為中度相關，可支援部分重要章節或方法；"
                "0.30～0.54 為低度相關，僅少量概念或架構可借鑑；"
                "0.00～0.29 為關聯極低或與核心需求明顯衝突。"
                "次要差異不應造成過度扣分。\n"
                "sameSubject 表示是否有足夠的實質相關性，值得讀取作為參考。"
                "核心主題或用途相近、能支援重要章節、可借鑑其規劃或分析方式，"
                "或能為開放型需求提供合理方向時，設為 true。"
                "只有分類相同卻沒有內容交集、與不可替換條件重大衝突且無其他參考價值，"
                "或無法支援任何重要部分時，才設為 false。"
                "sameSubject=true 不代表案例內容可直接複製，也不代表所有事實都適用。\n"
                "只能根據 metadata 判斷，不得推測未列出的事實，"
                "也不得把案例的數字、人物、地點或事件當成使用者的真實資料。"
                "reason 優先說明可參考的內容，再說明局部差異及使用限制。"
                "請依候選清單順序逐一回傳 sampleId、confidence、sameSubject、reason；"
                "維持原本 JSON 結構，不新增欄位。\n"
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
