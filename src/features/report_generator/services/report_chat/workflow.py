"""各獨立 Graph 的銜接與指定階段重跑入口。"""

from typing import Any, Literal

from src.features.report_generator.services.domain_report_service import ReportLLMTrace
from .content_graph import plan_section_contents
from .general_outline_graph import draft_general_outline
from .samples import DocumentTypeSample
from .schemas import GeneralDocumentOutline, GeneralDocumentPlan, ReportChatMessage
from .section_graph import plan_document_sections


PlanningStage = Literal["sections", "contents", "outline"]


def plan_general_document(
    *,
    document_type_id: str,
    messages: list[ReportChatMessage],
    model: Any,
    traces: list[ReportLLMTrace],
    start_at: PlanningStage = "sections",
    current_plan: GeneralDocumentPlan | None = None,
    current_outline: GeneralDocumentOutline | None = None,
    source_sample: DocumentTypeSample | None = None,
) -> tuple[GeneralDocumentPlan, GeneralDocumentOutline, list[ReportLLMTrace]]:
    """依序跑到大綱；也可從指定階段重跑。"""
    if start_at == "sections":
        section_plan, traces = plan_document_sections(
            document_type_id, messages, model, traces, current_plan,
            source_sample,
        )
    elif start_at in ("contents", "outline"):
        if current_plan is None or current_plan.documentTypeId != document_type_id:
            raise ValueError("從內容或大綱 Graph 重跑時需要相同文件種類的計畫")
        section_plan = current_plan
    else:
        raise ValueError("不支援的規劃起點")
    if start_at == "outline":
        plan = section_plan
    else:
        plan, traces = plan_section_contents(section_plan, messages, model, traces, source_sample)
    outline, traces = draft_general_outline(
        plan, messages, model, traces, current_outline, source_sample,
    )
    return plan, outline, traces
