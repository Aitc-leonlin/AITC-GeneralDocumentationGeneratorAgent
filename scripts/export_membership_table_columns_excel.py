from __future__ import annotations

import html
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.shared.database.connection import (
    get_table_column_details,
    get_table_names,
    open_database_connection,
)

OUTPUT_PATH = Path("output/membership_table_columns.xlsx")


TABLE_PURPOSES = {
    "membership_audit_log": "會員/權限模組操作稽核紀錄，追蹤操作者、動作、資源、結果與請求資訊。",
    "membership_data_permission_policy": "新版資料權限政策，針對角色或使用者定義 resource 的資料範圍、列規則、欄位規則與遮罩規則。",
    "membership_data_scope": "基礎版角色資料範圍設定，依角色與組織定義可存取資料範圍。",
    "membership_email_verification_token": "Email 驗證 token 紀錄，用於驗證使用者信箱。",
    "membership_field_permission_rule": "欄位層級資料權限規則，控制特定欄位是否可讀或可寫。",
    "membership_menu_item": "後台選單項目設定，支援選單階層、路由、圖示、排序與必要權限。",
    "membership_notification_outbox": "通知發送佇列，記錄通知 payload、收件人、狀態、排程與錯誤訊息。",
    "membership_notification_template": "通知模板設定，保存通知代碼、通道、標題與內容。",
    "membership_organization_unit": "組織單位主檔，保存公司、部門、團隊等階層結構與主管資訊。",
    "membership_password_reset_token": "忘記密碼/重設密碼 token 紀錄。",
    "membership_permission": "權限主檔，描述權限代碼、名稱、動作與權限分組。",
    "membership_permission_group": "權限分組主檔，用於分類權限。",
    "membership_position": "職位主檔，保存職位代碼、名稱、層級與排序。",
    "membership_refresh_token": "Refresh token 紀錄，用於登入續期、裝置追蹤與撤銷。",
    "membership_role": "角色主檔，保存角色代碼、名稱、類型與系統角色標記。",
    "membership_role_menu_permission": "角色對選單項目的操作權限設定。",
    "membership_role_permission": "角色與權限的對應關係，定義角色是否允許某權限。",
    "membership_row_permission_rule": "資料列層級權限規則，保存條件 expression 與允許/拒絕效果。",
    "membership_schema_migrations": "會員/權限模組 migration 套用紀錄。",
    "membership_sensitive_data_masking_rule": "敏感資料欄位遮罩規則，定義遮罩方式與 pattern。",
    "membership_session": "使用者登入 session 紀錄，追蹤裝置、IP、活動時間、過期與撤銷。",
    "membership_user": "使用者主檔，保存帳號、信箱、顯示名稱、組織、狀態與登入資訊。",
    "membership_user_credential": "使用者密碼與帳號安全設定，保存 password hash、登入失敗、鎖定與 MFA 狀態。",
    "membership_user_department_mapping": "使用者與部門/職位的對應關係，可標記主要部門與有效期間。",
    "membership_user_manager_relation": "主管與員工關係設定，支援直屬或其他管理關係。",
    "membership_user_role": "使用者與角色的對應關係，可指定組織與有效期間。",
}


