from __future__ import annotations

import io
import json
import os
import re
import unicodedata
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import PurePath

from fastapi import UploadFile, status

from src.features.chatbot.repositories.document_upload_repository import (
    DocumentUploadRepository,
)
from src.features.chatbot.services.document_chunking import (
    DocumentChunk,
    DocumentChunkingService,
    StructureAwareDocumentChunker,
)
from src.features.chatbot.services.document_parsers import (
    DocumentParserError,
    DocumentParserService,
)
from src.features.chatbot.services.document_parsers.xbrl_parser import (
    detect_xbrl_document_kind,
    parse_xbrl_root,
)
from src.features.chatbot.services.document_storage import (
    DocumentStorage,
    LocalDocumentStorage,
)
from src.features.chatbot.services.document_vector_indexing_service import (
    DocumentVectorIndexingService,
)
from src.features.chatbot.services.document_structure import (
    DoclingDocumentStructureAnalyzer,
)
from src.features.membership.core.exceptions import MembershipError
from src.features.membership.core.time import utc_now_iso


DEFAULT_MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024
READ_CHUNK_SIZE_BYTES = 1024 * 1024


def print_document_chunks_log(chunks: list[DocumentChunk]) -> None:
    payload = [chunk.model_dump(mode="json") for chunk in chunks]
    print(
        "\n========== [FINAL EMBEDDING CHUNKS] START ==========\n"
        + json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        + "\n========== [FINAL EMBEDDING CHUNKS] END ==========\n",
        flush=True,
    )


@dataclass(frozen=True)
class AllowedFileType:
    extension: str
    mime_type: str
    accepted_mime_types: frozenset[str]


ALLOWED_FILE_TYPES = {
    "pdf": AllowedFileType(
        extension="pdf",
        mime_type="application/pdf",
        accepted_mime_types=frozenset({"application/pdf"}),
    ),
    "docx": AllowedFileType(
        extension="docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        accepted_mime_types=frozenset({
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        }),
    ),
    "txt": AllowedFileType(
        extension="txt",
        mime_type="text/plain",
        accepted_mime_types=frozenset({"text/plain"}),
    ),
    "md": AllowedFileType(
        extension="md",
        mime_type="text/markdown",
        accepted_mime_types=frozenset({"text/markdown", "text/plain"}),
    ),
    "markdown": AllowedFileType(
        extension="markdown",
        mime_type="text/markdown",
        accepted_mime_types=frozenset({"text/markdown", "text/plain"}),
    ),
    "csv": AllowedFileType(
        extension="csv",
        mime_type="text/csv",
        accepted_mime_types=frozenset({"text/csv", "text/plain", "application/vnd.ms-excel"}),
    ),
    "xlsx": AllowedFileType(
        extension="xlsx",
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        accepted_mime_types=frozenset({
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }),
    ),
    "xbrl": AllowedFileType(
        extension="xbrl",
        mime_type="application/xbrl+xml",
        accepted_mime_types=frozenset({
            "application/xbrl+xml",
            "application/xml",
            "application/xhtml+xml",
            "text/html",
            "text/xml",
        }),
    ),
    "xml": AllowedFileType(
        extension="xbrl",
        mime_type="application/xbrl+xml",
        accepted_mime_types=frozenset({
            "application/xbrl+xml",
            "application/xml",
            "application/xhtml+xml",
            "text/xml",
        }),
    ),
    "html": AllowedFileType(
        extension="html",
        mime_type="text/html",
        accepted_mime_types=frozenset({
            "text/html",
            "application/xhtml+xml",
            "application/xml",
            "text/xml",
        }),
    ),
    "htm": AllowedFileType(
        extension="html",
        mime_type="text/html",
        accepted_mime_types=frozenset({
            "text/html",
            "application/xhtml+xml",
            "application/xml",
            "text/xml",
        }),
    ),
    "xhtml": AllowedFileType(
        extension="html",
        mime_type="application/xhtml+xml",
        accepted_mime_types=frozenset({
            "text/html",
            "application/xhtml+xml",
            "application/xml",
            "text/xml",
        }),
    ),
}
HTML_FILE_EXTENSIONS = frozenset({"html", "htm", "xhtml"})
GENERIC_MIME_TYPES = {"", "application/octet-stream", "binary/octet-stream"}
UNSAFE_FILENAME_CHARACTERS = re.compile(r"[\x00-\x1f\x7f<>:\"/\\|?*]+")


class DocumentUploadError(MembershipError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = status.HTTP_422_UNPROCESSABLE_ENTITY,
        details: dict | None = None,
    ):
        super().__init__(
            message=message,
            code=code,
            status_code=status_code,
            details=details or {},
        )


