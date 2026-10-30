from collections.abc import Callable
from typing import Any

from src.features.chatbot.models.langgraph_state_types import OverallState


# 所有分類目前均為可執行的初版標準模板，而非正式徵審政策。
DRAFT_REVIEW_NOTE = (
    "未完成：此 Workflow 目前僅為依既有 Semantic/RAG 流程建立的標準模板，"
    "分析目的、資料欄位、判斷門檻與輸出規則仍須由徵審、財會及風險專業人員逐項微調與驗證。"
)


STANDARD_SEMANTIC_WORKFLOW_NODES = {
    "FINANCIAL_STATEMENT_VALUE_QUERY": "financial_statement_value_query_workflow",
    "FINANCIAL_CONCEPT_EXPLANATION": "financial_concept_explanation_workflow",
    "FINANCIAL_TREND_CHANGE_ANALYSIS": "financial_trend_change_analysis_workflow",
    "PROFITABILITY_ANALYSIS": "profitability_analysis_workflow",
    "SOLVENCY_ANALYSIS": "solvency_analysis_workflow",
    "DEBT_CAPITAL_STRUCTURE_ANALYSIS": "debt_capital_structure_analysis_workflow",
    "CASH_FLOW_EARNINGS_QUALITY_ANALYSIS": "cash_flow_earnings_quality_analysis_workflow",
    "OPERATING_EFFICIENCY_ANALYSIS": "operating_efficiency_analysis_workflow",
    "FINANCIAL_ANOMALY_CAUSE_ANALYSIS": "financial_anomaly_cause_analysis_workflow",
    "PEER_INDUSTRY_COMPARISON_ANALYSIS": "peer_industry_comparison_analysis_workflow",
    "INDUSTRY_EXTERNAL_RISK_ANALYSIS": "industry_external_risk_analysis_workflow",
    "COMPANY_EVENT_MAJOR_RISK_ANALYSIS": "company_event_major_risk_analysis_workflow",
    "HISTORICAL_CREDIT_REVIEW_QUERY": "historical_credit_review_query_workflow",
    "COMPREHENSIVE_CREDIT_RISK_DECISION": "comprehensive_credit_risk_decision_workflow",
}


def _template(
    *,
    label: str,
    purposes: list[str],
    financial_data: list[str],
    rag_focus: list[str],
    analysis_steps: list[str],
    output_requirements: list[str],
) -> dict[str, Any]:
    return {
        "label": label,
        "implementation_status": "DRAFT_REQUIRES_PROFESSIONAL_REVIEW",
        "professional_review_note": DRAFT_REVIEW_NOTE,
        "analysis_purposes": purposes,
        "financial_data_requirements": financial_data,
        "rag_focus": rag_focus,
        "analysis_steps": analysis_steps,
        "output_requirements": output_requirements,
    }


