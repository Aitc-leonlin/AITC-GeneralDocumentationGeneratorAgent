"""為既存固定格式資料產生可重抽的 JSON 示範內容。"""

import re
from copy import deepcopy
from random import SystemRandom
from typing import Any


NUMBER_PATTERN = re.compile(r"\d[\d,]*(?:\.\d+)?")

SUBJECT_OPTIONS = {
    "medical": ["示範醫療中心內科門診", "示範區域醫院家醫科門診", "示範社區診所一般門診"],
    "finance": ["示範商業有限公司", "示範零售股份有限公司", "示範製造企業有限公司"],
    "education": ["示範國中七年級閱讀課程", "示範國中八年級閱讀課程", "示範學校閱讀社團"],
    "food": ["示範餐館季節餐點", "示範輕食店午間套餐", "示範咖啡館季節新品"],
}


def _vary_value(value: str, randomizer: SystemRandom) -> str:
    """依範例數值的單位產生小幅變化，保留原本的顯示格式。"""
    numbers = list(NUMBER_PATTERN.finditer(value))
    if not numbers:
        return value
    if "週內" in value and len(numbers) > 1:
        days = randomizer.randint(0, 4)
        return value[: numbers[-1].start()] + str(days) + value[numbers[-1].end() :]

    match = numbers[0]
    base = float(match.group().replace(",", ""))
    if "%" in value:
        varied = min(100.0, max(1.0, base + randomizer.uniform(-6, 6)))
    elif "/ 5" in value:
        varied = min(4.9, max(3.4, base + randomizer.uniform(-0.4, 0.4)))
    elif "/ 100" in value:
        varied = min(99.0, max(50.0, base + randomizer.uniform(-8, 8)))
    else:
        varied = max(1.0, base * randomizer.uniform(0.8, 1.2))

    decimals = len(match.group().split(".")[1]) if "." in match.group() else 0
    if decimals:
        replacement = f"{varied:.{decimals}f}"
    else:
        replacement = f"{round(varied):,}" if "," in match.group() else str(round(varied))
    return value[: match.start()] + replacement + value[match.end() :]


def _set_values(report: dict[str, Any], values: dict[str, str]) -> None:
    for metric in report["metrics"]:
        if metric["label"] in values:
            metric["value"] = values[metric["label"]]


def _medical_content(report: dict[str, Any], randomizer: SystemRandom) -> None:
    daily_visits = randomizer.randint(90, 155)
    wait = randomizer.randint(27, 52)
    peak_wait = wait + randomizer.randint(10, 22)
    p90_wait = peak_wait + randomizer.randint(8, 20)
    _set_values(report, {
        "每週門診人次": f"約 {daily_visits * 5} 人",
        "單日平均門診人次": f"{daily_visits} 人",
        "平均候診時間": f"{wait} 分鐘",
        "尖峰時段候診時間": f"{peak_wait} 分鐘",
        "候診時間第 90 百分位": f"{p90_wait} 分鐘",
    })
    report["summary"] = (
        f"{report['subject']}每週約服務 {daily_visits * 5} 人，平均候診 {wait} 分鐘。"
        "本報告整理門診動線與回診安排，以下均為隨機測試資料。"
    )
    report["sections"][0]["details"] = (
        f"本次範例平均候診 {wait} 分鐘，尖峰時段約 {peak_wait} 分鐘；"
        "建議檢視報到與叫號的時間落差。"
    )
    report["sections"][1]["details"] = randomizer.choice([
        "先在單一診間試行分時段報到四週，再依每週紀錄調整通知內容。",
        "先於尖峰時段試行候診進度提醒，並由櫃檯每週彙整異常狀況。",
    ])


def _finance_content(report: dict[str, Any], randomizer: SystemRandom) -> None:
    revenue = randomizer.randint(950, 1750)
    gross_margin = randomizer.randint(27, 42)
    operating_margin = randomizer.randint(8, 16)
    net_margin = randomizer.randint(4, min(11, operating_margin - 2))
    operating_profit = round(revenue * operating_margin / 100)
    net_profit = round(revenue * net_margin / 100)
    cash_flow = round(net_profit * randomizer.uniform(0.8, 1.5))
    _set_values(report, {
        "季度營收": f"新臺幣 {revenue:,} 萬元",
        "毛利率": f"{gross_margin}%",
        "營業利益率": f"{operating_margin}%",
        "淨利率": f"{net_margin}%",
        "季度營業利益": f"新臺幣 {operating_profit:,} 萬元",
        "季度稅後淨利": f"新臺幣 {net_profit:,} 萬元",
        "營業現金流量": f"新臺幣 {cash_flow:,} 萬元",
    })
    report["summary"] = (
        f"{report['subject']}本季示範營收為新臺幣 {revenue:,} 萬元、淨利率約 {net_margin}%。"
        "以下數值為隨機測試資料，供檢視報告格式與分析流程。"
    )
    report["sections"][0]["details"] = (
        f"本季示範營收 {revenue:,} 萬元、營業利益約 {operating_profit:,} 萬元；"
        "應收帳款與現金流為後續觀察重點。"
    )
    report["sections"][1]["details"] = randomizer.choice([
        "建議按月檢視回款與短期資金需求，並更新季度現金流預測。",
        "建議追蹤逾期應收款與存貨週轉，再討論資金安排。",
    ])


