# 文件產生器 LangGraph 流程

報告對話頁使用的 API、主要 LangGraph、Graph 之間的呼叫，以及 DOCX 的案例 JSON／大綱 LLM／使用者資料分流，收錄於 [REPORT_GENERATOR_WORKFLOW.mmd](REPORT_GENERATOR_WORKFLOW.mmd)。

圖中的虛線代表一個 Graph 的節點呼叫另一個 Graph。下載文件時，`sourceMode` 送入 `DOCX_CONTENT_GRAPH`；其中選擇 JSON、大綱 LLM 或使用者資料的撰寫分支。
