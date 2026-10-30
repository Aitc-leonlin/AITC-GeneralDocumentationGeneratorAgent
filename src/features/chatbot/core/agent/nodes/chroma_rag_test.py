from __future__ import annotations

import json

from src.features.chatbot.models.langgraph_state_types import OverallState
from src.features.chatbot.models.vector_store import VectorSearchFilter
from src.features.chatbot.services.vector_service_factory import retrieval_service


CHROMA_RAG_TEST_QUESTION = "請從我上傳的文件中查詢償債能力分析。"
CHROMA_RAG_TEST_TOP_K = 5


def is_chroma_rag_test_question(state: OverallState) -> bool:
    request_lines = (
        line.strip()
        for line in str(state.get("original_question") or "").splitlines()
    )
    return CHROMA_RAG_TEST_QUESTION in request_lines


def chroma_rag_test(state: OverallState) -> OverallState:
    """Phase 6 smoke route: query Chroma and expose source-aware Top-K chunks."""
    request_question = str(state.get("original_question") or "").strip()
    query = CHROMA_RAG_TEST_QUESTION
    chat_id = str(state.get("conversation_id") or "").strip()
    user_id = str(state.get("user_id") or "").strip()

    if not chat_id or not user_id:
        print("========== [CHROMA_RAG_RETRIEVAL_RESULTS] START ==========")
        print(
            json.dumps(
                {
                    "question": query,
                    "request_question": request_question,
                    "filters": {"chat_id": chat_id, "user_id": user_id},
                    "result_count": 0,
                    "results": [],
                    "error": "Missing conversationId/chat_id or user_id.",
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print("========== [CHROMA_RAG_RETRIEVAL_RESULTS] END ==========")
        return {
            **state,
            "answer": "RAG 測試需要 conversationId 與登入使用者資訊。",
            "rag_context": "",
            "retrieval_results": [],
        }

    service = retrieval_service()
    chunks = service.retrieve_chunks(
        query=query,
        filters=VectorSearchFilter(chat_id=chat_id, user_id=user_id),
        top_k=CHROMA_RAG_TEST_TOP_K,
    )
    serialized_chunks = [chunk.model_dump() for chunk in chunks]
    context = service.build_context(chunks)

    print(
        "[CHROMA_RAG_TEST] "
        f"question={query!r} chat_id={chat_id!r} user_id={user_id!r} "
        f"top_k={CHROMA_RAG_TEST_TOP_K} result_count={len(chunks)}"
    )
    log_results = [
        {
            "rank": rank,
            **chunk,
        }
        for rank, chunk in enumerate(serialized_chunks, start=1)
    ]
    print("========== [CHROMA_RAG_RETRIEVAL_RESULTS] START ==========")
    print(
        json.dumps(
            {
                "question": query,
                "request_question": request_question,
                "filters": {"chat_id": chat_id, "user_id": user_id},
                "result_count": len(log_results),
                "results": log_results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print("========== [CHROMA_RAG_RETRIEVAL_RESULTS] END ==========")

    answer = (
        "以下是 Chroma 向量檢索取得的 Top-K Context：\n\n" + context
        if context
        else "在目前 conversationId 與 user_id 篩選範圍內找不到向量資料。"
    )
    return {
        **state,
        "answer": answer,
        "rag_context": context,
        "retrieval_results": serialized_chunks,
        "reference_data": {
            "retrieval_results": serialized_chunks,
            "metadata_filter": {
                "chat_id": chat_id,
                "user_id": user_id,
            },
        },
    }
