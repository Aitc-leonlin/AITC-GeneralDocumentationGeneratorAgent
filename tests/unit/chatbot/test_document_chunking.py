import json
import unittest

from src.features.chatbot.services.document_chunking import (
    DocumentChunkingService,
    StructureAwareDocumentChunker,
)
from src.features.chatbot.services.document_parsers.models import DocumentElement


def element(
    content: str,
    *,
    file_type: str = "txt",
    content_type: str = "text",
    section: str | None = None,
    page: int | None = None,
    metadata: dict | None = None,
) -> DocumentElement:
    return DocumentElement(
        document_id="doc-1",
        file_name=f"report.{file_type}",
        file_type=file_type,
        content_type=content_type,
        content=content,
        section=section,
        page=page,
        metadata=metadata or {},
    )


def service(*, size: int = 30, overlap: int = 2) -> DocumentChunkingService:
    return DocumentChunkingService(
        engine=StructureAwareDocumentChunker(
            chunk_size=size,
            chunk_overlap=overlap,
        )
    )


def chunk(elements: list[DocumentElement], *, size: int = 30):
    return service(size=size).chunk(
        elements=elements,
        file_type=elements[0].file_type if elements else "txt",
        chat_id="chat-1",
        upload_user="user-1",
    )


class StrategySelectionTests(unittest.TestCase):
    def test_selects_profiles_by_format_and_keeps_document_type_extension_point(self):
        chunking = service()

        self.assertEqual(chunking.resolve("docx").strategy_name, "docx_structure")
        self.assertEqual(chunking.resolve("pdf").strategy_name, "pdf_structure")
        self.assertEqual(chunking.resolve("html").strategy_name, "html_structure")
        self.assertEqual(chunking.resolve("xbrl").strategy_name, "xbrl_semantic")
        self.assertEqual(
            chunking.resolve("pdf", document_type="contract").strategy_name,
            "pdf_structure",
        )

    def test_pdf_page_is_metadata_not_a_forced_boundary(self):
        strategy = service().resolve("pdf")
        prepared = strategy.prepare_elements(
            [
                element(
                    "Page content",
                    file_type="pdf",
                    page=1,
                    metadata={"format_partition_type": "page"},
                )
            ],
            document_type=None,
        )

        self.assertFalse(prepared[0].metadata["chunk_boundary"])


class StructureAwareChunkingTests(unittest.TestCase):
    def test_empty_document_returns_no_chunks(self):
        self.assertEqual(
            service().chunk(
                elements=[],
                file_type="txt",
                chat_id="chat-1",
                upload_user="user-1",
            ),
            [],
        )

    def test_plain_text_uses_filename_as_title_and_unified_schema(self):
        chunks = chunk([element("Plain text content")])

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].document_title, "report")
        self.assertEqual(chunks[0].chunk_index, 0)
        self.assertEqual(chunks[0].content_type, "text")

    def test_oversized_paragraph_uses_token_fallback(self):
        chunks = chunk([element("一二三四五六七八九十")], size=4)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(
            all(item.metadata["structure_level"] == "token" for item in chunks)
        )

    def test_long_section_keeps_section_metadata(self):
        chunks = chunk(
            [
                element("甲乙丙丁", file_type="docx", section="財務分析 > 營收"),
                element("戊己庚辛", file_type="docx", section="財務分析 > 營收"),
            ],
            size=6,
        )

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(item.section_title == "財務分析 > 營收" for item in chunks))
        self.assertTrue(all(item.parent_section == "財務分析" for item in chunks))

    def test_oversized_html_section_falls_back_without_losing_heading(self):
        chunks = chunk(
            [
                element(
                    "一二三四五六七八九十",
                    file_type="html",
                    section="Financial Analysis > Revenue",
                )
            ],
            size=4,
        )

        self.assertGreater(len(chunks), 1)
        self.assertTrue(
            all(item.section_title == "Financial Analysis > Revenue" for item in chunks)
        )

    def test_large_table_repeats_title_headers_section_and_unit(self):
        table = element(
            json.dumps(
                {
                    "columns": ["Year", "Revenue"],
                    "rows": [
                        {"Year": "2025", "Revenue": "100"},
                        {"Year": "2024", "Revenue": "90"},
                        {"Year": "2023", "Revenue": "80"},
                    ],
                }
            ),
            file_type="csv",
            content_type="table",
            section="Revenue",
            metadata={"tableTitle": "Revenue Table", "unit": "TWD thousands"},
        )

        chunks = chunk([table], size=20)

        self.assertGreater(len(chunks), 1)
        for item in chunks:
            payload = json.loads(item.content)
            self.assertEqual(payload["title"], "Revenue Table")
            self.assertEqual(payload["columns"], ["Year", "Revenue"])
            self.assertEqual(payload["section"], "Revenue")
            self.assertEqual(payload["unit"], "TWD thousands")

    def test_single_oversized_table_row_is_not_token_split(self):
        table = element(
            json.dumps(
                {"columns": ["Name"], "rows": [{"Name": "很長的表格內容不應拆開"}]}
            ),
            file_type="csv",
            content_type="table",
        )

        chunks = chunk([table], size=4)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(json.loads(chunks[0].content)["columns"], ["Name"])


