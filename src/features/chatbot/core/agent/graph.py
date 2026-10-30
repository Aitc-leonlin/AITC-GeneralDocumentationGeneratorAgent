# import LangGraph lib
from langgraph.graph import StateGraph, START, END
from langgraph.graph import MessagesState
from typing_extensions import TypedDict, NotRequired, Annotated

# import langGraph nodes
from src.features.chatbot.core.agent.nodes.rephrase_question import rephrase_question
from src.features.chatbot.core.agent.nodes.classify_is_question_in_range import (
    classify_is_question_in_range,
)
from src.features.chatbot.core.agent.nodes.extract_semantic_plan_node import extract_semantic_plan_node
from src.features.chatbot.core.agent.nodes.select_applied_expert_knowledge import (
    select_applied_expert_knowledge,
)
from src.features.chatbot.core.agent.nodes.select_applied_warehouse_data import (
    select_applied_warehouse_data,
)
from src.features.chatbot.core.agent.nodes.semantic_retrieval import semantic_retrieval
from src.features.chatbot.core.agent.nodes.use_external_data import (
    query_approved_external_data,
    review_external_data,
    use_external_data,
)
from src.features.chatbot.core.agent.checkpointer import create_graph_checkpointer
from src.features.chatbot.core.agent.nodes.question_out_of_range import question_out_of_range
from src.features.chatbot.core.agent.nodes.classify_semantic_workflow import (
    classify_semantic_workflow,
)
from src.features.chatbot.core.agent.nodes.deep_agent_fallback import deep_agent_fallback
from src.features.chatbot.core.agent.nodes.chroma_rag_test import (
    chroma_rag_test,
    is_chroma_rag_test_question,
)
from src.features.chatbot.core.agent.nodes.semantic_workflow_templates import (
    STANDARD_SEMANTIC_WORKFLOW_HANDLERS,
    STANDARD_SEMANTIC_WORKFLOW_NODES,
)

# import type
from src.features.chatbot.models.langgraph_state_types import OverallState


def initial_request_condition_edge(state: OverallState) -> str:
    """Only the exact Phase 6 test question bypasses the existing Agent workflow."""
    if is_chroma_rag_test_question(state):
        return "chroma_rag_test"
    return "rephrase_question"


def semantic_workflow_condition_edge(state: OverallState) -> str:
    """依徵審 Workflow 分類選擇標準節點，未命中則交給 Deep Agent。"""
    category = str(state.get("semantic_workflow_category") or "OTHER")
    confidence = float(state.get("semantic_workflow_category_confidence") or 0.0)
    if confidence < 0.55:
        return "OTHER"
    return category if category in STANDARD_SEMANTIC_WORKFLOW_NODES else "OTHER"


# 路徑判斷：根據 classify_is_question_in_range 產生的 is_question_in_range 決定是否繼續。
# - "True"：問題屬於財報/授信可處理範圍，進入既有 LLM 類別分類。
# - "False"：問題超出範圍，改由 question_out_of_range 產生固定回覆後結束。
# - 其他值：防呆，直接結束。
def is_question_in_range_edge(state: OverallState) -> str:
    try:
        # print("is_question_in_range_edge in========", state["is_question_in_range"])
        match state["is_question_in_range"]:
            case "True":
                return "classify_semantic_workflow"
            case "False":
                return "question_out_of_range"
            case _:
                return "END"
    except (ValueError, TypeError) as e:
        print(f"發生錯誤: {e}")


# 路徑判斷：use_external_data 判斷 requirements purpose 後，決定是否提前回前端確認。
# - awaiting_external_data_confirmation = True：
#   LLM 判斷需要外部資料，且已產生 external_data_query_text，進入 interrupt 等待前端確認。
# - False：不需要外查或已處理完外部資料狀態，繼續執行專家知識與資料倉儲節點。
def external_data_condition_edge(state: OverallState) -> str:
    if bool(state.get("awaiting_external_data_confirmation")):
        return "review_external_data"
    return "select_applied_expert_knowledge"


def reviewed_external_data_condition_edge(state: OverallState) -> str:
    if str(state.get("external_data_decision") or "").strip().lower() == "adopted":
        return "query_approved_external_data"
    return "select_applied_expert_knowledge"


# ===========宣告Graph Workflow
workflow = StateGraph(OverallState)

# ===========宣告 LangGraph Node 與各節點職責：
# - rephrase_question：依照對話歷史重寫問題，讓後續節點拿到可獨立理解的查詢文字。
workflow.add_node(rephrase_question)

# - classify_is_question_in_range：判斷問題是否屬於財報/授信系統處理範圍。
workflow.add_node(classify_is_question_in_range)

# - extract_semantic_plan_node：所有標準 Workflow 共用，規劃 requirements 與各 requirement 的 purpose。
workflow.add_node(extract_semantic_plan_node)

# - use_external_data：根據 requirements[].purpose 判斷是否需要外部資料，必要時產生 external_data_query_text 給前端確認。
workflow.add_node(use_external_data)

