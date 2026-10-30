from __future__ import annotations

import re
from typing import Any, Literal
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from src.features.chatbot.services.document_parsers.base import (
    BaseDocumentParser,
    DocumentParseInput,
    DocumentParserError,
)
from src.features.chatbot.services.document_parsers.models import (
    ParsedContentBlock,
    ParsedDocument,
    ParserWarning,
)


XBRL_INSTANCE_NAMESPACE = "http://www.xbrl.org/2003/instance"
INLINE_XBRL_NAMESPACES = frozenset(
    {
        "http://www.xbrl.org/2008/inlineXBRL",
        "http://www.xbrl.org/2013/inlineXBRL",
    }
)
INLINE_XBRL_FACT_NAMES = frozenset({"nonfraction", "nonnumeric", "fraction"})
XBRLDocumentKind = Literal["instance", "inline"]
XBRL_FACT_COLUMNS = [
    "concept",
    "qualifiedName",
    "label",
    "value",
    "entity",
    "period",
    "dimensions",
    "contextRef",
    "unit",
    "unitRef",
    "decimals",
    "scale",
    "sign",
    "format",
    "nil",
]
ENTITY_NAME_CONCEPTS = frozenset(
    {
        "entityregistrantname",
        "nameofreportingentityorothermeansofidentification",
        "entityname",
    }
)
REPORT_TYPE_CONCEPTS = frozenset({"documenttype", "typeofreportingentity"})
REPORT_PERIOD_CONCEPTS = frozenset({"documentperiodenddate", "reportingperiodenddate"})


def _tag_parts(tag: object) -> tuple[str, str]:
    value = str(tag or "")
    if value.startswith("{") and "}" in value:
        namespace, local_name = value[1:].split("}", 1)
        return namespace, local_name
    return "", value.split(":", 1)[-1]


def _normalized_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _element_text(element: Any) -> str:
    parts = [str(element.text or "")]
    for child in list(element):
        namespace, local_name = _tag_parts(child.tag)
        if not (
            namespace in INLINE_XBRL_NAMESPACES
            and local_name.lower() == "exclude"
        ):
            parts.append(_element_text(child))
        parts.append(str(child.tail or ""))
    return _normalized_text("".join(parts))


def xbrl_document_kind(root: Any) -> XBRLDocumentKind | None:
    namespace, local_name = _tag_parts(root.tag)
    if namespace == XBRL_INSTANCE_NAMESPACE and local_name.lower() == "xbrl":
        return "instance"
    if local_name.lower() != "html":
        return None

    has_header = False
    has_fact = False
    has_context = False
    for element in root.iter():
        element_namespace, element_name = _tag_parts(element.tag)
        normalized_name = element_name.lower()
        if element_namespace in INLINE_XBRL_NAMESPACES:
            has_header = has_header or normalized_name == "header"
            has_fact = has_fact or normalized_name in INLINE_XBRL_FACT_NAMES
        elif element_namespace == XBRL_INSTANCE_NAMESPACE:
            has_context = has_context or normalized_name == "context"
        if has_header and has_fact and has_context:
            return "inline"
    return None


def parse_xbrl_root(content: bytes) -> Any:
    try:
        root = ElementTree.fromstring(content)
    except (DefusedXmlException, ParseError, ValueError) as exc:
        raise DocumentParserError("invalid_xbrl", "XBRL XML 格式無效。") from exc

    if xbrl_document_kind(root) is None:
        raise DocumentParserError(
            "invalid_xbrl",
            "檔案不是有效的 XBRL Instance 或 Inline XBRL HTML 文件。",
        )
    return root


def detect_xbrl_document_kind(content: bytes) -> XBRLDocumentKind:
    root = parse_xbrl_root(content)
    kind = xbrl_document_kind(root)
    if kind is None:  # Guard for type checkers; parse_xbrl_root already validates it.
        raise DocumentParserError("invalid_xbrl", "無法判斷 XBRL 文件類型。")
    return kind


def _context_details(root: Any) -> dict[str, dict[str, str]]:
    contexts: dict[str, dict[str, str]] = {}
    for context in root.iter():
        namespace, local_name = _tag_parts(context.tag)
        if namespace != XBRL_INSTANCE_NAMESPACE or local_name.lower() != "context":
            continue
        context_id = str(context.attrib.get("id") or "").strip()
        if not context_id:
            continue

        entity = ""
        instant = ""
        start_date = ""
        end_date = ""
        dimensions: list[str] = []
        for item in context.iter():
            _, item_name = _tag_parts(item.tag)
            normalized_name = item_name.lower()
            if normalized_name == "identifier":
                entity = _element_text(item)
            elif normalized_name == "instant":
                instant = _element_text(item)
            elif normalized_name == "startdate":
                start_date = _element_text(item)
            elif normalized_name == "enddate":
                end_date = _element_text(item)
            elif normalized_name in {"explicitmember", "typedmember"}:
                dimension = str(item.attrib.get("dimension") or "").strip()
                member = _element_text(item)
                dimensions.append(
                    f"{dimension}={member}" if dimension and member else dimension or member
                )

        period = instant or (
            f"{start_date} - {end_date}" if start_date and end_date else start_date or end_date
        )
        contexts[context_id] = {
            "entity": entity,
            "period": period,
            "dimensions": "; ".join(value for value in dimensions if value),
        }
    return contexts


