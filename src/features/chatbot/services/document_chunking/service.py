from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Iterable, Literal

from src.features.chatbot.services.document_chunking.models import DocumentChunk
from src.features.chatbot.services.document_parsers.models import DocumentElement


DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 80
CHUNK_SIZE_ENV = "CHAT_DOCUMENT_CHUNK_SIZE"
CHUNK_OVERLAP_ENV = "CHAT_DOCUMENT_CHUNK_OVERLAP"
SECTION_SEPARATOR = " > "
CONTENT_SEPARATOR = "\n\n"
TOKEN_PATTERN = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]|"
    r"[A-Za-z0-9_]+(?:[.'’-][A-Za-z0-9_]+)*|"
    r"[^\s]",
    re.UNICODE,
)
StructureLevel = Literal[
    "document",
    "format_region",
    "section",
    "subsection",
    "paragraph",
    "table_rows",
    "atomic",
    "token",
]


@dataclass(frozen=True)
class _IndexedElement:
    index: int
    element: DocumentElement


@dataclass
class _StructureNode:
    path: tuple[str, ...]
    node_type: Literal["document", "format_region", "section"] = "section"
    format_partition: str | None = None
    all_elements: list[_IndexedElement] = field(default_factory=list)
    direct_elements: list[_IndexedElement] = field(default_factory=list)
    children: dict[str, _StructureNode] = field(default_factory=dict)

    @property
    def first_index(self) -> int:
        return self.all_elements[0].index if self.all_elements else -1


@dataclass(frozen=True)
class _ChunkDraft:
    content: str
    elements: tuple[_IndexedElement, ...]
    section: str | None
    structure_level: StructureLevel
    overlap_token_count: int = 0


