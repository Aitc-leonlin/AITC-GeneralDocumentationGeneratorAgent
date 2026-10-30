from __future__ import annotations

import os
import re
import tempfile
import uuid
from pathlib import Path
from typing import Protocol

from src.shared.database.config import PROJECT_ROOT


DOCUMENT_STORAGE_DIR_ENV = "CHAT_DOCUMENT_STORAGE_DIR"
DEFAULT_DOCUMENT_STORAGE_DIR = PROJECT_ROOT / "storage" / "chat_documents"
STORAGE_KEY_PATTERN = re.compile(
    r"^(?P<shard>[0-9a-f]{2})/(?P<document_id>[0-9a-f-]{36})\.(?P<extension>[a-z0-9]+)$"
)


class DocumentStorage(Protocol):
    def save(self, *, document_id: str, extension: str, content: bytes) -> str: ...

    def delete(self, storage_key: str) -> None: ...


class LocalDocumentStorage:
    """Local disk adapter that can later be replaced by object storage."""

    def __init__(self, root: Path | None = None):
        configured = os.getenv(DOCUMENT_STORAGE_DIR_ENV, "").strip()
        storage_root = root or (Path(configured) if configured else DEFAULT_DOCUMENT_STORAGE_DIR)
        if not storage_root.is_absolute():
            storage_root = PROJECT_ROOT / storage_root
        self.root = storage_root.expanduser().resolve()

    def save(self, *, document_id: str, extension: str, content: bytes) -> str:
        storage_key = self.build_storage_key(document_id, extension)
        destination = self._resolve(storage_key)
        destination.parent.mkdir(parents=True, exist_ok=True)

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
                temporary_path = Path(temporary_file.name)
            os.replace(temporary_path, destination)
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
        return storage_key

    def delete(self, storage_key: str) -> None:
        path = self._resolve(storage_key)
        path.unlink(missing_ok=True)
        try:
            path.parent.rmdir()
        except OSError:
            pass

    @staticmethod
    def build_storage_key(document_id: str, extension: str) -> str:
        normalized_id = str(uuid.UUID(document_id))
        normalized_extension = extension.strip().lower()
        if not re.fullmatch(r"[a-z0-9]+", normalized_extension):
            raise ValueError("Invalid document storage extension.")
        return f"{normalized_id.replace('-', '')[:2]}/{normalized_id}.{normalized_extension}"

    def _resolve(self, storage_key: str) -> Path:
        match = STORAGE_KEY_PATTERN.fullmatch(storage_key)
        if match is None:
            raise ValueError("Invalid document storage key.")
        document_id = str(uuid.UUID(match.group("document_id")))
        expected_shard = document_id.replace("-", "")[:2]
        if match.group("shard") != expected_shard:
            raise ValueError("Invalid document storage shard.")
        path = (self.root / storage_key).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Document storage path escapes the configured root.")
        return path
