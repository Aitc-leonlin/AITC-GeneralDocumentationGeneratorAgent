"""依 D 類型索引的案例；分類階段不載入完整資料。"""

import json
from pathlib import Path
from typing import Iterable, Literal

from pydantic import BaseModel, Field

from .catalog import load_document_type_templates


SAMPLE_DIR = Path(__file__).resolve().parents[2] / "data" / "document_type_samples"
SAMPLE_METADATA_DIR = SAMPLE_DIR.parent / "document_type_sample_metadata"


class DocumentSampleFact(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=300)


class DocumentSampleSource(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=1000)


class DocumentTypeSample(BaseModel):
    documentTypeId: str = Field(pattern=r"^D(?:0[1-9]|[12][0-9]|30)$")
    isSynthetic: Literal[True]
    title: str = Field(min_length=1, max_length=150)
    subject: str = Field(min_length=1, max_length=150)
    period: str = Field(min_length=1, max_length=100)
    objective: str = Field(min_length=1, max_length=500)
    context: str = Field(min_length=1, max_length=1000)
    facts: list[DocumentSampleFact] = Field(min_length=3)
    sourceMaterials: list[DocumentSampleSource] = Field(min_length=1)
    assumptions: list[str] = Field(min_length=1)
    sourceNote: str = Field(min_length=1, max_length=1000)


class DocumentSampleMetadata(BaseModel):
    """供來源比對使用的輕量欄位；日後可由資料庫分類查詢直接回傳。"""

    documentTypeId: str = Field(pattern=r"^D(?:0[1-9]|[12][0-9]|30)$")
    sampleId: str = Field(pattern=r"^D(?:0[1-9]|[12][0-9]|30)_[a-z0-9_]+$")
    title: str = Field(min_length=1, max_length=150)
    description: str = Field(min_length=1, max_length=600)


def load_document_type_sample_metadata(
    document_ids: Iterable[str],
) -> list[DocumentSampleMetadata]:
    """只讀取指定 D 類型的 metadata；完整案例檔案要等比對通過才開啟。"""
    templates = load_document_type_templates()
    requested = [
        document_id for document_id in dict.fromkeys(document_ids)
        if document_id in templates
    ]
    metadata: list[DocumentSampleMetadata] = []
    seen_ids: set[str] = set()
    for document_id in requested:
        path = SAMPLE_METADATA_DIR / f"{document_id}.json"
        if not path.is_file():
            raise ValueError(f"缺少 {document_id} 測試案例 metadata")
        with path.open(encoding="utf-8") as metadata_file:
            records = json.load(metadata_file)
        if not isinstance(records, list) or not records:
            raise ValueError(f"{document_id} 測試案例 metadata 必須是非空清單")
        for record in records:
            item = DocumentSampleMetadata.model_validate(record)
            if item.documentTypeId != document_id or not item.sampleId.startswith(document_id):
                raise ValueError(f"{item.sampleId} 的文件種類 ID 不一致")
            if item.sampleId in seen_ids:
                raise ValueError(f"{item.sampleId} 測試案例 metadata 重複")
            seen_ids.add(item.sampleId)
            metadata.append(item)
    return metadata


def load_document_type_sample(sample_id: str) -> DocumentTypeSample:
    """按 metadata 的案例 ID 只讀取選中的 JSON。"""
    document_id = sample_id.partition("_")[0]
    metadata = {
        item.sampleId: item
        for item in load_document_type_sample_metadata([document_id])
    }
    selected = metadata.get(sample_id)
    if selected is None:
        raise ValueError("測試案例不存在，無法載入資料")
    with (SAMPLE_DIR / f"{sample_id}.json").open(encoding="utf-8") as sample_file:
        sample = DocumentTypeSample.model_validate(json.load(sample_file))
    if sample.documentTypeId != selected.documentTypeId:
        raise ValueError(f"{sample_id} 測試案例的文件種類 ID 不一致")
    return sample


def load_document_type_samples() -> dict[str, DocumentTypeSample]:
    """相容既有 D ID 入口：回傳各類型 metadata 首筆案例。"""
    document_ids = set(load_document_type_templates())
    file_ids = {path.stem for path in SAMPLE_DIR.glob("*.json")}
    metadata = load_document_type_sample_metadata(document_ids)
    indexed_ids = {item.sampleId for item in metadata}
    first_ids: dict[str, str] = {}
    for item in metadata:
        first_ids.setdefault(item.documentTypeId, item.sampleId)
    if file_ids != indexed_ids or set(first_ids) != document_ids:
        raise ValueError("文件測試案例檔案與 metadata 清單不一致")

    samples = {}
    for document_id in sorted(document_ids):
        samples[document_id] = load_document_type_sample(first_ids[document_id])
    return samples
