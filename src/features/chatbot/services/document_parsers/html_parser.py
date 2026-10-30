from __future__ import annotations

from html.parser import HTMLParser as StandardHTMLParser
from typing import Any

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


class _StructuredHTMLExtractor(StandardHTMLParser):
    """Small fallback parser; Docling remains the primary HTML structure analyzer."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[ParsedContentBlock] = []
        self.headings: dict[int, str] = {}
        self.document_title = ""
        self._capture_tag: str | None = None
        self._capture_parts: list[str] = []
        self._ignored_depth = 0
        self._semantic_sections: list[str] = []
        self._section_tag_stack: list[bool] = []
        self._in_table = False
        self._table_rows: list[list[str]] = []
        self._table_row: list[str] | None = None
        self._table_cell_parts: list[str] | None = None
        self._table_caption = ""

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        tag = tag.lower()
        attributes = {name.lower(): value or "" for name, value in attrs}
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag in {"section", "article"}:
            label = compact_inline_text(
                attributes.get("aria-label")
                or attributes.get("title")
                or attributes.get("id")
                or ""
            )
            self._section_tag_stack.append(bool(label))
            if label:
                self._semantic_sections.append(label)
            return
        if tag == "table":
            self._in_table = True
            self._table_rows = []
            self._table_caption = ""
            return
        if self._in_table:
            if tag == "tr":
                self._table_row = []
            elif tag in {"th", "td"}:
                self._table_cell_parts = []
            elif tag == "caption":
                self._capture_tag = "caption"
                self._capture_parts = []
            elif tag == "br" and self._table_cell_parts is not None:
                self._table_cell_parts.append(" ")
            return
        if tag == "title" or tag in {"p", "li"} or (
            len(tag) == 2 and tag.startswith("h") and tag[1].isdigit()
        ):
            self._capture_tag = tag
            self._capture_parts = []
        elif tag == "br" and self._capture_tag:
            self._capture_parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if self._ignored_depth:
            return
        if self._in_table:
            if tag in {"th", "td"} and self._table_cell_parts is not None:
                if self._table_row is None:
                    self._table_row = []
                self._table_row.append(compact_inline_text("".join(self._table_cell_parts)))
                self._table_cell_parts = None
            elif tag == "tr" and self._table_row is not None:
                if any(self._table_row):
                    self._table_rows.append(self._table_row)
                self._table_row = None
            elif tag == "caption" and self._capture_tag == "caption":
                self._table_caption = compact_inline_text("".join(self._capture_parts))
                self._capture_tag = None
                self._capture_parts = []
            elif tag == "table":
                self._append_table()
                self._in_table = False
            return
        if tag in {"section", "article"}:
            if self._section_tag_stack and self._section_tag_stack.pop():
                self._semantic_sections.pop()
            return
        if self._capture_tag != tag:
            return

        content = compact_inline_text("".join(self._capture_parts))
        self._capture_tag = None
        self._capture_parts = []
        if not content:
            return
        if tag == "title":
            self.document_title = content
            return
        if tag.startswith("h"):
            level = int(tag[1])
            for existing in [value for value in self.headings if value >= level]:
                del self.headings[existing]
            self.headings[level] = content
            self.blocks.append(
                ParsedContentBlock(
                    type="heading",
                    content=content,
                    section=self._current_section(),
                    metadata={"level": level, "htmlTag": tag},
                )
            )
            return
        self.blocks.append(
            ParsedContentBlock(
                type="list" if tag == "li" else "paragraph",
                content=content,
                section=self._current_section(),
                metadata={"htmlTag": tag},
            )
        )

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._table_cell_parts is not None:
            self._table_cell_parts.append(data)
        elif self._capture_tag:
            self._capture_parts.append(data)

    def _current_section(self) -> str:
        values = [self.headings[level] for level in sorted(self.headings)]
        values.extend(self._semantic_sections)
        return section_path(values)

    def _append_table(self) -> None:
        if not self._table_rows:
            return
        columns, columns_changed = normalize_columns(self._table_rows[0])
        rows: list[dict[str, Any]] = []
        for values in self._table_rows[1:]:
            padded = [
                *values[: len(columns)],
                *([""] * max(0, len(columns) - len(values))),
            ]
            rows.append(dict(zip(columns, padded)))
        metadata: dict[str, Any] = {
            "rowCount": len(rows),
            "htmlTag": "table",
        }
        if self._table_caption:
            metadata["caption"] = self._table_caption
            metadata["tableTitle"] = self._table_caption
        if columns_changed:
            metadata["normalizedColumns"] = True
        self.blocks.append(
            ParsedContentBlock(
                type="table",
                section=self._current_section(),
                columns=columns,
                rows=rows,
                metadata=metadata,
            )
        )


class HTMLParser(BaseDocumentParser):
    parser_name = "html"
    supported_extensions = frozenset({"html"})

    def parse(self, source: DocumentParseInput) -> ParsedDocument:
        try:
            content = source.content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentParserError(
                "unsupported_text_encoding",
                "HTML 目前只支援 UTF-8 編碼。",
            ) from exc

        extractor = _StructuredHTMLExtractor()
        try:
            extractor.feed(content)
            extractor.close()
        except Exception as exc:
            raise DocumentParserError("invalid_html", f"HTML 解析失敗：{exc}") from exc

        blocks = list(extractor.blocks)
        if extractor.document_title:
            blocks.insert(
                0,
                ParsedContentBlock(
                    type="heading",
                    content=extractor.document_title,
                    section=extractor.document_title,
                    metadata={
                        "level": 0,
                        "htmlTag": "title",
                        "isDocumentTitle": True,
                    },
                ),
            )
        warnings: list[ParserWarning] = []
        if not blocks:
            warnings.append(
                ParserWarning(
                    code="empty_document",
                    message="HTML 沒有可解析的文字或表格。",
                )
            )
        return ParsedDocument(
            fileName=source.file_name,
            fileType=source.extension,
            parser=self.parser_name,
            blocks=blocks,
            warnings=warnings,
        )
