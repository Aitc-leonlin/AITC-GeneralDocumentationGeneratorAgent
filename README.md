# CreditInvestigationChatBotPython

This project is a backend server for a Credit Investigation ChatBot, implemented in Python 3.

## Setup

1. **Install dependencies:**
   ```bash
   make setup
   ```

2. **Run the server:**
   ```bash
   make start
    ```

If you want a single command similar to `package.json` scripts, use the included `Makefile`. `make start` will create `venv`, install the project and its `pyproject.toml` dependencies in editable mode, then run `app.py`. If dependencies are already installed and you only want to start the app, use `make run`.

## LLM Provider

The backend uses `src/features/chatbot/core/providers/chat_openAI_provider.py` as the shared chat model provider. Existing behavior remains OpenAI by default:

```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL_NAME=gpt-5-mini
```

To use an OpenAI-compatible local LLM server, switch only the environment variables:

```bash
LLM_PROVIDER=local
LOCAL_LLM_BASE_URL=http://192.168.20.169:8004/v1
LOCAL_LLM_MODEL_NAME=JunHowie/Qwen3-30B-A3B-Instruct-2507-GPTQ-Int4
LOCAL_LLM_API_KEY=not-needed
```

`LOCAL_LLM_BASE_URL` may also be set to a full chat completions endpoint such as `http://192.168.20.169:8004/v1/chat/completions`; the provider normalizes it to the `/v1` base URL required by LangChain.

## Database Connection Mode

The backend selects its database connection mode with `DATABASE_MODE`.

Use a local SQLite file:

```bash
DATABASE_MODE=sqlite
SQLITE_DB_PATH=FinancialStatementXBRL.db
```

Use an external PostgreSQL database:

```bash
DATABASE_MODE=postgresql
DATABASE_HOST=your-database.example.com
DATABASE_PORT=5432
DATABASE_NAME=aitc_credit_investigation
DATABASE_USER=aitc_app
DATABASE_PASSWORD=replace-with-a-secret
DATABASE_SSLMODE=require
DATABASE_SSLROOTCERT=
DATABASE_CONNECT_TIMEOUT_SECONDS=10
DATABASE_APPLICATION_NAME=aitc-credit-investigation-backend
DATABASE_SCHEMA=public
```

Render or another provider may supply one `DATABASE_URL` instead of
`DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER`, and
`DATABASE_PASSWORD`. `DATABASE_MODE=postgresql` is still required. Explicit
`DATABASE_SSLMODE` and `DATABASE_SCHEMA` settings continue to apply.

Database passwords are read only from the environment and are excluded from startup diagnostics. Copy `.env.example` to `.env` for local development; never commit `.env`.

## Semantic Workflow Routing

After question rewriting and scope classification, the chatbot uses its existing
LLM category classifier to choose one of 14 standard credit analysis workflows.
A classification with confidence below 0.55, or the `OTHER` category, goes to
the Deep Agent fallback. Standard categories use the Python templates in
`src/features/chatbot/core/agent/nodes/semantic_workflow_templates.py` for
analysis purposes, data requirements, retrieval focus, steps, and output rules.
This runtime route does not open a Neo4j connection or require Neo4j settings.

All standard workflows continue through semantic planning, optional frontend
source selection, retrieval, and answer generation. The old Neo4j compose file
and sync scripts are retained only as inactive reference material; they are not
part of application startup or routing.

The shared connection layer uses SQLAlchemy 2.x for both connection modes
(`sqlite+pysqlite` and `postgresql+psycopg`). Runtime parameters, result rows,
transactions, schema inspection, inserts, and upserts are normalized through
that layer. Business services do not branch on SQLite versus PostgreSQL;
dialect-specific timestamp compilation, locking, table clearing, and metadata
inspection are centralized in the shared database layer. Migration files remain
separated under `src/sql/migrations/sqlite`
and `src/sql/migrations/postgresql` because DDL differs by dialect; XBRL
migrations V1.0 and V2.0 plus membership migrations V1.1 through V1.12 are
selected automatically from `DATABASE_MODE` and applied when the backend
starts. Startup initialization also inserts missing default membership seed
records without replacing existing records.

Chatbot uploads are stored under `storage/chat_documents` by default. The
database stores document metadata and a relative storage key, not the raw file
bytes. Set `CHAT_DOCUMENT_STORAGE_DIR` to use another local directory and
`CHAT_DOCUMENT_MAX_FILE_SIZE_BYTES` to change the default 20 MB per-file limit.