def configured_max_file_size_bytes() -> int:
    raw_value = os.getenv("CHAT_DOCUMENT_MAX_FILE_SIZE_BYTES", "").strip()
    if not raw_value:
        return DEFAULT_MAX_FILE_SIZE_BYTES
    try:
        value = int(raw_value)
    except ValueError:
        return DEFAULT_MAX_FILE_SIZE_BYTES
    return value if value > 0 else DEFAULT_MAX_FILE_SIZE_BYTES


def sanitize_filename(filename: str) -> str:
    normalized = unicodedata.normalize("NFKC", filename or "")
    basename = PurePath(normalized.replace("\\", "/")).name
    cleaned = UNSAFE_FILENAME_CHARACTERS.sub("_", basename).strip(" .")
    if not cleaned:
        raise DocumentUploadError("INVALID_FILE", "檔名不可為空。")
    if len(cleaned) <= 180:
        return cleaned
    suffix = PurePath(cleaned).suffix
    stem_limit = max(1, 180 - len(suffix))
    return f"{PurePath(cleaned).stem[:stem_limit]}{suffix}"


def validate_file_content(
    filename: str,
    declared_mime_type: str | None,
    content: bytes,
) -> AllowedFileType:
    if not content:
        raise DocumentUploadError("INVALID_FILE", "不可上傳空白檔案。")

    extension = PurePath(filename).suffix.lower().lstrip(".")
    file_type = ALLOWED_FILE_TYPES.get(extension)
    if file_type is None:
        raise DocumentUploadError(
            "UNSUPPORTED_FILE_TYPE",
            "僅支援 PDF、DOCX、HTML、TXT、Markdown、CSV、XLSX 與 XBRL。",
            details={"extension": extension or None},
        )

    if extension in HTML_FILE_EXTENSIONS:
        try:
            document_kind = detect_xbrl_document_kind(content)
        except DocumentParserError:
            document_kind = None
        if document_kind == "inline":
            file_type = ALLOWED_FILE_TYPES["xbrl"]

    normalized_mime_type = (declared_mime_type or "").split(";", 1)[0].strip().lower()
    if (
        normalized_mime_type not in GENERIC_MIME_TYPES
        and normalized_mime_type not in file_type.accepted_mime_types
    ):
        raise DocumentUploadError(
            "INVALID_FILE",
            "檔案內容類型與副檔名不一致。",
            details={"declaredMimeType": normalized_mime_type, "extension": extension},
        )

    if extension == "pdf":
        if not content[:1024].lstrip().startswith(b"%PDF-"):
            raise DocumentUploadError("INVALID_FILE", "PDF 檔案格式無效。")
    elif extension in {"docx", "xlsx"}:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = set(archive.namelist())
        except (OSError, zipfile.BadZipFile):
            raise DocumentUploadError("INVALID_FILE", f"{extension.upper()} 檔案格式無效。")
        required_path = "word/document.xml" if extension == "docx" else "xl/workbook.xml"
        if required_path not in names:
            raise DocumentUploadError(
                "INVALID_FILE",
                f"檔案內容不是有效的 {extension.upper()} 文件。",
            )
    elif file_type.extension == "xbrl":
        try:
            parse_xbrl_root(content)
        except DocumentParserError as exc:
            raise DocumentUploadError(
                "INVALID_FILE",
                exc.message,
                details={"parserCode": exc.code},
            ) from exc
    else:
        if b"\x00" in content:
            raise DocumentUploadError("INVALID_FILE", "文字檔包含不支援的二進位內容。")
        try:
            content.decode("utf-8-sig")
        except UnicodeDecodeError:
            raise DocumentUploadError("INVALID_FILE", "文字檔目前只支援 UTF-8 編碼。")

    return file_type


