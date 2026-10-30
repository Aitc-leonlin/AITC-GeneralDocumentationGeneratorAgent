from __future__ import annotations

import json
import uuid
from abc import ABC
from pathlib import PurePath
from typing import Callable, Iterable

from src.features.chatbot.services.document_chunking.models import DocumentChunk
from src.features.chatbot.services.document_chunking.service import (
    SECTION_SEPARATOR,
    StructureAwareDocumentChunker,
)
from src.features.chatbot.services.document_parsers.models import DocumentElement


class BaseChunkingStrategy(ABC):
    """Format policy around the shared structure-aware chunking engine."""

    strategy_name = "base"
    supported_file_types: frozenset[str] = frozenset()
    supported_document_types: frozenset[str] = frozenset()

    def supports(self, file_type: str, document_type: str | None = None) -> bool:
        if file_type not in self.supported_file_types:
            return False
        return not self.supported_document_types or (
            document_type in self.supported_document_types
        )

    def chunk(
        self,
        *,
        engine: StructureAwareDocumentChunker,
        elements: list[DocumentElement],
        chat_id: str,
        upload_user: str,
        case_id: str | None = None,
        document_type: str | None = None,
    ) -> list[DocumentChunk]:
        prepared = self.prepare_elements(elements, document_type=document_type)
        return engine.chunk(
            elements=prepared,
            chat_id=chat_id,
            upload_user=upload_user,
            case_id=case_id,
        )

    def prepare_elements(
        self,
        elements: list[DocumentElement],
        *,
        document_type: str | None,
    ) -> list[DocumentElement]:
        if not elements:
            return []
        document_title = self.detect_document_title(elements)
        has_explicit_title = any(
            element.document_title
            or element.metadata.get("document_title")
            or element.metadata.get("isDocumentTitle")
            or element.metadata.get("docling_label") == "title"
            for element in elements
        )
        prepared: list[DocumentElement] = []
        for element in elements:
            section_parts = self._section_parts(element.section)
            stripped_title = bool(
                self.strip_explicit_title_from_section
                and has_explicit_title
                and section_parts
                and section_parts[0] == document_title
            )
            if stripped_title:
                section_parts = section_parts[1:]
            resolved_section = SECTION_SEPARATOR.join(section_parts) or None
            section_level = element.section_level
            if section_parts:
                section_level = len(section_parts)
            elif resolved_section is None:
                section_level = None
            parent_section = None if stripped_title else element.parent_section
            if parent_section is None and len(section_parts) > 1:
                parent_section = SECTION_SEPARATOR.join(section_parts[:-1])
            metadata = {
                **element.metadata,
                "document_title": document_title,
                "chunking_strategy": self.strategy_name,
                "chunk_boundary": self.is_format_partition_boundary(element),
            }
            if document_type:
                metadata["document_type"] = document_type
            prepared.append(
                element.model_copy(
                    update={
                        "document_title": document_title,
                        "section": resolved_section,
                        "section_level": section_level,
                        "parent_section": parent_section,
                        "metadata": metadata,
                    }
                )
            )
        return prepared

    def detect_document_title(self, elements: list[DocumentElement]) -> str:
        explicit = self._first_value(
            elements,
            lambda item: item.document_title
            or item.metadata.get("document_title")
            or (
                item.content
                if item.metadata.get("isDocumentTitle")
                or item.metadata.get("docling_label") == "title"
                else None
            ),
        )
        if explicit:
            return explicit
        heading = self._first_value(
            elements,
            lambda item: (
                item.content
                if item.metadata.get("source_block_type") == "heading"
                and item.metadata.get("level") in {0, 1}
                else None
            ),
        )
        return heading or PurePath(elements[0].file_name).stem

    def is_format_partition_boundary(self, element: DocumentElement) -> bool:
        return True

    @property
    def strip_explicit_title_from_section(self) -> bool:
        return False

    @staticmethod
    def _section_parts(section: str | None) -> tuple[str, ...]:
        return tuple(
            value.strip()
            for value in str(section or "").split(SECTION_SEPARATOR)
            if value.strip()
        )

    @staticmethod
    def _first_value(
        elements: Iterable[DocumentElement],
        getter: Callable[[DocumentElement], object],
    ) -> str:
        for element in elements:
            value = str(getter(element) or "").strip()
            if value:
                return value
        return ""


