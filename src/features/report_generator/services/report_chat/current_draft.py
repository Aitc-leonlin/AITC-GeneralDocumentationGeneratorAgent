"""將對話目前已有的規劃匯出成 DOCX，允許尚未完成大綱。"""

import json
import re
from datetime import datetime
from io import BytesIO
from typing import Callable, Literal
from zoneinfo import ZoneInfo

from docx import Document
from docx.document import Document as DocxDocument
from docx.shared import Cm, Pt

from src.features.report_generator.services.domain_report_service import (
    ReportLLMTrace,
    _render_markdown_body,
    # llm_trace_blocks,  # 恢復 DOCX LLM 呼叫紀錄時再啟用
)

from .catalog import (
    load_content_type_templates,
    load_document_type_templates,
    load_section_type_templates,
)
from .docx_content_graph import build_docx_content
from .json_evidence import JsonEvidence
from .markdown_tables import omit_unrenderable_markdown_tables
from .schemas import (
    GeneralDocumentOutline, GeneralDocumentPlan, PurposeDocumentOutline,
    PurposeDocumentPlan, ReportChatMessage, ReportToolUsage,
    ReportSampleSelection,
    required_source_satisfied,
)


def _download_filename(title: str) -> str:
    """以大綱預覽標題命名，移除各作業系統不允許的檔名字元。"""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', " ", title)
    name = " ".join(name.split()).strip(" .")
    if name.lower().endswith(".docx"):
        name = name[:-5].rstrip(" .")
    reserved = {"CON", "PRN", "AUX", "NUL"}
    reserved.update(f"COM{i}" for i in range(1, 10))
    reserved.update(f"LPT{i}" for i in range(1, 10))
    if not name:
        name = "文件規劃草稿"
    elif name.split(".", 1)[0].upper() in reserved:
        name = f"文件_{name}"
    return f"{name}.docx"


def _add_readable_evidence(document: DocxDocument, evidence: JsonEvidence, evidence_ids: list[str]) -> None:
    """Show cited context and source notes beside a section; list facts once below."""
    labels = {
        "title": "案例標題",
        "subject": "案例對象",
        "period": "案例期間",
        "objective": "案例目標",
        "context": "案例情境",
        "sourceMaterials": "來源描述",
        "assumptions": "案例假設",
        "sourceNote": "來源註記",
    }
    selected = set(evidence_ids)
    items = [
        item for item in evidence.items
        if item.id in selected and item.field.split("[", 1)[0] != "facts"
    ]
    if not items:
        return
    sample_titles = {
        sample_id: sample.title
        for sample_id, sample in zip(evidence.sampleIds, evidence.samples)
    }
    document.add_paragraph("本章參考的資料：")
    for item in items:
        label = labels[item.field.split("[", 1)[0]]
        origin = f"{sample_titles[item.sampleId]}／" if len(evidence.samples) > 1 and item.sampleId in sample_titles else ""
        document.add_paragraph(f"{origin}{label}：{item.text}", style="List Bullet")


def _add_generated_content(document: DocxDocument, paragraphs: list[str]) -> None:
    """Render prose and valid Word tables, omitting malformed Markdown tables."""
    markdown = omit_unrenderable_markdown_tables(paragraphs)
    if markdown:
        _render_markdown_body(document, markdown)


