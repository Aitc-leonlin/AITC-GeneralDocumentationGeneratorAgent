# 文件產生器 LangGraph 流程

目前所有八個 LangGraph、API 入口、Graph 之間的呼叫，以及 DOCX 的 JSON／LLM 分流，統一收錄於 [REPORT_GENERATOR_WORKFLOW.mmd](REPORT_GENERATOR_WORKFLOW.mmd)。

圖中的虛線代表一個 Graph 的節點呼叫另一個 Graph；`startAt` 與 `sourceMode` 判斷是 Graph 外的程式分支。`EXECUTION_GRAPH` 只回傳能力執行結果，不直接產生 DOCX。下載文件時由 `DOCX_CONTENT_GRAPH` 選擇 JSON 或大綱 LLM 分支。
