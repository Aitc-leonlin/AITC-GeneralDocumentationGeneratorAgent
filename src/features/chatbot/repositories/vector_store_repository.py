from __future__ import annotations

import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from src.features.chatbot.models.vector_store import (
    VectorRecord,
    VectorSearchFilter,
    VectorSearchResult,
)
from src.shared.database.config import PROJECT_ROOT


VECTOR_STORE_DIR_ENV = "CHAT_VECTOR_STORE_DIR"
VECTOR_COLLECTION_ENV = "CHAT_VECTOR_COLLECTION"
CHROMA_MODE_ENV = "CHAT_CHROMA_MODE"
CHROMA_HOST_ENV = "CHAT_CHROMA_HOST"
CHROMA_PORT_ENV = "CHAT_CHROMA_PORT"
CHROMA_SSL_ENV = "CHAT_CHROMA_SSL"
CHROMA_TENANT_ENV = "CHAT_CHROMA_TENANT"
CHROMA_DATABASE_ENV = "CHAT_CHROMA_DATABASE"
DEFAULT_VECTOR_STORE_DIR = PROJECT_ROOT / "storage" / "chroma"
DEFAULT_VECTOR_COLLECTION = "chat_documents_multilingual_e5_large"
DEFAULT_CHROMA_MODE = "http"
DEFAULT_CHROMA_HOST = "127.0.0.1"
DEFAULT_CHROMA_PORT = 8010
DEFAULT_CHROMA_TENANT = "default_tenant"
DEFAULT_CHROMA_DATABASE = "default_database"


