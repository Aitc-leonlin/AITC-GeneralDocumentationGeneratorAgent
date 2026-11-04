# 文件產生器 LangGraph 流程

報告對話頁使用的五支 API、四個 LangGraph、Graph 之間的呼叫，以及 DOCX 的 JSON／LLM 分流，收錄於 [REPORT_GENERATOR_WORKFLOW.mmd](REPORT_GENERATOR_WORKFLOW.mmd)。

圖中的虛線代表一個 Graph 的節點呼叫另一個 Graph；`sourceMode` 判斷是 Graph 外的程式分支。下載文件時由 `DOCX_CONTENT_GRAPH` 選擇 JSON 或大綱 LLM 分支。
