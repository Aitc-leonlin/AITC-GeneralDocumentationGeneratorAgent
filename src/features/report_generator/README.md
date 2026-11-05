# 對話式通用文件產生器

報告對話頁的 API、LangGraph 節點與畫面流程請見 [REPORT_GENERATOR_WORKFLOW.mmd](REPORT_GENERATOR_WORKFLOW.mmd)。
所有已註冊 API 的流程請見 [REPORT_GENERATOR_ALL_API_WORKFLOW.mmd](REPORT_GENERATOR_ALL_API_WORKFLOW.mmd)。

## 程式碼位置

`services/report_chat_service.py` 保留原本的公開匯入路徑，實際工作依流程放在 `services/report_chat/`：

| 檔案 | 責任 |
| --- | --- |
| `schemas.py` | 對話、文件／章節／內容種類、大綱及產生文件的資料結構 |
| `catalog.py` | D01～D30、S01～S20、C01～C20 目錄與範例問題的讀取、核對 |
| `samples.py` | D01～D30 固定輸入案例的結構與載入 |
| `llm.py` | 結構化 LLM 呼叫、重試與呼叫紀錄 |
| `document_type_graph.py` | 問題辨識與文件種類解析 Graph |
| `sample_matcher.py` | 依大綱與案例 metadata 選出相關測試資料 |
| `docx_content_graph.py` | 依 metadata 比對結果分流 JSON 與大綱 LLM 撰寫 |
| `current_draft.py` | 將目前大綱與產生的章節內容寫入 DOCX |
| `outline.py` | 對話入口、用途確認、資料來源與通用大綱的路由 |

API 入口在 `api/report_generator.py`，Thread 的資料庫讀寫在 `services/report_thread_service.py`，DOCX 排版在 `services/domain_report_service.py`。

## 內容種類目錄

[`data/content_type_templates.json`](data/content_type_templates.json) 固定收錄 C01～C20 的內容種類、性質、功能描述及所需能力。這些所需能力目前是規劃欄位，表示該內容種類日後需要什麼能力，不代表 Agent 已實作或會立即執行。

## 章節種類目錄

[`data/section_type_templates.json`](data/section_type_templates.json) 固定收錄 S01～S20 的章節種類、目的、建議內容種類 ID 與常見文件標籤；載入時會核對每個 C ID 均存在。「常見文件」沿用文字標籤；正式的 D→S 對應則使用文件目錄中的必要／可選章節 ID。D21～D30 原有的 `suggestedSections` 是先前提供的自由文字提示，與附件的 S ID 對應分開保存。

## 通用文件 Graph 流程

對話入口會把 D01～D30 的 ID、名稱、分類與 `purpose` 當作 LLM 的參考 metadata。`classify_question` 根據使用者問題、對話歷史與目前文件狀態判斷 `intent`、一個或多個用途、可選的範本參考和資料來源。若只是詢問文件或目前計畫，`answer_question` 回答後保留現有大綱；若要求建立或修訂文件，`assess_readiness` 判斷資訊是否足夠規劃。文件範圍或複合方式尚未確定時，回傳一個具體追問並存入 Thread；使用者回答後重新分類。數值、對象或期間缺漏不會單獨阻止大綱規劃。

資訊足夠時，`PURPOSE_WORKFLOW_GRAPH` 逐用途提出章節、合併重複章節，再產生一份統一大綱。D/S/C 目錄只提供參考，不再強制套用 D 範本的必要章節；自訂章節使用 `sectionKey`。結果保存在 Thread 的 `purposePlan`、`purposeOutline`，前端預覽和目前版本 DOCX 也使用這份統一大綱。

[`data/document_type_templates.json`](data/document_type_templates.json) 收錄 D01～D30 的文件種類、領域分類、目的，以及依附件順序排列的必要與可選章節 ID。每個 S ID 都會與章節目錄核對，必要與可選章節不可重複。附件的 212 筆「文件章節對應」可由這些 ID 清單及章節目錄完整還原。這些章節配置是初步規劃，法律及專業文件仍需依實際需求確認。

分類節點會參考完整對話、待確認問題與目前計畫，回傳一個或多個用途及可選的 D ID 參考；無法確定時可以不給範本 ID。分類 Prompt 只提供 ID、名稱、領域分類與目的，章節配置保留給後續規劃階段。