### Document Parser Layer

`src/features/chatbot/services/document_parsers` provides a common
`BaseDocumentParser` interface and format-specific PDF, DOCX, text/Markdown,
CSV, and XLSX parsers. Parsers convert raw bytes into `ParsedDocument` blocks
and do not create embeddings. PDF output remains page-based, Markdown and DOCX
retain section information, and spreadsheet formats retain columns and rows.
Expected limitations, such as scanned PDFs without extractable text or
irregular Excel layouts, are returned as a parser status or warning instead of
silently fabricating content.

The normalization layer converts every parser result into a parser-neutral
`list[DocumentElement]`. Each element contains the document ID, source file
information, `text` or `table` content, optional page, sheet, and section
coordinates, plus parser diagnostics in metadata. Table content is serialized
as JSON so downstream chunking, embedding, and retrieval code only depends on
the standard document schema instead of format-specific parser models.

### Docling Format Structure Layer

After normalization, `src/features/chatbot/services/document_structure` runs
Docling against the original in-memory file. PDF content is partitioned by page,
XLSX content by sheet, CSV content by table, and DOCX/Markdown content by its
detected top-level section. Docling reading order, item labels, heading levels,
groups, tables, page coordinates, and source references are retained in element
metadata. PDF heading-hierarchy inference is enabled.

The Docling layer handles PDF, DOCX, HTML, Markdown, CSV, XLSX, and XBRL.
Plain TXT keeps the normalized paragraph structure because Docling does not
expose TXT as a native input format. General HTML and Inline XBRL are
distinguished from their content instead of their filename alone. If conversion
fails or returns no usable structure, the layer
explicitly reports a warning and supplies format partitions derived from the
normalized elements instead of failing the upload.

### Structure-aware Chunking Layer

`src/features/chatbot/services/document_chunking` selects an extensible profile
for DOCX, PDF, HTML, XBRL, Markdown, plain text, or tabular files and converts
the prepared elements into retrieval-ready `DocumentChunk` records. The shared
engine first keeps semantic sections intact, then follows element and paragraph
boundaries before using token windows as the final fallback. PDF pages remain
source metadata rather than mandatory chunk boundaries. Oversized tables are
split by complete rows while repeating their headers, caption/title, section,
and unit context.

XBRL narrative content follows normal structure-aware chunking. Structured
facts become atomic retrieval units so concept, label, entity, context, period,
dimensions, unit, and value cannot be separated by token splitting. Docling is
used for XBRL narrative structure, while the local XBRL parser preserves the
complete fact context that Docling's current flattened key-value output omits.

Every chunk uses one schema with document title, content type, section title and
level, parent section, page, sheet, chat, case, and upload-user provenance.
Chunk metadata also records the selected strategy, source element indexes,
source parser metadata, structure level, token count, and overlap. Set
`CHAT_DOCUMENT_CHUNK_SIZE` and `CHAT_DOCUMENT_CHUNK_OVERLAP` to override the
default 800-token size and 80-token overlap.

### Inspecting an Upload

Keep the backend terminal visible, stage a document in the Chat upload dialog,
and then send the Chat message. Confirming the upload dialog only stages the
file; sending the message performs the backend upload. Search the terminal for
`FINAL EMBEDDING CHUNKS`. The JSON array between its `START` and `END` markers
contains only the final `DocumentChunk` records intended to become the source
objects for embedding and Vector DB persistence. Parser, normalization,
Docling, decision-summary, and content-preview debug payloads are not printed.
This marker is printed immediately before vector indexing, so it verifies chunk
generation only. A successful upload response means the subsequent embedding
and Vector DB upsert also completed; an indexing failure rolls the upload back.

### Document Embedding and Retrieval

The upload API passes final `DocumentChunk` objects to a separate vector
indexing pipeline. Phase 5 currently indexes `content_type=text` chunks only;
table, XBRL fact, and mixed chunks remain available to the parser pipeline but
are not embedded. It uses `intfloat/multilingual-e5-large` locally, prefixes
stored passages with `passage: `, prefixes retrieval queries with `query: `,
L2-normalizes the resulting 1024-dimensional vectors, and stores the raw
segment text plus flat filter metadata in Chroma. The default adapter connects
to a Chroma Docker/server instance at `127.0.0.1:8010`; local persistent mode
remains available as an adapter configuration.

