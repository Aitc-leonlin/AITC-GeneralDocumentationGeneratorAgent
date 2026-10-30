from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

from src.features.chatbot.models.vector_store import VectorRecord
from src.features.chatbot.repositories.vector_store_repository import (
    VectorStoreRepository,
)
from src.features.chatbot.services.document_chunking import DocumentChunk
from src.features.chatbot.services.embedding_service import (
    DEFAULT_EMBEDDING_MAX_TOKENS,
    DEFAULT_EMBEDDING_MODEL,
    EmbeddingService,
)


EMBEDDING_SEGMENT_OVERLAP_ENV = "CHAT_EMBEDDING_SEGMENT_OVERLAP"
DEFAULT_EMBEDDING_SEGMENT_OVERLAP = 64


@dataclass(frozen=True)
class EmbeddingSegment:
    source: DocumentChunk
    text: str
    segment_index: int
    segment_count: int
    model_token_count: int


class EmbeddingInputSegmenter(Protocol):
    def segment(self, chunks: list[DocumentChunk]) -> list[EmbeddingSegment]: ...


class E5EmbeddingInputSegmenter:
    """Split only chunks that exceed E5's input window; preserve source chunks."""

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        max_tokens: int = DEFAULT_EMBEDDING_MAX_TOKENS,
        overlap_tokens: int | None = None,
        tokenizer: Any | None = None,
    ) -> None:
        self.model_name = model_name
        self.max_tokens = max_tokens
        self.overlap_tokens = (
            overlap_tokens
            if overlap_tokens is not None
            else self._configured_overlap()
        )
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be greater than zero")
        if self.overlap_tokens < 0:
            raise ValueError("overlap_tokens cannot be negative")
        self._tokenizer = tokenizer

    @property
    def tokenizer(self) -> Any:
        if self._tokenizer is None:
            from transformers import AutoTokenizer

            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        return self._tokenizer

    def segment(self, chunks: list[DocumentChunk]) -> list[EmbeddingSegment]:
        output: list[EmbeddingSegment] = []
        for chunk in chunks:
            texts = self._split_text(chunk.content)
            output.extend(
                EmbeddingSegment(
                    source=chunk,
                    text=text,
                    segment_index=index,
                    segment_count=len(texts),
                    model_token_count=self._token_count(text),
                )
                for index, text in enumerate(texts)
            )
        return output

    def _split_text(self, text: str) -> list[str]:
        normalized = text.strip()
        if not normalized:
            return []
        if self._token_count(normalized) <= self.max_tokens:
            return [normalized]

        prefix_ids = self.tokenizer.encode("passage: ", add_special_tokens=False)
        special_tokens = int(self.tokenizer.num_special_tokens_to_add(pair=False))
        content_budget = self.max_tokens - len(prefix_ids) - special_tokens
        if content_budget <= 0:
            raise ValueError("E5 prefix leaves no tokens available for document text.")
        if self.overlap_tokens >= content_budget:
            raise ValueError("Embedding segment overlap must be smaller than content budget.")

        token_ids = self.tokenizer.encode(normalized, add_special_tokens=False)
        segments: list[str] = []
        start = 0
        while start < len(token_ids):
            maximum_end = min(len(token_ids), start + content_budget)
            end = self._largest_safe_end(token_ids, start, maximum_end)
            if end <= start:
                raise ValueError("Unable to create a non-empty E5 embedding segment.")
            segment = self.tokenizer.decode(
                token_ids[start:end],
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            ).strip()
            if segment:
                segments.append(segment)
            if end >= len(token_ids):
                break
            start = max(start + 1, end - self.overlap_tokens)
        return segments

    def _largest_safe_end(
        self,
        token_ids: list[int],
        start: int,
        maximum_end: int,
    ) -> int:
        low = start + 1
        high = maximum_end
        best = start
        while low <= high:
            middle = (low + high) // 2
            candidate = self.tokenizer.decode(
                token_ids[start:middle],
                skip_special_tokens=True,
                clean_up_tokenization_spaces=False,
            ).strip()
            if candidate and self._token_count(candidate) <= self.max_tokens:
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        return best

    def _token_count(self, text: str) -> int:
        return len(
            self.tokenizer.encode(
                f"passage: {text}",
                add_special_tokens=True,
                truncation=False,
            )
        )

    @staticmethod
    def _configured_overlap() -> int:
        try:
            value = int(os.getenv(EMBEDDING_SEGMENT_OVERLAP_ENV, "").strip())
        except ValueError:
            return DEFAULT_EMBEDDING_SEGMENT_OVERLAP
        return value if value >= 0 else DEFAULT_EMBEDDING_SEGMENT_OVERLAP