所有新訊息都先走 `DOCUMENT_TYPE_GRAPH`，依 `intent` 進入回答問題或文件規劃；規劃時再經過 `assess_readiness → PURPOSE_WORKFLOW_GRAPH`。沒有對應 D 範本時也可依使用者用途自訂章節，文件領域不受目錄限制。規劃階段不載入完整測試 JSON；複合用途明確要求測試 JSON 時，若資料來源不明確會先追問。

來源選擇是 `_OUTLINE_GRAPH` 中獨立的 `resolve_source_mode` 節點；此時只記錄來源模式，不讀取完整案例。下載 DOCX 時才依大綱與候選案例 metadata 判斷是否使用測試 JSON。

## 三十種固定測試案例

「下載目前版本 DOCX」的 JSON 取用、逐章撰寫與未來 DB 接點整理於 [`JSON_RAG_OVERVIEW.md`](JSON_RAG_OVERVIEW.md)。

[`data/document_type_samples/`](data/document_type_samples/) 為 D01～D30 各保留一份預設案例；案例檔名一律使用 `Dxx_後綴.json`，其中 D01 預設案例為 `D01_default.json`，也可在同一 D 類型下增加其他案例，例如 `D21_microwave_vongole.json`。每份案例包含情境、目標、輸入事實、來源描述與假設；metadata 依 D 類型分別存於 [`data/document_type_sample_metadata/`](data/document_type_sample_metadata/)，以獨立 `sampleId` 對應案例檔名。`services/report_chat/samples.py` 定義案例結構、metadata 與完整資料的載入。分類與大綱規劃階段不載入完整案例。下載文件時只讀先前規劃選出的 D 類型之 metadata，再由 LLM 比對大綱的具體主題；多用途文件可合併多個 D 類型的候選。只有最高分案例直接相關且信心達 0.8 才讀取完整 JSON 逐章撰寫；未達門檻時改由 `DOCX_CONTENT_GRAPH` 的 `draft_from_outline` 節點一次產出所有章節，不讀取案例 JSON；明確指定只用使用者資料時不執行此分流。

新用途流程透過 Thread 訊息入口回傳 `purposePlan`、`purposeOutline` 與 LLM 紀錄；需要追問時回傳 `pendingClarification`。Thread 會保存這些欄位供下一則訊息沿用。單一 D 計畫的 `documentTypeId`、`generalPlan`、`generalOutline` 仍可讀取；後續訊息一律轉入用途規劃流程。

前端聊天視窗送出訊息時呼叫 `POST /api/report-generator/threads/{thread_id}/messages`；後端讀取 Thread、歷史對話與目前大綱，再依問題意圖決定回答、追問或多用途規劃。快捷問題按鈕只送出與手動輸入相同的 `content`，不提供額外領域或指標，也不跳過主流程。

分類階段只讀 D01～D30 的 ID、名稱、分類與用途，不讀固定領域欄位目錄；沒有匹配的範本也可以規劃大綱。完整測試 JSON 只會在下載 DOCX 且 metadata 比對通過後載入。範例問題定義在 [`data/report_quick_starts.json`](data/report_quick_starts.json)，僅供前端顯示和送出文字；問題中的重點由一般需求分類流程理解。使用者可以持續對話修改大綱，修改後可再次下載目前版本。

使用者按下載後，前端送出 `{ "confirmed": true }` 至 `POST /api/report-generator/threads/{thread_id}/generate/stream`。此端點以 NDJSON 回傳比對案例、撰寫章節、檢查表格與編排 Word 的實際階段進度，完成時回傳 DOCX；原本的 `/generate` 端點仍可直接下載。Thread 已有使用者需求時可下載目前版本：有大綱且未指定只用使用者資料時，先比對候選案例 metadata；最高分案例直接相關且信心達 0.8 才讀取 JSON 撰寫章節，否則由 LLM 依大綱與使用者需求撰寫，不顯示「待補」佔位。尚無大綱時匯出規劃進度；指定只用使用者資料時不讀測試 JSON。DOCX 由 `current_draft.py` 輸出，文件最後附上最近一輪對話及本次 DOCX 產生過程的 LLM REQUEST JSON、Prompt 原文與 RESPONSE JSON。

大綱與文件 API 都需要 `report-generator.create` 權限。Thread 的對話、大綱與 LLM 呼叫紀錄存於帳號範圍內的資料庫；重新整理後可由 `GET /api/report-generator/threads` 載回。下載按鈕會直接送出 API 所需的確認參數。LangGraph 管理單次請求的節點路由，持久化仍由既有 Thread 資料表負責。本流程不使用 Neo4j，也不寫入舊版徵審歷史表。
