"""內容執行 Graph：按 C 類型派發能力工具並保留未接工具的狀態。"""

import json
import logging
from collections.abc import Callable
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from .catalog import load_content_type_templates, load_document_type_templates, load_section_type_templates
from .samples import load_document_type_samples
from .schemas import GeneralDocumentPlan, PurposeDocumentPlan, ReportChatMessage


logger = logging.getLogger(__name__)
RAG_CAPABILITIES = {"RAG", "Retrieval", "Evidence Retrieval"}


class CapabilityTask(BaseModel):
    sectionId: str
    contentTypeId: str
    capability: str


class CapabilityResult(CapabilityTask):
    tool: str | None = None
    status: Literal["completed", "simulated", "needs_source", "not_configured", "error"]
    output: str = ""


class GeneralExecutionResult(BaseModel):
    documentTypeId: str | None = None
    purposeIds: list[str] = Field(default_factory=list)
    capabilities: list[CapabilityResult] = Field(default_factory=list)


class ExecutionGraphState(TypedDict, total=False):
    plan: GeneralDocumentPlan | PurposeDocumentPlan
    messages: list[ReportChatMessage]
    user_id: str
    chat_id: str | None
    use_sample_data: bool
    section_id: str | None
    content_type_id: str | None
    capability: str | None
    tasks: list[CapabilityTask]
    results: list[CapabilityResult]
    execution_result: GeneralExecutionResult


CapabilityTool = Callable[[CapabilityTask, ExecutionGraphState], CapabilityResult]
CAPABILITY_TOOLS: dict[str, CapabilityTool] = {}


def register_capability_tool(capability: str, tool: CapabilityTool) -> None:
    """供後續 SQL、API、統計及圖表等能力接入同一執行 Graph。"""
    if capability in RAG_CAPABILITIES:
        raise ValueError("RAG 類能力由 run_rag 節點處理")
    CAPABILITY_TOOLS[capability] = tool


def _sample_document_type_id(plan: GeneralDocumentPlan | PurposeDocumentPlan) -> str:
    if isinstance(plan, GeneralDocumentPlan):
        return plan.documentTypeId
    references = [item for purpose in plan.purposes for item in purpose.referenceTemplateIds]
    if len(plan.purposes) == 1 and len(references) == 1:
        return references[0]
    raise ValueError("複合用途沒有單一對應的虛構測試 JSON，請改用使用者資料")


def _prepare_tasks(state: ExecutionGraphState) -> ExecutionGraphState:
    if state.get("chat_id") and state.get("use_sample_data"):
        raise ValueError("真實對話檢索與虛構測試資料不可在同一次執行中混用")
    plan = state["plan"]
    if state.get("use_sample_data"):
        _sample_document_type_id(plan)
    sections = load_section_type_templates()
    contents = load_content_type_templates()
    tasks = []
    if isinstance(plan, PurposeDocumentPlan):
        purpose_ids = {item.purposeId for item in plan.purposes}
        keys = [section.sectionKey for section in plan.sections]
        if len(keys) != len(set(keys)):
            raise ValueError("用途計畫中的章節識別重複")
        for section in plan.sections:
            selected = section.contentTypeIds
            if (not set(section.purposeIds) <= purpose_ids
                or len(selected) != len(set(selected)) or not set(selected) <= set(contents)):
                raise ValueError(f"{section.sectionKey} 的用途或內容種類不正確")
            for content_id in selected:
                for capability in contents[content_id].requiredCapabilities:
                    tasks.append(CapabilityTask(
                        sectionId=section.sectionKey, contentTypeId=content_id,
                        capability=capability,
                    ))
    else:
        template = load_document_type_templates()[plan.documentTypeId]
        selected_ids = [section.sectionId for section in plan.sections]
        allowed_sections = set(template.requiredSectionIds + template.optionalSectionIds)
        if (
            len(selected_ids) != len(set(selected_ids))
            or not set(template.requiredSectionIds) <= set(selected_ids)
            or not set(selected_ids) <= allowed_sections
        ):
            raise ValueError("執行計畫中的章節與文件範本不一致")
        for section in plan.sections:
            required = section.sectionId in template.requiredSectionIds
            if section.isRequired != required:
                raise ValueError(f"{section.sectionId} 的必要章節標記不正確")
            selected = section.contentTypeIds
            allowed = sections[section.sectionId].suggestedContentTypeIds
            if not selected or len(selected) != len(set(selected)) or not set(selected) <= set(allowed):
                raise ValueError(f"{section.sectionId} 的內容種類與章節範本不一致")
            for content_id in selected:
                for capability in contents[content_id].requiredCapabilities:
                    tasks.append(CapabilityTask(
                        sectionId=section.sectionId, contentTypeId=content_id,
                        capability=capability,
                    ))
    tasks = [
        task for task in tasks
        if (not state.get("section_id") or task.sectionId == state["section_id"])
        and (not state.get("content_type_id") or task.contentTypeId == state["content_type_id"])
        and (not state.get("capability") or task.capability == state["capability"])
    ]
    if not tasks:
        raise ValueError("指定的章節、內容種類或能力不在目前計畫中")
    return {"tasks": tasks, "results": []}


