from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Iterable

from src.features.chatbot.services.document_parsers.models import ParsedContentBlock


LIST_LINE_PATTERN = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+)")


def compact_inline_text(value: Any) -> str:
    normalized_value = "" if value is None else str(value)
    return " ".join(normalized_value.replace("\u00a0", " ").split())


def normalize_multiline_text(value: Any) -> str:
    lines = [compact_inline_text(line) for line in str(value or "").splitlines()]
    normalized: list[str] = []
    previous_blank = True
    for line in lines:
        if line:
            normalized.append(line)
            previous_blank = False
        elif not previous_blank:
            normalized.append("")
            previous_blank = True
    while normalized and not normalized[-1]:
        normalized.pop()
    return "\n".join(normalized)


def section_path(headings: Iterable[str]) -> str:
    return " > ".join(heading for heading in headings if heading)


def text_blocks(content: str, section: str = "") -> list[ParsedContentBlock]:
    normalized = normalize_multiline_text(content)
    if not normalized:
        return []

    blocks: list[ParsedContentBlock] = []
    for raw_paragraph in re.split(r"\n\s*\n", normalized):
        lines = [line.strip() for line in raw_paragraph.splitlines() if line.strip()]
        if not lines:
            continue
        is_list = all(LIST_LINE_PATTERN.match(line) for line in lines)
        blocks.append(
            ParsedContentBlock(
                type="list" if is_list else "paragraph",
                section=section,
                content="\n".join(lines) if is_list else " ".join(lines),
            )
        )
    return blocks


def normalize_columns(values: Iterable[Any], prefix: str = "column") -> tuple[list[str], bool]:
    columns: list[str] = []
    counts: dict[str, int] = {}
    changed = False
    for index, value in enumerate(values, start=1):
        base = compact_inline_text(value)
        if not base:
            base = f"{prefix}_{index}"
            changed = True
        count = counts.get(base, 0) + 1
        counts[base] = count
        if count > 1:
            columns.append(f"{base}_{count}")
            changed = True
        else:
            columns.append(base)
    return columns, changed


def serializable_cell_value(value: Any) -> Any:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)
