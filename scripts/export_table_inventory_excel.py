from __future__ import annotations

import html
import zipfile
from pathlib import Path


OUTPUT_PATH = Path("output/table_inventory.xlsx")


SHEETS = [
    (
        "FinancialStatementXBRL",
        [
            ["Table", "用途", "主要資料"],
            ["schema_migrations", "記錄 XBRL/財報主資料庫 migration 版本。", "version, description, applied_at"],
            ["report_instance", "一份財報申報實例，記錄公司、年度、季度、報表範圍、taxonomy 版本、模組、檔名與期間。", "company_code, year, quarter, industry_type, report_scope, taxonomy_version, module"],
            ["taxonomy_entry_point", "XBRL taxonomy 入口資訊，對應 XSD、presentation、label、calculation 檔。", "taxonomy_version, module, entry_point, xsd_file, presentation_file"],
            ["taxonomy_concept", "XBRL 科目/概念字典，例如中文名、英文名、資料型態、借貸方、是否抽象節點。", "concept_id, zh_label, en_label, period_type, balance_type, data_type"],
            ["taxonomy_presentation", "XBRL 科目的報表呈現階層，描述父子節點、排序、深度。", "parent_concept_id, child_concept_id, order_no, depth"],
            ["taxonomy_calculation", "XBRL 科目的計算關係，描述父子節點、權重與排序。", "parent_concept_id, child_concept_id, weight, order_no"],
            ["xbrl_fact", "從 XBRL 報表解析出的原始 fact 值，包含數值/文字、context、unit、期間與 segment。", "report_id, concept_id, context_id, unit_id, value_numeric, value_text"],
            ["field_dictionary", "系統內部標準欄位字典，把財報欄位轉成可查詢的 canonical field。", "canonical_name, zh_name, en_name, module, statement_type"],
            ["field_concept_mapping", "內部標準欄位與 XBRL concept 的 mapping，可依 taxonomy、產業與有效期間調整。", "field_id, concept_id, taxonomy_id, industry_type, priority"],
            ["financial_metric_value", "已標準化後的財務指標值，供查詢、分析、報告產生使用。", "company_code, year, quarter, field_id, concept_id, value"],
            ["report_generator_history", "報告產生紀錄，包含公司、年度、報告類型、檔案路徑、狀態、產生人等。", "company_code, year, period, report_type, status, file_path"],
            ["report_generator_dashboard", "報告產生後的 dashboard 資料，例如摘要、進度、指標與財務趨勢 JSON。", "history_id, summary_items_json, metrics_json, financial_trends_json"],
            ["expert_knowledge_entry", "專家知識設定，存放產業/公司/資料來源對應的 anchor、system prompt。", "data_source, industry, company_label, anchor_description, system_prompt"],
            ["warehouse_data_entry", "外部或內部倉儲資料條目，包含分類、標題、產業、公司、摘要、來源與 URL。", "category, title, industry, company_label, summary, source, url"],
            ["company_profile", "上市櫃公司基本資料，例如公司名稱、統編、地址、董總、發言人、股務、會計師、網站等。", "company_code, company_name, tax_id, chairman, general_manager, website"],
            ["sqlite_sequence", "SQLite 自動維護 AUTOINCREMENT 的系統表，不是業務 table。", "name, seq"],
        ],
    ),
    (
        "Membership",
        [
            ["Table", "用途", "主要資料"],
            ["membership_schema_migrations", "記錄會員/權限模組 migration 版本。", "version, description, applied_at"],
            ["membership_organization_unit", "組織單位樹，記錄部門/單位代碼、名稱、父層、路徑、層級、主管等。", "code, name, parent_id, path, level, unit_type, manager_user_id"],
            ["membership_user", "使用者主檔，包含帳號、email、顯示名稱、員編、組織、狀態、登入資訊。", "username, email, display_name, employee_no, organization_id, status"],
            ["membership_user_credential", "使用者密碼與登入安全資訊，例如 password hash、演算法、錯誤次數、鎖定時間、MFA。", "user_id, password_hash, failed_login_count, locked_until, mfa_enabled"],
            ["membership_role", "角色主檔，例如系統管理員、業務角色等。", "code, name, role_type, status, is_system"],
            ["membership_permission", "權限定義，描述權限代碼、名稱、動作與權限分組。", "code, name, action, group_id, status"],
            ["membership_permission_group", "權限分組，用來在 RBAC UI 或 API 中分類權限。", "code, name, status"],
            ["membership_user_role", "使用者與角色的關聯，可指定組織與生效期間。", "user_id, role_id, organization_id, effective_from, effective_to"],
            ["membership_role_permission", "角色與權限的關聯，定義該角色允許或拒絕某權限。", "role_id, permission_id, effect"],
            ["membership_menu_item", "系統選單項目，包含路由、元件 key、icon、父子層級與必要權限。", "code, title, parent_id, route_path, component_key, required_permission_code"],
            ["membership_role_menu_permission", "角色對選單的操作權限，例如可看、新增、修改、刪除。", "role_id, menu_item_id, can_view, can_create, can_update, can_delete"],
            ["membership_data_scope", "舊/基礎版角色資料範圍設定，依角色與組織定義可看的資料範圍。", "role_id, scope_type, organization_id, rule_json"],
            ["membership_data_permission_policy", "新版資料權限政策，可針對角色或使用者設定 resource 的資料範圍、列規則、欄位規則與遮罩規則。", "subject_type, subject_id, resource_code, data_scope"],
            ["membership_row_permission_rule", "資料列層級權限規則，描述某 policy 對某 resource 的 allow/deny 條件。", "policy_id, resource_code, rule_name, expression_json, effect"],
            ["membership_field_permission_rule", "欄位層級權限規則，控制某欄位是否可讀、可寫。", "policy_id, resource_code, field_name, can_read, can_write"],
            ["membership_sensitive_data_masking_rule", "敏感欄位遮罩規則，例如部分遮罩、遮罩 pattern。", "policy_id, resource_code, field_name, masking_type, masking_pattern"],
            ["membership_position", "職位主檔，例如職等、職稱、排序與狀態。", "code, name, level, sort_order, status"],
            ["membership_user_department_mapping", "使用者與部門/職位的關聯，可標記主要部門與有效期間。", "user_id, organization_id, position_id, is_primary"],
            ["membership_user_manager_relation", "主管與員工關係，支援直屬或其他管理關係。", "manager_user_id, employee_user_id, organization_id, relation_type"],
            ["membership_refresh_token", "Refresh token 記錄，用於登入續期、裝置、IP、UA、撤銷時間。", "user_id, token_hash, device_id, expires_at, revoked_at"],
            ["membership_session", "使用者 session 記錄，包含裝置、IP、UA、remember me、最後活動時間與過期時間。", "user_id, refresh_token_id, device_id, last_seen_at, expires_at"],
            ["membership_password_reset_token", "忘記密碼/重設密碼 token。", "user_id, token_hash, expires_at, used_at"],
            ["membership_email_verification_token", "Email 驗證 token。", "user_id, token_hash, expires_at, verified_at"],
            ["membership_audit_log", "稽核紀錄，記錄誰對什麼資源做了什麼操作、結果、IP、UA 與 metadata。", "actor_user_id, action, resource_type, resource_id, outcome"],
            ["membership_notification_template", "通知模板，例如 email/in-app 通知的 subject/body。", "code, channel, subject, body, status"],
            ["membership_notification_outbox", "通知發送佇列，記錄收件人、模板、payload、狀態、排程與錯誤訊息。", "template_code, recipient_user_id, channel, status, scheduled_at"],
        ],
    ),
    (
        "FinancialStatements",
        [
            ["Table", "用途", "主要資料"],
            ["account_title", "財報科目對照表，包含 concept name、中文、英文與科目代碼。", "concept_name, zh_tw, en, code"],
            ["balance_sheet", "資產負債表數值，依公司、年度、季度、科目代碼存 value 與 unit。", "company, company_code, year, quarter, account_title_code, value, unit"],
            ["comprehensive_income_statement", "綜合損益表數值，依公司、年度、季度、科目代碼存 value 與 unit。", "company, company_code, year, quarter, account_title_code, value, unit"],
            ["statement_of_cash_flows", "現金流量表數值，依公司、年度、季度、科目代碼存 value 與 unit。", "company, company_code, year, quarter, account_title_code, value, unit"],
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
        '<cols><col min="1" max="1" width="38" customWidth="1"/><col min="2" max="2" width="88" customWidth="1"/><col min="3" max="3" width="72" customWidth="1"/></cols>'
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