E5 accepts at most 512 model tokens. Existing parser and chunker behavior is
unchanged: an indexing-only segmenter checks each final chunk with the E5
tokenizer and splits only chunks that exceed that limit, using a default
64-token overlap. One source chunk may therefore create multiple vector
records; `source_chunk_id`, `embedding_segment_index`, and
`embedding_segment_count` preserve that relationship.

The vector domain models, embedding adapter, Chroma repository, indexing
service, and retrieval service are independent layers. Business logic searches
with a `VectorSearchFilter` instead of Chroma `where` dictionaries. Uploaded
raw files remain under document storage and are never stored in Chroma. On the
first indexed upload, Hugging Face downloads the configured model unless it is
already present in the local cache.

Configuration:

```env
CHAT_EMBEDDING_MODEL=intfloat/multilingual-e5-large
CHAT_EMBEDDING_DEVICE=auto
CHAT_EMBEDDING_BATCH_SIZE=8
CHAT_EMBEDDING_SEGMENT_OVERLAP=64
CHAT_VECTOR_STORE_PROVIDER=chroma
CHAT_VECTOR_COLLECTION=chat_documents_multilingual_e5_large
CHAT_CHROMA_MODE=http
CHAT_CHROMA_HOST=127.0.0.1
CHAT_CHROMA_PORT=8010
CHAT_CHROMA_SSL=FALSE
CHAT_CHROMA_TENANT=default_tenant
CHAT_CHROMA_DATABASE=default_database
# Only used for CHAT_CHROMA_MODE=persistent
CHAT_VECTOR_STORE_DIR=storage/chroma
```

When the backend itself runs in Docker, set `CHAT_CHROMA_HOST` to the Chroma
Compose service/container DNS name instead of `127.0.0.1`.

## Regression Tests

Run the backend regression suite with:

```bash
make test-regression
```

The runner first prints the current FastAPI API feature inventory, then executes contract and CRUD checks. It copies `FinancialStatementXBRL.db` to a temporary SQLite file and sets `SQLITE_DB_PATH` to that copy, so test writes do not modify the project database.

To only list the current API features:

```bash
venv/bin/python scripts/run_regression_tests.py --list-only
```

The default suite avoids successful chatbot/report generation calls because those paths may invoke an external or local LLM. It still verifies protected chatbot auth behavior and local LLM provider URL normalization.

## Project Structure
- `app.py`: Main entry point for the backend server.
- `pyproject.toml`: Project metadata, supported Python version, and Python dependencies.

## Backend Modules

Backend feature code is organized under `src/features`. Each module owns the API entry points, business logic, schemas, and module-specific utilities for one business domain.

Current modules:

- `src/features/chatbot`: Chatbot APIs, expert-knowledge APIs, warehouse-data APIs, LangGraph agent flow, LLM provider, XBRL mapping resources, and chatbot-specific helper services.
- `src/features/membership`: Membership, authentication, RBAC, menu permissions, organization, audit, notification, and admin APIs.
- `src/features/report_generator`: Credit report generation APIs, report history/dashboard logic, LLM conclusion service, and DOCX chapter generation services.

Common module folders:

| Folder | Purpose |
|---|---|
| `api` | FastAPI routers and endpoints. This is the HTTP entry layer called by frontend clients. |
| `schemas` | Pydantic request/response models and API validation shapes. These also affect Swagger/OpenAPI documentation. |
| `services` | Business logic and workflow orchestration. API handlers should delegate main behavior here. |
| `repositories` | Database access logic such as queries, inserts, updates, deletes, and row mapping. |
| `models` | Domain/data models used by the module, including database entities or workflow state types. |
| `core` | Module-specific shared utilities and lower-level building blocks, such as auth helpers, JWT/password utilities, LangGraph agent code, providers, or mappings. |
| `seeds` | Default seed data used during bootstrap, currently mainly used by membership. |
| `validation` | Shared validation helpers inside a module, currently mainly used by membership. |

Cross-module utilities should go under `src/shared` instead of inside one module. For example, shared database path utilities are under `src/shared/database`.

Placement rules for future changes:

- New API route: `src/features/<module>/api`
- New business workflow/service: `src/features/<module>/services`
- New DB access code: `src/features/<module>/repositories`
- New request/response schema: `src/features/<module>/schemas`
- New module-only helper: `src/features/<module>/core`
- Utility used by multiple modules: `src/shared`

## XBRL To SQL

