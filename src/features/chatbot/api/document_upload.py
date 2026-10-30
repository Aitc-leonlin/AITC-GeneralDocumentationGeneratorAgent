from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, UploadFile, status

from src.features.chatbot.schemas.document_upload import ChatDocumentResponse
from src.features.chatbot.services.document_upload_service import DocumentUploadService
from src.features.chatbot.services.vector_service_factory import (
    document_vector_indexing_service,
)
from src.features.membership.core.auth_middleware import require_permission
from src.features.membership.core.responses import ok
from src.features.membership.schemas.common import StandardResponse


document_upload_router = APIRouter(
    prefix="/api/chat/documents",
    tags=["chat-document-upload"],
)


def document_service() -> DocumentUploadService:
    return DocumentUploadService(
        vector_indexing_service=document_vector_indexing_service(),
    )


@document_upload_router.post(
    "",
    response_model=StandardResponse[ChatDocumentResponse],
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    file: Annotated[UploadFile, File()],
    chat_id: Annotated[str, Form(alias="chatId")],
    user: dict = Depends(require_permission("credit-ai.chat")),
):
    document = await document_service().upload(
        file=file,
        chat_id=chat_id,
        user_id=user["id"],
    )
    return ok(document)


@document_upload_router.get(
    "",
    response_model=StandardResponse[list[ChatDocumentResponse]],
)
async def list_documents(
    chat_id: str,
    user: dict = Depends(require_permission("credit-ai.chat")),
):
    return ok(document_service().list_for_chat(chat_id, user["id"]))


@document_upload_router.delete(
    "/{document_id}",
    response_model=StandardResponse[dict[str, bool]],
)
async def delete_document(
    document_id: str,
    user: dict = Depends(require_permission("credit-ai.chat")),
):
    document_service().delete(document_id, user["id"])
    return ok({"deleted": True})
