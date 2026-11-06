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
| `question_agent.py` | 回答問題時由 LLM 決定是否使用案例 metadata 清單與完整 JSON 的兩個 Tool |
| `sample_matcher.py` | 依大綱與案例 metadata 選出相關測試資料 |
| `docx_content_graph.py` | 依來源模式分流：讀取案例 JSON、依大綱撰寫，或只用使用者資料撰寫 |
| `current_draft.py` | 將目前大綱與產生的章節內容寫入 DOCX |
| `outline.py` | 對話入口、用途確認、資料來源與通用大綱的路由 |

API 入口在 `api/report_generator.py`，Thread 的資料庫讀寫在 `services/report_thread_service.py`，DOCX 排版在 `services/domain_report_service.py`。

## 內容種類目錄

[`data/content_type_templates.json`](data/content_type_templates.json) 固定收錄 C01～C20 的內容種類、性質、功能描述及所需能力。這些所需能力目前是規劃欄位，表示該內容種類日後需要什麼能力，不代表 Agent 已實作或會立即執行。

## 章節種類目錄

[`data/section_type_templates.json`](data/section_type_templates.json) 固定收錄 S01～S20 的章節種類、目的、建議內容種類 ID 與常見文件標籤；載入時會核對每個 C ID 均存在。「常見文件」沿用文字標籤；正式的 D→S 對應則使用文件目錄中的必要／可選章節 ID。D21～D30 原有的 `suggestedSections` 是先前提供的自由文字提示，與附件的 S ID 對應分開保存。

## 通用文件 Graph 流程

對話入口會把 D01～D30 的 ID、名稱、分類與 `purpose` 當作 LLM 的參考 metadata。`classify_question` 根據使用者問題、對話歷史與目前文件狀態判斷 `intent`、一個或多個用途、可選的範本參考和資料來源。若只是詢問文件或目前計畫，`answer_question` 呼叫 `QUESTION_SAMPLE_AGENT_GRAPH`：LLM 可直接回答；需要案例具體資料時才呼叫 `list_document_samples` 取得指定 D 類型 metadata，選出直接相關案例後才呼叫 `read_document_sample` 讀取完整 JSON；回答後保留現有大綱。若要求建立或修訂文件，`assess_readiness` 判斷資訊是否足夠規劃。文件範圍或複合方式尚未確定時，回傳一個具體追問並存入 Thread；使用者回答後重新分類。數值、對象或期間缺漏不會單獨阻止大綱規劃。

資訊足夠時，`OPEN_SAMPLE_AGENT_GRAPH` 先判斷核心主題是否已指定、輸出是單一方案／多個選項／指定對象比較，以及參考資料是否為完成任務的必要條件。Agent 透過 `list_document_samples` 與 `read_document_sample` 挑選可採用或僅供參考的案例；多選項與比較需求最多讀取五份不同案例，每份分別判斷用途。使用者修訂需求且系統準備沿用舊案例時，會重新讀取完整 JSON，核對新固定條件、案例原本的採用／參考用途與各輸出項目覆蓋；不再適用便重新搜尋候選案例。選案結果、要求數量、每個輸出項目由哪份案例支援，以及來源必要性存入 Thread 的 `sampleSelection`。一份案例可支援多個項目，但案例內容必須確實涵蓋它們；必要來源的多選項與比較需求會額外核對每項覆蓋，未覆蓋所有要求的項目與指定比較對象時追問並保留原大綱。可選來源不足時仍可用一般性內容規劃。接著 `PURPOSE_WORKFLOW_GRAPH` 逐用途提出章節、合併重複章節，再產生一份統一大綱；多選項保留要求數量，比較型保留各指定對象與共同比較面向。D/S/C 目錄只提供參考，不強制套用 D 範本的必要章節；自訂章節使用 `sectionKey`。結果保存在 Thread 的 `purposePlan`、`purposeOutline`，前端預覽和目前版本 DOCX 也使用這份統一大綱。

[`data/document_type_templates.json`](data/document_type_templates.json) 收錄 D01～D30 的文件種類、領域分類、目的，以及依附件順序排列的必要與可選章節 ID。每個 S ID 都會與章節目錄核對，必要與可選章節不可重複。附件的 212 筆「文件章節對應」可由這些 ID 清單及章節目錄完整還原。這些章節配置是初步規劃，法律及專業文件仍需依實際需求確認。

分類節點會參考完整對話、待確認問題與目前計畫，回傳一個或多個用途及可選的 D ID 參考；無法確定時可以不給範本 ID。分類 Prompt 只提供 ID、名稱、領域分類與目的，章節配置保留給後續規劃階段。

所有新訊息都先走 `DOCUMENT_TYPE_GRAPH`，依 `intent` 進入回答問題或文件規劃；規劃時再經過 `assess_readiness → route_open_sample → PURPOSE_WORKFLOW_GRAPH`。沒有對應 D 範本或案例時，仍可依使用者用途自訂章節，文件領域不受目錄限制。選案階段最多查看三種 D 類型的 metadata；單一需求最多讀一份完整案例，多選項與比較需求最多讀五份。開放需求不因未指定菜色或目的地而追問。

來源選擇是 `_OUTLINE_GRAPH` 中獨立的 `resolve_source_mode` 節點；來源模式為 `user_data` 時仍判斷單一／多選項／比較需求，但不呼叫案例 Tool。單純問答沿用問答案例 Agent。下載 DOCX 時，`user_data` 直接進入 `draft_from_user_data`，根據本 Thread 所有使用者訊息中實際提供的內容逐章撰寫；資料不足的章節說明可確認範圍與缺口。這條分支目前只接收聊天文字，使用者訊息合計超過 40000 字元會提示整理後重試。其他模式優先沿用 Thread 已選案例；舊版 Thread 沒有選案紀錄時，才依大綱與候選 metadata 比對。