Use `scripts/build_xbrl_sql.py` to parse a `tifrs-20200630` taxonomy directory together with one XBRL instance file, then generate SQL `INSERT` statements for these tables:

- `report_instance`
- `taxonomy_entry_point`
- `taxonomy_concept`
- `taxonomy_presentation`
- `taxonomy_calculation`
- `xbrl_fact`
- `field_dictionary`
- `field_concept_mapping`
- `financial_metric_value`

Example:

```bash
python3 scripts/build_xbrl_sql.py \
  --taxonomy-root /path/to/tifrs-20200630 \
  --instance /path/to/report.xbrl \
  --sql-output ./output/report_import.sql
```

### PostgreSQL XBRL parser

When `DATABASE_MODE=postgresql`, the common `scripts/build_xbrl_sql.py` command
automatically delegates to `scripts/build_xbrl_sql_postgresql.py`. The latter
can also be called directly. It reads connection settings from the database ENV
variables and generates idempotent PostgreSQL UPSERT statements.

First import, including taxonomy metadata:

```bash
venv/bin/python scripts/build_xbrl_sql_postgresql.py \
  --taxonomy-root "/path/to/tifrs-20200630" \
  --instance-dir "/path/to/financial-report-folder" \
  --sql-output output/xbrl_import_postgresql.sql \
  --load-db
```

After taxonomy data already exists in PostgreSQL:

```bash
venv/bin/python scripts/build_xbrl_sql_postgresql.py \
  --taxonomy-from-db \
  --instance "/path/to/company-report.html" \
  --sql-output output/company_report_postgresql.sql \
  --load-db
```

Omit `--load-db` to generate the SQL file without changing the database. The
PostgreSQL XBRL schema migrations V1.0 and V2.0 must exist first; normal
backend startup applies them automatically.

## 財務報表解析匯入流程

如果要把下載好的財務報表 XBRL/iXBRL 檔案匯入資料庫，主要使用 `scripts/build_xbrl_sql.py`。它會依 `DATABASE_MODE` 產生 SQLite 或 PostgreSQL 語法，並寫入 `report_instance`、`xbrl_fact`、`financial_metric_value` 等查詢報告會用到的資料表。

### 1. 準備財報檔案

把同一批要匯入的財報放在同一個資料夾中，支援副檔名：

- `.xbrl`
- `.xml`
- `.html`
- `.htm`

檔名建議維持公開資訊觀測站下載格式，例如：

```text
tifrs-fr1-m1-ci-cr-4960-2025Q1.html
tifrs-fr1-m1-ci-cr-4960-2025Q2.html
tifrs-fr1-m1-ci-cr-4960-2025Q3.html
tifrs-fr1-m1-ci-cr-4960-2025Q4.html
```

### 2. 使用既有 DB taxonomy 匯入財報

如果 `FinancialStatementXBRL.db` 已經有 taxonomy 資料，使用 `--taxonomy-from-db` 即可，不需要重新解析 taxonomy 目錄。

```bash
python3 scripts/build_xbrl_sql.py \
  --taxonomy-from-db \
  --db-path FinancialStatementXBRL.db \
  --instance-dir /path/to/financial-report-folder \
  --sql-output ./output/import_financial_reports.sql
```

這個指令會做兩件事：

- 產生 SQL 檔到 `--sql-output`
- 因為有帶 `--db-path`，會直接把 SQL 載入 `FinancialStatementXBRL.db`

匯入後會影響的主要資料表：

- `report_instance`: 每一份財報的基本資料，例如公司代碼、年度、季度、檔名、期間。
- `xbrl_fact`: 財報裡每一個 XBRL 科目的實際數值或文字，例如營收、淨利、資產、負債。
- `financial_metric_value`: 依照目前 mapping 建出的查詢用指標值，報告產生與趨勢圖會用到。

### 3. 只解析單一財報檔案

如果只要匯入一個檔案，用 `--instance`：

```bash
python3 scripts/build_xbrl_sql.py \
  --taxonomy-from-db \
  --db-path FinancialStatementXBRL.db \
  --instance /path/to/tifrs-fr1-m1-ci-cr-4960-2025Q1.html \
  --sql-output ./output/import_4960_2025Q1.sql
```

### 4. 第一次建立 taxonomy 資料

如果 DB 還沒有 taxonomy，才需要用 `--taxonomy-root` 指向 taxonomy 目錄。這會把 taxonomy metadata 與財報一起產生 SQL。

