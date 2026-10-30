from __future__ import annotations

import json
import os
import uuid
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

from src.features.chatbot.services.document_parsers.common import (
    normalize_columns,
    serializable_cell_value,
)
from src.features.chatbot.services.document_parsers.models import DocumentElement
from src.features.chatbot.services.document_parsers.xbrl_parser import (
    detect_xbrl_document_kind,
)
from src.features.chatbot.services.document_structure.models import (
    DocumentFormatPartition,
    DocumentPartitionType,
    DocumentStructureAnalysis,
    DocumentStructureWarning,
)


DOCLING_SUPPORTED_FILE_TYPES = frozenset(
    {"pdf", "docx", "html", "md", "markdown", "csv", "xlsx", "xbrl"}
)
SECTION_SEPARATOR = " > "


def _environment_flag_enabled(name: str) -> bool:
    return os.getenv(name, "").strip().upper() == "TRUE"


def _xbrl_taxonomy_access_configured() -> bool:
    return bool(os.getenv("CHAT_XBRL_TAXONOMY_DIR", "").strip()) or (
        _environment_flag_enabled("CHAT_XBRL_ENABLE_REMOTE_FETCH")
    )


@lru_cache(maxsize=1)
def configured_docling_converter() -> Any:
    from docling.datamodel.backend_options import XBRLBackendOptions
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import (
        HeadingHierarchyOptions,
        PdfPipelineOptions,
    )
    from docling.document_converter import (
        DocumentConverter,
        PdfFormatOption,
        XBRLFormatOption,
    )

    pdf_options = PdfPipelineOptions(
        heading_hierarchy_options=HeadingHierarchyOptions(enabled=True),
    )
    taxonomy_directory = os.getenv("CHAT_XBRL_TAXONOMY_DIR", "").strip()
    taxonomy_path = (
        Path(taxonomy_directory).expanduser().resolve()
        if taxonomy_directory
        else None
    )
    if taxonomy_path is not None and not taxonomy_path.is_dir():
        raise ValueError(
            "CHAT_XBRL_TAXONOMY_DIR 必須指向存在的 Taxonomy 目錄。"
        )
    xbrl_options = XBRLBackendOptions(
        taxonomy=taxonomy_path,
        enable_local_fetch=taxonomy_path is not None,
        enable_remote_fetch=_environment_flag_enabled(
            "CHAT_XBRL_ENABLE_REMOTE_FETCH"
        ),
    )
    return DocumentConverter(
        allowed_formats=[
            InputFormat.PDF,
            InputFormat.DOCX,
            InputFormat.MD,
            InputFormat.CSV,
            InputFormat.XLSX,
            InputFormat.HTML,
            InputFormat.XML_XBRL,
        ],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
            InputFormat.XML_XBRL: XBRLFormatOption(
                backend_options=xbrl_options,
            ),
        },
    )