class StructuralChunkingStrategy(BaseChunkingStrategy):
    def __init__(
        self,
        *,
        strategy_name: str,
        supported_file_types: Iterable[str],
        page_is_boundary: bool = True,
        strip_explicit_title_from_section: bool = False,
    ) -> None:
        self.strategy_name = strategy_name
        self.supported_file_types = frozenset(supported_file_types)
        self.page_is_boundary = page_is_boundary
        self._strip_explicit_title_from_section = strip_explicit_title_from_section

    @property
    def strip_explicit_title_from_section(self) -> bool:
        return self._strip_explicit_title_from_section

    def is_format_partition_boundary(self, element: DocumentElement) -> bool:
        if (
            not self.page_is_boundary
            and element.metadata.get("format_partition_type") == "page"
        ):
            return False
        return True


class XBRLChunkingStrategy(BaseChunkingStrategy):
    strategy_name = "xbrl_semantic"
    supported_file_types = frozenset({"xbrl"})

    def detect_document_title(self, elements: list[DocumentElement]) -> str:
        entity = self._first_value(
            elements,
            lambda item: item.metadata.get("documentEntity"),
        )
        report_type = self._first_value(
            elements,
            lambda item: item.metadata.get("reportType"),
        )
        title = " ".join(value for value in (entity, report_type) if value)
        return title or super().detect_document_title(elements)

    def prepare_elements(
        self,
        elements: list[DocumentElement],
        *,
        document_type: str | None,
    ) -> list[DocumentElement]:
        enriched = super().prepare_elements(
            elements,
            document_type=document_type,
        )
        prepared: list[DocumentElement] = []
        for element in enriched:
            rows = self._fact_rows(element)
            if rows is None:
                prepared.append(element)
                continue
            for row_index, row in enumerate(rows):
                prepared.append(self._fact_element(element, row, row_index))
        return prepared

    @staticmethod
    def _fact_rows(element: DocumentElement) -> list[dict[str, object]] | None:
        if element.content_type != "table":
            return None
        if not (
            element.metadata.get("parser") == "xbrl"
            or element.metadata.get("xbrl_fact_count") is not None
            or element.metadata.get("factCount") is not None
        ):
            return None
        try:
            table = json.loads(element.content)
        except (TypeError, ValueError):
            return None
        rows = table.get("rows") if isinstance(table, dict) else None
        if not isinstance(rows, list):
            return None
        return [row for row in rows if isinstance(row, dict)]

    @classmethod
    def _fact_element(
        cls,
        source: DocumentElement,
        row: dict[str, object],
        row_index: int,
    ) -> DocumentElement:
        normalized = {
            "concept": str(row.get("concept") or "").strip(),
            "qualified_name": str(row.get("qualifiedName") or "").strip(),
            "label": str(row.get("label") or row.get("concept") or "").strip(),
            "entity": str(row.get("entity") or "").strip(),
            "report_type": str(
                row.get("reportType") or source.metadata.get("reportType") or ""
            ).strip(),
            "context_ref": str(row.get("contextRef") or "").strip(),
            "period": str(row.get("period") or "").strip(),
            "dimensions": str(row.get("dimensions") or "").strip(),
            "unit": str(row.get("unit") or "").strip(),
            "unit_ref": str(row.get("unitRef") or "").strip(),
            "value": str(row.get("value") or "").strip(),
            "decimals": str(row.get("decimals") or "").strip(),
            "scale": str(row.get("scale") or "").strip(),
            "sign": str(row.get("sign") or "").strip(),
            "format": str(row.get("format") or "").strip(),
            "nil": str(row.get("nil") or "").strip(),
        }
        content = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
        identity = "|".join(
            (
                normalized["qualified_name"] or normalized["concept"],
                normalized["context_ref"],
                normalized["unit_ref"],
                str(row_index),
            )
        )
        partition_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"aitc:{source.document_id}:xbrl-fact:{identity}",
            )
        )
        metadata = {
            **source.metadata,
            **normalized,
            "atomic": True,
            "force_partition": True,
            "semantic_unit": "xbrl_fact",
            "chunk_boundary": True,
            "format_partition_id": partition_id,
            "format_partition_key": f"xbrl-fact:{identity}",
            "format_partition_type": "table",
            "format_partition_label": normalized["label"] or "XBRL Fact",
            "xbrl_fact_row_index": row_index,
        }
        return source.model_copy(
            update={
                "content_type": "xbrl_fact",
                "content": content,
                "section": str(row.get("statement") or source.section or "XBRL Facts"),
                "metadata": metadata,
            }
        )


