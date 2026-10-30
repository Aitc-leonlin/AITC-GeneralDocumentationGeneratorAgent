from __future__ import annotations

import json

from src.features.chatbot.services.document_parsers.models import (
    DocumentElement,
    ParsedContentBlock,
    ParsedDocument,
)


class DocumentNormalizer:
    """Convert format-specific parser blocks into the standard document schema."""

    @classmethod
    def normalize(
        cls,
        *,
        document_id: str,
        document: ParsedDocument,
    ) -> list[DocumentElement]:
        parser_warnings = [warning.model_dump(mode="json") for warning in document.warnings]
        return [
            cls._normalize_block(
                document_id=document_id,
                document=document,
                block=block,
                parser_warnings=parser_warnings,
            )
            for block in document.blocks
        ]

    @staticmethod
    def _normalize_block(
        *,
        document_id: str,
        document: ParsedDocument,
        block: ParsedContentBlock,
        parser_warnings: list[dict],
    ) -> DocumentElement:
        is_table = block.type == "table"
        section_parts = [
            part.strip()
            for part in str(block.section or "").split(" > ")
            if part.strip()
        ]
        raw_level = block.metadata.get("level")
        section_level = (
            int(raw_level)
            if isinstance(raw_level, int)
            else len(section_parts) or None
        )
        content = (
            json.dumps(
                {
                    "columns": block.columns,
                    "rows": block.rows,
                },
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            )
            if is_table
            else block.content
        )
        metadata = {
            "parser": document.parser,
            "parser_status": document.status,
            "source_block_type": block.type,
            **block.metadata,
        }
        if parser_warnings:
            metadata["parser_warnings"] = parser_warnings

        return DocumentElement(
            document_id=document_id,
            file_name=document.fileName,
            file_type=document.fileType,
            document_title=(
                block.content
                if block.metadata.get("isDocumentTitle")
                else None
            ),
            content_type="table" if is_table else "text",
            content=content,
            page=block.page,
            sheet=block.sheet or None,
            section=block.section or None,
            section_level=section_level,
            parent_section=(" > ".join(section_parts[:-1]) or None),
            metadata=metadata,
        )
