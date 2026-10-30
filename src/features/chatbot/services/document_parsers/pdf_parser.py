from __future__ import annotations

import math
import re
import tempfile
from collections import Counter
from pathlib import Path

from langchain_community.document_loaders import PyPDFLoader

from src.features.chatbot.services.document_parsers.base import (
    BaseDocumentParser,
    DocumentParseInput,
    DocumentParserError,
)
from src.features.chatbot.services.document_parsers.common import compact_inline_text
from src.features.chatbot.services.document_parsers.models import (
    ParsedContentBlock,
    ParsedDocument,
    ParserWarning,
)


HEADER_FOOTER_SCAN_LINES = 3
REPEATED_LINE_RATIO = 0.6
MIN_EXTRACTED_TEXT_CHARACTERS = 20
PAGE_COUNTER_PATTERN = re.compile(
    r"^(?:page\s*)?\d+(?:\s*(?:/|of)\s*\d+)?$",
    re.IGNORECASE,
)


class PDFParser(BaseDocumentParser):
    parser_name = "pdf"
    supported_extensions = frozenset({"pdf"})

    def parse(self, source: DocumentParseInput) -> ParsedDocument:
        if not source.content:
            raise DocumentParserError("empty_document", "PDF 文件沒有內容。")

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temporary_file:
                temporary_file.write(source.content)
                temporary_path = Path(temporary_file.name)
            documents = PyPDFLoader(temporary_path, mode="page").load()
        except ImportError as exc:
            raise DocumentParserError(
                "parser_dependency_missing",
                "PDF Parser 需要安裝 pypdf。",
            ) from exc
        except Exception as exc:
            raise DocumentParserError("invalid_pdf", f"PDF 解析失敗：{exc}") from exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

        page_lines = [self._page_lines(document.page_content) for document in documents]
        repeated_headers, repeated_footers = self._repeated_marginal_lines(page_lines)
        cleaned_pages = [
            self._clean_page(lines, repeated_headers, repeated_footers)
            for lines in page_lines
        ]
        extracted_characters = sum(
            len(re.sub(r"\s+", "", page_content)) for page_content in cleaned_pages
        )

        if extracted_characters < MIN_EXTRACTED_TEXT_CHARACTERS:
            return ParsedDocument(
                fileName=source.file_name,
                fileType=source.extension,
                parser=self.parser_name,
                status="unsupported_scanned_pdf",
                warnings=[
                    ParserWarning(
                        code="unsupported_scanned_pdf",
                        message="PDF 幾乎無法擷取文字，第一版不支援 OCR。",
                        context={
                            "pageCount": len(documents),
                            "extractedCharacters": extracted_characters,
                        },
                    )
                ],
            )

        warnings: list[ParserWarning] = []
        empty_pages = [index for index, content in enumerate(cleaned_pages, start=1) if not content]
        if empty_pages:
            warnings.append(
                ParserWarning(
                    code="empty_pdf_pages",
                    message="部分 PDF 頁面沒有可擷取文字。",
                    context={"pages": empty_pages},
                )
            )

        return ParsedDocument(
            fileName=source.file_name,
            fileType=source.extension,
            parser=self.parser_name,
            blocks=[
                ParsedContentBlock(type="page", page=index, content=content)
                for index, content in enumerate(cleaned_pages, start=1)
            ],
            warnings=warnings,
        )

    @staticmethod
    def _page_lines(content: str) -> list[str]:
        return [
            line
            for raw_line in str(content or "").splitlines()
            if (line := compact_inline_text(raw_line))
        ]

    @staticmethod
    def _repeated_marginal_lines(
        pages: list[list[str]],
    ) -> tuple[set[str], set[str]]:
        if len(pages) < 2:
            return set(), set()

        header_counts: Counter[str] = Counter()
        footer_counts: Counter[str] = Counter()
        for lines in pages:
            header_counts.update(set(lines[:HEADER_FOOTER_SCAN_LINES]))
            footer_counts.update(set(lines[-HEADER_FOOTER_SCAN_LINES:]))

        threshold = max(2, math.ceil(len(pages) * REPEATED_LINE_RATIO))
        headers = {line for line, count in header_counts.items() if count >= threshold}
        footers = {line for line, count in footer_counts.items() if count >= threshold}
        return headers, footers

    @staticmethod
    def _clean_page(lines: list[str], headers: set[str], footers: set[str]) -> str:
        kept_lines: list[str] = []
        footer_start = max(0, len(lines) - HEADER_FOOTER_SCAN_LINES)
        for index, line in enumerate(lines):
            if index < HEADER_FOOTER_SCAN_LINES and line in headers:
                continue
            if index >= footer_start and (line in footers or PAGE_COUNTER_PATTERN.fullmatch(line)):
                continue
            kept_lines.append(line)
        return "\n".join(kept_lines).strip()