## 三十種固定測試案例

選案回覆必須明列採用的案例 ID；多選項與比較需求還須明列各輸出項目對應的案例。缺少有效對應時，系統不會把已讀案例自動採用；仍有實質價值的案例可保留為部分章節參考。

單一需求若必須依據案例資料，選案後會再以完整 JSON 獨立核對核心主題與固定條件。只能借鑑方法的案例會降為參考；必要來源因此不足時，對話會請使用者補資料。複核 LLM 紀錄會隨對話 Tool 紀錄列入 DOCX。

匯出 DOCX 時，多選項與比較需求會核對實際內文是否寫出要求數量的不同選項、指定比較對象及共同比較面向。缺漏時依原來源限制重寫章節一次並重新核對；仍不足則停止匯出，避免只在大綱列出選項而內文遺漏。單一需求不需額外的數量覆蓋檢查；核對 LLM 紀錄列在 DOCX 的 Tool 紀錄章節。

「下載目前版本 DOCX」的 JSON 取用、逐章撰寫與未來 DB 接點整理於 [`JSON_RAG_OVERVIEW.md`](JSON_RAG_OVERVIEW.md)。

[`data/document_type_samples/`](data/document_type_samples/) 為 D01～D30 各保留一份預設案例；案例檔名一律使用 `Dxx_後綴.json`，其中 D01 預設案例為 `D01_default.json`，也可在同一 D 類型下增加其他案例，例如 `D21_microwave_vongole.json`。每份案例包含情境、目標、輸入事實、來源描述與假設；metadata 依 D 類型分別存於 [`data/document_type_sample_metadata/`](data/document_type_sample_metadata/)，以獨立 `sampleId` 對應案例檔名。`services/report_chat/samples.py` 定義案例結構、metadata 與完整資料的載入。規劃階段只在選案時透過 Tool 讀取選中的完整 JSON；匯出 DOCX 時優先重讀 Thread 已選案例。案例的標題、對象、期間、目標、情境、事實、來源描述、假設與來源註記會完整列在 DOCX 的資料來源章節，每項事實標示是否由章節標記引用；章節內文仍只採用相關欄位。舊版 Thread 沒有選案紀錄時，依大綱比對候選 metadata，相關分數達 0.55 才讀取一份完整 JSON；沒有可用案例時由 `DOCX_CONTENT_GRAPH` 的 `draft_from_outline` 產生章節。

新用途流程透過 Thread 訊息入口回傳 `purposePlan`、`purposeOutline` 與 LLM 紀錄；需要追問時回傳 `pendingClarification`。Thread 會保存這些欄位供下一則訊息沿用。單一 D 計畫的 `documentTypeId`、`generalPlan`、`generalOutline` 仍可讀取；後續訊息一律轉入用途規劃流程。

前端聊天視窗送出訊息時呼叫 `POST /api/report-generator/threads/{thread_id}/messages`；後端讀取 Thread、歷史對話與目前大綱，再依問題意圖決定回答、追問或多用途規劃。快捷問題按鈕只送出與手動輸入相同的 `content`，不提供額外領域或指標，也不跳過主流程。

分類階段只讀 D01～D30 的 ID、名稱、分類與用途，不讀固定領域欄位目錄；沒有匹配的範本也可以規劃大綱。完整測試 JSON 只在問答 Agent、規劃選案 Agent 或 DOCX 匯出流程選中相關案例後讀取。範例問題定義在 [`data/report_quick_starts.json`](data/report_quick_starts.json)，僅供前端顯示和送出文字；問題中的重點由一般需求分類流程理解。使用者可以持續對話修改大綱，修改後可再次下載目前版本。

使用者按下載後，前端送出 `{ "confirmed": true }` 至 `POST /api/report-generator/threads/{thread_id}/generate/stream`。此端點以 NDJSON 回傳案例讀取、撰寫章節與編排 Word 的實際階段進度，完成時回傳 DOCX；原本的 `/generate` 端點仍可直接下載。有大綱時，來源為 `user_data` 便只根據使用者訊息產生章節內文，完全不查預設案例；其他模式優先重讀 Thread 所選案例。多選項或比較需求把各案例的證據分開編號，再逐章撰寫；每章完成後由 LLM 語意核對引用 ID 與案例事實，明確不一致時修正一次並重查，仍不一致則回報錯誤。案例不足時仍保留大綱要求的選項或比較對象，不把缺少來源的內容說成案例事實。若 Thread 記錄來源為必要且案例讀取失敗，匯出會回報資料不足，不會退回一般性內文。舊版 Thread 沒有選案紀錄時才在匯出階段比對 metadata；沒有可用案例則由 LLM 依大綱與需求撰寫。尚無大綱時匯出規劃進度。DOCX 由 `current_draft.py` 輸出，資料來源章節說明採用的模式，最後一章列出對話問答與本次文件產生的決策 LLM REQUEST／RESPONSE，以及 Tool 的 REQUEST 和完整取回資料；其他 LLM 呼叫紀錄仍不附加。

大綱與文件 API 都需要 `report-generator.create` 權限。Thread 的對話、大綱與 LLM 呼叫紀錄存於帳號範圍內的資料庫；重新整理後可由 `GET /api/report-generator/threads` 載回。下載按鈕會直接送出 API 所需的確認參數。LangGraph 管理單次請求的節點路由，持久化仍由既有 Thread 資料表負責。本流程不使用 Neo4j，也不寫入舊版徵審歷史表。
