from __future__ import annotations

import html
import zipfile
from pathlib import Path


OUTPUT_PATH = Path("output/current_features_inventory.xlsx")


SHEETS = [
    (
        "Overview",
        [
            ["分類", "功能模組", "目前功能摘要", "前端入口", "後端支援"],
            ["前後端", "授信 AI 聊天", "支援登入後使用聊天介面送出授信/財報問題，後端透過 LangGraph 執行分類、查詢、語意檢索與回答生成。", "/chatbot", "POST /api/chatbot"],
            ["前後端", "外部知識輔助聊天", "可管理外部倉儲資料，聊天流程可套用外部資料與專家知識作為回答依據。", "/external-knowledge, /chatbot", "POST /api/chatbot-with-external, /api/warehouse-data/*, /api/expert-knowledge/*"],
            ["前後端", "專家知識庫", "支援專家知識清單、搜尋、新增、編輯、刪除、檢視，並提供 LLM 產生錨定指令與分析指引。", "/expert-knowledge", "/api/expert-knowledge/*"],
            ["前後端", "資料倉儲", "支援外部/倉儲資料清單、分類篩選、搜尋、新增、編輯、刪除、檢視與套用查詢。", "/external-knowledge", "/api/warehouse-data/*"],
            ["前後端", "授信報告產生", "可依公司與年度產生 DOCX 授信報告，記錄歷史、dashboard 摘要、下載檔案。", "/report-generator, /report-generator/history", "/api/report-generator/*"],
            ["前後端", "會員登入與帳號安全", "支援登入、refresh token、登出、目前使用者、session、忘記密碼、重設密碼、email 驗證。", "/login, /forgot-password, /reset-password, /verify-email", "/api/membership/auth/*"],
            ["前後端", "會員與權限管理", "支援使用者、角色、權限、權限分組、使用者角色、角色權限、選單權限、組織與資料權限管理。", "/membership/*", "/api/membership/*"],
            ["前端", "展示/範例頁", "保留 LangChain、AI SDK、retrieval、structured output、agent/tools 等示範頁，主要作為研發展示。", "/agents, /retrieval, /retrieval_agents, /langgraph, /structured_output, /ai_sdk/*", "部分為前端 demo，正式後端 API 未完整對應"],
        ],
    ),
    (
        "Frontend Features",
        [
            ["功能分類", "功能", "路由/檔案", "目前提供的操作", "串接後端/資料來源"],
            ["首頁/導覽", "首頁功能入口", "app/page.tsx, components/Navbar.tsx", "展示主要功能入口與導覽列，連到聊天、專家知識、外部知識、報告產生、會員管理。", "前端路由"],
            ["認證", "登入", "app/login/page.tsx", "輸入帳號密碼、remember me，登入成功後儲存 access/refresh token 並導向會員管理。", "data/membershipAuthApi.ts -> /api/membership/auth/login"],
            ["認證", "忘記密碼", "app/forgot-password/page.tsx", "輸入 email 申請 reset token，頁面提供重設密碼連結。", "POST /api/membership/auth/forgot-password"],
            ["認證", "重設密碼", "app/reset-password/page.tsx", "使用 token 與新密碼完成密碼重設。", "POST /api/membership/auth/reset-password"],
            ["認證", "Email 驗證", "app/verify-email/page.tsx", "使用 token 驗證 email。", "POST /api/membership/auth/email-verification/verify"],
            ["AI 聊天", "授信聊天主頁", "app/chatbot/page.tsx, components/ChatWindow.tsx", "聊天訊息送出、顯示回答、中繼步驟、資料來源與對話內容。", "POST /api/chatbot, POST /api/chatbot-with-external"],
            ["專家知識", "專家知識清單", "app/expert-knowledge/page.tsx", "分頁、搜尋、清單檢視、進入新增/編輯/詳細頁、刪除。", "GET/DELETE /api/expert-knowledge"],
            ["專家知識", "新增專家知識", "app/expert-knowledge/new/page.tsx, components/expert-knowledge/ExpertKnowledgeForm.tsx", "輸入標題、資料來源、產業、公司、錨定說明、system prompt 並儲存。", "POST /api/expert-knowledge"],
            ["專家知識", "編輯/檢視專家知識", "app/expert-knowledge/[entryId]/page.tsx, app/expert-knowledge/[entryId]/edit/page.tsx", "讀取單筆資料、更新內容、返回清單。", "GET/PATCH /api/expert-knowledge/{entryId}"],
            ["專家知識", "AI 產生錨定/分析指引", "components/expert-knowledge/ExpertKnowledgeForm.tsx", "依輸入內容呼叫後端 LLM 產生 anchor description 或專業分析 system prompt。", "POST /api/expert-knowledge/generate-anchor, /generate-analysis"],
            ["外部知識", "資料倉儲管理", "app/external-knowledge/page.tsx, components/external-knowledge/WarehouseDataManager.tsx", "清單、搜尋、分類篩選、新增、編輯、刪除、檢視來源 URL。", "GET/POST/PATCH/DELETE /api/warehouse-data"],
            ["報告產生", "通用文件產生", "app/report-generator/page.tsx", "依對話大綱產生 DOCX，並檢視歷史對話。", "POST /api/report-generator/threads/{thread_id}/generate"],
            ["報告產生", "報告歷史", "app/report-generator/history/page.tsx", "查詢歷史報告、狀態/關鍵字篩選、查看 dashboard、下載報告。", "GET /api/report-generator/history, /download"],
            ["會員", "會員管理 Layout/守衛", "app/membership/layout.tsx, components/membership/MembershipSessionGuard.tsx", "登入狀態檢查、未授權導向、後台側欄與權限導覽。", "GET /api/membership/auth/me, GET /api/membership/menus/current"],
            ["會員", "會員總覽 Dashboard", "app/membership/dashboard/page.tsx, components/membership/MembershipDashboard.tsx", "顯示使用者、權限、登入、通知統計與近期 audit log。", "GET /api/membership/admin/dashboard"],
            ["會員", "使用者管理", "app/membership/users/page.tsx, components/membership/UserManagement.tsx", "使用者清單、搜尋/篩選、新增、編輯、啟用/停用、鎖定/解鎖、密碼重設。", "data/membershipUsersApi.ts -> /api/membership/users"],
            ["會員", "角色管理", "app/membership/roles/page.tsx, components/membership/RoleManagement.tsx", "角色清單、新增、編輯、刪除，管理角色資訊。", "data/membershipRbacApi.ts -> /api/membership/rbac/roles"],
            ["會員", "權限管理", "app/membership/permissions/page.tsx, components/membership/PermissionManagement.tsx", "權限與權限分組清單、新增、編輯、刪除。", "/api/membership/rbac/permissions, /permission-groups"],
            ["會員", "使用者角色", "app/membership/user-roles/page.tsx, components/membership/UserRoleManagement.tsx", "查詢使用者角色並設定 roleIds 與組織範圍。", "GET/PUT /api/membership/rbac/users/{userId}/roles"],
            ["會員", "選單管理", "app/membership/menus/page.tsx, components/membership/MenuManagement.tsx", "選單樹管理、選單 CRUD、角色對選單的查看/新增/修改/刪除權限。", "/api/membership/menus"],
            ["會員", "組織與資料權限", "app/membership/organizations/page.tsx, components/membership/OrganizationPermissionManagement.tsx", "組織樹、職位、部門關聯、主管關係、資料權限 policy、列/欄/遮罩規則。", "/api/membership/organizations/*"],
            ["會員", "稽核紀錄", "app/membership/audit/page.tsx, components/membership/AuditLogManagement.tsx", "查詢 audit log，依 action/resource/outcome 篩選分頁。", "GET /api/membership/admin/audit-logs"],
            ["會員", "通知管理", "app/membership/notifications/page.tsx, components/membership/NotificationManagement.tsx", "通知模板、通知 outbox 查詢與 dispatch 狀態更新。", "/api/membership/admin/notification-*"],
            ["Demo/研發", "LangChain / Retrieval / Agents 範例", "app/agents/page.tsx, app/retrieval/page.tsx, app/retrieval_agents/page.tsx, app/langgraph/page.tsx", "展示 LangChain、retrieval、agent/langgraph 相關範例 UI。", "多為展示頁或前端範例"],
            ["Demo/研發", "AI SDK 範例", "app/ai_sdk/page.tsx, app/ai_sdk/agent/page.tsx, app/ai_sdk/tools/page.tsx", "展示 AI SDK streaming、agent、tool calling 範例。", "app/ai_sdk/*/action.ts"],
            ["Demo/研發", "Structured Output / Negative News", "app/structured_output/page.tsx, app/negative-news/page.tsx", "展示 structured output 與負面新聞相關頁面/入口。", "依頁面實作與 demo data"],
        ],
    ),
    (
        "Backend Features",
        [
            ["功能分類", "功能", "主要檔案", "目前提供的能力", "資料/服務"],
            ["系統", "FastAPI App 與 CORS", "app.py", "建立 FastAPI、註冊所有 API router、CORS、MembershipError handler、SQLite DB diagnostics。", "src.shared.database.db_path"],
            ["AI Agent", "LangGraph 授信問答流程", "src/agent/graph.py, src/agent/nodes/*.py", "包含問題改寫、範圍判斷、問題分類、語意規劃、報表類型分類、精準查詢、語意檢索、外部資料使用、最終回答。", "LangGraph, OpenAI/LangChain, SQLite 財報資料"],
            ["AI Agent", "精準查詢工具", "src/agent/tools/exact_query.py, src/agent/nodes/exact_query.py", "依公司、年度、季度、財報科目等條件查詢標準化財務數值。", "FinancialStatementXBRL.db / FinancialStatements.db"],
            ["聊天 API", "授信聊天", "src/features/chatbot/api/chatbot.py, src/features/chatbot/schemas/chatbot_base.py", "接收聊天訊息與條件，組 graph input，呼叫 LangGraph，回傳答案、資料來源、專家知識、倉儲資料等。", "graph.invoke"],
            ["聊天 API", "外部資料聊天", "src/features/chatbot/api/chatbot_with_external.py", "支援外部資料採用決策，要求 adopted 時必須有 externalDataQueryText，回傳套用外部資料結果。", "graph.invoke"],
            ["專家知識", "專家知識 CRUD", "src/features/chatbot/api/expert_knowledge/entries.py, src/features/chatbot/services/expert_knowledge_service.py", "清單/分頁/搜尋、套用查詢、單筆讀取、新增、更新、刪除。", "expert_knowledge_entry table"],
            ["專家知識", "AI 產生 anchor", "src/features/chatbot/api/expert_knowledge/generate_anchor.py", "把使用者提供的專業知識改寫成 Agent 判斷何時採用的錨定指令。", "ChatOpenAI / prompt"],
            ["專家知識", "AI 產生分析指引", "src/features/chatbot/api/expert_knowledge/generate_analysis.py", "把專業知識改寫成可供 RAG 使用的授信分析指引。", "ChatOpenAI / prompt"],
            ["資料倉儲", "Warehouse Data CRUD", "src/features/chatbot/api/warehouse_data.py, src/features/chatbot/services/warehouse_data_service.py", "資料倉儲分頁、搜尋、分類篩選、套用查詢、單筆讀取、新增、更新、刪除。", "warehouse_data_entry table"],
            ["報告產生", "授信報告 DOCX", "src/features/report_generator/api/report_generator.py, src/features/report_generator/services/report_generator_service.py, src/features/report_generator/services/docx/*.py", "產生授信報告 DOCX，包含公司基本資料、財報分析、現金流、償債能力、產業環境、負面新聞、合併文件。", "FinancialStatementXBRL.db, generated-reports"],
            ["報告產生", "報告歷史與 Dashboard", "src/features/report_generator/api/report_generator.py, src/features/report_generator/services/report_generator_service.py", "查詢報告歷史、取得 dashboard 摘要、依 public_id 下載報告。", "report_generator_history, report_generator_dashboard"],
            ["會員認證", "登入/Token/Session", "src/features/membership/api/auth_controller.py, src/features/membership/services/auth_service.py", "登入、refresh、logout、me、sessions，支援 access/refresh token 與 session 管理。", "membership_user, credential, refresh_token, session"],
            ["會員認證", "密碼與 Email 流程", "src/features/membership/api/auth_controller.py", "忘記密碼、重設密碼、email verification request/verify。", "password_reset_token, email_verification_token"],
            ["會員管理", "使用者管理", "src/features/membership/api/user_controller.py, src/features/membership/services/user_service.py", "使用者列表、搜尋/篩選、建立、讀取、更新、刪除、狀態、鎖定、解鎖、profile、密碼變更與管理員重設。", "membership_user, membership_user_credential"],
            ["RBAC", "角色/權限/分組", "src/features/membership/api/rbac_controller.py, src/features/membership/services/rbac_service.py", "目前使用者權限、角色 CRUD、權限分組 CRUD、權限 CRUD、角色權限設定、使用者角色設定。", "membership_role, permission, user_role, role_permission"],
            ["選單權限", "選單與角色選單權限", "src/features/membership/api/menu_controller.py, src/features/membership/services/menu_service.py", "取得目前使用者選單、選單 CRUD、選單權限查詢/設定/刪除。", "membership_menu_item, role_menu_permission"],
            ["組織權限", "組織/職位/關係", "src/features/membership/api/organization_controller.py, src/features/membership/services/organization_service.py", "組織單位列表/樹/CRUD、職位 CRUD、使用者部門關聯、主管關係。", "organization_unit, position, user_department_mapping, user_manager_relation"],
            ["組織權限", "資料權限規則", "src/features/membership/api/organization_controller.py", "資料權限 policy、row rules、field rules、masking rules 的查詢/新增或更新/刪除。", "data_permission_policy, row/field/masking rule tables"],
            ["後台管理", "Dashboard / Audit / Notification", "src/features/membership/api/notification_controller.py, src/features/membership/services/notification_service.py", "會員後台統計、audit log 查詢、通知模板查詢/保存、notification outbox 查詢與 dispatch。", "audit_log, notification_template, notification_outbox"],
            ["資料庫", "Schema Migration 與 Seed", "src/sql/migrations/*.sql, src/features/membership/services/bootstrap_service.py, src/features/membership/seeds/default_seed_data.py", "維護 XBRL 財報資料庫 schema、會員/權限 schema、預設角色權限選單 seed。", "FinancialStatementXBRL.db"],
            ["工具腳本", "XBRL 與公司資料匯入", "scripts/*.py", "解析 XBRL 字典、切分 taxonomy、建立 mapping JSON/SQL、匯入上市公司 profile、smoke test。", "src/features/chatbot/services/xbrl_* JSON, SQLite"],
        ],
    ),
    (
        "API Endpoints",
        [
            ["分類", "Method", "Endpoint", "用途", "權限/備註"],
            ["Chatbot", "POST", "/api/chatbot", "授信聊天問答。", "需登入"],
            ["Chatbot", "POST", "/api/chatbot-with-external", "含外部資料決策的聊天問答。", "需登入"],
            ["Report", "POST", "/api/report-generator/threads/{thread_id}/generate", "依目前 Thread 大綱產生 DOCX 並回傳檔案。", "需登入"],
            ["Report", "GET", "/api/report-generator/history", "查詢報告產生歷史。", "需登入"],
            ["Report", "GET", "/api/report-generator/history/{history_id}/dashboard", "取得報告 dashboard 資料。", "需登入"],
            ["Report", "GET", "/api/report-generator/history/{public_id}/download", "下載歷史報告檔案。", "需登入"],
            ["Expert Knowledge", "GET", "/api/expert-knowledge", "專家知識分頁/搜尋清單。", ""],
            ["Expert Knowledge", "GET", "/api/expert-knowledge/applied", "依公司/產業/資料來源查可套用專家知識。", ""],
            ["Expert Knowledge", "GET", "/api/expert-knowledge/{entry_id}", "取得單筆專家知識。", ""],
            ["Expert Knowledge", "POST", "/api/expert-knowledge", "新增專家知識。", ""],
            ["Expert Knowledge", "PUT/PATCH", "/api/expert-knowledge/{entry_id}", "更新專家知識。", ""],
            ["Expert Knowledge", "DELETE", "/api/expert-knowledge/{entry_id}", "刪除專家知識。", ""],
            ["Expert Knowledge", "POST", "/api/expert-knowledge/generate-anchor", "LLM 產生錨定指令。", ""],
            ["Expert Knowledge", "POST", "/api/expert-knowledge/generate-analysis", "LLM 產生專業分析指引。", ""],
            ["Warehouse Data", "GET", "/api/warehouse-data", "倉儲資料分頁/搜尋/分類清單。", ""],
            ["Warehouse Data", "GET", "/api/warehouse-data/applied", "依公司/產業/分類查可套用倉儲資料。", ""],
            ["Warehouse Data", "GET", "/api/warehouse-data/{entry_id}", "取得單筆倉儲資料。", ""],
            ["Warehouse Data", "POST", "/api/warehouse-data", "新增倉儲資料。", ""],
            ["Warehouse Data", "PUT/PATCH", "/api/warehouse-data/{entry_id}", "更新倉儲資料。", ""],
            ["Warehouse Data", "DELETE", "/api/warehouse-data/{entry_id}", "刪除倉儲資料。", ""],
            ["Membership Auth", "POST", "/api/membership/auth/login", "登入並取得 access/refresh token。", ""],
            ["Membership Auth", "POST", "/api/membership/auth/refresh", "刷新 token。", ""],
            ["Membership Auth", "POST", "/api/membership/auth/logout", "登出並撤銷 token。", ""],
            ["Membership Auth", "GET", "/api/membership/auth/me", "取得目前登入使用者。", "需 token"],
            ["Membership Auth", "GET", "/api/membership/auth/sessions", "取得目前使用者 sessions。", "需 token"],
            ["Membership Auth", "POST", "/api/membership/auth/forgot-password", "申請忘記密碼 token。", ""],
            ["Membership Auth", "POST", "/api/membership/auth/reset-password", "使用 token 重設密碼。", ""],
            ["Membership Auth", "POST", "/api/membership/auth/email-verification/request", "申請 email 驗證 token。", "需 token"],
            ["Membership Auth", "POST", "/api/membership/auth/email-verification/verify", "驗證 email token。", ""],
            ["Membership Users", "GET/POST", "/api/membership/users", "使用者列表/新增。", "membership.read/write"],
            ["Membership Users", "GET/PUT/DELETE", "/api/membership/users/{user_id}", "使用者讀取/更新/刪除。", "membership.read/write"],
            ["Membership Users", "PATCH", "/api/membership/users/{user_id}/status", "更新使用者狀態。", "membership.write"],
            ["Membership Users", "POST", "/api/membership/users/{user_id}/activate|deactivate|lock|unlock", "啟用、停用、鎖定、解鎖使用者。", "membership.write"],
            ["Membership Users", "PUT", "/api/membership/users/{user_id}/profile|password|reset-password", "更新 profile、變更密碼、管理員重設密碼。", "membership.write"],
            ["Membership RBAC", "GET", "/api/membership/rbac/me/permissions", "取得目前使用者權限代碼。", "需登入"],
            ["Membership RBAC", "GET/POST", "/api/membership/rbac/roles", "角色列表/新增。", "rbac.view/rbac.add"],
            ["Membership RBAC", "PUT/DELETE", "/api/membership/rbac/roles/{role_id}", "角色更新/刪除。", "rbac.edit/rbac.delete"],
            ["Membership RBAC", "GET/POST", "/api/membership/rbac/permission-groups", "權限分組列表/新增。", "rbac.view/rbac.add"],
            ["Membership RBAC", "PUT/DELETE", "/api/membership/rbac/permission-groups/{group_id}", "權限分組更新/刪除。", "rbac.edit/rbac.delete"],
            ["Membership RBAC", "GET/POST", "/api/membership/rbac/permissions", "權限列表/新增。", "rbac.view/rbac.add"],
            ["Membership RBAC", "PUT/DELETE", "/api/membership/rbac/permissions/{permission_id}", "權限更新/刪除。", "rbac.edit/rbac.delete"],
            ["Membership RBAC", "GET/PUT", "/api/membership/rbac/roles/{role_id}/permissions", "讀取/設定角色權限。", "rbac.view/rbac.edit"],
            ["Membership RBAC", "GET/PUT", "/api/membership/rbac/users/{user_id}/roles", "讀取/設定使用者角色。", "rbac.view/rbac.edit"],
            ["Membership Menus", "GET", "/api/membership/menus/current", "取得目前使用者可見選單。", "需登入"],
            ["Membership Menus", "GET/POST", "/api/membership/menus", "選單列表/新增。", "menu.read/manage"],
            ["Membership Menus", "PUT/DELETE", "/api/membership/menus/{menu_id}", "選單更新/刪除。", "menu.manage"],
            ["Membership Menus", "GET/PUT", "/api/membership/menus/{menu_id}/permissions", "讀取/設定選單角色權限。", "menu.read/manage"],
            ["Membership Menus", "DELETE", "/api/membership/menus/{menu_id}/permissions/{role_id}", "刪除選單角色權限。", "menu.manage"],
            ["Membership Organizations", "GET/POST", "/api/membership/organizations/units", "組織單位列表/新增。", "organization-scope.view/organization-scope.add"],
            ["Membership Organizations", "GET", "/api/membership/organizations/tree", "組織樹。", "organization-scope.view"],
            ["Membership Organizations", "PUT/DELETE", "/api/membership/organizations/units/{unit_id}", "組織單位更新/刪除。", "organization-scope.edit/organization-scope.delete"],
            ["Membership Organizations", "GET/POST", "/api/membership/organizations/positions", "職位列表/新增。", "organization-scope.view/organization-scope.add"],
            ["Membership Organizations", "PUT/DELETE", "/api/membership/organizations/positions/{position_id}", "職位更新/刪除。", "organization-scope.edit/organization-scope.delete"],
            ["Membership Organizations", "GET/POST/DELETE", "/api/membership/organizations/user-departments", "使用者部門關聯查詢/新增/刪除。", "organization-scope.view/organization-scope.add/organization-scope.delete"],
            ["Membership Organizations", "GET/POST/DELETE", "/api/membership/organizations/manager-relations", "主管關係查詢/新增/刪除。", "organization-scope.view/organization-scope.add/organization-scope.delete"],
            ["Membership Organizations", "GET/POST/DELETE", "/api/membership/organizations/data-policies", "資料權限 policy 查詢/保存/刪除。", "organization-scope.view/organization-scope.add/organization-scope.delete"],
            ["Membership Organizations", "GET/POST/DELETE", "/api/membership/organizations/row-rules", "列權限規則查詢/新增/刪除。", "organization-scope.view/organization-scope.add/organization-scope.delete"],
            ["Membership Organizations", "GET/POST/DELETE", "/api/membership/organizations/field-rules", "欄位權限規則查詢/保存/刪除。", "organization-scope.view/organization-scope.add/organization-scope.delete"],
            ["Membership Organizations", "GET/POST/DELETE", "/api/membership/organizations/masking-rules", "敏感資料遮罩規則查詢/保存/刪除。", "organization-scope.view/organization-scope.add/organization-scope.delete"],
            ["Membership Admin", "GET", "/api/membership/admin/dashboard", "會員管理 dashboard 統計。", "membership.read"],
            ["Membership Admin", "GET", "/api/membership/admin/audit-logs", "稽核紀錄查詢。", "audit-log.read"],
            ["Membership Admin", "GET/POST", "/api/membership/admin/notification-templates", "通知模板查詢/保存。", "notification.manage"],
            ["Membership Admin", "GET", "/api/membership/admin/notification-outbox", "通知 outbox 查詢。", "notification.manage"],
            ["Membership Admin", "POST", "/api/membership/admin/notification-outbox/{outbox_id}/dispatch", "更新通知 outbox dispatch 狀態。", "notification.manage"],
            ["Membership System", "GET", "/api/membership", "會員模組 metadata。", ""],
            ["Membership System", "POST", "/api/membership/bootstrap", "套用會員 migration/seed。", "系統初始化用途"],
        ],
    ),
]


