from __future__ import annotations

from langchain_text_splitters import MarkdownHeaderTextSplitter

from src.features.chatbot.services.document_parsers.base import (
    BaseDocumentParser,
    DocumentParseInput,
    DocumentParserError,
)
from src.features.chatbot.services.document_parsers.common import section_path, text_blocks
from src.features.chatbot.services.document_parsers.models import (
    ParsedContentBlock,
    ParsedDocument,
    ParserWarning,
)


MARKDOWN_HEADERS = [("#" * level, f"h{level}") for level in range(1, 7)]


class TextParser(BaseDocumentParser):
    parser_name = "text"
    supported_extensions = frozenset({"txt", "md", "markdown"})

    def parse(self, source: DocumentParseInput) -> ParsedDocument:
        try:
            content = source.content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise DocumentParserError(
                "unsupported_text_encoding",
                "TXT 與 Markdown 目前只支援 UTF-8 編碼。",
            ) from exc

        blocks = (
            self._markdown_blocks(content)
            if source.extension in {"md", "markdown"}
            else text_blocks(content)
        )
        warnings = []
        if not blocks:
            warnings.append(
                ParserWarning(code="empty_document", message="文字文件沒有可解析的內容。")
            )
        return ParsedDocument(
            fileName=source.file_name,
            fileType=source.extension,
            parser=self.parser_name,
            blocks=blocks,
            warnings=warnings,
        )

    @staticmethod
    def _markdown_blocks(content: str) -> list[ParsedContentBlock]:
        splitter = MarkdownHeaderTextSplitter(
            headers_to_split_on=MARKDOWN_HEADERS,
            strip_headers=True,
        )
        documents = splitter.split_text(content)
        blocks: list[ParsedContentBlock] = []
        previous_hierarchy: list[tuple[int, str]] = []

        for document in documents:
            hierarchy = [
                (level, str(document.metadata.get(f"h{level}") or "").strip())
                for level in range(1, 7)
            ]
            hierarchy = [(level, heading) for level, heading in hierarchy if heading]
            common_length = 0
            for previous, current in zip(previous_hierarchy, hierarchy):
                if previous != current:
                    break
                common_length += 1
            for index in range(common_length, len(hierarchy)):
                blocks.append(
                    ParsedContentBlock(
                        type="heading",
                        content=hierarchy[index][1],
                        section=section_path(
                            heading for _, heading in hierarchy[: index + 1]
                        ),
                        metadata={"level": hierarchy[index][0]},
                    )
                )
            blocks.extend(
                text_blocks(
                    document.page_content,
                    section_path(heading for _, heading in hierarchy),
                )
            )
            previous_hierarchy = hierarchy

        return blocks
