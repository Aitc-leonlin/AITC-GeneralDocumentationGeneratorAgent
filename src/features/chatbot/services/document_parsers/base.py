from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from src.features.chatbot.services.document_parsers.models import ParsedDocument


@dataclass(frozen=True)
class DocumentParseInput:
    file_name: str
    file_type: str
    content: bytes
    mime_type: str = ""

    @property
    def extension(self) -> str:
        return self.file_type.strip().lower().lstrip(".")


class DocumentParserError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


class BaseDocumentParser(ABC):
    parser_name = "base"
    supported_extensions: frozenset[str] = frozenset()

    def supports(self, extension: str) -> bool:
        return extension.strip().lower().lstrip(".") in self.supported_extensions

    @abstractmethod
    def parse(self, source: DocumentParseInput) -> ParsedDocument:
        """Convert raw file bytes into understandable structured content."""

    def empty_result(self, source: DocumentParseInput) -> ParsedDocument:
        return ParsedDocument(
            fileName=source.file_name,
            fileType=source.extension,
            parser=self.parser_name,
        )

