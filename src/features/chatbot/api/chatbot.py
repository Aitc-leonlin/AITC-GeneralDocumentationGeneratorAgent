from time import perf_counter

from fastapi import APIRouter, Depends, Request

from src.features.chatbot.core.agent.graph import graph
from src.features.chatbot.core.agent.trace import run_graph_with_trace
from src.features.chatbot.schemas.chatbot_base import (
    ChatbotRequest,
    ChatbotResponse,
    build_chatbot_response,
    build_graph_config,
    build_graph_input,
    dump_log_payload,
    resolve_workflow_thread_id,
)
from src.features.membership.core.auth_middleware import require_permission


chatbot_router = APIRouter(tags=["chatbot"])


@chatbot_router.post("/api/chatbot", response_model=ChatbotResponse)
async def get_chatbot_answer(
    http_request: Request,
    request: ChatbotRequest,
    user: dict = Depends(require_permission("credit-ai.chat")),
):
    started_at = perf_counter()
    raw_request_body = await http_request.body()
    if raw_request_body:
        print(
            "[chatbot] raw request body:\n"
            + raw_request_body.decode("utf-8", errors="replace")
        )
    graph_input = build_graph_input(
        request,
        request_source="chatbot",
        user_id=user["id"],
    )
    workflow_thread_id = resolve_workflow_thread_id(request)
    graph_config = build_graph_config(
        request,
        request_source="chatbot",
        user_id=user["id"],
        workflow_thread_id=workflow_thread_id,
    )
    print("[chatbot] request payload:\n" + dump_log_payload(request.model_dump()))
    print("[chatbot] graph input:\n" + dump_log_payload(graph_input))
    graph_answer, graph_nodes = run_graph_with_trace(graph, graph_input, graph_config)
    print(
        f"[timing] chatbot.total_graph_to_final_answer took "
        f"{perf_counter() - started_at:.3f}s"
    )
    return build_chatbot_response(
        graph_answer,
        workflow_thread_id=workflow_thread_id,
        graph_nodes=graph_nodes,
    )
