"""Read one document type's JSON evidence and draft cited section text."""

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import BaseModel, Field

from src.features.report_generator.services.domain_report_service import ReportLLMTrace

from .llm import _invoke_report_structured
from .markdown_tables import TABLE_FORMAT_FEW_SHOT
from .samples import DocumentTypeSample, load_document_type_sample
from .schemas import (
    GeneralDocumentOutline, PurposeDocumentOutline, ReportChatMessage,
    ReportSampleSelection,
)


@dataclass(frozen=True)
class EvidenceItem:
    id: str
    field: str
    text: str
    sampleId: str = ""


@dataclass(frozen=True)
class JsonEvidence:
    sample: DocumentTypeSample
    items: tuple[EvidenceItem, ...]
    samples: tuple[DocumentTypeSample, ...] = ()
    sampleIds: tuple[str, ...] = ()


class SectionAnswer(BaseModel):
    paragraphs: list[str] = Field(min_length=1, max_length=8)
    evidenceIds: list[str] = Field(default_factory=list)


class EvidenceConsistencyCheck(BaseModel):
    consistent: bool
    issues: list[str] = Field(default_factory=list)


def _check_section_evidence(
    *, model: Any, heading: str, answer: SectionAnswer, source: str,
    cases: str, user_requests: list[str], traces: list[ReportLLMTrace],
) -> EvidenceConsistencyCheck:
    return _invoke_report_structured(
        model=model, schema=EvidenceConsistencyCheck,
        operation=f"general_document.check_json_evidence.{heading}", traces=traces,
        prompt=(
            "你是文件章節與 JSON 案例引用的語意核對器，只檢查來源對應，不評文筆。"
            "允許合理改寫、概括與一般性規劃建議；不要求內文逐字重複來源，"
            "也不要求單一案例涵蓋整章。"
            "以下有明確問題時 consistent=false，並以 issues 簡述可修正的差異："
            "內文把案例數字、食材、對象、地點或期間用錯；引用 ID 與內文沒有實質關係；"
            "使用案例具體事實卻未列支援它的 evidenceIds；把僅供參考的案例誤寫成"
            "使用者的真實個案；把模擬來源描述當成已查證的真實資料；"
            "或內文與來源明確矛盾。"
            "一般知識、方法與不含案例特定條件的示例規劃可以沒有 evidenceIds；"
            "只要用了案例的具體內容，即使標示為示例仍須列出支援的 ID。"
            "使用者在需求中明確提供的條件可作為寫作依據，但不能說成案例已查證。"
            "sourceNote 是來源註記，不可用來證明個案數值。"
            "只有明確不一致才判 false；不因未引用所有案例欄位而判錯。"
            "consistent=true 時 issues 留空；否則最多列出六個具體問題。\n"
            f"章節：{heading}\n"
            f"草稿：{answer.model_dump_json()}\n"
            f"案例用途：{cases}\n"
            f"使用者需求：{json.dumps(user_requests[-15:], ensure_ascii=False)}\n"
            f"JSON 證據：{source}"
        ),
    )


def _repair_section_evidence(
    *, model: Any, heading: str, answer: SectionAnswer,
    issues: list[str], source: str, cases: str, user_requests: list[str],
    section_plan: str,
    traces: list[ReportLLMTrace],
) -> SectionAnswer:
    return _invoke_report_structured(
        model=model, schema=SectionAnswer,
        operation=f"general_document.repair_json_evidence.{heading}", traces=traces,
        prompt=(
            "你是繁體中文文件編輯。只修正下列案例引用核對問題，回傳完整修正版段落"
            "與 evidenceIds，保留與大綱相符且有用的內容。"
            "可以改用真正支援敘述的證據 ID、改正條件與數字、明示案例僅供參考，"
            "或刪除無來源的個案結論；不可發明新事實。"
            "一般性說明可保留且不必硬加引用。\n"
            f"章節：{heading}\n"
            f"章節規劃：{section_plan}\n"
            f"原草稿：{answer.model_dump_json()}\n"
            f"待修正問題：{json.dumps(issues, ensure_ascii=False)}\n"
            f"案例用途：{cases}\n"
            f"使用者需求：{json.dumps(user_requests[-15:], ensure_ascii=False)}\n"
            f"JSON 證據：{source}"
        ),
    )


def retrieve_json_evidence(sample_id: str) -> JsonEvidence:
    """The storage boundary: replace this function when evidence moves to a DB."""
    return evidence_from_sample(load_document_type_sample(sample_id))