class XBRLChunkingTests(unittest.TestCase):
    def test_narrative_and_structured_facts_use_separate_retrieval_units(self):
        narrative = element(
            "Management expects stable growth.",
            file_type="xbrl",
            section="Risk Disclosure",
            metadata={"docling_label": "paragraph"},
        )
        facts = element(
            json.dumps(
                {
                    "columns": ["concept", "value", "period", "unit"],
                    "rows": [
                        {
                            "concept": "Revenue",
                            "label": "Revenue",
                            "value": "125000000",
                            "period": "2025",
                            "unit": "TWD",
                            "contextRef": "c1",
                        },
                        {
                            "concept": "Assets",
                            "label": "Assets",
                            "value": "500000000",
                            "period": "2025-12-31",
                            "unit": "TWD",
                            "contextRef": "c2",
                        },
                    ],
                }
            ),
            file_type="xbrl",
            content_type="table",
            section="XBRL Facts",
            metadata={
                "parser": "xbrl",
                "factCount": 2,
                "documentEntity": "Example Corp",
                "reportType": "Annual Report",
            },
        )

        chunks = chunk([narrative, facts], size=500)
        fact_chunks = [item for item in chunks if item.content_type == "xbrl_fact"]

        self.assertEqual(len(fact_chunks), 2)
        self.assertTrue(any(item.content_type == "text" for item in chunks))
        self.assertEqual(fact_chunks[0].document_title, "Example Corp Annual Report")
        self.assertEqual(fact_chunks[0].metadata["concept"], "Revenue")
        self.assertEqual(fact_chunks[0].metadata["period"], "2025")
        self.assertEqual(fact_chunks[0].metadata["unit"], "TWD")
        self.assertEqual(fact_chunks[0].metadata["value"], "125000000")
        self.assertEqual(fact_chunks[0].metadata["structure_level"], "atomic")

    def test_oversized_fact_remains_atomic(self):
        facts = element(
            json.dumps(
                {
                    "columns": ["concept", "value", "period", "unit"],
                    "rows": [
                        {
                            "concept": "Disclosure",
                            "value": "非常長的內容" * 20,
                            "period": "2025",
                            "unit": "pure",
                            "contextRef": "c1",
                        }
                    ],
                }
            ),
            file_type="xbrl",
            content_type="table",
            section="XBRL Facts",
            metadata={"parser": "xbrl", "factCount": 1},
        )

        chunks = chunk([facts], size=5)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0].metadata["structure_level"], "atomic")


if __name__ == "__main__":
    unittest.main()