def _add_json_record(document: DocxDocument, label: str, value: str | None) -> None:
    document.add_paragraph(label)
    if value is None:
        document.add_paragraph("舊紀錄未保存此內容。")
        return
    try:
        content = json.dumps(json.loads(value), ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        content = value
    run = document.add_paragraph().add_run(content)
    run.font.name = "Consolas"
    run.font.size = Pt(8)


def _latest_conversation_traces(traces: list[ReportLLMTrace]) -> list[ReportLLMTrace]:
    """只保留最近一輪報告對話的 LLM 呼叫紀錄。"""
    for index in range(len(traces) - 1, -1, -1):
        if traces[index].stage.startswith("report_outline.classify_question（第 1 次）"):
            return traces[index:]
    return []


def export_current_draft(
    *,
    document_type_id: str | None,
    plan: GeneralDocumentPlan | None,
    outline: GeneralDocumentOutline | None,
    messages: list[ReportChatMessage],
    llm_traces: list[ReportLLMTrace] | None = None,
    tool_usages: list[ReportToolUsage] | None = None,
    use_sample_data: bool = False,
    source_mode: Literal["default_json", "user_data"] | None = None,
    sample_selection: ReportSampleSelection | None = None,
    purpose_plan: PurposeDocumentPlan | None = None,
    purpose_outline: PurposeDocumentOutline | None = None,
    progress_callback: Callable[[int, str], None] | None = None,
) -> tuple[bytes, str]:
    """有大綱時依相關 JSON 或 LLM 撰寫；尚無大綱時匯出規劃進度。"""
    user_requests = [message.content for message in messages if message.role == "user"]
    if not user_requests:
        raise ValueError("請先描述文件需求，再下載目前版本")
    if sample_selection and not required_source_satisfied(sample_selection):
        raise ValueError("這份文件要求必要參考資料，請先提供資料或調整來源要求，再下載 DOCX")
    if progress_callback:
        progress_callback(5, "讀取文件規劃")

    document_types = load_document_type_templates()
    section_types = load_section_type_templates()
    content_types = load_content_type_templates()
    purpose_references = (
        [item for purpose in purpose_plan.purposes for item in purpose.referenceTemplateIds]
        if purpose_plan else []
    )
    type_id = (
        purpose_references[0] if len(purpose_plan.purposes) == 1
        and len(purpose_references) == 1 else None
    ) if purpose_plan else (
        outline.documentTypeId if outline else plan.documentTypeId if plan else document_type_id
    )
    template = document_types.get(type_id) if type_id else None
    active_outline = purpose_outline or outline
    effective_source_mode = source_mode or ("default_json" if use_sample_data else "user_data")
    if progress_callback:
        progress_callback(10, "準備報告內容")
    generated = (
        build_docx_content(
            active_outline, messages, document_type_id,
            sample_selection=sample_selection,
            source_mode=effective_source_mode,
            progress_callback=progress_callback,
        )
        if active_outline else None
    )
    if generated and generated.get("sample_selection"):
        sample_selection = generated["sample_selection"]
    if progress_callback:
        progress_callback(84, "編排 Word 文件")
    evidence = generated.get("evidence") if generated else None
    sample = evidence.sample if evidence else None
    samples = evidence.samples if evidence else ()
    answers = generated["answers"] if generated else None
    content_mode = generated["mode"] if generated else None
    title = (
        purpose_outline.title if purpose_outline else
        outline.title if outline else f"{template.name}（規劃草稿）" if template else "文件規劃草稿"
    )

    document = Document()
    page = document.sections[0]
    page.page_width, page.page_height = Cm(21), Cm(29.7)
    page.top_margin = page.bottom_margin = Cm(2)
    page.left_margin = page.right_margin = Cm(2.5)
    normal = document.styles["Normal"]
    normal.font.name = "Microsoft JhengHei"
    normal.font.size = Pt(11)

    document.add_heading(title, 0)
    if content_mode == "user_data":
        version_text = "版本：依目前大綱與使用者資料撰寫。"
    elif content_mode == "outline_llm":
        version_text = "版本：依目前大綱撰寫。"
    else:
        version_text = "版本：目前進度；缺少來源的內容標示為待補。"
    document.add_paragraph(
        f"文件用途：{'、'.join(item.description for item in purpose_plan.purposes) if purpose_plan else type_id + ' ' + template.name if type_id and template else '待辨識'}\n"
        f"匯出日期：{datetime.now(ZoneInfo('Asia/Taipei')).date().isoformat()}\n"
        f"{version_text}"
    )

    document.add_heading("文件目的與範圍", level=1)
    if purpose_outline:
        document.add_paragraph(f"目的：{purpose_outline.objective}")
        document.add_paragraph(f"對象：{purpose_outline.subject}；期間：{purpose_outline.period}")
    elif outline:
        document.add_paragraph(f"目的：{outline.objective}")
        document.add_paragraph(f"對象：{outline.subject}；期間：{outline.period}")
    else:
        document.add_paragraph(f"預計目的：{template.purpose if template else '待確認'}")
        document.add_paragraph("對象與期間：待補")

    
    # if sample:
    #     print("==================sample:==================" + sample.model_dump_json())
    #     document.add_heading("預設測試資料", level=1)
    #     document.add_paragraph("以下資料為虛構測試案例，僅供文件產生。")
    #     document.add_paragraph(f"案例：{sample.title}；對象：{sample.subject}；期間：{sample.period}")
    #     document.add_paragraph(sample.context)
    #     table = document.add_table(rows=1, cols=2)
    #     table.style = "Light Shading Accent 1"
    #     table.rows[0].cells[0].text = "項目"
    #     table.rows[0].cells[1].text = "測試資料"
    #     for fact in sample.facts:
    #         cells = table.add_row().cells
    #         cells[0].text, cells[1].text = fact.label, fact.value

    document.add_heading("章節內容" if answers else "目前章節", level=1)
    if purpose_outline:
        for index, section in enumerate(purpose_outline.sections, start=1):
            document.add_heading(f"{index}. {section.heading}", level=2)
            if answers:
                _add_generated_content(document, answers[index - 1].paragraphs)
                if evidence and answers[index - 1].evidenceIds:
                    _add_readable_evidence(document, evidence, answers[index - 1].evidenceIds)
            else:
                document.add_paragraph(f"規劃重點：{section.focus}")
                document.add_paragraph("章節內文與來源資料：待補")
    elif purpose_plan:
        for index, section in enumerate(purpose_plan.sections, start=1):
            document.add_heading(f"{index}. {section.heading}", level=2)
            document.add_paragraph(f"規劃重點：{section.focusHint}")
            document.add_paragraph("章節內文與來源資料：待補")
    elif outline:
        for index, section in enumerate(outline.sections, start=1):
            document.add_heading(f"{index}. {section.heading}", level=2)
            if answers:
                _add_generated_content(document, answers[index - 1].paragraphs)
                if evidence and answers[index - 1].evidenceIds:
                    _add_readable_evidence(document, evidence, answers[index - 1].evidenceIds)
            else:
                document.add_paragraph(f"規劃重點：{section.focus}")
                document.add_paragraph("章節內文與來源資料：待補")
    elif plan:
        for index, section in enumerate(plan.sections, start=1):
            heading = section_types.get(section.sectionId)
            document.add_heading(
                f"{index}. {heading.name if heading else section.sectionId}", level=2
            )
            names = [
                content_types[item].name for item in section.contentTypeIds
                if item in content_types
            ]
            document.add_paragraph("預計內容：" + ("、".join(names) if names else "待規劃"))
            document.add_paragraph("章節重點、內文與來源資料：待補")
    elif template:
        for index, section_id in enumerate(template.requiredSectionIds, start=1):
            heading = section_types.get(section_id)
            document.add_heading(
                f"{index}. {heading.name if heading else section_id}", level=2
            )
            document.add_paragraph("章節內容：待規劃")
    else:
        document.add_paragraph("文件種類與章節：待規劃")

    document.add_heading("資料來源與限制", level=1)
    if content_mode == "user_data":
        source_description = (
            "章節依使用者在本對話提供的資料與需求撰寫，未查詢預設測試 JSON；"
            "使用者提供的資料未經系統獨立查證，資料不足處已在章節中說明。"
        )
    elif content_mode == "outline_llm":
        source_description = (
            "章節依目前大綱與使用者需求由 AI 撰寫，未使用預設測試 JSON；"
            "內容中的一般性說明不代表已完成個案查證。"
        )
    else:
        source_description = (
            purpose_outline.sourcePlan if purpose_outline else
            outline.sourcePlan if outline else "尚未確認資料來源。"
        )
    document.add_paragraph(source_description)
    if samples:
        cited_ids = {item for answer in (answers or []) for item in answer.evidenceIds}
        cited_facts: dict[str, set[str]] = {}
        for item in evidence.items:
            if item.id in cited_ids and item.field.startswith("facts["):
                cited_facts.setdefault(item.sampleId, set()).add(item.field)
        if sample_selection and sample_selection.mode != "none":
            usage_label = "選為本文件示例方案" if sample_selection.mode == "adopt" else "作為部分章節參考"
            document.add_paragraph(f"案例用途：{usage_label}；{sample_selection.reason}")
        for index, case in enumerate(samples, start=1):
            case_id = evidence.sampleIds[index - 1] if evidence and index <= len(evidence.sampleIds) else ""
            document.add_heading(f"參考案例 {index}：{case.title}", level=2)
            document.add_paragraph(f"文件類型：{case.documentTypeId}；資料性質：虛構測試案例")
            if sample_selection and case_id:
                case_role = "採用為方案" if case_id in sample_selection.adoptedSampleIds else "僅供參考"
                document.add_paragraph(f"使用方式：{case_role}")
                covered_labels = [
                    item.label for item in sample_selection.outputCoverage
                    if item.sampleId == case_id
                ]
                if covered_labels:
                    document.add_paragraph(f"支援的輸出項目：{'、'.join(covered_labels)}")
            document.add_paragraph(f"案例對象：{case.subject}；案例期間：{case.period}")
            document.add_paragraph(f"案例目標：{case.objective}")
            document.add_paragraph(f"來源註記：{case.sourceNote}")
            document.add_paragraph("案例情境：" + case.context, style="List Bullet")
            if case.facts:
                cited_fields = cited_facts.get(case_id, set())
                document.add_paragraph(
                    f"案例事實：共 {len(case.facts)} 項，"
                    f"其中 {len(cited_fields)} 項於章節標示引用。"
                )
                for fact_index, fact in enumerate(case.facts):
                    usage = (
                        "章節標示引用" if f"facts[{fact_index}]" in cited_fields
                        else "僅列於來源資料"
                    )
                    document.add_paragraph(
                        f"{fact.label}：{fact.value}（{usage}）", style="List Bullet"
                    )
            for source in case.sourceMaterials:
                document.add_paragraph(f"模擬來源描述：{source.title}：{source.content}", style="List Bullet")
            for assumption in case.assumptions:
                document.add_paragraph(f"案例假設：{assumption}", style="List Bullet")
    document.add_paragraph(
        "本文件依目前對話與已完成的大綱規劃匯出；"
        + ("若章節引用案例具體內容，其依據來自JSON資料；" if sample else "")
        + "未經資料查證的內容不作為事實或結論。"
    )
    document.add_heading("使用者於此聊天視窗提過的報告需求", level=1)
    for request in user_requests:
        document.add_paragraph(request, style="List Bullet")

    # 除下方案例 Agent 決策外，其他 LLM REQUEST、PROMPT 與 RESPONSE 暫不附加到 DOCX。
    # all_traces = [
    #     *_latest_conversation_traces(llm_traces or []),
    #     *(generated.get("traces", []) if generated else []),
    # ]
    # if all_traces:
    #     document.add_page_break()
    #     document.add_heading("最近一輪對話與本次匯出的 LLM API 呼叫紀錄", level=1)
    #     for block in llm_trace_blocks(all_traces):
    #         document.add_heading(block.title, level=2)
    #         run = document.add_paragraph().add_run(block.content)
    #         run.font.name = "Consolas"
    #         run.font.size = Pt(8)

    document.add_page_break()
    document.add_heading("AI Agent Tool 請求與取得資料", level=1)
    document.add_paragraph(
        "以下分別記錄對話規劃、問答與本次 DOCX 產生時的案例查詢及輸出核對。"
        "Tool 取回資料是否用於章節，請以本次 DOCX 的查詢結果與資料來源說明為準。"
    )
    document.add_paragraph(
        "LLM REQUEST／RESPONSE 為後端 LangChain 傳入內容與合併後的回覆紀錄；"
        "供應商實際 HTTP 封包可能另含參數。Tool RESPONSE 為工具實際回傳內容。"
    )
    conversation_decisions = [
        trace for trace in (llm_traces or [])
        if trace.stage.startswith((
            "report_question.decide_sample_lookup", "report_question.select_samples",
            "general_document.classify_sample_route",
            "general_document.choose_sample_types",
            "general_document.choose_open_sample",
            "general_document.decide_open_sample_use",
            "general_document.review_required_case_coverage",
            "general_document.review_required_single_case",
            "general_document.review_reused_sample",
        ))
    ]
    document_decisions = [
        trace for trace in (generated.get("traces", []) if generated else [])
        if trace.stage.startswith((
            "general_document.decide_sample_lookup",
            "general_document.review_generated_output_coverage",
        ))
    ]
    document.add_heading("對話規劃與問答中的案例查詢", level=2)
    if not conversation_decisions and not tool_usages:
        document.add_paragraph("此對話沒有進入案例問答 Agent，或既有 Thread 尚未保存紀錄。")
    else:
        for index, trace in enumerate(conversation_decisions, start=1):
            document.add_heading(f"{index}. {trace.stage}", level=3)
            _add_json_record(document, "REQUEST", trace.requestJson)
            _add_json_record(document, "RESPONSE", trace.responseJson)
        for index, usage in enumerate(tool_usages or [], start=1):
            document.add_heading(f"{index}. {usage.toolName}", level=3)
            document.add_paragraph(
                f"執行結果：{'成功' if usage.status == 'success' else '失敗'}"
            )
            _add_json_record(document, "TOOL REQUEST", usage.requestJson)
            _add_json_record(document, "TOOL RESPONSE（取回資料）", usage.responseJson)

    document.add_heading("本次 DOCX 產生時的案例查詢與輸出核對", level=2)
    if generated:
        document.add_paragraph(f"來源處理：{generated.get('lookup_reason') or '未記錄原因。'}")
        for index, trace in enumerate(document_decisions, start=1):
            document.add_heading(f"{index}. {trace.stage}", level=3)
            _add_json_record(document, "REQUEST", trace.requestJson)
            _add_json_record(document, "RESPONSE", trace.responseJson)
        for index, usage in enumerate(generated.get("tool_usages", []), start=1):
            document.add_heading(f"{index}. {usage.toolName}", level=3)
            document.add_paragraph(
                f"執行結果：{'成功' if usage.status == 'success' else '失敗'}"
            )
            _add_json_record(document, "TOOL REQUEST", usage.requestJson)
            _add_json_record(document, "TOOL RESPONSE（取回資料）", usage.responseJson)
    elif not active_outline:
        document.add_paragraph("目前沒有完整大綱，僅匯出規劃進度；未執行 DOCX 案例查詢。")
    else:
        document.add_paragraph("資料來源設定為只使用使用者資料；未執行 DOCX 案例查詢。")

    stream = BytesIO()
    document.save(stream)
    if progress_callback:
        progress_callback(95, "完成 Word 文件，準備下載")
    return stream.getvalue(), _download_filename(title)
