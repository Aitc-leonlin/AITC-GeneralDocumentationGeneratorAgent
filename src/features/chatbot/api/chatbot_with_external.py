from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException, Request
from langgraph.types import Command

from src.features.chatbot.core.agent.graph import graph
from src.features.chatbot.core.agent.trace import run_graph_with_trace
from src.features.chatbot.schemas.chatbot_base import (
    ChatbotWithExternalRequest,
    ChatbotWithExternalResponse,
    build_chatbot_response,
    build_graph_config,
    compact_text,
    dump_log_payload,
    resolve_workflow_thread_id,
)
from src.features.membership.core.auth_middleware import require_permission


chatbot_with_external_router = APIRouter(tags=["chatbot"])


@chatbot_with_external_router.post(
    "/api/chatbot-with-external",
    response_model=ChatbotWithExternalResponse,
)
async def get_chatbot_answer_with_external(
    http_request: Request,
    request: ChatbotWithExternalRequest,
    user: dict = Depends(require_permission("credit-ai.chat")),
):
    started_at = perf_counter()
    raw_request_body = await http_request.body()
    if raw_request_body:
        print(
            "[chatbotwithexternal] raw request body:\n"
            + raw_request_body.decode("utf-8", errors="replace")
        )

    if request.externalDataDecision == "adopted" and not compact_text(
        request.externalDataQueryText
    ):
        raise HTTPException(
            status_code=400,
            detail="externalDataQueryText is required when externalDataDecision is adopted.",
        )

    workflow_thread_id = resolve_workflow_thread_id(request, required=True)
    graph_config = build_graph_config(
        request,
        request_source="chatbot-with-external",
        user_id=user["id"],
        workflow_thread_id=workflow_thread_id,
    )
    print(
        "[chatbotwithexternal] request payload:\n"
        + dump_log_payload(request.model_dump())
    )
    snapshot = graph.get_state(graph_config)
    has_pending_interrupt = any(task.interrupts for task in snapshot.tasks)
    if not has_pending_interrupt:
        raise HTTPException(
            status_code=409,
            detail="The workflow is not waiting for external data approval.",
        )
    checkpoint_conversation_id = compact_text(snapshot.values.get("conversation_id"))
    if checkpoint_conversation_id != compact_text(request.conversationId):
        raise HTTPException(status_code=409, detail="The workflow conversation does not match.")

    resume_value = {
        "decision": request.externalDataDecision,
        "externalDataQueryText": request.externalDataQueryText,
    }
    print("[chatbotwithexternal] resume input:\n" + dump_log_payload(resume_value))
    graph_answer, graph_nodes = run_graph_with_trace(
        graph, Command(resume=resume_value), graph_config
    )
    print(
        "[timing] chatbotwithexternal.total_graph_to_final_answer took "
        f"{perf_counter() - started_at:.3f}s"
    )
    return build_chatbot_response(
        graph_answer,
        include_external_data_query_text=False,
        include_applied_external_data=True,
        workflow_thread_id=workflow_thread_id,
        graph_nodes=graph_nodes,
    )
