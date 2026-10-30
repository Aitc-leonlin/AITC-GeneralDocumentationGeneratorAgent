import os
from functools import lru_cache

from src.features.chatbot.repositories.vector_store_repository import (
    ChromaVectorStoreRepository,
    VectorStoreRepository,
)
from src.features.chatbot.services.document_vector_indexing_service import (
    DocumentVectorIndexingService,
    E5EmbeddingInputSegmenter,
)
from src.features.chatbot.services.embedding_service import (
    DEFAULT_EMBEDDING_DIMENSION,
    DEFAULT_EMBEDDING_MAX_TOKENS,
    MultilingualE5EmbeddingService,
)
from src.features.chatbot.services.retrieval_service import RetrievalService


VECTOR_STORE_PROVIDER_ENV = "CHAT_VECTOR_STORE_PROVIDER"


@lru_cache(maxsize=1)
def embedding_service() -> MultilingualE5EmbeddingService:
    return MultilingualE5EmbeddingService()


@lru_cache(maxsize=1)
def vector_repository() -> VectorStoreRepository:
    service = embedding_service()
    provider = os.getenv(VECTOR_STORE_PROVIDER_ENV, "chroma").strip().lower()
    if provider != "chroma":
        raise ValueError(f"Unsupported vector store provider: {provider}")
    return ChromaVectorStoreRepository(
        embedding_model=service.model_name,
        embedding_dimension=DEFAULT_EMBEDDING_DIMENSION,
    )


@lru_cache(maxsize=1)
def document_vector_indexing_service() -> DocumentVectorIndexingService:
    service = embedding_service()
    return DocumentVectorIndexingService(
        embedding_service=service,
        vector_repository=vector_repository(),
        segmenter=E5EmbeddingInputSegmenter(
            model_name=service.model_name,
            max_tokens=DEFAULT_EMBEDDING_MAX_TOKENS,
        ),
        embedding_model=service.model_name,
    )


@lru_cache(maxsize=1)
def retrieval_service() -> RetrievalService:
    return RetrievalService(
        embedding_service=embedding_service(),
        vector_repository=vector_repository(),
    )
