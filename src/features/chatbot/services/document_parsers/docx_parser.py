from __future__ import annotations

import io
import re
from typing import Any

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from src.features.chatbot.services.document_parsers.base import (
    BaseDocumentParser,
    DocumentParseInput,
    DocumentParserError,
)
from src.features.chatbot.services.document_parsers.common import (
    compact_inline_text,
    normalize_columns,
    section_path,
)
from src.features.chatbot.services.document_parsers.models import (
    ParsedContentBlock,
    ParsedDocument,
    ParserWarning,
)


HEADING_STYLE_PATTERN = re.compile(r"heading\s*(?P<level>[1-9])", re.IGNORECASE)
TITLE_STYLE_PATTERN = re.compile(r"^(?:document\s*)?title$", re.IGNORECASE)


class DocxParser(BaseDocumentParser):
    parser_name = "docx"
    supported_extensions = frozenset({"docx"})

    def parse(self, source: DocumentParseInput) -> ParsedDocument:
        if not source.content:
            raise DocumentParserError("empty_document", "DOCX 文件沒有內容。")
        try:
            document = Document(io.BytesIO(source.content))
        except Exception as exc:
            raise DocumentParserError("invalid_docx", f"DOCX 解析失敗：{exc}") from exc

        blocks: list[ParsedContentBlock] = []
        warnings: list[ParserWarning] = []
        headings: dict[int, str] = {}

        for item in document.iter_inner_content():
            if isinstance(item, Paragraph):
                self._append_paragraph(blocks, headings, item)
            elif isinstance(item, Table):
                table_block, table_warnings = self._parse_table(
                    item,
                    section_path(headings[level] for level in sorted(headings)),
                )
                if table_block is not None:
                    blocks.append(table_block)
                warnings.extend(table_warnings)

        if not blocks:
            warnings.append(
                ParserWarning(code="empty_document", message="DOCX 沒有可解析的文字或表格。")
            )

        return ParsedDocument(
            fileName=source.file_name,
            fileType=source.extension,
            parser=self.parser_name,
            blocks=blocks,
            warnings=warnings,
        )

    def _append_paragraph(
        self,
        blocks: list[ParsedContentBlock],
        headings: dict[int, str],
        paragraph: Paragraph,
    ) -> None:
        content = compact_inline_text(paragraph.text)
        if not content:
            return

        heading_level = self._heading_level(paragraph)
        if self._is_title(paragraph):
            headings.clear()
            headings[0] = content
            blocks.append(
                ParsedContentBlock(
                    type="heading",
                    content=content,
                    section=content,
                    metadata={"level": 0, "isDocumentTitle": True},
                )
            )
            return
        if heading_level is not None:
            for level in [level for level in headings if level >= heading_level]:
                del headings[level]
            headings[heading_level] = content
            blocks.append(
                ParsedContentBlock(
                    type="heading",
                    content=content,
                    section=section_path(headings[level] for level in sorted(headings)),
                    metadata={"level": heading_level},
                )
            )
            return

        block_type = "list" if self._is_list(paragraph) else "paragraph"
        blocks.append(
            ParsedContentBlock(
                type=block_type,
                content=content,
                section=section_path(headings[level] for level in sorted(headings)),
                metadata={"listLevel": self._list_level(paragraph)} if block_type == "list" else {},
            )
        )

    @staticmethod
    def _heading_level(paragraph: Paragraph) -> int | None:
        style = paragraph.style
        for candidate in (getattr(style, "name", ""), getattr(style, "style_id", "")):
            match = HEADING_STYLE_PATTERN.search(str(candidate or ""))
            if match:
                return int(match.group("level"))
        return None

    @staticmethod
    def _is_title(paragraph: Paragraph) -> bool:
        style = paragraph.style
        return any(
            TITLE_STYLE_PATTERN.fullmatch(str(candidate or "").strip())
            for candidate in (
                getattr(style, "name", ""),
                getattr(style, "style_id", ""),
            )
        )

    @staticmethod
    def _is_list(paragraph: Paragraph) -> bool:
        style_name = str(getattr(paragraph.style, "name", "") or "").lower()
        paragraph_properties = paragraph._p.pPr
        return "list" in style_name or bool(
            paragraph_properties is not None and paragraph_properties.numPr is not None
        )

    @staticmethod
    def _list_level(paragraph: Paragraph) -> int:
        paragraph_properties = paragraph._p.pPr
        numbering = paragraph_properties.numPr if paragraph_properties is not None else None
        level = numbering.ilvl if numbering is not None else None
        try:
            return int(level.val) if level is not None else 0
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _parse_table(
        table: Table,
        section: str,
    ) -> tuple[ParsedContentBlock | None, list[ParserWarning]]:
        matrix = [
            [compact_inline_text(cell.text) for cell in row.cells]
            for row in table.rows
        ]
        matrix = [row for row in matrix if any(row)]
        if not matrix:
            return None, []

        columns, columns_changed = normalize_columns(matrix[0])
        warnings: list[ParserWarning] = []
        if columns_changed:
            warnings.append(
                ParserWarning(
                    code="normalized_docx_table_columns",
                    message="DOCX 表格包含空白或重複欄名，已產生安全欄名。",
                    context={"section": section},
                )
            )

        rows: list[dict[str, Any]] = []
        irregular_rows: list[int] = []
        for row_number, values in enumerate(matrix[1:], start=2):
            if len(values) != len(columns):
                irregular_rows.append(row_number)
            padded = [*values[: len(columns)], *([""] * max(0, len(columns) - len(values)))]
            rows.append(dict(zip(columns, padded)))
        if irregular_rows:
            warnings.append(
                ParserWarning(
                    code="irregular_docx_table",
                    message="DOCX 表格部分資料列的欄位數與標題列不同。",
                    context={"section": section, "rows": irregular_rows},
                )
            )

        return (
            ParsedContentBlock(
                type="table",
                section=section,
                columns=columns,
                rows=rows,
                metadata={"rowCount": len(rows)},
            ),
            warnings,
        )
