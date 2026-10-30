"""文件、章節與內容種類目錄。"""

import json
from pathlib import Path

from .schemas import (
    ContentTypeTemplate, DocumentSectionPlan, DocumentTypeTemplate,
    ReportQuickStart, ReportQuickStartDefinition, SectionTypeTemplate,
)

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
QUICK_STARTS_PATH = DATA_DIR / "report_quick_starts.json"
DOCUMENT_TYPES_PATH = DATA_DIR / "document_type_templates.json"
CONTENT_TYPES_PATH = DATA_DIR / "content_type_templates.json"
SECTION_TYPES_PATH = DATA_DIR / "section_type_templates.json"


def load_content_type_templates() -> dict[str, ContentTypeTemplate]:
    """載入 C01～C20 的內容種類；所需能力目前僅為規劃資料。"""
    with CONTENT_TYPES_PATH.open(encoding="utf-8") as template_file:
        raw_templates = json.load(template_file)
    templates = [ContentTypeTemplate.model_validate(item) for item in raw_templates]
    expected_ids = {f"C{number:02d}" for number in range(1, 21)}
    if len(templates) != 20 or {item.id for item in templates} != expected_ids:
        raise ValueError("內容種類目錄必須包含不重複的 C01～C20")
    return {item.id: item for item in templates}


def load_section_type_templates() -> dict[str, SectionTypeTemplate]:
    """載入 S01～S20，確認每個建議內容種類都存在於 C01～C20。"""
    with SECTION_TYPES_PATH.open(encoding="utf-8") as template_file:
        raw_templates = json.load(template_file)
    templates = [SectionTypeTemplate.model_validate(item) for item in raw_templates]
    expected_ids = {f"S{number:02d}" for number in range(1, 21)}
    if len(templates) != 20 or {item.id for item in templates} != expected_ids:
        raise ValueError("章節種類目錄必須包含不重複的 S01～S20")
    content_ids = set(load_content_type_templates())
    for template in templates:
        suggested_ids = template.suggestedContentTypeIds
        if len(suggested_ids) != len(set(suggested_ids)) or not set(suggested_ids) <= content_ids:
            raise ValueError(f"{template.id} 的建議內容種類 ID 不正確")
    return {item.id: item for item in templates}


def load_document_type_templates() -> dict[str, DocumentTypeTemplate]:
    """載入 D01～D30 及其必要、可選章節，並核對 S ID。"""
    with DOCUMENT_TYPES_PATH.open(encoding="utf-8") as template_file:
        raw_templates = json.load(template_file)
    templates = [DocumentTypeTemplate.model_validate(item) for item in raw_templates]
    expected_ids = {f"D{number:02d}" for number in range(1, 31)}
    if len(templates) != 30 or {item.id for item in templates} != expected_ids:
        raise ValueError("文件分類目錄必須包含不重複的 D01～D30")
    section_ids = set(load_section_type_templates())
    for template in templates:
        required = template.requiredSectionIds
        optional = template.optionalSectionIds
        if (
            len(required) != len(set(required))
            or len(optional) != len(set(optional))
            or set(required) & set(optional)
            or not set(required + optional) <= section_ids
        ):
            raise ValueError(f"{template.id} 的必要或可選章節 ID 不正確")
    return {item.id: item for item in templates}


def get_document_section_plan(document_type_id: str) -> DocumentSectionPlan | None:
    """依 D ID 取得有順序的必要／可選章節及其建議內容種類。"""
    template = load_document_type_templates().get(document_type_id)
    if template is None:
        return None
    sections = load_section_type_templates()
    return DocumentSectionPlan(
        documentTemplate=template,
        requiredSections=[sections[section_id] for section_id in template.requiredSectionIds],
        optionalSections=[sections[section_id] for section_id in template.optionalSectionIds],
    )


def _load_quick_start_definitions() -> list[ReportQuickStartDefinition]:
    with QUICK_STARTS_PATH.open(encoding="utf-8") as quick_start_file:
        raw_definitions = json.load(quick_start_file)
    definitions = [ReportQuickStartDefinition.model_validate(item) for item in raw_definitions]
    if len({item.id for item in definitions}) != len(definitions):
        raise ValueError("快捷問題 ID 不可重複")
    return definitions


def load_report_quick_starts() -> list[ReportQuickStart]:
    return [ReportQuickStart(**definition.model_dump()) for definition in _load_quick_start_definitions()]