```bash
python3 scripts/build_xbrl_sql.py \
  --taxonomy-root /path/to/tifrs-20200630 \
  --instance-dir /path/to/financial-report-folder \
  --db-path FinancialStatementXBRL.db \
  --sql-output ./output/import_with_taxonomy.sql
```

### 5. 匯入後檢查

確認 `report_instance` 是否有進資料：

```bash
python3 -c "import sqlite3; con=sqlite3.connect('FinancialStatementXBRL.db'); print(con.execute(\"select report_id, company_code, year, quarter from report_instance where company_code='4960' order by year, quarter\").fetchall()); con.close()"
```

確認每季 `xbrl_fact` 筆數：

```bash
python3 -c "import sqlite3; con=sqlite3.connect('FinancialStatementXBRL.db'); print(con.execute(\"select ri.quarter, count(xf.fact_id) from report_instance ri left join xbrl_fact xf on xf.report_id=ri.report_id where ri.company_code='4960' and ri.year=2025 group by ri.quarter order by ri.quarter\").fetchall()); con.close()"
```

確認 `financial_metric_value` 筆數：

```bash
python3 -c "import sqlite3; con=sqlite3.connect('FinancialStatementXBRL.db'); print(con.execute(\"select quarter, count(*) from financial_metric_value where company_code='4960' and year=2025 group by quarter order by quarter\").fetchall()); con.close()"
```

### 6. XBRL Dictionary 與公司基本資料維護 scripts

以下四支 script 都是人工執行的維護工具，不會由 FastAPI 啟動流程或 Chatbot API 自動呼叫：

- `parse_xbrl_dictionary.py`、`build_xbrl_mapping_json.py`、`split_xbrl_dictionary.py` 只產生 JSON，不會產生 SQL 檔或修改 SQLite DB。
- `import_listed_company_profile.py` 不會產生 SQL 檔，會依 `DATABASE_MODE` 連線並執行 `INSERT ... ON CONFLICT DO UPDATE`，直接修改 `company_profile`。
- 真正會產生 XBRL SQL 檔的是 `scripts/build_xbrl_sql.py`。

#### 6.1 `parse_xbrl_dictionary.py`

目的：解析完整的 XBRL Criteria/Taxonomy 目錄，建立 Chatbot 科目比對所需的完整 Dictionary、精簡索引與解析摘要。

支援解析：

- XSD Concept 定義
- Label Linkbase
- Presentation Linkbase
- Calculation Linkbase
- Definition Linkbase（目錄模式）

建議在 XBRL Criteria 版本或原始檔更新時重新執行：

```bash
python3 scripts/parse_xbrl_dictionary.py \
  --root-dir "/path/to/XBRL Criteria tifrs-20200630" \
  --output src/features/chatbot/services/xbrl_data_dictionary_all.json \
  --compact-output src/features/chatbot/services/xbrl_account_title_compact.json \
  --summary-output src/features/chatbot/services/xbrl_dictionary_summary_all.json
```

主要輸出：

- `xbrl_data_dictionary_all.json`：完整 Concept、Label、Role、Presentation、Calculation 與 Definition 資訊。
- `xbrl_account_title_compact.json`：精簡的 Concept、中文、英文與代碼索引。
- `xbrl_dictionary_summary_all.json`：來源路徑、檔案數與 Concept 數量摘要。

也支援單組檔案模式；此模式必須同時提供 `--xsd`、`--label`、`--presentation`、`--calculation`。

#### 6.2 `build_xbrl_mapping_json.py`

目的：讀取 `parse_xbrl_dictionary.py` 產出的完整 Dictionary，整理每個 Concept 的中文、英文、Alias、報表類型、產業類型與 Presentation Path，供 Chatbot 科目名稱比對。

應在 `parse_xbrl_dictionary.py` 完成後執行：

```bash
python3 scripts/build_xbrl_mapping_json.py \
  --dictionary-json src/features/chatbot/services/xbrl_data_dictionary_all.json \
  --output src/features/chatbot/services/xbrl_mapping/concept_mapping.json \
  --summary-output src/features/chatbot/services/xbrl_mapping/summary.json \
  --taxonomy-root "/path/to/XBRL Criteria tifrs-20200630"
```

主要輸出：

- `xbrl_mapping/concept_mapping.json`：Chatbot 使用的 Concept 名稱與 Alias Mapping。
- `xbrl_mapping/summary.json`：Concept、中文、英文、Alias 與 Label Role 統計。

