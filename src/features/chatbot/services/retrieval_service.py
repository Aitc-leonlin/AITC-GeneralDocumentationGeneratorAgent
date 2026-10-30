from __future__ import annotations

from src.features.chatbot.models.vector_store import (
    RetrievedChunk,
    VectorSearchFilter,
    VectorSearchResult,
)
from src.features.chatbot.repositories.vector_store_repository import (
    VectorStoreRepository,
)
from src.features.chatbot.services.embedding_service import EmbeddingService


class RetrievalService:
    def __init__(
        self,
        *,
        embedding_service: EmbeddingService,
        vector_repository: VectorStoreRepository,
    ) -> None:
        self.embedding_service = embedding_service
        self.vector_repository = vector_repository

    def retrieve(
        self,
        query: str,
        filters: VectorSearchFilter,
        top_k: int = 10,
    ) -> list[VectorSearchResult]:
        query_vector = self.embedding_service.embed_query(query)
        return self.vector_repository.search(
            query_vector=query_vector,
            filters=filters,
            top_k=top_k,
        )

    def retrieve_chunks(
        self,
        query: str,
        filters: VectorSearchFilter,
        top_k: int = 10,
    ) -> list[RetrievedChunk]:
        """Retrieve context chunks without discarding their source metadata."""
        return [
            self._to_retrieved_chunk(result)
            for result in self.retrieve(query, filters, top_k)
        ]

    @staticmethod
    def build_context(chunks: list[RetrievedChunk]) -> str:
        sections: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            source_parts = [f"file={chunk.file_name or 'unknown'}"]
            if chunk.page is not None:
                source_parts.append(f"page={chunk.page}")
            if chunk.section:
                source_parts.append(f"section={chunk.section}")
            source_parts.append(f"score={chunk.score:.4f}")
            sections.append(
                f"[Context {index} | {' | '.join(source_parts)}]\n{chunk.content}"
            )
        return "\n\n".join(sections)

    @staticmethod
    def _to_retrieved_chunk(result: VectorSearchResult) -> RetrievedChunk:
        metadata = dict(result.metadata)
        page_value = metadata.get("page_number")
        try:
            page = int(page_value) if page_value is not None else None
        except (TypeError, ValueError):
            page = None
        return RetrievedChunk(
            content=result.text,
            score=result.score,
            document_id=result.document_id,
            file_name=RetrievalService._optional_text(metadata.get("file_name")),
            page=page,
            section=RetrievalService._optional_text(
                metadata.get("section_title")
                or metadata.get("parent_section")
            ),
            chunk_id=result.id,
            chat_id=result.chat_id,
            case_id=result.case_id,
            user_id=result.user_id,
            metadata=metadata,
        )

    @staticmethod
    def _optional_text(value: object) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None