def _unit_details(root: Any) -> dict[str, str]:
    units: dict[str, str] = {}
    for unit in root.iter():
        namespace, local_name = _tag_parts(unit.tag)
        if namespace != XBRL_INSTANCE_NAMESPACE or local_name.lower() != "unit":
            continue
        unit_id = str(unit.attrib.get("id") or "").strip()
        measures = [
            _element_text(item)
            for item in unit.iter()
            if _tag_parts(item.tag)[1].lower() == "measure"
            and _element_text(item)
        ]
        if unit_id:
            units[unit_id] = " / ".join(measures)
    return units


class XBRLParser(BaseDocumentParser):
    parser_name = "xbrl"
    supported_extensions = frozenset({"xbrl"})

    def parse(self, source: DocumentParseInput) -> ParsedDocument:
        root = parse_xbrl_root(source.content)
        document_kind = xbrl_document_kind(root)
        contexts = _context_details(root)
        units = _unit_details(root)
        rows: list[dict[str, str]] = []

        for element in root.iter():
            namespace, element_name = _tag_parts(element.tag)
            context_ref = str(element.attrib.get("contextRef") or "").strip()
            if not context_ref:
                continue
            is_inline_fact = (
                namespace in INLINE_XBRL_NAMESPACES
                and element_name.lower() in INLINE_XBRL_FACT_NAMES
            )
            if document_kind == "inline" and not is_inline_fact:
                continue

            concept = (
                str(element.attrib.get("name") or "").strip()
                if is_inline_fact
                else element_name
            )
            qualified_name = concept if is_inline_fact else f"{{{namespace}}}{element_name}"
            value = _element_text(element)
            nil_value = next(
                (
                    str(attribute_value)
                    for attribute_name, attribute_value in element.attrib.items()
                    if _tag_parts(attribute_name)[1].lower() == "nil"
                ),
                "",
            )
            context = contexts.get(context_ref, {})
            unit_ref = str(element.attrib.get("unitRef") or "").strip()
            rows.append(
                {
                    "concept": concept,
                    "qualifiedName": qualified_name,
                    # The local parser has no taxonomy label linkbase; retaining an
                    # explicit fallback keeps the normalized fact contract stable.
                    "label": concept,
                    "value": value,
                    "entity": context.get("entity", ""),
                    "period": context.get("period", ""),
                    "dimensions": context.get("dimensions", ""),
                    "contextRef": context_ref,
                    "unit": units.get(unit_ref, ""),
                    "unitRef": unit_ref,
                    "decimals": str(element.attrib.get("decimals") or "").strip(),
                    "scale": str(element.attrib.get("scale") or "").strip(),
                    "sign": str(element.attrib.get("sign") or "").strip(),
                    "format": str(element.attrib.get("format") or "").strip(),
                    "nil": nil_value,
                }
            )

        def first_fact_value(concept_names: frozenset[str]) -> str:
            return next(
                (
                    row["value"]
                    for row in rows
                    if row["concept"].split(":")[-1].lower() in concept_names
                    and row["value"]
                ),
                "",
            )

        document_entity = first_fact_value(ENTITY_NAME_CONCEPTS)
        report_type = first_fact_value(REPORT_TYPE_CONCEPTS)
        report_period_end = first_fact_value(REPORT_PERIOD_CONCEPTS)

        warnings: list[ParserWarning] = []
        if not rows:
            warnings.append(
                ParserWarning(
                    code="empty_xbrl_facts",
                    message="XBRL 文件內沒有可擷取的 Facts。",
                )
            )

        return ParsedDocument(
            fileName=source.file_name,
            fileType=source.extension,
            parser=self.parser_name,
            blocks=(
                [
                    ParsedContentBlock(
                        type="table",
                        section="XBRL Facts",
                        columns=XBRL_FACT_COLUMNS,
                        rows=rows,
                        metadata={
                            "factCount": len(rows),
                            "xbrlDocumentKind": document_kind,
                            "documentEntity": document_entity,
                            "reportType": report_type,
                            "reportPeriodEnd": report_period_end,
                        },
                    )
                ]
                if rows
                else []
            ),
            warnings=warnings,
        )