class DocumentUploadService:
    def __init__(
        self,
        repository: DocumentUploadRepository | None = None,
        storage: DocumentStorage | None = None,
        parser_service: DocumentParserService | None = None,
        document_structure_analyzer: DoclingDocumentStructureAnalyzer | None = None,
        document_chunker: DocumentChunkingService | StructureAwareDocumentChunker | None = None,
        vector_indexing_service: DocumentVectorIndexingService | None = None,
    ):
        self.repository = repository or DocumentUploadRepository()
        self.storage = storage or LocalDocumentStorage()
        self.parser_service = parser_service or DocumentParserService()
        self.document_structure_analyzer = (
            document_structure_analyzer or DoclingDocumentStructureAnalyzer()
        )
        if isinstance(document_chunker, DocumentChunkingService):
            self.document_chunker = document_chunker
        else:
            self.document_chunker = DocumentChunkingService(
                engine=document_chunker,
            )
        self.vector_indexing_service = vector_indexing_service
        self.max_file_size_bytes = configured_max_file_size_bytes()

    async def upload(
        self,
        *,
        file: UploadFile,
        chat_id: str,
        user_id: str,
        case_id: str | None = None,
    ) -> dict:
        chat_id = chat_id.strip()
        case_id = (case_id or "").strip() or None
        if not chat_id or len(chat_id) > 128:
            raise DocumentUploadError("INVALID_CHAT_ID", "對話 ID 格式無效。")
        if not self.repository.conversation_belongs_to_user(chat_id, user_id):
            raise DocumentUploadError(
                "CHAT_NOT_FOUND",
                "找不到這個對話，或您沒有存取權限。",
                status_code=status.HTTP_404_NOT_FOUND,
            )

        filename = sanitize_filename(file.filename or "")
        content = bytearray()
        while chunk := await file.read(READ_CHUNK_SIZE_BYTES):
            content.extend(chunk)
            if len(content) > self.max_file_size_bytes:
                raise DocumentUploadError(
                    "FILE_TOO_LARGE",
                    f"檔案大小不可超過 {self.max_file_size_bytes // (1024 * 1024)} MB。",
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    details={"maxFileSize": self.max_file_size_bytes},
                )

        raw_content = bytes(content)
        file_type = validate_file_content(filename, file.content_type, raw_content)
        document_id = str(uuid.uuid4())
        try:
            document_elements = self.parser_service.parse(
                document_id=document_id,
                file_name=filename,
                file_type=file_type.extension,
                mime_type=file_type.mime_type,
                content=raw_content,
            )
        except DocumentParserError as exc:
            print(
                "[chatbot.document-parser] parse failed:\n"
                + json.dumps(
                    {
                        "fileName": filename,
                        "fileType": file_type.extension,
                        "code": exc.code,
                        "message": exc.message,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                flush=True,
            )
            raise DocumentUploadError(
                "DOCUMENT_PARSE_FAILED",
                exc.message,
                details={"parserCode": exc.code},
            ) from exc

        if not document_elements:
            raise DocumentUploadError(
                "DOCUMENT_PARSE_UNSUPPORTED",
                "文件沒有可供 Chunking 與檢索的內容。",
                details={"fileType": file_type.extension},
            )

        structure_analysis = self.document_structure_analyzer.analyze(
            document_id=document_id,
            file_name=filename,
            file_type=file_type.extension,
            content=raw_content,
            normalized_elements=document_elements,
        )
        document_chunks = self.document_chunker.chunk(
            elements=structure_analysis.elements,
            file_type=file_type.extension,
            chat_id=chat_id,
            case_id=case_id,
            upload_user=user_id,
        )
        print_document_chunks_log(document_chunks)
        now = utc_now_iso()
        storage_key = self.storage.save(
            document_id=document_id,
            extension=file_type.extension,
            content=raw_content,
        )
        payload = {
            "document_id": document_id,
            "chat_id": chat_id,
            "upload_user_id": user_id,
            "case_id": case_id,
            "file_name": filename,
            "file_type": file_type.extension,
            "mime_type": file_type.mime_type,
            "file_size_bytes": len(raw_content),
            "storage_key": storage_key,
            "status": "UPLOADED",
            "created_at": now,
            "updated_at": now,
        }
        try:
            created_document = self.repository.create(payload)
        except Exception:
            self.storage.delete(storage_key)
            raise
        if self.vector_indexing_service is not None:
            try:
                self.vector_indexing_service.index(document_chunks)
            except Exception as exc:
                try:
                    self.vector_indexing_service.delete_by_document(document_id)
                except Exception:
                    pass
                try:
                    self.repository.delete_for_user(document_id, user_id)
                except Exception:
                    pass
                try:
                    self.storage.delete(storage_key)
                except Exception:
                    pass
                raise DocumentUploadError(
                    "DOCUMENT_INDEX_FAILED",
                    "文件已解析，但建立 Embedding 或寫入 Vector DB 失敗。",
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    details={"errorType": type(exc).__name__},
                ) from exc
        return created_document

    def list_for_chat(self, chat_id: str, user_id: str) -> list[dict]:
        chat_id = chat_id.strip()
        if not self.repository.conversation_belongs_to_user(chat_id, user_id):
            raise DocumentUploadError(
                "CHAT_NOT_FOUND",
                "找不到這個對話，或您沒有存取權限。",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return self.repository.list_for_chat(chat_id, user_id)

    def delete(self, document_id: str, user_id: str) -> None:
        if self.vector_indexing_service is not None:
            storage_key = self.repository.storage_key_for_user(document_id, user_id)
            if storage_key is None:
                raise DocumentUploadError(
                    "DOCUMENT_NOT_FOUND",
                    "找不到這份文件，或您沒有刪除權限。",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            self.vector_indexing_service.delete_by_document(document_id)
        storage_key = self.repository.delete_for_user(document_id, user_id)
        if storage_key is None:
            raise DocumentUploadError(
                "DOCUMENT_NOT_FOUND",
                "找不到這份文件，或您沒有刪除權限。",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        self.storage.delete(storage_key)