class StructureAwareDocumentChunker:
    """Chunk normalized elements from document structure down to token fallback."""

    def __init__(
        self,
        *,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be greater than zero")
        if chunk_overlap < 0:
            raise ValueError("chunk_overlap cannot be negative")
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    @classmethod
    def from_environment(cls) -> StructureAwareDocumentChunker:
        chunk_size = cls._configured_integer(
            CHUNK_SIZE_ENV,
            DEFAULT_CHUNK_SIZE,
            minimum=1,
        )
        chunk_overlap = cls._configured_integer(
            CHUNK_OVERLAP_ENV,
            DEFAULT_CHUNK_OVERLAP,
            minimum=0,
        )
        if chunk_overlap >= chunk_size:
            chunk_overlap = min(DEFAULT_CHUNK_OVERLAP, max(0, chunk_size - 1))
        return cls(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    @staticmethod
    def _configured_integer(name: str, default: int, *, minimum: int) -> int:
        try:
            value = int(os.getenv(name, "").strip())
        except ValueError:
            return default
        return value if value >= minimum else default

    def chunk(
        self,
        *,
        elements: list[DocumentElement],
        chat_id: str,
        upload_user: str,
        case_id: str | None = None,
    ) -> list[DocumentChunk]:
        if not elements:
            return []
        self._validate_elements(elements)

        root = self._build_structure_tree(elements)
        drafts = self._chunk_node(root, is_document=True)
        chunk_count = len(drafts)
        document = elements[0]
        return [
            self._to_document_chunk(
                draft=draft,
                document=document,
                chat_id=chat_id,
                upload_user=upload_user,
                case_id=case_id,
                chunk_index=index,
                chunk_count=chunk_count,
            )
            for index, draft in enumerate(drafts)
        ]

    @staticmethod
    def _validate_elements(elements: list[DocumentElement]) -> None:
        expected_source = (
            elements[0].document_id,
            elements[0].file_name,
            elements[0].file_type,
        )
        for element in elements[1:]:
            source = (element.document_id, element.file_name, element.file_type)
            if source != expected_source:
                raise ValueError("all elements must belong to the same document")

    @classmethod
    def _build_structure_tree(
        cls,
        elements: list[DocumentElement],
    ) -> _StructureNode:
        root = _StructureNode(path=(), node_type="document")
        for index, element in enumerate(elements):
            indexed_element = _IndexedElement(index=index, element=element)
            root.all_elements.append(indexed_element)
            node = root
            format_partition = str(
                element.metadata.get("format_partition_id") or ""
            ).strip()
            if format_partition and element.metadata.get("chunk_boundary", True):
                partition_key = f"format:{format_partition}"
                node = node.children.setdefault(
                    partition_key,
                    _StructureNode(
                        path=(),
                        node_type="format_region",
                        format_partition=format_partition,
                    ),
                )
                node.all_elements.append(indexed_element)
            for section_name in cls._section_path(element.section):
                section_key = f"section:{section_name}"
                node = node.children.setdefault(
                    section_key,
                    _StructureNode(
                        path=(*node.path, section_name),
                        node_type="section",
                        format_partition=format_partition or node.format_partition,
                    ),
                )
                node.all_elements.append(indexed_element)
            node.direct_elements.append(indexed_element)
        return root

    @staticmethod
    def _section_path(section: str | None) -> tuple[str, ...]:
        return tuple(
            part.strip()
            for part in str(section or "").split(SECTION_SEPARATOR)
            if part.strip()
        )

    def _chunk_node(
        self,
        node: _StructureNode,
        *,
        is_document: bool = False,
    ) -> list[_ChunkDraft]:
        content = self._join_elements(node.all_elements)
        force_partition = any(
            item.element.metadata.get("force_partition")
            for item in node.all_elements
        )
        if (
            content
            and not force_partition
            and self._token_count(content) <= self.chunk_size
        ):
            structure_level: StructureLevel
            if is_document:
                structure_level = "document"
            elif node.node_type == "format_region":
                structure_level = "format_region"
            elif len(node.path) == 1:
                structure_level = "section"
            else:
                structure_level = "subsection"
            return [
                _ChunkDraft(
                    content=content,
                    elements=tuple(node.all_elements),
                    section=self._section_value(node.path),
                    structure_level=structure_level,
                )
            ]

        drafts: list[_ChunkDraft] = []
        direct_buffer: list[_IndexedElement] = []
        parts: list[tuple[int, _IndexedElement | _StructureNode]] = [
            (item.index, item) for item in node.direct_elements
        ]
        parts.extend((child.first_index, child) for child in node.children.values())
        parts.sort(key=lambda item: item[0])

        def flush_direct_buffer() -> None:
            if not direct_buffer:
                return
            drafts.extend(
                self._chunk_semantic_elements(
                    direct_buffer,
                    section=self._section_value(node.path),
                )
            )
            direct_buffer.clear()

        for _, part in parts:
            if isinstance(part, _IndexedElement):
                direct_buffer.append(part)
                continue
            flush_direct_buffer()
            drafts.extend(self._chunk_node(part))
        flush_direct_buffer()
        return drafts

    def _chunk_semantic_elements(
        self,
        elements: list[_IndexedElement],
        *,
        section: str | None,
    ) -> list[_ChunkDraft]:
        drafts: list[_ChunkDraft] = []
        current_content = ""
        current_elements: tuple[_IndexedElement, ...] = ()
        current_overlap_token_count = 0

        def flush_current() -> None:
            nonlocal current_content, current_elements, current_overlap_token_count
            if not current_content:
                return
            drafts.append(
                _ChunkDraft(
                    content=current_content,
                    elements=current_elements,
                    section=section,
                    structure_level="paragraph",
                    overlap_token_count=current_overlap_token_count,
                )
            )
            current_content = ""
            current_elements = ()
            current_overlap_token_count = 0

        for indexed_element in elements:
            element_content = indexed_element.element.content.strip()
            if not element_content:
                continue
            if indexed_element.element.metadata.get("atomic"):
                flush_current()
                drafts.extend(
                    self._split_large_element(indexed_element, section=section)
                )
                continue
            if self._token_count(element_content) > self.chunk_size:
                flush_current()
                drafts.extend(self._split_large_element(indexed_element, section=section))
                continue

            candidate = CONTENT_SEPARATOR.join(
                value for value in (current_content, element_content) if value
            )
            if current_content and self._token_count(candidate) > self.chunk_size:
                previous_content = current_content
                previous_elements = current_elements
                flush_current()
                overlap_text = self._tail_tokens(previous_content, self.chunk_overlap)
                allowed_overlap = max(
                    0,
                    self.chunk_size - self._token_count(element_content),
                )
                overlap_text = self._tail_tokens(
                    overlap_text,
                    min(self.chunk_overlap, allowed_overlap),
                )
                current_content = CONTENT_SEPARATOR.join(
                    value for value in (overlap_text, element_content) if value
                )
                overlap_elements = self._overlap_elements(
                    previous_elements,
                    self._token_count(overlap_text),
                )
                current_elements = self._unique_elements(
                    [*overlap_elements, indexed_element]
                )
                current_overlap_token_count = self._token_count(overlap_text)
                continue
            current_content = candidate
            current_elements = self._unique_elements(
                [*current_elements, indexed_element]
            )

        flush_current()
        return drafts

    def _split_large_element(
        self,
        indexed_element: _IndexedElement,
        *,
        section: str | None,
    ) -> list[_ChunkDraft]:
        if indexed_element.element.metadata.get("atomic"):
            return [
                _ChunkDraft(
                    content=indexed_element.element.content.strip(),
                    elements=(indexed_element,),
                    section=section or indexed_element.element.section,
                    structure_level="atomic",
                )
            ]
        if indexed_element.element.content_type == "table":
            table_drafts = self._split_table(indexed_element, section=section)
            if table_drafts is not None:
                return table_drafts
        return [
            _ChunkDraft(
                content=content,
                elements=(indexed_element,),
                section=section or indexed_element.element.section,
                structure_level="token",
                overlap_token_count=overlap_count,
            )
            for content, overlap_count in self._token_windows(
                indexed_element.element.content
            )
        ]

    def _split_table(
        self,
        indexed_element: _IndexedElement,
        *,
        section: str | None,
    ) -> list[_ChunkDraft] | None:
        try:
            table = json.loads(indexed_element.element.content)
        except (TypeError, ValueError):
            return None
        if not isinstance(table, dict):
            return None
        columns = table.get("columns")
        rows = table.get("rows")
        if not isinstance(columns, list) or not isinstance(rows, list):
            return None

        table_context = self._table_context(indexed_element.element, section)

        row_groups: list[list[object]] = []
        current_rows: list[object] = []
        for row in rows:
            candidate_rows = [*current_rows, row]
            candidate = self._serialize_table(columns, candidate_rows, table_context)
            if current_rows and self._token_count(candidate) > self.chunk_size:
                row_groups.append(current_rows)
                overlap_rows = self._table_overlap_rows(
                    columns,
                    current_rows,
                    table_context,
                )
                current_rows = [*overlap_rows, row]
                if self._token_count(
                    self._serialize_table(columns, current_rows, table_context)
                ) > self.chunk_size:
                    current_rows = [row]
            else:
                current_rows = candidate_rows
        if current_rows or not rows:
            row_groups.append(current_rows)

        drafts: list[_ChunkDraft] = []
        for group_index, row_group in enumerate(row_groups):
            content = self._serialize_table(columns, row_group, table_context)
            if self._token_count(content) > self.chunk_size:
                # A single oversized row is still an atomic table unit. Returning
                # it intact is safer than separating values from their headers.
                if len(row_group) <= 1:
                    drafts.append(
                        _ChunkDraft(
                            content=content,
                            elements=(indexed_element,),
                            section=section or indexed_element.element.section,
                            structure_level="table_rows",
                        )
                    )
                    continue
                return None
            overlap_count = 0
            if group_index > 0 and self.chunk_overlap:
                previous_rows = row_groups[group_index - 1]
                maximum_overlap = min(len(previous_rows), len(row_group))
                overlap_row_count = next(
                    (
                        count
                        for count in range(maximum_overlap, 0, -1)
                        if previous_rows[-count:] == row_group[:count]
                    ),
                    0,
                )
                overlap_count = self._token_count(
                    json.dumps(
                        row_group[:overlap_row_count],
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=str,
                    )
                )
            drafts.append(
                _ChunkDraft(
                    content=content,
                    elements=(indexed_element,),
                    section=section or indexed_element.element.section,
                    structure_level="table_rows",
                    overlap_token_count=overlap_count,
                )
            )
        return drafts

    def _table_overlap_rows(
        self,
        columns: list[object],
        rows: list[object],
        table_context: dict[str, object],
    ) -> list[object]:
        if not self.chunk_overlap:
            return []
        overlap: list[object] = []
        for row in reversed(rows):
            candidate = [row, *overlap]
            if (
                self._token_count(
                    self._serialize_table(columns, candidate, table_context)
                )
                > self.chunk_overlap
            ):
                break
            overlap = candidate
        return overlap

    @staticmethod
    def _table_context(
        element: DocumentElement,
        section: str | None,
    ) -> dict[str, object]:
        metadata = element.metadata
        return {
            key: value
            for key, value in {
                "title": metadata.get("tableTitle") or metadata.get("table_title"),
                "caption": metadata.get("caption"),
                "unit": metadata.get("unit"),
                "section": section or element.section,
            }.items()
            if value not in (None, "")
        }

    @staticmethod
    def _serialize_table(
        columns: list[object],
        rows: list[object],
        context: dict[str, object] | None = None,
    ) -> str:
        return json.dumps(
            {**(context or {}), "columns": columns, "rows": rows},
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )

    def _token_windows(self, content: str) -> list[tuple[str, int]]:
        spans = self._token_spans(content)
        if not spans:
            return []
        step = self.chunk_size - self.chunk_overlap
        windows: list[tuple[str, int]] = []
        start_token = 0
        while start_token < len(spans):
            end_token = min(len(spans), start_token + self.chunk_size)
            start_character = spans[start_token][0]
            end_character = spans[end_token - 1][1]
            windows.append(
                (
                    content[start_character:end_character].strip(),
                    0 if not windows else min(self.chunk_overlap, end_token - start_token),
                )
            )
            if end_token == len(spans):
                break
            start_token += step
        return windows

    @classmethod
    def _token_count(cls, content: str) -> int:
        return len(cls._token_spans(content))

    @staticmethod
    def _token_spans(content: str) -> list[tuple[int, int]]:
        return [(match.start(), match.end()) for match in TOKEN_PATTERN.finditer(content)]

    @classmethod
    def _tail_tokens(cls, content: str, token_count: int) -> str:
        if token_count <= 0:
            return ""
        spans = cls._token_spans(content)
        if not spans:
            return ""
        start = spans[max(0, len(spans) - token_count)][0]
        return content[start:].strip()

    @staticmethod
    def _join_elements(elements: Iterable[_IndexedElement]) -> str:
        return CONTENT_SEPARATOR.join(
            item.element.content.strip()
            for item in elements
            if item.element.content.strip()
        )

    @staticmethod
    def _section_value(path: tuple[str, ...]) -> str | None:
        return SECTION_SEPARATOR.join(path) or None

    @staticmethod
    def _unique_elements(
        elements: Iterable[_IndexedElement],
    ) -> tuple[_IndexedElement, ...]:
        by_index = {element.index: element for element in elements}
        return tuple(by_index[index] for index in sorted(by_index))

    def _overlap_elements(
        self,
        elements: Iterable[_IndexedElement],
        overlap_token_count: int,
    ) -> tuple[_IndexedElement, ...]:
        if overlap_token_count <= 0:
            return ()
        selected: list[_IndexedElement] = []
        selected_token_count = 0
        for element in reversed(tuple(elements)):
            selected.append(element)
            selected_token_count += self._token_count(element.element.content)
            if selected_token_count >= overlap_token_count:
                break
        return tuple(reversed(selected))

    def _to_document_chunk(
        self,
        *,
        draft: _ChunkDraft,
        document: DocumentElement,
        chat_id: str,
        upload_user: str,
        case_id: str | None,
        chunk_index: int,
        chunk_count: int,
    ) -> DocumentChunk:
        source_elements = [item.element for item in draft.elements]
        pages = sorted({item.page for item in source_elements if item.page is not None})
        sheets = sorted({item.sheet for item in source_elements if item.sheet})
        sections = list(
            dict.fromkeys(item.section for item in source_elements if item.section)
        )
        content_types = sorted({item.content_type for item in source_elements})
        source_metadata = [item.metadata for item in source_elements]
        source_docling_region_ids = list(
            dict.fromkeys(
                str(item.metadata.get("docling_region_id"))
                for item in source_elements
                if item.metadata.get("docling_region_id")
            )
        )
        format_partitions = list(
            dict.fromkeys(
                str(item.metadata.get("format_partition_id"))
                for item in source_elements
                if item.metadata.get("format_partition_id")
            )
        )
        chunking_strategies = list(
            dict.fromkeys(
                str(item.metadata.get("chunking_strategy"))
                for item in source_elements
                if item.metadata.get("chunking_strategy")
            )
        )
        content_hash = hashlib.sha256(draft.content.encode("utf-8")).hexdigest()
        chunk_id = str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"aitc:{document.document_id}:{chunk_index}:{content_hash}",
            )
        )
        metadata = {
            "chunk_index": chunk_index,
            "chunk_count": chunk_count,
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "token_count": self._token_count(draft.content),
            "structure_level": draft.structure_level,
            "overlap_token_count": draft.overlap_token_count,
            "source_element_indexes": [item.index for item in draft.elements],
            "source_content_types": content_types,
            "source_docling_region_ids": source_docling_region_ids,
            "source_metadata": source_metadata,
        }
        if len(chunking_strategies) == 1:
            metadata["chunking_strategy"] = chunking_strategies[0]
        elif len(chunking_strategies) > 1:
            metadata["chunking_strategies"] = chunking_strategies
        if len(format_partitions) == 1:
            partition_metadata = next(
                item.metadata
                for item in source_elements
                if item.metadata.get("format_partition_id") == format_partitions[0]
            )
            metadata.update(
                {
                    "format_partition_id": format_partitions[0],
                    "format_partition_type": partition_metadata.get(
                        "format_partition_type"
                    ),
                    "format_partition_label": partition_metadata.get(
                        "format_partition_label"
                    ),
                }
            )
        elif len(format_partitions) > 1:
            metadata["format_partition_ids"] = format_partitions
        if len(pages) > 1:
            metadata["pages"] = pages
        if len(sheets) > 1:
            metadata["sheets"] = sheets
        if len(sections) > 1:
            metadata["sections"] = sections
        resolved_section = draft.section
        if resolved_section is None and len(sections) == 1:
            resolved_section = sections[0]
        section_parts = self._section_path(resolved_section)
        section_levels = {
            item.section_level
            for item in source_elements
            if item.section_level is not None
        }
        resolved_section_level = (
            next(iter(section_levels))
            if len(section_levels) == 1
            else len(section_parts) or None
        )
        parent_sections = list(
            dict.fromkeys(
                item.parent_section for item in source_elements if item.parent_section
            )
        )
        resolved_parent_section = (
            parent_sections[0]
            if len(parent_sections) == 1
            else self._section_value(section_parts[:-1])
        )
        document_title = next(
            (
                str(item.document_title or item.metadata.get("document_title") or "").strip()
                for item in source_elements
                if str(
                    item.document_title or item.metadata.get("document_title") or ""
                ).strip()
            ),
            PurePath(document.file_name).stem,
        )
        resolved_content_type = (
            content_types[0] if len(content_types) == 1 else "mixed"
        )
        if len(source_elements) == 1 and source_elements[0].content_type == "xbrl_fact":
            for key in (
                "concept",
                "qualified_name",
                "label",
                "entity",
                "report_type",
                "context_ref",
                "period",
                "dimensions",
                "unit",
                "unit_ref",
                "value",
                "decimals",
                "scale",
                "sign",
                "format",
                "nil",
            ):
                if key in source_elements[0].metadata:
                    metadata[key] = source_elements[0].metadata[key]
        if len(source_elements) == 1 and source_elements[0].content_type == "table":
            for key in ("tableTitle", "table_title", "caption", "unit"):
                if key in source_elements[0].metadata:
                    metadata[key] = source_elements[0].metadata[key]

        return DocumentChunk(
            chunk_id=chunk_id,
            document_id=document.document_id,
            document_title=document_title,
            file_name=document.file_name,
            file_type=document.file_type,
            chunk_index=chunk_index,
            content=draft.content,
            content_type=resolved_content_type,
            section_title=resolved_section,
            section_level=resolved_section_level,
            parent_section=resolved_parent_section,
            page_number=pages[0] if len(pages) == 1 else None,
            page=pages[0] if len(pages) == 1 else None,
            sheet=sheets[0] if len(sheets) == 1 else None,
            section=resolved_section,
            chat_id=chat_id,
            case_id=case_id,
            upload_user=upload_user,
            metadata=metadata,
        )
