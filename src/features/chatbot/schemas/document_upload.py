from pydantic import BaseModel


class ChatDocumentResponse(BaseModel):
    documentId: str
    fileName: str
    fileType: str
    fileSize: int
    mimeType: str
    uploadUser: str
    chatId: str
    caseId: str | None = None
    status: str
    createdAt: str
