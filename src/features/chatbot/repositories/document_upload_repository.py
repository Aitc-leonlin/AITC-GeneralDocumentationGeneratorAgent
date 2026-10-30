from typing import Any

from src.features.membership.core.database import get_membership_connection
from src.features.membership.core.time import utc_now_iso


class DocumentUploadRepository:
    def conversation_belongs_to_user(self, chat_id: str, user_id: str) -> bool:
        with get_membership_connection() as connection:
            row = connection.execute(
                """
                SELECT 1
                FROM chat_conversation
                WHERE id = ? AND user_id = ? AND deleted_at IS NULL
                LIMIT 1
                """,
                [chat_id, user_id],
            ).fetchone()
        return row is not None

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        with get_membership_connection() as connection:
            connection.begin_write_transaction()
            connection.insert("chat_document", payload)
            connection.commit()
        return self._metadata(payload)

    def list_for_chat(self, chat_id: str, user_id: str) -> list[dict[str, Any]]:
        with get_membership_connection() as connection:
            rows = connection.execute(
                """
                SELECT document_id, chat_id, upload_user_id, case_id, file_name,
                       file_type, mime_type, file_size_bytes, status, created_at
                FROM chat_document
                WHERE chat_id = ? AND upload_user_id = ?
                ORDER BY created_at DESC, document_id DESC
                """,
                [chat_id, user_id],
            ).fetchall()
        return [self._metadata(dict(row)) for row in rows]

    def delete_for_user(self, document_id: str, user_id: str) -> str | None:
        with get_membership_connection() as connection:
            connection.begin_write_transaction()
            row = connection.execute(
                """
                SELECT storage_key
                FROM chat_document
                WHERE document_id = ? AND upload_user_id = ?
                LIMIT 1
                """,
                [document_id, user_id],
            ).fetchone()
            if row is None:
                connection.rollback()
                return None
            cursor = connection.execute(
                """
                DELETE FROM chat_document
                WHERE document_id = ? AND upload_user_id = ?
                """,
                [document_id, user_id],
            )
            connection.commit()
        return str(row["storage_key"]) if cursor.rowcount == 1 else None

    def storage_key_for_user(self, document_id: str, user_id: str) -> str | None:
        with get_membership_connection() as connection:
            row = connection.execute(
                """
                SELECT storage_key
                FROM chat_document
                WHERE document_id = ? AND upload_user_id = ?
                LIMIT 1
                """,
                [document_id, user_id],
            ).fetchone()
        return str(row["storage_key"]) if row is not None else None

    @staticmethod
    def _metadata(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "documentId": row["document_id"],
            "fileName": row["file_name"],
            "fileType": row["file_type"],
            "fileSize": int(row["file_size_bytes"]),
            "mimeType": row["mime_type"],
            "uploadUser": row["upload_user_id"],
            "chatId": row["chat_id"],
            "caseId": row.get("case_id"),
            "status": row["status"],
            "createdAt": row["created_at"],
        }
