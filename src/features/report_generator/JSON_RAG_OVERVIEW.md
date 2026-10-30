# 通用文件 DOCX：JSON 資料取用總覽

下載「目前版本 DOCX」時，若有大綱且對話未指定只用使用者資料，`DOCX_CONTENT_GRAPH` 先依 D 範本分類篩出候選案例，再把候選的 title、description 與大綱交給 LLM 比對。具體主題相符且最高信心達 0.8 時，讀取完整 JSON 逐章撰寫；未達門檻或沒有候選時，改由 `draft_from_outline` 節點用一次 LLM 呼叫直接依大綱撰寫所有章節，不讀取完整案例 JSON，也不輸出「待補」佔位。只有計畫、尚無大綱時仍匯出規劃進度。JSON 資料只作為範例，使用時產出文件會明示其虛構性。

| 階段 | 目前使用 JSON | 將來改用結構化 DB 的接點 |
| --- | --- | --- |
| 候選預篩 | 從大綱參考的 D ID 取得文件分類，只列出同分類的案例 | 以 DB 分類欄位查詢候選列 |
| metadata 比對 | `samples.load_document_type_sample_metadata()` 從 `data/document_type_sample_metadata.json` 取 title、description；`sample_matcher.match_document_type_sample()` 請 LLM 逐一評分並選出最高的相關案例 | 改由 DB 讀取候選列的 title、description，沿用比對介面 |
| 取完整資料 | 僅比對通過時，`json_evidence.retrieve_json_evidence()` 依選中的 `sampleId` 讀取 `data/document_type_samples/{sampleId}.json` | 將此函式改接 Repository／SQL 查詢，回傳相同的證據項目 |
| 低信心分支 | `docx_content_graph.draft_from_outline` 以一次結構化 LLM 呼叫，依大綱與使用者需求撰寫所有章節，不使用案例 JSON | 保留作為 DB 候選不足時的內容分支 |
| 證據編號 | 案例情境 `CTX`、事實 `F1...`、模擬來源描述 `M1...`、假設 `A1...` | 以資料列 ID 或穩定的來源 ID 取代暫時編號 |
| 逐章撰寫 | AI 依大綱章節重點，從該 D 案例的證據項目挑選可用內容 | 保留撰寫流程，改提供 DB 查詢結果 |
| 引用檢查 | 程式確認 AI 回傳的證據 ID 存在；沒有依據的章節標「待補」 | 以資料列與來源權限檢查取代 JSON ID 檢查 |
| DOCX 輸出 | 章節 Markdown 由既有轉換器寫成 Word 段落與表格，並列出可讀的資料依據；內部 ID 不顯示 | 保留輸出格式，將資料表與引用改為 DB 來源 |

目前不使用向量檢索。metadata 索引與完整案例分開保存；修改案例的標題、對象、目的或情境時，需同步更新索引中的 title、description。每份案例資料量小，所以通過 metadata 比對後，逐章撰寫會提供選中案例的全部證據項目，由 AI 選擇與章節相關者。低信心分支只根據大綱與使用者需求提供一般性內容，不宣稱有案例證據。`sourceMaterials` 只有模擬來源的描述，不代表已檢索或驗證真實文件。