def evidence_from_sample(sample: DocumentTypeSample) -> JsonEvidence:
    """Convert a validated sample returned by the Agent Tool into chapter evidence."""
    items = [
        EvidenceItem("TITLE", "title", sample.title),
        EvidenceItem("SUB", "subject", sample.subject),
        EvidenceItem("PER", "period", sample.period),
        EvidenceItem("OBJ", "objective", sample.objective),
        EvidenceItem("CTX", "context", sample.context),
        EvidenceItem("NOTE", "sourceNote", sample.sourceNote),
    ]
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
    return JsonEvidence(sample=sample, items=tuple(items), samples=(sample,), sampleIds=("",))


def evidence_from_samples(samples: list[tuple[str, DocumentTypeSample]]) -> JsonEvidence:
    """合併多份案例，為各案例的證據建立不衝突的 ID。"""
    if not samples:
        raise ValueError("至少需要一份案例")
    if len(samples) == 1:
        sample_id, sample = samples[0]
        evidence = evidence_from_sample(sample)
        return JsonEvidence(
            sample=sample, items=tuple(
                EvidenceItem(item.id, item.field, item.text, sample_id)
                for item in evidence.items
            ),
            samples=(sample,), sampleIds=(sample_id,),
        )
    items: list[EvidenceItem] = []
    for index, (sample_id, sample) in enumerate(samples, start=1):
        for item in evidence_from_sample(sample).items:
            items.append(EvidenceItem(
                id=f"S{index}_{item.id}", field=item.field,
                text=item.text, sampleId=sample_id,
            ))
    return JsonEvidence(
        sample=samples[0][1], items=tuple(items),
        samples=tuple(sample for _, sample in samples),
        sampleIds=tuple(sample_id for sample_id, _ in samples),
    )