# - review_external_data：以 interrupt 暫停，等待人工採用、修改或拒絕外部查詢文字。
workflow.add_node(review_external_data)

# - query_approved_external_data：只在人工採用後執行外部網路搜尋。
workflow.add_node(query_approved_external_data)

# - select_applied_expert_knowledge：根據前端傳入的 appliedExpertKnowledge 選出本題要套用的專家知識。
workflow.add_node(select_applied_expert_knowledge)

# - select_applied_warehouse_data：固定執行；節點內根據 useWarehouseData 決定是否套用前端傳入的 appliedWarehouseData。
workflow.add_node(select_applied_warehouse_data)

# - semantic_retrieval：依 semantic plan 查財報資料，整合專家知識/資料倉儲/外部資料後產生分析回答。
workflow.add_node(semantic_retrieval)

# - question_out_of_range：問題超出處理範圍時產生回覆。
workflow.add_node(question_out_of_range)

# - classify_semantic_workflow：將範圍內問題分類為 14 種徵審 Workflow。
workflow.add_node(classify_semantic_workflow)

# - 14 個標準 Workflow 注入各分類的分析目的、資料、RAG 與輸出模板；模板仍待專業人員微調。
for semantic_node_name, semantic_node_handler in STANDARD_SEMANTIC_WORKFLOW_HANDLERS.items():
    workflow.add_node(semantic_node_name, semantic_node_handler)

# - deep_agent_fallback：處理無法歸入 14 種標準 Workflow 的徵審問題。
workflow.add_node(deep_agent_fallback)

# - chroma_rag_test：Phase 6 專用測試路由，執行 query embedding、metadata filter 與 Top-K Chroma search。
workflow.add_node(chroma_rag_test)

# =========宣告 LangGraph Edge：
# START 先精確比對 Phase 6 測試問題；未命中仍走原有的問題重寫流程。
workflow.add_conditional_edges(
    source=START,
    path=initial_request_condition_edge,
    path_map={
        "chroma_rag_test": "chroma_rag_test",
        "rephrase_question": "rephrase_question",
    },
)
workflow.add_edge("chroma_rag_test", END)

# 重寫完成後，先判斷是否屬於系統處理範圍。
workflow.add_edge("rephrase_question", "classify_is_question_in_range")
workflow.add_conditional_edges(
    source="classify_is_question_in_range",
    path=is_question_in_range_edge,
    path_map={
        "classify_semantic_workflow": "classify_semantic_workflow",
        "question_out_of_range": "question_out_of_range",
    },
)
workflow.add_edge("question_out_of_range", END)

# 類別路由：命中標準類別就進入對應 Python Workflow 模板；OTHER 交由 Deep Agent。
workflow.add_conditional_edges(
    source="classify_semantic_workflow",
    path=semantic_workflow_condition_edge,
    path_map={
        **STANDARD_SEMANTIC_WORKFLOW_NODES,
        "OTHER": "deep_agent_fallback",
    },
)

# 14 個標準 Workflow 都共用資料規劃、前端來源勾選及檢索流程。
for semantic_node_name in STANDARD_SEMANTIC_WORKFLOW_NODES.values():
    workflow.add_edge(semantic_node_name, "extract_semantic_plan_node")
workflow.add_edge("deep_agent_fallback", END)

# 共用分析路線：先規劃 requirements，再由 use_external_data 節點依前端勾選判斷是否需要外查。
# 若 LLM 判斷需要外部資料，本輪會在 review_external_data 暫停並回傳確認內容；
# 若不需要外部資料，才繼續執行專家知識與資料倉儲節點。
workflow.add_edge("extract_semantic_plan_node", "use_external_data")

# 外部資料需求判斷後，若需要前端確認 externalDataQueryText 就進入 interrupt；
# 否則回到正常流程，繼續執行專家知識與資料倉儲節點。
workflow.add_conditional_edges(
    source="use_external_data",
    path=external_data_condition_edge,
    path_map={
        "review_external_data": "review_external_data",
        "select_applied_expert_knowledge": "select_applied_expert_knowledge",
    },
)

# 人工恢復流程後，採用才執行外查；拒絕則直接回到正常分析流程。
workflow.add_conditional_edges(
    source="review_external_data",
    path=reviewed_external_data_condition_edge,
    path_map={
        "query_approved_external_data": "query_approved_external_data",
        "select_applied_expert_knowledge": "select_applied_expert_knowledge",
    },
)
workflow.add_edge("query_approved_external_data", "select_applied_expert_knowledge")

# SEMANTIC 正常流程：先選專家知識，再執行資料倉儲節點。
workflow.add_edge("select_applied_expert_knowledge", "select_applied_warehouse_data")
workflow.add_edge("select_applied_warehouse_data", "semantic_retrieval")

# 語意檢索節點產生最終分析答案後結束。
workflow.add_edge("semantic_retrieval", END)

# interrupt/resume 必須搭配 checkpointer；依 DATABASE_MODE 使用 SQLite 或 PostgreSQL。
graph = workflow.compile(checkpointer=create_graph_checkpointer())