def col_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def sheet_xml(rows: list[list[str]]) -> str:
    row_xml = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row, start=1):
            cell_ref = f"{col_name(column_index)}{row_index}"
            escaped = html.escape(str(value), quote=False)
            style = ' s="1"' if row_index == 1 else ""
            cells.append(f'<c r="{cell_ref}" t="inlineStr"{style}><is><t>{escaped}</t></is></c>')
        row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        '<cols>'
        '<col min="1" max="1" width="24" customWidth="1"/>'
        '<col min="2" max="2" width="30" customWidth="1"/>'
        '<col min="3" max="3" width="72" customWidth="1"/>'
        '<col min="4" max="4" width="56" customWidth="1"/>'
        '<col min="5" max="5" width="56" customWidth="1"/>'
        '</cols>'
        f'<sheetData>{"".join(row_xml)}</sheetData>'
        '</worksheet>'
    )


def workbook_xml() -> str:
    sheets = []
    for index, (name, _) in enumerate(SHEETS, start=1):
        sheets.append(f'<sheet name="{html.escape(name)}" sheetId="{index}" r:id="rId{index}"/>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{"".join(sheets)}</sheets>'
        '</workbook>'
    )


def workbook_rels_xml() -> str:
    rels = []
    for index in range(1, len(SHEETS) + 1):
        rels.append(
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
        )
    rels.append(
        f'<Relationship Id="rId{len(SHEETS) + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{"".join(rels)}'
        '</Relationships>'
    )


def content_types_xml() -> str:
    overrides = [
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
    ]
    for index in range(1, len(SHEETS) + 1):
        overrides.append(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'{"".join(overrides)}'
        '</Types>'
    )


STYLES_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '</styleSheet>'
)


ROOT_RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    '</Relationships>'
)


def main() -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT_PATH, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml())
        archive.writestr("_rels/.rels", ROOT_RELS_XML)
        archive.writestr("xl/workbook.xml", workbook_xml())
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml())
        archive.writestr("xl/styles.xml", STYLES_XML)
        for index, (_, rows) in enumerate(SHEETS, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", sheet_xml(rows))
    print(OUTPUT_PATH.resolve())


if __name__ == "__main__":
    main()
