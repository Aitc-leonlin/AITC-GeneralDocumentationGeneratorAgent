"""Validate generated Markdown tables and omit ones that cannot become DOCX tables."""

from docx import Document
from markdown_it import MarkdownIt

from src.features.report_generator.services.domain_report_service import _render_markdown_body


TABLE_FORMAT_FEW_SHOT = """Markdown 表格格式範例（以下整段放在同一個 paragraphs 字串內）：
正確：
以下為項目與數量：

| 項目 | 數量 | 備註 |
|---|---:|---|
| 範例甲 | 2 | 僅格式 |
| 範例乙 | 3 | 僅格式 |

數量可依需求調整。

錯誤：以下為項目與數量：| 項目 | 數量 | 備註 |
|---|---:|---|
表格前後各留一個空行；表頭、分隔列、每筆資料各占一行且欄數相同。
不要用程式碼區塊包住表格，也不要把表頭接在敘述文字後面。
以上項目與數值只格式，不得當成這份文件的事實。
"""


def join_markdown_paragraphs(paragraphs: list[str]) -> str:
    """Use the same joining rules when validating and rendering section text."""
    blocks: list[str] = []
    for paragraph in paragraphs:
        content = paragraph.strip()
        if not content:
            continue
        if blocks and content.startswith("|") and blocks[-1].rstrip().endswith("|"):
            blocks[-1] += "\n" + content
        else:
            blocks.append(content)
    return "\n\n".join(blocks)


def _looks_like_table_line(line: str) -> bool:
    return line.count("|") >= 2 or " | " in line or _is_separator_line(line)


def _is_separator_line(line: str) -> bool:
    cells = line.strip().strip("|").split("|")
    return len(cells) >= 2 and all(
        len(cell.strip().strip(":")) >= 3
        and set(cell.strip().strip(":")) == {"-"}
        for cell in cells
    )


def markdown_table_issue(paragraphs: list[str]) -> str | None:
    """Return an issue when table-looking text will not render as a Word table."""
    markdown = join_markdown_paragraphs(paragraphs)
    groups: list[list[str]] = []
    current: list[str] = []
    for line in markdown.splitlines():
        if _looks_like_table_line(line):
            current.append(line)
        elif current:
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    expected = sum(
        len(group) >= 2
        or any(_is_separator_line(line) for line in group)
        or any(line.lstrip().startswith("|") and line.count("|") >= 2 for line in group)
        for group in groups
    )
    if not expected:
        return None

    tokens = MarkdownIt("default").enable("table").parse(markdown)
    table_count = 0
    data_row_counts: list[int] = []
    in_body = False
    for token in tokens:
        if token.type == "table_open":
            table_count += 1
            data_row_counts.append(0)
        elif token.type == "tbody_open":
            in_body = True
        elif token.type == "tbody_close":
            in_body = False
        elif token.type == "tr_open" and in_body:
            data_row_counts[-1] += 1
    if table_count != expected:
        return f"偵測到 {expected} 個疑似 Markdown 表格，但只有 {table_count} 個可轉成 Word 表格"
    if any(count == 0 for count in data_row_counts):
        return "Markdown 表格缺少資料列"
    try:
        preview = Document()
        _render_markdown_body(preview, markdown)
    except Exception as error:
        return f"Word 表格建立失敗：{error}"
    if len(preview.tables) != expected or any(len(table.rows) < 2 for table in preview.tables):
        return "Markdown 表格未產生完整的 Word 表格"
    return None


def omit_unrenderable_markdown_tables(paragraphs: list[str]) -> str:
    """Keep prose and renderable tables; discard only malformed table-like lines."""
    markdown = join_markdown_paragraphs(paragraphs)
    if not markdown:
        return markdown

    lines = markdown.splitlines()
    tokens = MarkdownIt("default").enable("table").parse(markdown)
    table_ranges = {
        tuple(token.map) for token in tokens
        if token.type == "table_open" and token.map
    }
    code_lines = {
        index
        for token in tokens if token.type in {"fence", "code_block"} and token.map
        for index in range(*token.map)
    }

    kept: list[str] = []
    index = 0
    while index < len(lines):
        if index in code_lines or not _looks_like_table_line(lines[index]):
            kept.append(lines[index])
            index += 1
            continue

        start = index
        while (
            index < len(lines)
            and index not in code_lines
            and _looks_like_table_line(lines[index])
        ):
            index += 1
        group = lines[start:index]
        looks_like_table = (
            len(group) >= 2
            or any(_is_separator_line(line) or line.count("|") >= 2 for line in group)
        )
        if not looks_like_table or (
            (start, index) in table_ranges
            and markdown_table_issue(["\n".join(group)]) is None
        ):
            kept.extend(group)
            continue

        # A common failure puts the table header after a sentence on one line.
        # Keep that sentence while discarding the malformed table and its rows.
        prefix = group[0].split("|", 1)[0].rstrip()
        if prefix.endswith(("。", "：", ":", "！", "？", "!", "?")):
            kept.append(prefix)

    return "\n".join(kept)
