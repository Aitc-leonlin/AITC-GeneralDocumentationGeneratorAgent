from __future__ import annotations

from pathlib import PurePath
from typing import Iterable

from src.features.chatbot.services.document_parsers.base import (
    BaseDocumentParser,
    DocumentParseInput,
    DocumentParserError,
)
from src.features.chatbot.services.document_parsers.csv_parser import CsvParser
from src.features.chatbot.services.document_parsers.docx_parser import DocxParser
from src.features.chatbot.services.document_parsers.excel_parser import ExcelParser
from src.features.chatbot.services.document_parsers.html_parser import HTMLParser
from src.features.chatbot.services.document_parsers.models import DocumentElement
from src.features.chatbot.services.document_parsers.normalizer import DocumentNormalizer
from src.features.chatbot.services.document_parsers.pdf_parser import PDFParser
from src.features.chatbot.services.document_parsers.text_parser import TextParser
from src.features.chatbot.services.document_parsers.xbrl_parser import XBRLParser


class DocumentParserService:
    def __init__(self, parsers: Iterable[BaseDocumentParser] | None = None):
        parser_instances = list(
            parsers
            if parsers is not None
            else [
                PDFParser(),
                DocxParser(),
                TextParser(),
                CsvParser(),
                ExcelParser(),
                HTMLParser(),
                XBRLParser(),
            ]
        )
        self._parsers: dict[str, BaseDocumentParser] = {}
        for parser in parser_instances:
            for extension in parser.supported_extensions:
                if extension in self._parsers:
                    raise ValueError(f"Duplicate document parser for extension: {extension}")
                self._parsers[extension] = parser

    @property
    def supported_extensions(self) -> frozenset[str]:
        return frozenset(self._parsers)

    def parse(
        self,
        *,
        document_id: str,
        file_name: str,
        content: bytes,
        file_type: str = "",
        mime_type: str = "",
    ) -> list[DocumentElement]:
        extension = file_type.strip().lower().lstrip(".")
        if not extension:
            extension = PurePath(file_name).suffix.lower().lstrip(".")
        parser = self._parsers.get(extension)
        if parser is None:
            raise DocumentParserError(
                "unsupported_file_type",
                f"沒有可處理 .{extension or 'unknown'} 文件的 Parser。",
            )
        parsed_document = parser.parse(
            DocumentParseInput(
                file_name=file_name,
                file_type=extension,
                mime_type=mime_type,
                content=content,
            )
        )
        return DocumentNormalizer.normalize(
            document_id=document_id,
            document=parsed_document,
        )