COLUMN_PURPOSES = {
    "id": "資料列唯一識別碼，通常為 UUID 或文字 ID。",
    "created_at": "資料建立時間。",
    "updated_at": "資料最後更新時間。",
    "deleted_at": "軟刪除時間；有值代表資料已被邏輯刪除。",
    "status": "資料狀態，例如 ACTIVE / INACTIVE。",
    "code": "系統內部唯一代碼，用於程式與設定識別。",
    "name": "顯示名稱或資料名稱。",
    "description": "資料說明文字。",
    "sort_order": "排序值，數字越小通常越前面。",
    "version": "migration 版本號。",
    "applied_at": "migration 套用時間。",
    "action": "被執行的操作名稱，例如 login、create、update、delete。",
    "actor_user_id": "執行操作的使用者 ID，可為空代表系統或匿名操作。",
    "resource_type": "被操作的資源類型。",
    "resource_id": "被操作的資源 ID。",
    "outcome": "操作結果，例如 SUCCESS / FAILED。",
    "ip_address": "請求來源 IP。",
    "user_agent": "請求端瀏覽器或 client user-agent。",
    "metadata_json": "操作附加資訊，使用 JSON 字串保存。",
    "subject_type": "資料權限主體類型，例如 ROLE 或 USER。",
    "subject_id": "資料權限主體 ID，對應角色 ID 或使用者 ID。",
    "resource_code": "資料權限適用的資源代碼。",
    "data_scope": "資料可見範圍，例如 ONLY_MYSELF、SAME_DEPARTMENT、SUB_DEPARTMENT、WHOLE_COMPANY、CUSTOM。",
    "custom_scope_json": "自訂資料範圍清單，使用 JSON array 保存。",
    "row_rule_json": "資料列規則設定，使用 JSON object 保存。",
    "field_rule_json": "欄位權限規則設定，使用 JSON object 保存。",
    "masking_rule_json": "資料遮罩規則設定，使用 JSON object 保存。",
    "role_id": "角色 ID，關聯 membership_role。",
    "scope_type": "資料範圍類型，用於描述角色可存取的組織/資料範圍。",
    "organization_id": "組織單位 ID，關聯 membership_organization_unit。",
    "rule_json": "彈性規則內容，使用 JSON object 保存。",
    "user_id": "使用者 ID，關聯 membership_user。",
    "token_hash": "token 雜湊值，只保存 hash 避免明文 token 外洩。",
    "expires_at": "token 或 session 過期時間。",
    "verified_at": "Email 完成驗證時間。",
    "requested_ip_address": "申請 token 時的來源 IP。",
    "policy_id": "資料權限 policy ID，關聯 membership_data_permission_policy。",
    "field_name": "套用權限或遮罩規則的欄位名稱。",
    "can_read": "是否允許讀取該欄位，1 為允許、0 為不允許。",
    "can_write": "是否允許寫入該欄位，1 為允許、0 為不允許。",
    "title": "選單顯示標題。",
    "parent_id": "父層資料 ID，用於階層結構。",
    "route_path": "前端路由路徑。",
    "component_key": "前端元件識別 key，用於動態選單/頁面對應。",
    "icon": "選單圖示名稱。",
    "required_permission_code": "進入或顯示此選單所需的權限代碼。",
    "template_code": "通知模板代碼，對應 membership_notification_template.code。",
    "recipient_user_id": "通知收件人使用者 ID。",
    "channel": "通知通道，例如 email 或 in-app。",
    "payload_json": "通知發送所需變數與內容，使用 JSON object 保存。",
    "scheduled_at": "通知預計發送時間。",
    "sent_at": "通知實際送出時間。",
    "error_message": "通知發送失敗時的錯誤訊息。",
    "subject": "通知標題。",
    "body": "通知內容模板。",
    "path": "組織階層路徑，用於快速判斷上下層關係。",
    "level": "階層層級，根節點通常為 0。",
    "unit_type": "組織單位類型，例如 COMPANY、DEPARTMENT、TEAM。",
    "company_id": "所屬公司組織 ID。",
    "manager_user_id": "組織單位主管使用者 ID。",
    "used_at": "token 被使用的時間。",
    "action": "權限或稽核操作的動作名稱。",
    "group_id": "權限分組 ID，關聯 membership_permission_group。",
    "device_id": "登入裝置識別碼。",
    "revoked_at": "token 或 session 被撤銷時間。",
    "session_id": "登入 session ID，關聯 membership_session。",
    "role_type": "角色類型，例如 SYSTEM 或 BUSINESS。",
    "is_system": "是否為系統內建角色，1 為是、0 為否。",
    "menu_item_id": "選單項目 ID，關聯 membership_menu_item。",
    "can_view": "是否允許查看選單。",
    "can_create": "是否允許新增。",
    "can_update": "是否允許修改。",
    "can_delete": "是否允許刪除。",
    "permission_id": "權限 ID，關聯 membership_permission。",
    "effect": "規則效果，例如 ALLOW 或 DENY。",
    "rule_name": "規則名稱。",
    "expression_json": "列權限條件 expression，使用 JSON object 保存。",
    "masking_type": "遮罩類型，例如 PARTIAL。",
    "masking_pattern": "遮罩 pattern 或格式設定。",
    "refresh_token_id": "refresh token ID，關聯 membership_refresh_token。",
    "remember_me": "是否為記住我登入，1 為是、0 為否。",
    "started_at": "session 開始時間。",
    "last_seen_at": "session 最後活動時間。",
    "username": "使用者登入帳號。",
    "email": "使用者 email。",
    "display_name": "使用者顯示名稱。",
    "employee_no": "員工編號。",
    "locale": "使用者語系設定。",
    "timezone": "使用者時區設定。",
    "last_login_at": "最後登入時間。",
    "email_verified_at": "Email 驗證完成時間。",
    "last_login_ip": "最後登入 IP。",
    "password_hash": "密碼雜湊值。",
    "password_algorithm": "密碼雜湊演算法，例如 argon2id。",
    "password_changed_at": "密碼最後變更時間。",
    "must_change_password": "是否要求下次登入變更密碼，1 為是、0 為否。",
    "mfa_enabled": "是否啟用多因素驗證，1 為是、0 為否。",
    "failed_login_count": "連續登入失敗次數。",
    "locked_until": "帳號鎖定到期時間。",
    "last_failed_login_at": "最後登入失敗時間。",
    "last_failed_login_ip": "最後登入失敗 IP。",
    "position_id": "職位 ID，關聯 membership_position。",
    "is_primary": "是否為主要部門/主要職位，1 為是、0 為否。",
    "effective_from": "關聯或授權生效開始時間。",
    "effective_to": "關聯或授權生效結束時間。",
    "manager_user_id": "主管使用者 ID。",
    "employee_user_id": "員工使用者 ID。",
    "relation_type": "主管關係類型，例如 DIRECT。",
}