class VectorStoreRepository(ABC):
    @abstractmethod
    def upsert(self, records: list[VectorRecord]) -> None:
        raise NotImplementedError

    @abstractmethod
    def search(
        self,
        query_vector: list[float],
        filters: VectorSearchFilter,
        top_k: int = 10,
    ) -> list[VectorSearchResult]:
        raise NotImplementedError

    @abstractmethod
    def delete_by_document(self, document_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete_by_chat(self, chat_id: str) -> None:
        raise NotImplementedError


class ChromaVectorStoreRepository(VectorStoreRepository):
    """Chroma adapter; no embedding or retrieval policy belongs in this class."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        persist_directory: str | Path | None = None,
        collection_name: str | None = None,
        embedding_model: str = "intfloat/multilingual-e5-large",
        embedding_dimension: int = 1024,
        mode: str | None = None,
        host: str | None = None,
        port: int | None = None,
        ssl: bool | None = None,
        tenant: str | None = None,
        database: str | None = None,
    ) -> None:
        configured_directory = os.getenv(VECTOR_STORE_DIR_ENV, "").strip()
        directory = Path(
            persist_directory or configured_directory or DEFAULT_VECTOR_STORE_DIR
        )
        if not directory.is_absolute():
            directory = PROJECT_ROOT / directory
        self.persist_directory = directory.expanduser().resolve()
        self.collection_name = (
            collection_name
            or os.getenv(VECTOR_COLLECTION_ENV, "").strip()
            or DEFAULT_VECTOR_COLLECTION
        )
        self.embedding_model = embedding_model
        self.embedding_dimension = embedding_dimension
        self.mode = (
            mode or os.getenv(CHROMA_MODE_ENV, "").strip() or DEFAULT_CHROMA_MODE
        ).lower()
        if self.mode not in {"http", "persistent"}:
            raise ValueError("CHAT_CHROMA_MODE must be 'http' or 'persistent'.")
        self.host = (
            host or os.getenv(CHROMA_HOST_ENV, "").strip() or DEFAULT_CHROMA_HOST
        )
        self.port = port or self._configured_port()
        self.ssl = ssl if ssl is not None else self._configured_ssl()
        self.tenant = (
            tenant
            or os.getenv(CHROMA_TENANT_ENV, "").strip()
            or DEFAULT_CHROMA_TENANT
        )
        self.database = (
            database
            or os.getenv(CHROMA_DATABASE_ENV, "").strip()
            or DEFAULT_CHROMA_DATABASE
        )
        self._client = client
        self._collection: Any | None = None

    @property
    def client(self) -> Any:
        if self._client is None:
            import chromadb

            if self.mode == "http":
                self._client = chromadb.HttpClient(
                    host=self.host,
                    port=self.port,
                    ssl=self.ssl,
                    tenant=self.tenant,
                    database=self.database,
                )
            else:
                self.persist_directory.mkdir(parents=True, exist_ok=True)
                self._client = chromadb.PersistentClient(
                    path=str(self.persist_directory),
                    tenant=self.tenant,
                    database=self.database,
                )
        return self._client

    @property
    def collection(self) -> Any:
        if self._collection is None:
            self._collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={
                    "hnsw:space": "cosine",
                    "embedding_model": self.embedding_model,
                    "embedding_dimension": self.embedding_dimension,
                },
                embedding_function=None,
            )
            metadata = self._collection.metadata or {}
            if metadata.get("embedding_model") != self.embedding_model:
                raise ValueError(
                    "Chroma collection embedding model does not match configuration."
                )
            if int(metadata.get("embedding_dimension", 0)) != self.embedding_dimension:
                raise ValueError(
                    "Chroma collection embedding dimension does not match configuration."
                )
        return self._collection

    def upsert(self, records: list[VectorRecord]) -> None:
        if not records:
            return
        for record in records:
            if len(record.embedding) != self.embedding_dimension:
                raise ValueError(
                    f"Vector {record.id} has dimension {len(record.embedding)}; "
                    f"expected {self.embedding_dimension}."
                )
        self.collection.upsert(
            ids=[record.id for record in records],
            embeddings=[record.embedding for record in records],
            documents=[record.text for record in records],
            metadatas=[self._metadata(record) for record in records],
        )

    def search(
        self,
        query_vector: list[float],
        filters: VectorSearchFilter,
        top_k: int = 10,
    ) -> list[VectorSearchResult]:
        if top_k <= 0:
            return []
        if len(query_vector) != self.embedding_dimension:
            raise ValueError(
                f"Query vector has dimension {len(query_vector)}; "
                f"expected {self.embedding_dimension}."
            )
        result = self.collection.query(
            query_embeddings=[query_vector],
            n_results=top_k,
            where=self._where(filters),
            include=["documents", "metadatas", "distances"],
        )
        ids = (result.get("ids") or [[]])[0]
        documents = (result.get("documents") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        output: list[VectorSearchResult] = []
        for record_id, text, metadata, distance in zip(
            ids,
            documents,
            metadatas,
            distances,
        ):
            values = dict(metadata or {})
            document_id = str(values.pop("document_id"))
            chat_id = self._optional_string(values.pop("chat_id", None))
            case_id = self._optional_string(values.pop("case_id", None))
            user_id = str(values.pop("user_id"))
            numeric_distance = float(distance)
            output.append(
                VectorSearchResult(
                    id=str(record_id),
                    text=str(text or ""),
                    document_id=document_id,
                    chat_id=chat_id,
                    case_id=case_id,
                    user_id=user_id,
                    distance=numeric_distance,
                    score=1.0 - numeric_distance,
                    metadata=values,
                )
            )
        return output

    def delete_by_document(self, document_id: str) -> None:
        normalized = document_id.strip()
        if normalized:
            self.collection.delete(where={"document_id": normalized})

    def delete_by_chat(self, chat_id: str) -> None:
        normalized = chat_id.strip()
        if normalized:
            self.collection.delete(where={"chat_id": normalized})

    @staticmethod
    def _where(filters: VectorSearchFilter) -> dict[str, Any] | None:
        clauses = [
            {key: value}
            for key, value in filters.model_dump().items()
            if value is not None
        ]
        if not clauses:
            return None
        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}

    @classmethod
    def _metadata(cls, record: VectorRecord) -> dict[str, Any]:
        metadata: dict[str, Any] = {
            "document_id": record.document_id,
            "user_id": record.user_id,
        }
        if record.chat_id is not None:
            metadata["chat_id"] = record.chat_id
        if record.case_id is not None:
            metadata["case_id"] = record.case_id
        reserved_keys = {"document_id", "chat_id", "case_id", "user_id"}
        for key, value in record.metadata.items():
            if key in reserved_keys:
                continue
            if value is None or isinstance(value, (dict, list, tuple, set)):
                continue
            if isinstance(value, (str, int, float, bool)):
                metadata[key] = value
        return metadata

    @staticmethod
    def _optional_string(value: object) -> str | None:
        normalized = str(value or "").strip()
        return normalized or None

    @staticmethod
    def _configured_port() -> int:
        try:
            value = int(os.getenv(CHROMA_PORT_ENV, "").strip())
        except ValueError:
            return DEFAULT_CHROMA_PORT
        return value if 1 <= value <= 65535 else DEFAULT_CHROMA_PORT

    @staticmethod
    def _configured_ssl() -> bool:
        return os.getenv(CHROMA_SSL_ENV, "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
