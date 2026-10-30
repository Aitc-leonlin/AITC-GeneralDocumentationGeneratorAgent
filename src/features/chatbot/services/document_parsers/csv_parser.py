from __future__ import annotations

import csv
import io

from src.features.chatbot.services.document_parsers.base import (
    BaseDocumentParser,
    DocumentParseInput,
    DocumentParserError,
)
from src.features.chatbot.services.document_parsers.common import normalize_columns
from src.features.chatbot.services.document_parsers.models import (
    ParsedContentBlock,
    ParsedDocument,
    ParserWarning,
)


class CsvParser(BaseDocumentParser):
    parser_name = "csv"
    supported_extensions = frozenset({"csv"})

    def parse(self, source: DocumentParseInput) -> ParsedDocument:
        try:
            content = source.content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentParserError(
                "unsupported_text_encoding",
                "CSV 目前只支援 UTF-8 編碼。",
            ) from exc

        warnings: list[ParserWarning] = []
        try:
            dialect = csv.Sniffer().sniff(content[:8192], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
            warnings.append(
                ParserWarning(
                    code="csv_dialect_fallback",
                    message="無法可靠判斷 CSV 分隔符號，已使用逗號解析。",
                )
            )

        try:
            matrix = list(csv.reader(io.StringIO(content), dialect=dialect, strict=True))
        except csv.Error as exc:
            raise DocumentParserError("invalid_csv", f"CSV 解析失敗：{exc}") from exc
        matrix = [row for row in matrix if any(str(value).strip() for value in row)]
        if not matrix:
            return ParsedDocument(
                fileName=source.file_name,
                fileType=source.extension,
                parser=self.parser_name,
                warnings=[ParserWarning(code="empty_document", message="CSV 沒有資料。")],
            )

        columns, columns_changed = normalize_columns(matrix[0])
        if columns_changed:
            warnings.append(
                ParserWarning(
                    code="normalized_csv_columns",
                    message="CSV 包含空白或重複欄名，已產生安全欄名。",
                )
            )

        rows: list[dict[str, str]] = []
        irregular_rows: list[int] = []
        for row_number, values in enumerate(matrix[1:], start=2):
            if len(values) != len(columns):
                irregular_rows.append(row_number)
            padded = [*values[: len(columns)], *([""] * max(0, len(columns) - len(values)))]
            rows.append(dict(zip(columns, padded)))
        if irregular_rows:
            warnings.append(
                ParserWarning(
                    code="irregular_csv_rows",
                    message="CSV 部分資料列的欄位數與標題列不同，已截斷或補空值。",
                    context={"rows": irregular_rows},
                )
            )

        return ParsedDocument(
            fileName=source.file_name,
            fileType=source.extension,
            parser=self.parser_name,
            blocks=[
                ParsedContentBlock(
                    type="table",
                    columns=columns,
                    rows=rows,
                    metadata={"delimiter": dialect.delimiter, "rowCount": len(rows)},
                )
            ],
            warnings=warnings,
        )

