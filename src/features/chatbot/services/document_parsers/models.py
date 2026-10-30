from typing import Any, Literal

from pydantic import BaseModel, Field


ParserStatus = Literal["parsed", "unsupported_scanned_pdf"]
ParsedBlockType = Literal["page", "heading", "paragraph", "list", "table"]
DocumentContentType = Literal["text", "table", "xbrl_fact"]


class DocumentElement(BaseModel):
    """Parser-neutral document unit consumed by downstream processing."""

    document_id: str
    file_name: str
    file_type: str
    document_title: str | None = None
    content_type: DocumentContentType
    content: str
    page: int | None = None
    sheet: str | None = None
    section: str | None = None
    section_level: int | None = None
    parent_section: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParserWarning(BaseModel):
    code: str
    message: str
    context: dict[str, Any] = Field(default_factory=dict)


class ParsedContentBlock(BaseModel):
    type: ParsedBlockType
    content: str = ""
    section: str = ""
    page: int | None = None
    sheet: str = ""
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParsedDocument(BaseModel):
    fileName: str
    fileType: str
    parser: str
    status: ParserStatus = "parsed"
    blocks: list[ParsedContentBlock] = Field(default_factory=list)
    warnings: list[ParserWarning] = Field(default_factory=list)
