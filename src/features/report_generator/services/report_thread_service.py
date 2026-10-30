"""Account-scoped report conversation state and multi-turn outline drafting."""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

from src.features.membership.core.database import get_membership_connection, membership_transaction
from src.features.membership.core.time import utc_now_iso
from src.features.report_generator.services.report_chat_service import (
    GeneralDocumentOutline,
    GeneralDocumentPlan,
    PendingClarification,
    PurposeDocumentOutline,
    PurposeDocumentPlan,
    ReportChatMessage,
    ReportOutlineRequest,
    create_report_outline,
)
from src.features.report_generator.services.domain_report_service import ReportLLMTrace
from src.shared.database.connection import DatabaseIntegrityError
from src.shared.database.serialization import database_json_dumps


class ReportThreadMessageCommand(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class ReportThreadFinalizeCommand(BaseModel):
    confirmed: Literal[True]


class GeneralThreadExecuteCommand(BaseModel):
    confirmed: Literal[True]
    chatId: str | None = None
    useSampleData: bool = False
    sectionId: str | None = Field(default=None, pattern=r"^(?:S(?:0[1-9]|1[0-9]|20)|section-[1-9][0-9]*)$")
    contentTypeId: str | None = Field(default=None, pattern=r"^C(?:0[1-9]|1[0-9]|20)$")
    capability: str | None = None


class ReportThreadConflict(Exception):
    """Another request changed the thread while its next outline was being drafted."""


class ReportThreadState(BaseModel):
    messages: list[ReportChatMessage] = Field(default_factory=list)
    documentTypeId: str | None = None
    generalPlan: GeneralDocumentPlan | None = None
    generalOutline: GeneralDocumentOutline | None = None
    purposePlan: PurposeDocumentPlan | None = None
    purposeOutline: PurposeDocumentOutline | None = None
    pendingClarification: PendingClarification | None = None
    sourceMode: Literal["default_json", "user_data"] | None = None
    llmTraces: list[ReportLLMTrace] = Field(default_factory=list)


def _thread(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        **ReportThreadState.model_validate_json(row["state_json"]).model_dump(mode="json"),
    }


def list_report_threads(user_id: str) -> list[dict[str, Any]]:
    with get_membership_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM report_conversation_thread WHERE user_id = ? "
            "ORDER BY updated_at DESC, id DESC",
            [user_id],
        ).fetchall()
        return [_thread(row) for row in rows]


def get_report_thread(thread_id: str, user_id: str) -> dict[str, Any] | None:
    with get_membership_connection() as connection:
        row = connection.execute(
            "SELECT * FROM report_conversation_thread WHERE id = ? AND user_id = ?",
            [thread_id, user_id],
        ).fetchone()
        return _thread(row) if row else None


def add_report_thread_message(
    thread_id: str, user_id: str, command: ReportThreadMessageCommand
) -> dict[str, Any]:
    # A UUID prevents path-like or arbitrary user-provided thread identifiers.
    UUID(thread_id)
    existing = get_report_thread(thread_id, user_id)
    if existing is None:
        with get_membership_connection() as connection:
            owner = connection.execute(
                "SELECT user_id FROM report_conversation_thread WHERE id = ?", [thread_id]
            ).fetchone()
            if owner is not None:
                raise PermissionError("報告對話不存在")

    previous = ReportThreadState.model_validate(existing or {})
    content = command.content.strip()
    if not content:
        raise ValueError("請輸入報告需求")
    user_message = ReportChatMessage(role="user", content=content)
    messages = [*previous.messages[-28:], user_message]
    result = create_report_outline(
        ReportOutlineRequest(
            messages=messages,
            currentDocumentTypeId=previous.documentTypeId,
            currentGeneralPlan=previous.generalPlan,
            currentGeneralOutline=previous.generalOutline,
            currentPurposePlan=previous.purposePlan,
            currentPurposeOutline=previous.purposeOutline,
            pendingClarification=previous.pendingClarification,
            currentSourceMode=previous.sourceMode,
        )
    )
    state = ReportThreadState(
        messages=[
            *previous.messages,
            user_message,
            ReportChatMessage(role="assistant", content=result.assistantMessage),
        ],
        documentTypeId=result.documentTemplate.id if result.documentTemplate else None,
        generalPlan=result.generalPlan,
        generalOutline=result.generalOutline,
        purposePlan=result.purposePlan,
        purposeOutline=result.purposeOutline,
        pendingClarification=result.pendingClarification,
        sourceMode=result.sourceMode,
        llmTraces=[*previous.llmTraces, *result.llmTraces],
    )
    now = utc_now_iso()
    title = (existing or {}).get("title") or content[:80]
    with membership_transaction() as connection:
        if existing:
            cursor = connection.execute(
                "UPDATE report_conversation_thread SET title = ?, state_json = ?, updated_at = ? "
                "WHERE id = ? AND user_id = ? AND updated_at = ?",
                [title, database_json_dumps(state.model_dump(mode="json"), ensure_ascii=False),
                 now, thread_id, user_id, existing["updatedAt"]],
            )
            if cursor.rowcount == 0:
                raise ReportThreadConflict("這段報告對話已在其他視窗更新，請重新整理後再傳送")
        else:
            try:
                connection.execute(
                    "INSERT INTO report_conversation_thread "
                    "(id, user_id, title, state_json, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [thread_id, user_id, title,
                     database_json_dumps(state.model_dump(mode="json"), ensure_ascii=False),
                     now, now],
                )
            except DatabaseIntegrityError as error:
                raise ReportThreadConflict("這段報告對話已建立，請重新整理後再傳送") from error
    return {
        **(get_report_thread(thread_id, user_id) or {}),
        "graphNodes": result.graphNodes,
    }


def delete_report_thread(thread_id: str, user_id: str) -> bool:
    with membership_transaction() as connection:
        cursor = connection.execute(
            "DELETE FROM report_conversation_thread WHERE id = ? AND user_id = ?",
            [thread_id, user_id],
        )
        return cursor.rowcount > 0


