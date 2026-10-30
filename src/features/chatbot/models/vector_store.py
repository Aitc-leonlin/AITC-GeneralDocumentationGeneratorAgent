from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class VectorRecord(BaseModel):
    """Vector-store-neutral record produced after embedding a chunk segment."""

    id: str
    text: str
    embedding: list[float]
    document_id: str
    chat_id: str | None = None
    case_id: str | None = None
    user_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class VectorSearchFilter(BaseModel):
    document_id: str | None = None
    chat_id: str | None = None
    case_id: str | None = None
    user_id: str | None = None


class VectorSearchResult(BaseModel):
    id: str
    text: str
    document_id: str
    chat_id: str | None = None
    case_id: str | None = None
    user_id: str
    distance: float
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievedChunk(BaseModel):
    """Source-aware retrieval result exposed to the RAG application layer."""

    content: str
    score: float
    document_id: str
    file_name: str | None = None
    page: int | None = None
    section: str | None = None
    chunk_id: str
    chat_id: str | None = None
    case_id: str | None = None
    user_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