class DocumentChunkingService:
    """Resolve file-format policy first, leaving room for document-type policies."""

    def __init__(
        self,
        *,
        engine: StructureAwareDocumentChunker | None = None,
        strategies: Iterable[BaseChunkingStrategy] | None = None,
    ) -> None:
        self.engine = engine or StructureAwareDocumentChunker.from_environment()
        self.strategies = list(strategies or self._default_strategies())
        self.fallback_strategy = StructuralChunkingStrategy(
            strategy_name="generic_fallback",
            supported_file_types=(),
        )

    @staticmethod
    def _default_strategies() -> list[BaseChunkingStrategy]:
        return [
            StructuralChunkingStrategy(
                strategy_name="docx_structure",
                supported_file_types={"docx"},
                strip_explicit_title_from_section=True,
            ),
            StructuralChunkingStrategy(
                strategy_name="pdf_structure",
                supported_file_types={"pdf"},
                page_is_boundary=False,
                strip_explicit_title_from_section=True,
            ),
            StructuralChunkingStrategy(
                strategy_name="html_structure",
                supported_file_types={"html"},
                strip_explicit_title_from_section=True,
            ),
            XBRLChunkingStrategy(),
            StructuralChunkingStrategy(
                strategy_name="markdown_structure",
                supported_file_types={"md", "markdown"},
            ),
            StructuralChunkingStrategy(
                strategy_name="plain_text",
                supported_file_types={"txt"},
            ),
            StructuralChunkingStrategy(
                strategy_name="tabular",
                supported_file_types={"csv", "xlsx"},
            ),
        ]

    def resolve(
        self,
        file_type: str,
        document_type: str | None = None,
    ) -> BaseChunkingStrategy:
        normalized_file_type = file_type.strip().lower().lstrip(".")
        document_specific = next(
            (
                strategy
                for strategy in self.strategies
                if strategy.supported_document_types
                and strategy.supports(normalized_file_type, document_type)
            ),
            None,
        )
        if document_specific is not None:
            return document_specific
        return next(
            (
                strategy
                for strategy in self.strategies
                if not strategy.supported_document_types
                and strategy.supports(normalized_file_type, document_type)
            ),
            self.fallback_strategy,
        )

    def chunk(
        self,
        *,
        elements: list[DocumentElement],
        chat_id: str,
        upload_user: str,
        case_id: str | None = None,
        file_type: str = "",
        document_type: str | None = None,
    ) -> list[DocumentChunk]:
        if not elements:
            return []
        resolved_file_type = file_type or elements[0].file_type
        strategy = self.resolve(resolved_file_type, document_type)
        return strategy.chunk(
            engine=self.engine,
            elements=elements,
            chat_id=chat_id,
            upload_user=upload_user,
            case_id=case_id,
            document_type=document_type,
        )