def _run_rag(state: ExecutionGraphState) -> ExecutionGraphState:
    results = list(state["results"])
    section_templates = None
    sample = None
    for task in state["tasks"]:
        if task.capability not in RAG_CAPABILITIES:
            continue
        try:
            if state.get("chat_id"):
                if not state.get("user_id"):
                    raise ValueError("RAG 查詢需要使用者 ID")
                from src.features.chatbot.models.vector_store import VectorSearchFilter
                from src.features.chatbot.services.vector_service_factory import retrieval_service

                if section_templates is None:
                    section_templates = load_section_type_templates()
                if isinstance(state["plan"], PurposeDocumentPlan):
                    planned = next(item for item in state["plan"].sections if item.sectionKey == task.sectionId)
                    section_name, section_purpose = planned.heading, planned.focusHint
                else:
                    section = section_templates[task.sectionId]
                    section_name, section_purpose = section.name, section.purpose
                latest_request = next(
                    (message.content for message in reversed(state["messages"]) if message.role == "user"),
                    "",
                )
                query = f"{section_name}：{section_purpose}。{latest_request}"
                service = retrieval_service()
                chunks = service.retrieve_chunks(
                    query=query,
                    filters=VectorSearchFilter(
                        chat_id=state["chat_id"], user_id=state["user_id"],
                    ),
                    top_k=5,
                )
                results.append(CapabilityResult(
                    **task.model_dump(),
                    tool="user_scoped_rag",
                    status="completed" if chunks else "needs_source",
                    output=service.build_context(chunks),
                ))
            elif state.get("use_sample_data"):
                if sample is None:
                    sample = load_document_type_samples()[_sample_document_type_id(state["plan"])]
                results.append(CapabilityResult(
                    **task.model_dump(),
                    tool="synthetic_source_lookup",
                    status="simulated",
                    output=json.dumps(
                        [source.model_dump() for source in sample.sourceMaterials],
                        ensure_ascii=False,
                    ),
                ))
            else:
                results.append(CapabilityResult(
                    **task.model_dump(),
                    status="needs_source",
                    output="需要 chatId 或明確選用虛構測試案例。",
                ))
        except Exception:
            logger.exception("general document retrieval failed")
            results.append(CapabilityResult(
                **task.model_dump(), tool="user_scoped_rag", status="error",
                output="來源檢索失敗",
            ))
    return {"results": results}


def _sample_data_mapping(task: CapabilityTask, state: ExecutionGraphState) -> CapabilityResult:
    if not state.get("use_sample_data"):
        return CapabilityResult(
            **task.model_dump(), status="needs_source",
            output="Data Mapping 需要已接入的資料來源或明確選用虛構測試案例。",
        )
    sample = load_document_type_samples()[_sample_document_type_id(state["plan"])]
    return CapabilityResult(
        **task.model_dump(), tool="synthetic_fact_lookup", status="simulated",
        output=json.dumps([fact.model_dump() for fact in sample.facts], ensure_ascii=False),
    )


register_capability_tool("Data Mapping", _sample_data_mapping)


def _run_other_tools(state: ExecutionGraphState) -> ExecutionGraphState:
    results = list(state["results"])
    for task in state["tasks"]:
        if task.capability in RAG_CAPABILITIES:
            continue
        tool = CAPABILITY_TOOLS.get(task.capability)
        if tool is None:
            results.append(CapabilityResult(
                **task.model_dump(), status="not_configured",
                output=f"尚未接入 {task.capability} 工具。",
            ))
            continue
        try:
            results.append(tool(task, state))
        except Exception:
            logger.exception("general document capability failed: %s", task.capability)
            results.append(CapabilityResult(
                **task.model_dump(), status="error", output="工具執行失敗",
            ))
    return {"results": results}


def _collect_results(state: ExecutionGraphState) -> ExecutionGraphState:
    by_task = {
        (result.sectionId, result.contentTypeId, result.capability): result
        for result in state["results"]
    }
    ordered = [
        by_task[(task.sectionId, task.contentTypeId, task.capability)]
        for task in state["tasks"]
    ]
    return {"execution_result": GeneralExecutionResult(
        documentTypeId=(state["plan"].documentTypeId
                        if isinstance(state["plan"], GeneralDocumentPlan) else None),
        purposeIds=([item.purposeId for item in state["plan"].purposes]
                    if isinstance(state["plan"], PurposeDocumentPlan) else []),
        capabilities=ordered,
    )}


_builder = StateGraph(ExecutionGraphState)
_builder.add_node("prepare_capability_tasks", _prepare_tasks)
_builder.add_node("run_rag", _run_rag)
_builder.add_node("run_other_tools", _run_other_tools)
_builder.add_node("collect_results", _collect_results)
_builder.add_edge(START, "prepare_capability_tasks")
_builder.add_edge("prepare_capability_tasks", "run_rag")
_builder.add_edge("run_rag", "run_other_tools")
_builder.add_edge("run_other_tools", "collect_results")
_builder.add_edge("collect_results", END)
EXECUTION_GRAPH = _builder.compile()


def execute_general_plan(
    plan: GeneralDocumentPlan | PurposeDocumentPlan,
    messages: list[ReportChatMessage],
    *,
    user_id: str,
    chat_id: str | None = None,
    use_sample_data: bool = False,
    section_id: str | None = None,
    content_type_id: str | None = None,
    capability: str | None = None,
) -> GeneralExecutionResult:
    result = EXECUTION_GRAPH.invoke({
        "plan": plan,
        "messages": messages,
        "user_id": user_id,
        "chat_id": chat_id,
        "use_sample_data": use_sample_data,
        "section_id": section_id,
        "content_type_id": content_type_id,
        "capability": capability,
    })
    return result["execution_result"]
