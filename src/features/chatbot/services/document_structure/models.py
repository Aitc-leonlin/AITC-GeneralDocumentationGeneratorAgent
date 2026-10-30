from typing import Any, Literal

from pydantic import BaseModel, Field

from src.features.chatbot.services.document_parsers.models import DocumentElement


DocumentStructureStatus = Literal["analyzed", "fallback"]
DocumentPartitionType = Literal["body", "page", "sheet", "section", "table"]


class DocumentStructureWarning(BaseModel):
    code: str
    message: str
    context: dict[str, Any] = Field(default_factory=dict)


class DocumentFormatPartition(BaseModel):
    partition_id: str
    partition_type: DocumentPartitionType
    label: str
    page: int | None = None
    sheet: str | None = None
    section: str | None = None
    element_indexes: list[int] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentStructureAnalysis(BaseModel):
    document_id: str
    file_name: str
    file_type: str
    analyzer: str
    status: DocumentStructureStatus
    elements: list[DocumentElement] = Field(default_factory=list)
    partitions: list[DocumentFormatPartition] = Field(default_factory=list)
    warnings: list[DocumentStructureWarning] = Field(default_factory=list)