STANDARD_SEMANTIC_WORKFLOW_TEMPLATES = {
    # 未完成：財報欄位與期間解析規則仍須由財會專業人員微調。
    "FINANCIAL_STATEMENT_VALUE_QUERY": _template(
        label="財報數值查詢",
        purposes=["辨識公司、財報科目與期間", "回傳可追溯的單一或多個財報數值"],
        financial_data=["使用者指定的資產負債表、綜合損益表或現金流量表科目"],
        rag_focus=["會計科目別名與財報欄位定義"],
        analysis_steps=["解析公司與期間", "匹配正式財報科目", "查詢資料庫並核對單位"],
        output_requirements=["直接回答數值", "標示期間、單位與財報來源"],
    ),
    # 未完成：概念解釋口徑與適用例外仍須由財會及徵審專業人員微調。
    "FINANCIAL_CONCEPT_EXPLANATION": _template(
        label="財務概念解釋",
        purposes=["解釋財務名詞、指標或現象", "連結概念與授信風險意義"],
        financial_data=["僅在題目涉及特定公司時，查詢該概念必要的相關財報欄位"],
        rag_focus=["專家知識中的會計定義、判讀原則與授信注意事項"],
        analysis_steps=["定義概念", "說明常見成因", "說明正反向風險與判讀限制"],
        output_requirements=["先白話定義再說明徵審意義", "不得把一般原則當成該公司的既定事實"],
    ),
    # 未完成：比較期間、重大變動門檻及產業季節性仍須由專業人員微調。
    "FINANCIAL_TREND_CHANGE_ANALYSIS": _template(
        label="財務趨勢與變動分析",
        purposes=["比較多期財務數據", "辨識趨勢方向、幅度與轉折"],
        financial_data=["題目核心科目的至少二至三期數值", "必要的同比或環比基期資料"],
        rag_focus=["產業季節性、公司營運背景與專家趨勢判讀規則"],
        analysis_steps=["取得一致口徑的多期資料", "計算增減與比率", "辨識持續趨勢或單期異常"],
        output_requirements=["列出關鍵期間與變動幅度", "區分資料事實與可能原因"],
    ),
    # 未完成：獲利指標組合與警示門檻仍須由徵審及財會專業人員微調。
    "PROFITABILITY_ANALYSIS": _template(
        label="獲利能力分析",
        purposes=["評估本業獲利能力與獲利穩定性", "辨識毛利、營益與淨利的變化來源"],
        financial_data=["營業收入、營業成本、營業毛利、營業利益、稅前淨利、本期淨利", "必要時搭配資產與權益資料計算報酬率"],
        rag_focus=["產業毛利結構、一次性損益與專家獲利判讀規則"],
        analysis_steps=["計算主要利潤率", "比較多期變化", "拆分本業與業外因素", "評估持續性"],
        output_requirements=["呈現獲利指標及趨勢", "指出改善或惡化證據與限制"],
    ),
    # 未完成：流動性與償債警示門檻仍須依產業及授信政策由專業人員微調。
    "SOLVENCY_ANALYSIS": _template(
        label="償債能力分析",
        purposes=["評估短期流動性與債務清償能力", "辨識到期壓力及資金缺口"],
        financial_data=["現金及約當現金、流動資產、流動負債、短期借款、一年內到期負債", "營業活動現金流量與利息支出（若題目需要）"],
        rag_focus=["授信政策門檻、債務到期資訊、資金調度及專家償債判讀規則"],
        analysis_steps=["計算流動性指標", "比較現金與短期債務", "檢視營業現金流支應能力", "揭露資料缺口"],
        output_requirements=["分開說明短期與長期償債能力", "不得只用單一比率下結論"],
    ),
    # 未完成：合理槓桿水準及資本結構門檻仍須依產業由專業人員微調。
    "DEBT_CAPITAL_STRUCTURE_ANALYSIS": _template(
        label="負債與資本結構分析",
        purposes=["評估舉債程度、負債組成與財務槓桿", "判斷資本緩衝是否充足"],
        financial_data=["資產總額、負債總額、權益總額、短長期借款與應付公司債", "利息支出及獲利資料（若需評估保障倍數）"],
        rag_focus=["同業槓桿慣例、融資條件、資本計畫與專家結構判讀規則"],
        analysis_steps=["計算負債與槓桿比率", "拆分有息及短長期負債", "評估權益緩衝與再融資風險"],
        output_requirements=["交代負債規模與結構", "說明槓桿對授信風險的影響"],
    ),
    # 未完成：盈餘品質判斷期間與異常門檻仍須由財會及徵審專業人員微調。
    "CASH_FLOW_EARNINGS_QUALITY_ANALYSIS": _template(
        label="現金流與盈餘品質分析",
        purposes=["驗證帳面獲利是否由現金流支持", "辨識應計盈餘與現金轉換風險"],
        financial_data=["本期淨利、營業活動現金流量、折舊攤銷、應收帳款與存貨變動", "投資及籌資活動現金流量（若需解釋資金來源去向）"],
        rag_focus=["一次性項目、會計政策、營運資金背景與專家盈餘品質規則"],
        analysis_steps=["比較淨利與營業現金流", "分析營運資金變動", "辨識持續背離或一次性因素"],
        output_requirements=["明確說明盈餘與現金的支持程度", "列出背離原因及尚待確認資料"],
    ),
    # 未完成：週轉天數與效率基準仍須依產業營運模式由專業人員微調。
    "OPERATING_EFFICIENCY_ANALYSIS": _template(
        label="營運效率分析",
        purposes=["評估應收、存貨與營運資產的使用效率", "辨識資金占用及回收惡化"],
        financial_data=["營業收入、營業成本、應收帳款、存貨、應付帳款", "必要的期初期末平均餘額"],
        rag_focus=["產業交易條件、季節性、客戶供應商結構與專家週轉判讀規則"],
        analysis_steps=["計算週轉率或週轉天數", "比較多期趨勢", "連結營運資金與現金流影響"],
        output_requirements=["呈現效率指標及方向", "避免脫離產業特性解讀"],
    ),
    # 未完成：異常偵測規則、重要性門檻及原因證據標準仍須由專業人員微調。
    "FINANCIAL_ANOMALY_CAUSE_ANALYSIS": _template(
        label="財務異常與原因追查",
        purposes=["辨識跨期間或跨報表的不一致現象", "建立可能原因並以證據驗證"],
        financial_data=["題目涉及的損益、資產負債與現金流核心欄位", "至少二期以上可供交叉驗證的資料"],
        rag_focus=["重大事件、附註背景、營運變化、專家異常判讀與外部資訊"],
        analysis_steps=["量化異常", "跨表勾稽", "列出可能原因", "區分已證實、合理推論與待查證事項"],
        output_requirements=["以證據鏈說明異常", "不得將未驗證原因寫成事實"],
    ),
    # 未完成：同業樣本、可比口徑與產業基準仍須由產業及徵審專業人員微調。
    "PEER_INDUSTRY_COMPARISON_ANALYSIS": _template(
        label="同業／產業比較分析",
        purposes=["比較公司與同業或產業基準", "辨識相對優劣勢及偏離程度"],
        financial_data=["公司本身的比較指標與一致期間資料", "若本地資料可取得，使用可比公司的相同財報欄位"],
        rag_focus=["同業名單、產業平均、商業模式差異及資料口徑說明"],
        analysis_steps=["確認可比對象與口徑", "計算公司指標", "引用同業基準", "解釋差異及限制"],
        output_requirements=["清楚列出比較對象、期間與口徑", "資料不足時不得虛構產業平均"],
    ),
    # 未完成：外部風險項目、來源可信度及影響評分仍須由產業專業人員微調。
    "INDUSTRY_EXTERNAL_RISK_ANALYSIS": _template(
        label="產業與外部風險分析",
        purposes=["辨識景氣、政策、利率、匯率、原料與供應鏈風險", "評估外部因素對公司財務及還款能力的傳導"],
        financial_data=["與風險傳導相關的營收、毛利、存貨、借款、利息與現金流資料"],
        rag_focus=["最新產業研究、政策法規、總體資料、供應鏈資訊與外部檢索結果"],
        analysis_steps=["確認外部風險事件", "建立對公司營運及財務的傳導路徑", "用財務資料檢視承受能力"],
        output_requirements=["區分外部事實與情境推演", "標示資料日期、來源與不確定性"],
    ),
    # 未完成：重大事件清單、嚴重度分級與查證規範仍須由法遵及徵審專業人員微調。
    "COMPANY_EVENT_MAJOR_RISK_ANALYSIS": _template(
        label="公司事件與重大風險分析",
        purposes=["查核訴訟、裁罰、違約、治理或負面新聞", "評估事件對營運、財務與信用的影響"],
        financial_data=["用於衡量事件承受能力的現金、負債、獲利與現金流資料"],
        rag_focus=["公司重大訊息、主管機關公告、司法或裁罰資訊、可信新聞與外部檢索結果"],
        analysis_steps=["確認事件與日期", "交叉驗證來源", "區分已發生與指控", "評估財務及授信影響"],
        output_requirements=["標示來源與事件狀態", "避免把未證實消息當成事實"],
    ),
    # 未完成：歷史徵審資料權限、版本與決策脈絡規則仍須由授信管理人員微調。
    "HISTORICAL_CREDIT_REVIEW_QUERY": _template(
        label="歷史徵審／授信資訊查詢",
        purposes=["查詢歷史徵審結論、額度變動與核決條件", "還原當時決策依據與後續差異"],
        financial_data=["當期問題若要求重新檢視，補充與歷史決策相關的同期及最新財報欄位"],
        rag_focus=["內部歷史徵審報告、授信批覆、條件變更、覆審紀錄與版本資訊"],
        analysis_steps=["定位正確公司與歷史版本", "擷取決策、原因及條件", "必要時比較最新狀態"],
        output_requirements=["區分歷史紀錄原文與本次分析", "標示資料日期、版本與存取限制"],
    ),
    # 未完成：准駁、額度、條件及風險分級規則必須由授信政策與核決人員微調及核准。
    "COMPREHENSIVE_CREDIT_RISK_DECISION": _template(
        label="綜合授信風險與決策建議",
        purposes=["整合財務、產業、事件與歷史授信資訊", "形成可追溯的風險判斷及條件式建議"],
        financial_data=["獲利、現金流、流動性、槓桿、營運效率等核心財報資料", "題目指定的擔保、額度或還款來源相關資料"],
        rag_focus=["授信政策、專家知識、產業資料、重大事件、歷史徵審與外部檢索結果"],
        analysis_steps=["彙整關鍵證據", "分析還款來源與主要風險", "列出風險緩釋條件", "形成附帶限制的決策建議"],
        output_requirements=["分開列出支持、反對與待補資料", "不得取代正式授信核決", "所有建議須可回溯至證據或政策"],
    ),
}


def build_standard_workflow_node(
    category: str,
    node_name: str,
) -> Callable[[OverallState], OverallState]:
    """將所選 Workflow 的 Python 模板交給既有 Semantic/RAG pipeline。"""
    workflow_template = STANDARD_SEMANTIC_WORKFLOW_TEMPLATES[category]

    def standard_workflow(state: OverallState) -> OverallState:
        return {
            **state,
            "semantic_workflow_node": node_name,
            "semantic_workflow_status": "draft_standard_template_requires_professional_review",
            "semantic_workflow_template": {
                "category": category,
                **workflow_template,
            },
        }

    standard_workflow.__name__ = node_name
    standard_workflow.__doc__ = DRAFT_REVIEW_NOTE
    return standard_workflow


STANDARD_SEMANTIC_WORKFLOW_HANDLERS = {
    node_name: build_standard_workflow_node(category, node_name)
    for category, node_name in STANDARD_SEMANTIC_WORKFLOW_NODES.items()
}