class DoclingDocumentStructureAnalyzer:
    """Create a format-aware structural overlay after normalization."""

    def __init__(self, converter: Any | None = None) -> None:
        self._converter = converter

    @property
    def converter(self) -> Any:
        if self._converter is None:
            self._converter = configured_docling_converter()
        return self._converter

    def analyze(
        self,
        *,
        document_id: str,
        file_name: str,
        file_type: str,
        content: bytes,
        normalized_elements: list[DocumentElement],
    ) -> DocumentStructureAnalysis:
        normalized_file_type = file_type.strip().lower().lstrip(".")
        xbrl_document_kind: str | None = None
        if normalized_file_type not in DOCLING_SUPPORTED_FILE_TYPES:
            return self._fallback_analysis(
                document_id=document_id,
                file_name=file_name,
                file_type=normalized_file_type,
                normalized_elements=normalized_elements,
                warning=DocumentStructureWarning(
                    code="docling_format_not_supported",
                    message="Docling 未處理此格式，Chunking 將使用 Normalize 結構。",
                    context={"fileType": normalized_file_type},
                ),
            )
        if normalized_file_type == "xbrl":
            try:
                xbrl_document_kind = detect_xbrl_document_kind(content)
            except Exception as exc:
                return self._fallback_analysis(
                    document_id=document_id,
                    file_name=file_name,
                    file_type=normalized_file_type,
                    normalized_elements=normalized_elements,
                    warning=DocumentStructureWarning(
                        code="xbrl_type_detection_failed",
                        message="無法判斷 XBRL 文件類型，已使用本地 Facts Parser。",
                        context={"errorType": type(exc).__name__},
                    ),
                )
        if (
            xbrl_document_kind == "instance"
            and not _xbrl_taxonomy_access_configured()
        ):
            return self._fallback_analysis(
                document_id=document_id,
                file_name=file_name,
                file_type=normalized_file_type,
                normalized_elements=normalized_elements,
                warning=DocumentStructureWarning(
                    code="xbrl_taxonomy_not_configured",
                    message=(
                        "未設定 XBRL Taxonomy 來源，已使用安全的本地 Facts Parser。"
                    ),
                ),
            )

        try:
            structured_elements = self._analyze_with_docling(
                document_id=document_id,
                file_name=file_name,
                file_type=normalized_file_type,
                content=content,
                normalized_elements=normalized_elements,
                xbrl_document_kind=xbrl_document_kind,
            )
        except Exception as exc:
            return self._fallback_analysis(
                document_id=document_id,
                file_name=file_name,
                file_type=normalized_file_type,
                normalized_elements=normalized_elements,
                warning=DocumentStructureWarning(
                    code="docling_analysis_failed",
                    message=(
                        "Docling 文件結構分析失敗，Chunking 已回退 Normalize 結構。"
                    ),
                    context={"errorType": type(exc).__name__, "message": str(exc)},
                ),
            )

        if not structured_elements:
            return self._fallback_analysis(
                document_id=document_id,
                file_name=file_name,
                file_type=normalized_file_type,
                normalized_elements=normalized_elements,
                warning=DocumentStructureWarning(
                    code="docling_empty_structure",
                    message=(
                        "Docling 沒有產生可用結構，Chunking 已回退 Normalize 結構。"
                    ),
                ),
            )

        return DocumentStructureAnalysis(
            document_id=document_id,
            file_name=file_name,
            file_type=normalized_file_type,
            analyzer="docling",
            status="analyzed",
            elements=structured_elements,
            partitions=self._collect_partitions(structured_elements),
        )

    def _analyze_with_docling(
        self,
        *,
        document_id: str,
        file_name: str,
        file_type: str,
        content: bytes,
        normalized_elements: list[DocumentElement],
        xbrl_document_kind: str | None = None,
    ) -> list[DocumentElement]:
        from docling.datamodel.base_models import DocumentStream
        from docling_core.types.doc import ContentLayer, DocItemLabel, TableItem

        result = self.converter.convert(
            DocumentStream(name=file_name, stream=BytesIO(content)),
        )
        document = result.document
        groups_by_ref = {group.self_ref: group for group in document.groups}
        normalization_summary = self._normalization_summary(normalized_elements)
        headings: dict[int, str] = {}
        structured_elements: list[DocumentElement] = []

        for reading_order, (item, tree_level) in enumerate(
            document.iterate_items(
                included_content_layers={ContentLayer.BODY},
                traverse_pictures=True,
            )
        ):
            label = self._enum_value(getattr(item, "label", None)) or "unknown"
            text = str(getattr(item, "text", "") or "").strip()
            if label == DocItemLabel.TITLE.value:
                self._set_heading(headings, 0, text)
            elif label == DocItemLabel.SECTION_HEADER.value:
                heading_level = max(1, int(getattr(item, "level", 1) or 1))
                self._set_heading(headings, heading_level, text)

            content_type = "text"
            table_caption = ""
            if isinstance(item, TableItem):
                content_type = "table"
                text = self._table_content(item, document)
                table_caption = str(item.caption_text(document) or "").strip()
            elif not text and label == DocItemLabel.PICTURE.value:
                text = str(item.caption_text(document) or "").strip()
            if not text:
                continue

            page = self._page_number(item)
            group_path, sheet = self._group_path(item, groups_by_ref)
            section = SECTION_SEPARATOR.join(
                headings[level] for level in sorted(headings) if headings[level]
            ) or None
            section_parts = [
                headings[level]
                for level in sorted(headings)
                if level > 0 and headings[level]
            ]
            top_level_section = next(
                (headings[level] for level in sorted(headings) if level > 0),
                None,
            )
            partition_type, partition_label, partition_key = self._partition_details(
                document_id=document_id,
                file_type=file_type,
                page=page,
                sheet=sheet,
                top_level_section=top_level_section,
                reading_order=reading_order,
                label=label,
            )
            partition_id = self._stable_id(document_id, "partition", partition_key)
            region_id = self._stable_id(
                document_id,
                "region",
                str(getattr(item, "self_ref", reading_order)),
            )
            metadata = {
                "structure_analyzer": "docling",
                "docling_region_id": region_id,
                "docling_self_ref": str(getattr(item, "self_ref", "")),
                "docling_label": label,
                "docling_tree_level": tree_level,
                "docling_heading_level": getattr(item, "level", None),
                "docling_group_path": group_path,
                "docling_provenance": self._provenance(item),
                "format_partition_id": partition_id,
                "format_partition_key": partition_key,
                "format_partition_type": partition_type,
                "format_partition_label": partition_label,
                "normalization_source": normalization_summary,
            }
            if headings.get(0):
                metadata["document_title"] = headings[0]
            if table_caption:
                metadata["caption"] = table_caption
                metadata["tableTitle"] = table_caption
            structured_elements.append(
                DocumentElement(
                    document_id=document_id,
                    file_name=file_name,
                    file_type=file_type,
                    content_type=content_type,
                    content=text,
                    page=page,
                    sheet=sheet,
                    section=section,
                    document_title=headings.get(0),
                    section_level=len(section_parts) or None,
                    parent_section=(
                        SECTION_SEPARATOR.join(section_parts[:-1]) or None
                    ),
                    metadata=metadata,
                )
            )
        if file_type == "xbrl":
            structured_elements.extend(
                self._xbrl_fact_elements(
                    document_id=document_id,
                    normalized_elements=normalized_elements,
                    normalization_summary=normalization_summary,
                )
            )
        document_title = self._normalized_document_title(
            normalized_elements
        ) or headings.get(0)
        if document_title:
            structured_elements = [
                element.model_copy(
                    update={
                        "document_title": document_title,
                        "metadata": {
                            **element.metadata,
                            "document_title": document_title,
                        },
                    }
                )
                for element in structured_elements
            ]
        return structured_elements

    @staticmethod
    def _set_heading(headings: dict[int, str], level: int, text: str) -> None:
        if not text:
            return
        for existing_level in [value for value in headings if value >= level]:
            del headings[existing_level]
        headings[level] = text

    @classmethod
    def _table_content(cls, item: Any, document: Any) -> str:
        dataframe = item.export_to_dataframe(document)
        columns, _ = normalize_columns(dataframe.columns)
        rows = [
            {
                column: serializable_cell_value(value)
                for column, value in zip(columns, values)
            }
            for values in dataframe.itertuples(index=False, name=None)
        ]
        return json.dumps(
            {"columns": columns, "rows": rows},
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )

    @classmethod
    def _xbrl_fact_elements(
        cls,
        *,
        document_id: str,
        normalized_elements: list[DocumentElement],
        normalization_summary: dict[str, Any],
    ) -> list[DocumentElement]:
        partition_key = "table:xbrl-facts"
        partition_id = cls._stable_id(document_id, "partition", partition_key)
        return [
            element.model_copy(
                update={
                    "metadata": {
                        **element.metadata,
                        "structure_analyzer": "docling+xbrl_parser",
                        "format_partition_id": partition_id,
                        "format_partition_key": partition_key,
                        "format_partition_type": "table",
                        "format_partition_label": "XBRL Facts",
                        "normalization_source": normalization_summary,
                    }
                }
            )
            for element in normalized_elements
        ]

    @classmethod
    def _group_path(
        cls,
        item: Any,
        groups_by_ref: dict[str, Any],
    ) -> tuple[list[str], str | None]:
        path: list[str] = []
        sheet: str | None = None
        parent = getattr(item, "parent", None)
        parent_ref = getattr(parent, "cref", None)
        visited: set[str] = set()
        while parent_ref and parent_ref not in visited:
            visited.add(parent_ref)
            group = groups_by_ref.get(parent_ref)
            if group is None:
                break
            name = str(getattr(group, "name", "") or "").strip()
            label = cls._enum_value(getattr(group, "label", None))
            if name and name != "_root_":
                path.append(name)
            if label == "sheet" and name:
                sheet = name
            parent = getattr(group, "parent", None)
            parent_ref = getattr(parent, "cref", None)
        return list(reversed(path)), sheet

    @classmethod
    def _partition_details(
        cls,
        *,
        document_id: str,
        file_type: str,
        page: int | None,
        sheet: str | None,
        top_level_section: str | None,
        reading_order: int,
        label: str,
    ) -> tuple[DocumentPartitionType, str, str]:
        if file_type == "pdf" and page is not None:
            return "page", f"第 {page} 頁", f"page:{page}"
        if file_type == "xlsx" and sheet:
            return "sheet", sheet, f"sheet:{sheet}"
        if file_type == "csv":
            return "table", "CSV 表格", "table:csv"
        normalized_section = str(top_level_section or "").strip()
        if normalized_section:
            return "section", normalized_section, f"section:{normalized_section}"
        if label == "table":
            return "table", "表格", f"table:{reading_order}"
        return "body", "文件本文", f"body:{document_id}"

    @staticmethod
    def _page_number(item: Any) -> int | None:
        provenance = getattr(item, "prov", None) or []
        page_number = getattr(provenance[0], "page_no", None) if provenance else None
        return int(page_number) if page_number is not None else None

    @staticmethod
    def _provenance(item: Any) -> list[dict[str, Any]]:
        return [
            item.model_dump(mode="json")
            for item in (getattr(item, "prov", None) or [])
        ]

    @staticmethod
    def _enum_value(value: Any) -> str:
        return str(getattr(value, "value", value) or "")

    @staticmethod
    def _normalization_summary(
        normalized_elements: list[DocumentElement],
    ) -> dict[str, Any]:
        parsers = sorted(
            {
                str(element.metadata.get("parser"))
                for element in normalized_elements
                if element.metadata.get("parser")
            }
        )
        statuses = sorted(
            {
                str(element.metadata.get("parser_status"))
                for element in normalized_elements
                if element.metadata.get("parser_status")
            }
        )
        return {
            "element_count": len(normalized_elements),
            "parsers": parsers,
            "parser_statuses": statuses,
        }

    @staticmethod
    def _normalized_document_title(
        normalized_elements: list[DocumentElement],
    ) -> str:
        return next(
            (
                str(element.document_title or element.content or "").strip()
                for element in normalized_elements
                if element.document_title
                or element.metadata.get("isDocumentTitle")
            ),
            "",
        )

    def _fallback_analysis(
        self,
        *,
        document_id: str,
        file_name: str,
        file_type: str,
        normalized_elements: list[DocumentElement],
        warning: DocumentStructureWarning,
    ) -> DocumentStructureAnalysis:
        elements = [
            self._with_fallback_partition(document_id, index, element)
            for index, element in enumerate(normalized_elements)
        ]
        return DocumentStructureAnalysis(
            document_id=document_id,
            file_name=file_name,
            file_type=file_type,
            analyzer="normalized_fallback",
            status="fallback",
            elements=elements,
            partitions=self._collect_partitions(elements),
            warnings=[warning],
        )

    def _with_fallback_partition(
        self,
        document_id: str,
        index: int,
        element: DocumentElement,
    ) -> DocumentElement:
        if element.sheet:
            partition_type: DocumentPartitionType = "sheet"
            partition_label = element.sheet
            partition_key = f"sheet:{element.sheet}"
        elif element.page is not None:
            partition_type = "page"
            partition_label = f"第 {element.page} 頁"
            partition_key = f"page:{element.page}"
        elif element.section:
            partition_type = "section"
            partition_label = element.section.split(SECTION_SEPARATOR, 1)[0]
            partition_key = f"section:{partition_label}"
        elif element.content_type == "table":
            partition_type = "table"
            partition_label = "表格"
            partition_key = f"table:{index}"
        else:
            partition_type = "body"
            partition_label = "文件本文"
            partition_key = f"body:{document_id}"
        metadata = {
            **element.metadata,
            "structure_analyzer": "normalized_fallback",
            "format_partition_id": self._stable_id(
                document_id,
                "partition",
                partition_key,
            ),
            "format_partition_key": partition_key,
            "format_partition_type": partition_type,
            "format_partition_label": partition_label,
        }
        return element.model_copy(update={"metadata": metadata})

    @classmethod
    def _collect_partitions(
        cls,
        elements: list[DocumentElement],
    ) -> list[DocumentFormatPartition]:
        partitions: dict[str, DocumentFormatPartition] = {}
        for index, element in enumerate(elements):
            partition_id = str(element.metadata.get("format_partition_id") or "")
            if not partition_id:
                continue
            partition = partitions.get(partition_id)
            if partition is None:
                partition = DocumentFormatPartition(
                    partition_id=partition_id,
                    partition_type=str(
                        element.metadata.get("format_partition_type") or "body"
                    ),
                    label=str(
                        element.metadata.get("format_partition_label") or "文件本文"
                    ),
                    page=element.page,
                    sheet=element.sheet,
                    section=element.section,
                    metadata={
                        "partition_key": element.metadata.get("format_partition_key"),
                        "structure_analyzer": element.metadata.get("structure_analyzer"),
                    },
                )
                partitions[partition_id] = partition
            partition.element_indexes.append(index)
        return list(partitions.values())

    @staticmethod
    def _stable_id(document_id: str, category: str, value: str) -> str:
        return str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"aitc:{document_id}:{category}:{value}",
            )
        )
