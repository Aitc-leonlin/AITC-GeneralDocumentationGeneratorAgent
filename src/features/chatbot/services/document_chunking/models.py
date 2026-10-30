from typing import Any, Literal

from pydantic import BaseModel, Field


class DocumentChunk(BaseModel):
    """Retrieval-ready content unit with complete source provenance."""

    chunk_id: str
    document_id: str
    document_title: str
    file_name: str
    file_type: str
    chunk_index: int
    content: str
    content_type: Literal["text", "table", "xbrl_fact", "mixed"]
    section_title: str | None = None
    section_level: int | None = None
    parent_section: str | None = None
    page_number: int | None = None
    # Backward-compatible source coordinates used by the existing upload flow.
    page: int | None = None
    sheet: str | None = None
    section: str | None = None
    chat_id: str
    case_id: str | None = None
    upload_user: str
    metadata: dict[str, Any] = Field(default_factory=dict)