def _education_content(report: dict[str, Any], randomizer: SystemRandom) -> None:
    students = randomizer.randint(72, 118)
    long_completion = randomizer.randint(55, 75)
    short_completion = randomizer.randint(85, 98)
    _set_values(report, {
        "參與學生": f"{students} 人",
        "長篇文本完成率": f"{long_completion}%",
        "短篇文本完成率": f"{short_completion}%",
    })
    report["summary"] = (
        f"{report['subject']}本次示範共有 {students} 名學生參與，"
        f"短篇與長篇文本完成率分別為 {short_completion}% 與 {long_completion}%。"
        "以下為隨機測試資料。"
    )
    report["sections"][0]["details"] = (
        f"短篇文本完成率 {short_completion}%，高於長篇文本的 {long_completion}%；"
        "可觀察閱讀長度對參與情況的影響。"
    )
    report["sections"][1]["details"] = randomizer.choice([
        "下一階段每兩週蒐集一次學生回饋，並追蹤不同文本的完成情況。",
        "安排長篇文本的分段閱讀與小組討論，觀察作業完成情況。",
    ])


def _food_content(report: dict[str, Any], randomizer: SystemRandom) -> None:
    price = randomizer.randrange(240, 361, 10)
    cost = round(price * randomizer.uniform(0.28, 0.36))
    cost_rate = round(cost / price * 100, 1)
    weeks = randomizer.randint(3, 6)
    daily_target = randomizer.randint(25, 45)
    achievement = randomizer.randint(70, 105)
    sold = round(daily_target * 5 * weeks * achievement / 100)
    prep_target = randomizer.randint(10, 15)
    _set_values(report, {
        "預計售價": f"新臺幣 {price} 元",
        "目標食材成本率": f"{cost_rate:.1f}%",
        "單份預估食材成本": f"新臺幣 {cost} 元",
        "單份預估毛利": f"新臺幣 {price - cost} 元",
        "試賣期間": f"{weeks} 週",
        "目標每日銷量": f"{daily_target} 份",
        "試賣累計售出": f"{sold} 份",
        "試賣目標達成率": f"{achievement}%",
        "備餐目標時間": f"{prep_target} 分鐘",
        "實際平均出餐時間": f"{prep_target + randomizer.randint(0, 4)} 分鐘",
        "缺貨天數": f"{weeks} 週內 {randomizer.randint(0, 3)} 天",
        "預估每週備料量": f"{daily_target * 5 + randomizer.randint(5, 25)} 份",
    })
    report["summary"] = (
        f"{report['subject']}預計售價新臺幣 {price} 元，"
        f"示範試賣 {weeks} 週、累計售出 {sold} 份。以下均為隨機測試資料。"
    )
    report["sections"][0]["details"] = (
        f"每份示範售價 {price} 元、食材成本約 {cost} 元；"
        "以當季食材與簡潔出餐流程作為產品定位。"
    )
    report["sections"][1]["details"] = randomizer.choice([
        f"以 {weeks} 週試賣紀錄銷量、剩料與顧客意見，再調整份量。",
        f"在 {weeks} 週試賣期間每週檢視成本與出餐時間，調整備料量。",
    ])


DOMAIN_CONTENT_BUILDERS = {
    "medical": _medical_content,
    "finance": _finance_content,
    "education": _education_content,
    "food": _food_content,
}


def randomize_report_sample(domain: str, template: dict[str, Any], randomizer: SystemRandom) -> dict[str, Any]:
    report = deepcopy(template)
    report["subject"] = randomizer.choice(SUBJECT_OPTIONS[domain])
    for metric in report["metrics"]:
        metric["value"] = _vary_value(str(metric["value"]), randomizer)
    DOMAIN_CONTENT_BUILDERS[domain](report, randomizer)
    report["sourceNote"] = report["sourceNote"].replace(
        "固定 JSON 測試資料", "依固定 JSON 範本隨機產生的測試資料"
    )
    return report