class DocumentVectorIndexingService:
    def __init__(
        self,
        *,
        embedding_service: EmbeddingService,
        vector_repository: VectorStoreRepository,
        segmenter: EmbeddingInputSegmenter,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        indexed_content_types: frozenset[str] = frozenset({"text"}),
    ) -> None:
        self.embedding_service = embedding_service
        self.vector_repository = vector_repository
        self.segmenter = segmenter
        self.embedding_model = embedding_model
        self.indexed_content_types = indexed_content_types

    def index(self, chunks: list[DocumentChunk]) -> list[VectorRecord]:
        indexable_chunks = [
            chunk
            for chunk in chunks
            if chunk.content_type in self.indexed_content_types
        ]
        segments = self.segmenter.segment(indexable_chunks)
        if not segments:
            return []
        embeddings = self.embedding_service.embed_documents(
            [segment.text for segment in segments]
        )
        if len(embeddings) != len(segments):
            raise ValueError("Embedding result count does not match segment count.")
        records = [
            self._record(segment, embedding)
            for segment, embedding in zip(segments, embeddings)
        ]
        self.vector_repository.upsert(records)
        return records

    def delete_by_document(self, document_id: str) -> None:
        self.vector_repository.delete_by_document(document_id)

    def delete_by_chat(self, chat_id: str) -> None:
        self.vector_repository.delete_by_chat(chat_id)

    def _record(
        self,
        segment: EmbeddingSegment,
        embedding: list[float],
    ) -> VectorRecord:
        chunk = segment.source
        record_id = (
            chunk.chunk_id
            if segment.segment_count == 1
            else f"{chunk.chunk_id}:segment:{segment.segment_index}"
        )
        metadata = {
            "source_chunk_id": chunk.chunk_id,
            "source_chunk_index": chunk.chunk_index,
            "chunk_index": chunk.chunk_index,
            "embedding_segment_index": segment.segment_index,
            "embedding_segment_count": segment.segment_count,
            "embedding_token_count": segment.model_token_count,
            "embedding_model": self.embedding_model,
            "document_title": chunk.document_title,
            "file_name": chunk.file_name,
            "file_type": chunk.file_type,
            "content_type": chunk.content_type,
            "section_title": chunk.section_title,
            "section_level": chunk.section_level,
            "parent_section": chunk.parent_section,
            "page_number": chunk.page_number,
            "sheet": chunk.sheet,
            "structure_level": chunk.metadata.get("structure_level"),
            "chunking_strategy": chunk.metadata.get("chunking_strategy"),
            "source_token_count": chunk.metadata.get("token_count"),
            "source_overlap_token_count": chunk.metadata.get(
                "overlap_token_count"
            ),
        }
        for key in (
            "concept",
            "qualified_name",
            "label",
            "entity",
            "report_type",
            "context_ref",
            "period",
            "dimensions",
            "unit",
            "unit_ref",
            "value",
            "decimals",
            "scale",
            "sign",
            "format",
            "nil",
            "tableTitle",
            "table_title",
            "caption",
        ):
            if key in chunk.metadata:
                metadata[key] = chunk.metadata[key]
        return VectorRecord(
            id=record_id,
            text=segment.text,
            embedding=embedding,
            document_id=chunk.document_id,
            chat_id=chunk.chat_id,
            case_id=chunk.case_id,
            user_id=chunk.upload_user,
            metadata=metadata,
        )
