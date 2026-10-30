"""Final-answer instructions for each standard SemanticWorkflow and routing kind."""

from typing import Any


WORKFLOW_FINAL_PROMPTS: dict[str, dict[str, Any]] = {
    "FINANCIAL_STATEMENT_VALUE_QUERY": {
        "focus": "直接回答使用者指定的財報數值；每個數值都要能對回公司、科目、期間、單位及實際查得的報表證據。",
        "sections": ("查詢結果", "資料來源與口徑", "查無資料或限制"),
        "rules": (
            "先列數值再補充必要說明；多個科目或期間逐項對照，不延伸成未要求的授信判斷。",
            "查無數值時明確說明缺少哪個科目或期間，不用相近欄位或背景資料代填。",
        ),
    },
    "FINANCIAL_CONCEPT_EXPLANATION": {
        "focus": "以白話解釋問題中的財務概念、必要的計算或構成，以及它在授信判讀中的意義。",
        "sections": ("概念與計算口徑", "授信判讀意義", "本題資料與適用限制"),
        "rules": (
            "一般概念可直接解釋；只有取得該公司的證據時，才把概念套用到該公司。",
            "區分定義、常見可能原因與本題已證實的事實，不以一般原則推定公司現況。",
        ),
    },
    "FINANCIAL_TREND_CHANGE_ANALYSIS": {
        "focus": "比較可比期間的數值，量化變動方向、幅度與轉折，再解釋其授信意義。",
        "sections": ("比較期間與關鍵數據", "變動與趨勢分析", "可能原因及限制"),
        "rules": (
            "明列比較基期、期末、絕對變動與有證據支持的變動率；同比與環比不可混用。",
            "先陳述觀察到的趨勢，再將季節性或事件背景標為可驗證的可能解釋。",
        ),
    },
    "PROFITABILITY_ANALYSIS": {
        "focus": "評估本業獲利能力、利潤結構與獲利持續性。",
        "sections": ("獲利數據與比率", "本業及業外變化", "持續性與授信影響"),
        "rules": (
            "依已取得資料比較營收、毛利、營業利益與淨利，說明比率分子分母及期間。",
            "拆分本業與一次性或業外因素；沒有證據時不推定獲利改善可以持續。",
        ),
    },
    "SOLVENCY_ANALYSIS": {
        "focus": "分別評估短期流動性、債務到期壓力與現金流支應能力。",
        "sections": ("流動性與債務數據", "短期及長期償債分析", "資金缺口與待查事項"),
        "rules": (
            "把現金、流動資產負債、到期債務及營業現金流放在相同期間比較。",
            "不得只憑單一比率判斷可否償債；缺少到期結構或還款來源時明確列為限制。",
        ),
    },
    "DEBT_CAPITAL_STRUCTURE_ANALYSIS": {
        "focus": "說明負債規模與組成、財務槓桿、權益緩衝及再融資風險。",
        "sections": ("負債與權益結構", "槓桿及期限風險", "資本緩衝與限制"),
        "rules": (
            "區分有息負債、短長期負債及其他負債；比率須說明口徑。",
            "沒有可比資料或政策門檻時，不宣稱特定槓桿水準安全或超標。",
        ),
    },
    "CASH_FLOW_EARNINGS_QUALITY_ANALYSIS": {
        "focus": "檢查帳面獲利與營業現金流是否一致，並分析現金轉換與營運資金變動。",
        "sections": ("淨利與現金流對照", "背離因素與營運資金", "盈餘品質判讀"),
        "rules": (
            "並列相同期間的淨利與營業活動現金流，指出持續背離或一次性項目。",
            "資料不足時只描述背離現象，不把差異直接歸因於造假或特定會計處理。",
        ),
    },
    "OPERATING_EFFICIENCY_ANALYSIS": {
        "focus": "評估應收、存貨與應付項目的週轉效率及其對營運資金的影響。",
        "sections": ("週轉資料與計算口徑", "效率變化", "現金流與授信影響"),
        "rules": (
            "計算週轉率或天數時說明使用平均餘額或期末餘額，並保持期間口徑一致。",
            "解釋資金占用及回收風險；沒有產業基準時不宣稱優於或劣於同業。",
        ),
    },
    "FINANCIAL_ANOMALY_CAUSE_ANALYSIS": {
        "focus": "量化異常，跨期間或跨報表核對，再建立可檢驗的原因假說。",
        "sections": ("異常事實", "跨表勾稽與原因假說", "已證實、待查證與風險"),
        "rules": (
            "每個異常都列出比較期間及數值差異，指出相互支持或衝突的證據。",
            "把已證實事實、合理推論與待查證事項分開，不把原因假說寫成結論。",
        ),
    },
    "PEER_INDUSTRY_COMPARISON_ANALYSIS": {
        "focus": "在可比對象、期間與會計口徑明確時，評估公司相對同業或產業基準的差異。",
        "sections": ("比較對象與口徑", "指標差異", "相對風險與資料限制"),
        "rules": (
            "分別標示公司與同業資料的來源、期間及計算方式；只比較可比的數值。",
            "若沒有真實同業或產業基準，只陳述公司自身數據與缺口，不虛構平均值或排名。",
        ),
    },
    "INDUSTRY_EXTERNAL_RISK_ANALYSIS": {
        "focus": "辨識已確認的產業或外部風險，說明其傳導至公司營收、成本、現金流及還款能力的路徑。",
        "sections": ("外部風險與來源", "對公司的傳導路徑", "財務承受能力與情境限制"),
        "rules": (
            "標示外部資訊日期與來源，區分已發生事件、趨勢及情境推演。",
            "沒有公司財務證據時只提出待驗證的傳導假說，不宣稱實際影響已發生。",
        ),
    },
    "COMPANY_EVENT_MAJOR_RISK_ANALYSIS": {
        "focus": "查核公司重大事件的狀態、時間與可信來源，再評估可能的信用影響。",
        "sections": ("事件與查證狀態", "財務及營運影響", "授信風險與待確認事項"),
        "rules": (
            "清楚區分已發生事件、裁決、指控、傳聞及後續進展，標明資料日期。",
            "只能根據確認的事件與財務證據評估影響，不把負面消息直接視為違約事實。",
        ),
    },
    "HISTORICAL_CREDIT_REVIEW_QUERY": {
        "focus": "還原歷史徵審或授信紀錄中的結論、額度、條件及當時的決策依據。",
        "sections": ("歷史紀錄與版本", "當時核決依據及條件", "與目前資訊的差異或缺口"),
        "rules": (
            "每項歷史說法標明文件日期、版本或來源，並把原紀錄與本次分析分開。",
            "找不到內部紀錄時直接說明缺少資料，不從現行財報反推過去的核決內容。",
        ),
    },
    "COMPREHENSIVE_CREDIT_RISK_DECISION": {
        "focus": "整合財務、產業、事件與歷史授信證據，形成可追溯的條件式風險建議。",
        "sections": ("支持授信的證據", "反對或限制授信的風險", "還款來源與風險緩釋條件", "待補資料與條件式建議"),
        "rules": (
            "分開列出支持與反對證據，說明還款來源、主要風險與可行的緩釋條件。",
            "證據不足時只列待補資料與可成立的條件，不代替正式授信核決或捏造額度門檻。",
        ),
    },
}


def build_workflow_final_prompt_section(
    workflow_template: dict[str, Any],
) -> str:
    """Compose the answer format from the selected Python workflow template."""
    category = str(workflow_template.get("category") or "")
    profile = WORKFLOW_FINAL_PROMPTS.get(category)
    if profile is None:
        raise ValueError(f"No final answer prompt is defined for workflow {category!r}")

    output_requirements = workflow_template.get("output_requirements") or []
    lines = [
        f"選定 Workflow：{workflow_template.get('label') or category}（{category}）",
        f"本類分析重點：{profile['focus']}",
        "本類回答規則：",
        *(f"- {rule}" for rule in profile["rules"]),
        f"建議回答段落：{' → '.join(profile['sections'])}。只列出本題有內容的段落。",
    ]
    if output_requirements:
        lines.append("本類輸出限制：" + "；".join(output_requirements))
    return "\n".join(lines)