`--taxonomy-root` 只會記錄在 Summary 中供追溯，不會在這支 script 內重新解析 Criteria 原始檔。

#### 6.3 `split_xbrl_dictionary.py`

目的：將完整 Dictionary 依報表類型與 Taxonomy Family 拆成較小 JSON，讓 Chatbot 優先載入與公司及報表類型相關的候選科目。

應在 `parse_xbrl_dictionary.py` 完成後執行：

```bash
python3 scripts/split_xbrl_dictionary.py \
  --input src/features/chatbot/services/xbrl_data_dictionary_all.json \
  --output-dir src/features/chatbot/services/xbrl_dictionary_splits \
  --summary-output src/features/chatbot/services/xbrl_dictionary_splits/summary.json
```

主要輸出目錄：

- `xbrl_dictionary_splits/balance_sheet/`
- `xbrl_dictionary_splits/comprehensive_income_statement/`
- `xbrl_dictionary_splits/statement_of_cash_flows/`

每個報表目錄包含 `__all__.json`，以及 BSCI、SCF、IFRS 等 Family 分檔。Chatbot Runtime 會依公司實際使用的 Taxonomy Family 選擇這些檔案。

#### 6.4 `import_listed_company_profile.py`

目的：將上市公司基本資料 JSON 匯入 `company_profile`，供報告產生器查詢公司名稱、統編、產業、負責人、地址、資本額、會計師與聯絡資料。

輸入 JSON 的根節點必須是公司物件陣列，例如：

```json
[
  {
    "出表日期": "2026-01-01",
    "公司代號": "1101",
    "公司名稱": "台灣水泥股份有限公司",
    "公司簡稱": "台泥",
    "產業別": "01",
    "營利事業統一編號": "11913502"
  }
]
```

執行方式：

```bash
python3 scripts/import_listed_company_profile.py \
  /path/to/listed_company_profiles.json
```

未指定 `--db` 時，會依 `DATABASE_MODE` 使用完整的 DB ENV 設定；SQLite
預設為專案根目錄的 `FinancialStatementXBRL.db`。`--db` 僅供 SQLite
臨時覆寫檔案路徑，PostgreSQL 模式不可使用。

匯入以 `company_code` 為唯一鍵：公司已存在時更新資料，不存在時新增。這支 script 會直接修改 DB，執行前應確認 JSON 與 DB 路徑。

#### 6.5 建議使用順序

XBRL Criteria 更新時：

```text
1. parse_xbrl_dictionary.py
   ↓ 產生 xbrl_data_dictionary_all.json
2. build_xbrl_mapping_json.py
   ↓ 產生 xbrl_mapping/concept_mapping.json
3. split_xbrl_dictionary.py
   ↓ 產生 xbrl_dictionary_splits/*
4. 重新啟動後端服務
   ↓ 清除 lru_cache，讓 Runtime 載入新版 JSON
```

`build_xbrl_mapping_json.py` 與 `split_xbrl_dictionary.py` 都依賴第 1 步的完整 Dictionary，兩者彼此沒有先後相依。

上市公司基本資料更新時，獨立執行：

```text
import_listed_company_profile.py
→ 直接新增或更新 company_profile
```

公司財報 XBRL/iXBRL 匯入則使用 `scripts/build_xbrl_sql.py`，不屬於上述 Dictionary JSON 維護流程。

If you only want taxonomy SQL first, `--instance` is optional:

```bash
python3 scripts/build_xbrl_sql.py \
  --taxonomy-root /path/to/tifrs-20200630 \
  --sql-output ./output/taxonomy_only.sql
```

By default, `field_dictionary` and `field_concept_mapping` are created in `auto-concept` mode, which means each parsed concept is mapped 1:1 to an internal field. If you already have your own business field definitions, switch to `--field-mode custom` and provide a JSON file shaped like:

```json
{
  "fields": [
    {
      "field_id": "assets",
      "canonical_name": "assets",
      "zh_name": "資產總額",
      "en_name": "Assets",
      "module": "BSCI",
      "statement_type": "balance_sheet",
      "value_type": "numeric",
      "description": "Total assets"
    }
  ],
  "mappings": [
    {
      "field_id": "assets",
      "taxonomy_id": "tifrs-20200630:BSCI",
      "concept_ids": ["ifrs-full_Assets"],
      "industry_type": "CI",
      "priority": 1,
      "effective_from": "2020-06-30",
      "effective_to": null
    }
  ]
}
```