def column_purpose(column_name: str) -> str:
    return COLUMN_PURPOSES.get(column_name, "目前 schema 未提供明確業務說明，依欄位名稱推定為系統保留欄位。")


def col_name(index: int) -> str:
    name = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def sheet_xml(rows: list[list[object]], widths: list[int]) -> str:
    row_xml = []
    for row_index, row in enumerate(rows, start=1):
        cells = []
        for column_index, value in enumerate(row, start=1):
            cell_ref = f"{col_name(column_index)}{row_index}"
            escaped = html.escape("" if value is None else str(value), quote=False)
            style = ' s="1"' if row_index == 1 else ""
            cells.append(f'<c r="{cell_ref}" t="inlineStr"{style}><is><t>{escaped}</t></is></c>')
        row_xml.append(f'<row r="{row_index}">{"".join(cells)}</row>')
    cols = "".join(
        f'<col min="{index}" max="{index}" width="{width}" customWidth="1"/>'
        for index, width in enumerate(widths, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f"<cols>{cols}</cols>"
        f'<sheetData>{"".join(row_xml)}</sheetData>'
        "</worksheet>"
    )


def workbook_xml(sheet_names: list[str]) -> str:
    sheets = "".join(
        f'<sheet name="{html.escape(name)}" sheetId="{index}" r:id="rId{index}"/>'
        for index, name in enumerate(sheet_names, start=1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{sheets}</sheets>"
        "</workbook>"
    )


def workbook_rels_xml(sheet_count: int) -> str:
    rels = []
    for index in range(1, sheet_count + 1):
        rels.append(
            f'<Relationship Id="rId{index}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
        )
    rels.append(
        f'<Relationship Id="rId{sheet_count + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
        'Target="styles.xml"/>'
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'{"".join(rels)}'
        "</Relationships>"
    )


def content_types_xml(sheet_count: int) -> str:
    overrides = [
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
    ]
    for index in range(1, sheet_count + 1):
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
        "</Types>"
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
    "</styleSheet>"
)


ROOT_RELS_XML = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    "</Relationships>"
)


def get_membership_schema() -> tuple[list[list[object]], list[list[object]]]:
    con = open_database_connection()
    try:
        tables = get_table_names(con, prefix="membership_")
        table_rows = [["Table", "用途", "欄位數"]]
        column_rows = [["Table", "Table 用途", "Column", "Type", "必填", "PK", "Default", "欄位用途"]]
        for table in tables:
            columns = get_table_column_details(con, table)
            table_purpose = TABLE_PURPOSES.get(table, "")
            table_rows.append([table, table_purpose, len(columns)])
            for column in columns:
                name = column["name"]
                column_type = column["column_type"]
                not_null = column["not_null"]
                default = column["default_value"]
                pk = column["is_pk"]
                column_rows.append(
                    [
                        table,
                        table_purpose,
                        name,
                        column_type,
                        "是" if not_null else "否",
                        "是" if pk else "否",
                        "" if default is None else default,
                        column_purpose(name),
                    ]
                )
        return table_rows, column_rows
    finally:
        con.close()


def main() -> None:
    table_rows, column_rows = get_membership_schema()
    sheets = [
        ("Tables", table_rows, [42, 92, 12]),
        ("Columns", column_rows, [42, 72, 34, 16, 10, 8, 22, 80]),
    ]
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUTPUT_PATH, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types_xml(len(sheets)))
        archive.writestr("_rels/.rels", ROOT_RELS_XML)
        archive.writestr("xl/workbook.xml", workbook_xml([name for name, _, _ in sheets]))
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml(len(sheets)))
        archive.writestr("xl/styles.xml", STYLES_XML)
        for index, (_, rows, widths) in enumerate(sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", sheet_xml(rows, widths))
    print(OUTPUT_PATH.resolve())


if __name__ == "__main__":
    main()
