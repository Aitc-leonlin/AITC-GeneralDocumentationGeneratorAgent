import io
import unittest
import zipfile

from fastapi import UploadFile

from src.features.chatbot.services.document_upload_service import (
    DocumentUploadError,
    DocumentUploadService,
    sanitize_filename,
    validate_file_content,
)


class FakeDocumentUploadRepository:
    def __init__(self, *, owns_chat: bool = True, delete_result: str | None = "ab/document-1.txt"):
        self.owns_chat = owns_chat
        self.delete_result = delete_result
        self.created_payload = None

    def conversation_belongs_to_user(self, chat_id: str, user_id: str) -> bool:
        return self.owns_chat

    def create(self, payload):
        self.created_payload = payload
        return payload

    def list_for_chat(self, chat_id: str, user_id: str):
        return []

    def delete_for_user(self, document_id: str, user_id: str) -> str | None:
        return self.delete_result


class FakeDocumentStorage:
    def __init__(self):
        self.saved = None
        self.deleted = []

    def save(self, *, document_id: str, extension: str, content: bytes) -> str:
        self.saved = (document_id, extension, content)
        return f"ab/{document_id}.{extension}"

    def delete(self, storage_key: str) -> None:
        self.deleted.append(storage_key)


def office_archive(required_path: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr(required_path, "<document />")
    return buffer.getvalue()


class DocumentUploadValidationTests(unittest.TestCase):
    def test_sanitize_filename_removes_path_and_unsafe_characters(self):
        self.assertEqual(sanitize_filename("../../客戶:報告?.PDF"), "客戶_報告_.PDF")

    def test_supported_file_signatures_are_accepted(self):
        self.assertEqual(
            validate_file_content("report.pdf", "application/pdf", b"%PDF-1.7\n").extension,
            "pdf",
        )
        self.assertEqual(
            validate_file_content(
                "report.docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                office_archive("word/document.xml"),
            ).extension,
            "docx",
        )
        self.assertEqual(
            validate_file_content(
                "report.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                office_archive("xl/workbook.xml"),
            ).extension,
            "xlsx",
        )

    def test_unsupported_extension_is_rejected(self):
        with self.assertRaises(DocumentUploadError) as context:
            validate_file_content("malware.exe", "application/octet-stream", b"MZ")
        self.assertEqual(context.exception.code, "UNSUPPORTED_FILE_TYPE")

    def test_invalid_content_is_rejected(self):
        with self.assertRaises(DocumentUploadError) as context:
            validate_file_content("fake.pdf", "application/pdf", b"not a PDF")
        self.assertEqual(context.exception.code, "INVALID_FILE")

    def test_distinguishes_regular_html_from_inline_xbrl(self):
        regular_html = validate_file_content(
            "report.html",
            "text/html",
            b"<!doctype html><html><body><h1>Report</h1></body></html>",
        )
        inline_xbrl = validate_file_content(
            "filing.html",
            "text/html",
            b"""<html xmlns="http://www.w3.org/1999/xhtml"
              xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
              xmlns:xbrli="http://www.xbrl.org/2003/instance">
              <body><ix:header><xbrli:context id="c1"><xbrli:entity>
              <xbrli:identifier scheme="test">1234</xbrli:identifier></xbrli:entity>
              <xbrli:period><xbrli:instant>2025-12-31</xbrli:instant></xbrli:period>
              </xbrli:context></ix:header><ix:nonNumeric name="dei:DocumentType"
              contextRef="c1">Annual Report</ix:nonNumeric></body></html>""",
        )

        self.assertEqual(regular_html.extension, "html")
        self.assertEqual(inline_xbrl.extension, "xbrl")


class DocumentUploadServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_upload_saves_authenticated_chat_metadata(self):
        repository = FakeDocumentUploadRepository()
        storage = FakeDocumentStorage()
        service = DocumentUploadService(repository=repository, storage=storage)
        upload = UploadFile(filename="notes.txt", file=io.BytesIO("授信文件".encode()))

        await service.upload(file=upload, chat_id="chat-1", user_id="user-1")

        payload = repository.created_payload
        self.assertIsNotNone(payload)
        self.assertEqual(payload["chat_id"], "chat-1")
        self.assertEqual(payload["upload_user_id"], "user-1")
        self.assertEqual(payload["file_type"], "txt")
        self.assertEqual(payload["status"], "UPLOADED")
        self.assertEqual(payload["storage_key"], f"ab/{payload['document_id']}.txt")
        self.assertNotIn("content", payload)
        self.assertEqual(storage.saved[1:], ("txt", "授信文件".encode()))
        self.assertIsNone(payload["case_id"])
        self.assertTrue(payload["document_id"])

    async def test_upload_rejects_file_over_configured_limit(self):
        service = DocumentUploadService(
            repository=FakeDocumentUploadRepository(),
            storage=FakeDocumentStorage(),
        )
        service.max_file_size_bytes = 3
        upload = UploadFile(filename="notes.txt", file=io.BytesIO(b"1234"))

        with self.assertRaises(DocumentUploadError) as context:
            await service.upload(file=upload, chat_id="chat-1", user_id="user-1")
        self.assertEqual(context.exception.code, "FILE_TOO_LARGE")

    async def test_upload_rejects_chat_owned_by_another_user(self):
        service = DocumentUploadService(
            repository=FakeDocumentUploadRepository(owns_chat=False),
            storage=FakeDocumentStorage(),
        )
        upload = UploadFile(filename="notes.txt", file=io.BytesIO(b"hello"))

        with self.assertRaises(DocumentUploadError) as context:
            await service.upload(file=upload, chat_id="chat-1", user_id="user-2")
        self.assertEqual(context.exception.code, "CHAT_NOT_FOUND")

    async def test_upload_rejects_document_without_parseable_content(self):
        service = DocumentUploadService(
            repository=FakeDocumentUploadRepository(),
            storage=FakeDocumentStorage(),
        )
        upload = UploadFile(filename="notes.txt", file=io.BytesIO(b"   \n"))

        with self.assertRaises(DocumentUploadError) as context:
            await service.upload(file=upload, chat_id="chat-1", user_id="user-1")

        self.assertEqual(context.exception.code, "DOCUMENT_PARSE_UNSUPPORTED")

    def test_delete_rejects_document_not_owned_by_user(self):
        service = DocumentUploadService(
            repository=FakeDocumentUploadRepository(delete_result=None),
            storage=FakeDocumentStorage(),
        )
        with self.assertRaises(DocumentUploadError) as context:
            service.delete("document-1", "user-2")
        self.assertEqual(context.exception.code, "DOCUMENT_NOT_FOUND")

    def test_delete_removes_file_from_storage(self):
        storage = FakeDocumentStorage()
        service = DocumentUploadService(
            repository=FakeDocumentUploadRepository(delete_result="ab/document-1.txt"),
            storage=storage,
        )

        service.delete("document-1", "user-1")

        self.assertEqual(storage.deleted, ["ab/document-1.txt"])


if __name__ == "__main__":
    unittest.main()