def draft_sections_from_json(
    outline: PurposeDocumentOutline | GeneralDocumentOutline,
    evidence: JsonEvidence,
    messages: list[ReportChatMessage],
    *,
    traces: list[ReportLLMTrace] | None = None,
    use_mode: Literal["adopt", "reference"] = "reference",
    sample_selection: ReportSampleSelection | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
    coverage_feedback: str = "",
) -> list[SectionAnswer]:
    """Generate each outlined section from the retrieved JSON, with evidence IDs."""
    if traces is None:
        traces = []
    from src.features.chatbot.core.providers.chat_openAI_provider import chat_model

    known_ids = {item.id for item in evidence.items}
    source = json.dumps(
        [
            {"id": item.id, "sampleId": item.sampleId, "field": item.field, "text": item.text}
            for item in evidence.items
        ],
        ensure_ascii=False,
    )
    coverage_by_id: dict[str, list[str]] = {}
    if sample_selection:
        for item in sample_selection.outputCoverage:
            coverage_by_id.setdefault(item.sampleId, []).append(item.label)
    cases = json.dumps([
        {
            "sampleId": sample_id, "title": sample.title,
            "subject": sample.subject, "period": sample.period,
            "objective": sample.objective,
            "coveredOutputs": coverage_by_id.get(sample_id, []),
            "use": "adopt" if sample_selection and sample_id in sample_selection.adoptedSampleIds else "reference",
        }
        for sample_id, sample in zip(evidence.sampleIds, evidence.samples)
    ], ensure_ascii=False)
    user_requests = [message.content for message in messages if message.role == "user"]
    if os.getenv("LLM_PROVIDER", "openai").strip().lower() == "local":
        table_instruction = (
            "不要產生 Markdown 表格或其他表格格式；即使預計內容列出比較矩陣或數據表格，"
            "也請改用一般段落或條列清單逐項說明。"
        )
        table_example = ""
    else:
        table_instruction = (
            "需要表格時請使用完整的 Markdown 表格語法（表頭、分隔列、資料列），"
            "放在同一個 paragraphs 項目內，不要包在程式碼區塊中。"
        )
        table_example = f"{TABLE_FORMAT_FEW_SHOT}\n"
    answers = []
    for section in outline.sections:
        section_plan = json.dumps({
            "heading": section.heading,
            "focus": section.focus,
            "contents": [item.model_dump() for item in section.contents],
        }, ensure_ascii=False)
        if progress_callback:
            progress_callback(
                25 + 55 * len(answers) // len(outline.sections),
                f"撰寫「{section.heading}」",
            )
        prompt = (
            "你正在撰寫繁體中文 DOCX 的單一章節。大綱與使用者明確需求決定內容範圍；"
            "案例資料是可用的示例來源，通用知識可用於一般性方法、規劃與建議。"
            "使用者需求中的未驗證敘述不得寫成已查證事實。"
            "use_mode=adopt 表示至少一份案例已選為文件的具體示例主題；"
            "每份案例的實際用途以案例清單中的 use 欄位為準。"
            "對 use=adopt 的案例，可使用其適用的材料、步驟或行程安排，"
            "並標示這是案例方案；"
            "不得把案例中的日期、費用、營業資訊或其他未查證內容說成現況。"
            "對 use=reference 的案例，只借鑑相關內容、結構或方法；"
            "不同情境的人物、地點、事件與數字不得改寫成使用者文件的事實。"
            "先核對案例與文件的主題、對象、地點和期間，若提及不同情境的具體案例，"
            "須明確標示為參考案例。"
            "根據章節標題與重點挑選相關資料，不要把所有資料硬塞進每章。"
            "field=sourceMaterials 的資料只是模擬來源的描述，不代表已查閱真實文件，"
            "也不能推導其未列出的數字；field=sourceNote 是來源註記，不是個案事實。"
            "不要捏造數值、比較、結論、法規、建議或真實來源。"
            "案例不足以涵蓋本章時，仍應根據大綱寫出可用的一般性內容；"
            "只有必須依個案證據才能成立的具體內容才標示『待補』。"
            "本章每個預計內容項目都要有對應文字，可以將相關項目合併在同一段。"
            "若要求多份方案，應清楚區分各方案；若要求比較，應在相關章節"
            "以相同面向逐一比較，不得把不同案例的數字與情境混為一談。"
            "選中的案例少於使用者要求數量時，其餘選項只能依大綱寫成一般性示例，"
            "不可假稱有案例來源。"
            "若提供全文件輸出缺漏回饋，只在本章相關時補足；不必每章重複所有選項，"
            "且不得因此放寬案例引用與事實限制。"
            "每段應是可直接放入文件的內文，不要重複章節標題。"
            f"{table_instruction}"
            "evidenceIds 只列實際支撐所引用案例內容的 ID；"
            "純一般性內容或只能寫待補時可回傳空陣列。\n"
            f"{table_example}"
            f"use_mode：{use_mode}\n"
            f"輸出需求：{sample_selection.model_dump_json() if sample_selection else '單份文件'}\n"
            f"全文件輸出缺漏回饋：{coverage_feedback or '無'}\n"
            f"文件：{outline.title}；對象：{outline.subject}；期間：{outline.period}；目的：{outline.objective}\n"
            f"章節：{section.heading}\n重點：{section.focus}\n"
            f"預計內容：{json.dumps([item.model_dump() for item in section.contents], ensure_ascii=False)}\n"
            f"使用者需求：{json.dumps(user_requests[-15:], ensure_ascii=False)}\n"
            f"案例：{cases}\n"
            f"來源資料：{source}\n"
        )
        answer = _invoke_report_structured(
            model=chat_model,
            schema=SectionAnswer,
            operation=f"general_document.json_answer.{section.heading}",
            traces=traces,
            prompt=prompt,
        )
        if progress_callback:
            progress_callback(
                25 + 55 * len(answers) // len(outline.sections),
                f"核對「{section.heading}」的案例引用",
            )
        for revision in range(2):
            answer = answer.model_copy(update={
                "evidenceIds": list(dict.fromkeys(answer.evidenceIds)),
            })
            unknown_ids = sorted(set(answer.evidenceIds) - known_ids)
            if unknown_ids:
                issues = [f"引用了不存在的證據 ID：{', '.join(unknown_ids)}"]
            else:
                check = _check_section_evidence(
                    model=chat_model, heading=section.heading, answer=answer,
                    source=source, cases=cases, user_requests=user_requests,
                    traces=traces,
                )
                reported_issues = [item.strip() for item in check.issues if item.strip()]
                if check.consistent and not reported_issues:
                    break
                issues = reported_issues or ["案例事實與引用證據不一致"]
            if revision == 1:
                raise ValueError(
                    f"章節「{section.heading}」的案例引用核對未通過：{issues[0]}"
                )
            if progress_callback:
                progress_callback(
                    25 + 55 * len(answers) // len(outline.sections),
                    f"修正「{section.heading}」的案例引用",
                )
            answer = _repair_section_evidence(
                model=chat_model, heading=section.heading, answer=answer,
                issues=issues, source=source, cases=cases,
                user_requests=user_requests, section_plan=section_plan,
                traces=traces,
            )
        answers.append(answer)
        if progress_callback:
            progress_callback(
                25 + 55 * len(answers) // len(outline.sections),
                f"已完成 {len(answers)}/{len(outline.sections)} 個章節",
            )
    return answers
