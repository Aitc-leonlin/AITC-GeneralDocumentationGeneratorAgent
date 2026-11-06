"""在規劃大綱前，讓開放需求選擇可採用的具體案例。"""

import json
import logging
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from src.features.report_generator.services.domain_report_service import ReportLLMTrace

from .catalog import load_document_type_templates
from .llm import _invoke_report_structured
from .question_agent import list_document_samples, read_document_sample
from .samples import DocumentSampleMetadata, DocumentTypeSample
from .schemas import (
    DocumentPurpose, ReportOutputCoverage, ReportOutlineRequest,
    ReportSampleSelection, ReportToolUsage, required_source_satisfied,
)


logger = logging.getLogger(__name__)
MAX_CASES_PER_DOCUMENT = 5


class RequestScope(BaseModel):
    route: Literal["open", "specified", "reuse"]
    outputMode: Literal["single", "multiple", "compare"] = "single"
    requestedCount: int = Field(default=1, ge=1)
    comparisonSubjects: list[str] = Field(default_factory=list)
    sourceRequirement: Literal["optional", "required"] = "optional"
    requiredSource: Literal["case", "user_data", "external", "any"] = "any"
    sourceProvided: bool = False
    sourceReason: str = Field(default="", max_length=300)
    fixedConditions: list[str] = Field(default_factory=list)
    freeChoices: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=300)


class CandidateChoice(BaseModel):
    sampleId: str = ""
    sampleIds: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1, max_length=300)


class DocumentTypeChoice(BaseModel):
    documentTypeIds: list[str] = Field(default_factory=list, max_length=3)


class AdoptionChoice(BaseModel):
    mode: Literal["adopt", "reference", "none"]
    adoptedSampleIds: list[str] = Field(default_factory=list)
    referenceSampleIds: list[str] = Field(default_factory=list)
    outputCoverage: list[ReportOutputCoverage]
    reason: str = Field(min_length=1, max_length=300)


class CoverageReview(BaseModel):
    supportedOutputIndexes: list[int]
    reason: str = Field(min_length=1, max_length=300)


class SingleCaseReview(BaseModel):
    canAdopt: bool
    canReference: bool
    reason: str = Field(min_length=1, max_length=300)


class ReuseReview(BaseModel):
    reuse: bool
    route: Literal["open", "specified"]
    reason: str = Field(min_length=1, max_length=300)


class OpenSampleState(TypedDict, total=False):
    request: ReportOutlineRequest
    purposes: list[DocumentPurpose]
    fallback_document_type_id: str | None
    allow_tools: bool
    model: Any
    traces: list[ReportLLMTrace]
    tool_usages: list[ReportToolUsage]
    scope: RequestScope
    metadata: list[DocumentSampleMetadata]
    sample_id: str
    sample_ids: list[str]
    sample: DocumentTypeSample | None
    samples: list[tuple[str, DocumentTypeSample]]
    selection: ReportSampleSelection
    reuse_valid: bool


def _empty_selection(scope: RequestScope, reason: str) -> ReportSampleSelection:
    return ReportSampleSelection(
        route=scope.route if scope.route != "reuse" else "none",
        outputMode=scope.outputMode,
        requestedCount=scope.requestedCount,
        comparisonSubjects=scope.comparisonSubjects,
        sourceRequirement=scope.sourceRequirement,
        requiredSource=scope.requiredSource,
        sourceProvided=scope.sourceProvided,
        sourceReason=scope.sourceReason,
        reason=reason,
    )


def _classify_scope(state: OpenSampleState) -> OpenSampleState:
    traces = list(state["traces"])
    request = state["request"]
    scope = _invoke_report_structured(
        model=state["model"], schema=RequestScope,
        operation="general_document.classify_sample_route", traces=traces,
        prompt=(
            "你是文件需求的選案路由器。只判斷使用者是否留下可由案例決定的具體主題，"
            "不撰寫文件。route=open：可從候選案例選一道菜、目的地或其他具體方案，"
            "並以它作為文件主題；例如『義大利麵食譜』可選一種義大利麵，"
            "『日本四天三夜旅遊』可選日本的一個城市。"
            "route=specified：使用者已指定不可替換的核心菜色、目的地、公司或對象，"
            "例如『波隆那義大利麵』；不得用其他案例取代。"
            "route=reuse：已有案例選擇，而最新訊息只修改章節、格式或其他非核心條件，"
            "可延續原選擇；若最新訊息改變核心主題、要求數量或輸出形式，不得 reuse。"
            "另外判斷 outputMode：single 是一份方案；multiple 是多份獨立選項；"
            "compare 是比較兩個或多個對象。requestedCount 是使用者要求的選項或比較對象數，"
            "未明說時 single=1、compare 依明確列出的對象數，multiple 依語意推斷。"
            "comparisonSubjects 只列使用者明確指定要比較的對象，勿從案例推測。"
            "另外獨立判斷 sourceRequirement：只有使用者明確要求依特定資料、"
            "引用可核對來源、取得真實個案結論，或文件任務本身必須有來源才能成立時才選 required；"
            "一般食譜、旅行規劃、範例方案及一般說明預設為 optional。"
            "requiredSource=case 表示必須找到適用的案例 JSON；"
            "user_data 表示必須依使用者實際提供的資料；"
            "external 表示必須查證最新或外部真實資料；"
            "any 表示任何一種合適來源即可。"
            "sourceProvided 只有對話中已包含足以支援任務的實際資料內容才是 true；"
            "僅說『我有資料』、貼網址但沒有可讀內容，或提供不相關數字都算 false。"
            "若使用者已貼上有出處的來源內容，且要求根據貼上的內容寫作，選 user_data；"
            "若仍要求獨立驗證即時或外部資訊，選 external。"
            "修改既有文件時，若最新訊息未改變來源要求，沿用目前案例選擇中的"
            "sourceRequirement 與 requiredSource；不要因為最新訊息沒有重述就改成 optional。"
            "sourceReason 簡述為何資料必要及要求哪種來源。"
            "fixedConditions 列出必須保留的明確條件，包括天數、地區、對象、限制與用途；"
            "freeChoices 列出可由案例具體化的空位。不得把候選案例的條件當作使用者條件。\n"
            f"用途：{json.dumps([item.model_dump() for item in state['purposes']], ensure_ascii=False)}\n"
            f"目前案例：{request.currentSampleSelection.model_dump_json() if request.currentSampleSelection else 'null'}\n"
            f"目前大綱：{request.currentPurposeOutline.model_dump_json() if request.currentPurposeOutline else 'null'}\n"
            f"對話：{json.dumps([item.model_dump() for item in request.messages], ensure_ascii=False)}"
        ),
    )
    comparison_subjects = list(dict.fromkeys(
        item.strip() for item in scope.comparisonSubjects if item.strip()
    ))
    if comparison_subjects != scope.comparisonSubjects:
        scope = scope.model_copy(update={"comparisonSubjects": comparison_subjects})
    minimum_count = (
        max(2, len(scope.comparisonSubjects)) if scope.outputMode == "compare"
        else 2 if scope.outputMode == "multiple" else 1
    )
    if scope.requestedCount < minimum_count or (
        scope.outputMode == "single" and scope.requestedCount != 1
    ):
        scope = scope.model_copy(update={
            "requestedCount": minimum_count if scope.outputMode != "single" else 1,
        })
    if scope.route == "reuse":
        previous = request.currentSampleSelection
        if not previous or previous.mode == "none" or not (previous.sampleIds or previous.sampleId):
            scope = scope.model_copy(update={
                "route": "open" if scope.freeChoices else "specified",
            })
        elif (
            previous.outputMode != scope.outputMode
            or previous.requestedCount != scope.requestedCount
            or previous.comparisonSubjects != scope.comparisonSubjects
        ):
            scope = scope.model_copy(update={
                "route": previous.route if previous.route != "none" else "open",
            })
    return {
        "scope": scope, "traces": traces,
        "selection": _empty_selection(scope, scope.reason),
    }


def _scope_route(state: OpenSampleState) -> Literal["list", "reuse", "end"]:
    if not state.get("allow_tools", True):
        return "end"
    scope = state["scope"]
    if scope.sourceRequirement == "required" and scope.requiredSource in ("user_data", "external"):
        return "end"
    route = state["scope"].route
    return "reuse" if route == "reuse" else "list"


def _retry_case_selection(
    state: OpenSampleState, *, route: Literal["open", "specified"], reason: str,
    read_result: OpenSampleState,
) -> OpenSampleState:
    scope = state["scope"].model_copy(update={"route": route, "reason": reason})
    return {
        "scope": scope, "selection": _empty_selection(scope, reason),
        "sample_id": "", "sample_ids": [], "sample": None, "samples": [],
        "reuse_valid": False,
        "tool_usages": read_result["tool_usages"],
        "traces": read_result.get("traces", state["traces"]),
    }


def _reuse_selection(state: OpenSampleState) -> OpenSampleState:
    previous = state["request"].currentSampleSelection
    scope = state["scope"]
    selected_ids = list(dict.fromkeys([
        *previous.sampleIds, *([previous.sampleId] if previous.sampleId else []),
    ]))
    fallback_route: Literal["open", "specified"] = (
        previous.route if previous.route in ("open", "specified")
        else "open" if scope.freeChoices else "specified"
    )
    if len(selected_ids) > MAX_CASES_PER_DOCUMENT:
        return _retry_case_selection(
            state, route=fallback_route, reason="舊選案數量超過目前上限，重新搜尋案例。",
            read_result=state,
        )
    read_result = _read_candidate({**state, "sample_ids": selected_ids})
    samples = read_result["samples"]
    if len(samples) != len(selected_ids):
        return _retry_case_selection(
            state, route=fallback_route, reason="舊案例無法完整讀取，重新搜尋案例。",
            read_result=read_result,
        )
    adopted_ids = previous.adoptedSampleIds or (
        [previous.sampleId] if previous.mode == "adopt" and previous.sampleId else []
    )
    if set(adopted_ids) - set(selected_ids) or any(
        item.sampleId not in adopted_ids for item in previous.outputCoverage
    ):
        return _retry_case_selection(
            state, route=fallback_route, reason="舊選案的採用與覆蓋紀錄不一致，重新搜尋案例。",
            read_result=read_result,
        )
    traces = list(state["traces"])
    review = _invoke_report_structured(
        model=state["model"], schema=ReuseReview,
        operation="general_document.review_reused_sample", traces=traces,
        prompt=(
            "你是文件案例沿用核對器。使用者修訂需求後，逐份核對舊選案是否仍可"
            "以原本用途使用。reuse=true 只有在所有採用案例仍能作為原先的具體選項或"
            "比較對象、所有參考案例仍有實質參考價值，且每一筆 outputCoverage 仍由"
            "對應案例的完整 JSON 支援時才可給出。若其中一份應從採用降為參考、"
            "已不相關、比較對象改變，或固定條件與案例實質衝突，請回傳 false，"
            "讓系統重新搜尋候選案例。不要只看標題。"
            "以最新對話與需求判斷為準；舊案例中的地點、人數、預算、偏好等額外"
            "條件，若不是使用者明確指定且不可替換的條件，不構成衝突。"
            "案例只支援部分重要章節或可借鑑方法時，仍可保留 reference；"
            "開放需求可沿用合理的具體方案。不要要求與需求逐字相同，也不要"
            "要求單一案例涵蓋整份文件。不得推測 JSON 未列出的事實。"
            "route 請依最新需求填 open 或 specified，供需要重新搜尋時使用；"
            "reason 簡述可沿用的內容或需要重選的條件。\n"
            f"最新需求：{scope.model_dump_json()}\n"
            f"舊選案：{previous.model_dump_json()}\n"
            f"目前大綱：{state['request'].currentPurposeOutline.model_dump_json() if state['request'].currentPurposeOutline else 'null'}\n"
            f"對話：{json.dumps([item.model_dump() for item in state['request'].messages], ensure_ascii=False)}\n"
            f"完整案例：{json.dumps([{'sampleId': sample_id, **sample.model_dump()} for sample_id, sample in samples], ensure_ascii=False)}"
        ),
    )
    read_result["traces"] = traces
    if not review.reuse:
        return _retry_case_selection(
            state, route=review.route, reason=review.reason,
            read_result=read_result,
        )
    selection = previous.model_copy(update={
        "sourceRequirement": scope.sourceRequirement,
        "requiredSource": scope.requiredSource,
        "sourceProvided": scope.sourceProvided,
        "sourceReason": scope.sourceReason,
        "reason": review.reason,
    })
    if not required_source_satisfied(selection):
        return _retry_case_selection(
            state, route=review.route,
            reason="舊案例無法滿足目前必要資料的覆蓋要求，重新搜尋案例。",
            read_result=read_result,
        )
    return {
        **read_result, "selection": selection, "reuse_valid": True,
    }


def _reuse_route(state: OpenSampleState) -> Literal["list", "end"]:
    return "end" if state.get("reuse_valid") else "list"


def _list_metadata(state: OpenSampleState) -> OpenSampleState:
    document_ids = [
        item for purpose in state["purposes"]
        for item in purpose.referenceTemplateIds
    ]
    document_ids = list(dict.fromkeys(document_ids))[:3]
    traces = list(state["traces"])
    if not document_ids and state.get("fallback_document_type_id"):
        document_ids = [state["fallback_document_type_id"]]
    if not document_ids:
        templates = load_document_type_templates()
        choice = _invoke_report_structured(
            model=state["model"], schema=DocumentTypeChoice,
            operation="general_document.choose_sample_types", traces=traces,
            prompt=(
                "你是案例查詢範圍選擇 Agent。根據使用者文件用途，從目錄選出最多三個"
                "最可能含有實質相關案例的 D ID；若目錄沒有相關類型，回傳空清單。"
                "只決定查詢範圍，不推測案例內容。\n"
                f"用途：{json.dumps([item.model_dump() for item in state['purposes']], ensure_ascii=False)}\n"
                f"需求判斷：{state['scope'].model_dump_json()}\n"
                f"文件類型：{json.dumps([{'id': item.id, 'name': item.name, 'purpose': item.purpose} for item in templates.values()], ensure_ascii=False)}"
            ),
        )
        document_ids = [
            item for item in dict.fromkeys(choice.documentTypeIds)
            if item in templates
        ][:3]
    if not document_ids:
        return {"metadata": [], "traces": traces}
    request = {"document_type_ids": document_ids}
    status: Literal["success", "error"] = "success"
    try:
        response = list_document_samples.invoke(request)
        metadata = [DocumentSampleMetadata.model_validate(item) for item in json.loads(response)]
    except Exception as error:
        logger.exception("open sample agent: list_document_samples failed")
        status, metadata = "error", []
        response = json.dumps({"error": str(error)}, ensure_ascii=False)
    usage = ReportToolUsage(
        toolName="list_document_samples", documentTypeIds=document_ids,
        resultCount=len(metadata), status=status,
        requestJson=json.dumps(request, ensure_ascii=False), responseJson=response,
    )
    return {
        "metadata": metadata, "traces": traces,
        "tool_usages": [*state["tool_usages"], usage],
    }


def _metadata_route(state: OpenSampleState) -> Literal["choose", "end"]:
    return "choose" if state.get("metadata") else "end"


def _choose_candidate(state: OpenSampleState) -> OpenSampleState:
    traces = list(state["traces"])
    choice = _invoke_report_structured(
        model=state["model"], schema=CandidateChoice,
        operation="general_document.choose_open_sample", traces=traces,
        prompt=(
            "你是文件需求的案例選擇 Agent。根據使用者固定條件、可自由決定的空位及"
            "候選 title、description，挑選最值得讀取的案例。"
            "single 最多選一份；multiple 或 compare 可選多份，優先涵蓋使用者要求的"
            "不同選項或比較對象。必要來源的多選項／比較需求可多選備用案例，"
            "避免讀取後才發現部分案例只能參考。最多選五份。"
            "sampleIds 依優先順序列出候選 ID，不要重複；sampleId 只供舊版單份格式相容。"
            "route=open 時，優先挑選符合固定條件的具體方案，不要求文字完全一致；"
            "若只有部分條件不同但方法有明顯價值，仍可讀取並在下一步判斷為 reference。"
            "route=specified 時，只選擇核心菜色、目的地、公司或對象與使用者指定主題一致的案例；"
            "compare 中明確列出的每個對象可各選一份。"
            "其他菜色的食譜、其他目的地的行程只能提供方法，不能作為指定主題的資料來源。"
            "案例不得改寫使用者固定條件，例如地區、料理種類、天數或限制。"
            "只有分類相同而無實質內容，或所有案例都違反核心條件時，sampleIds 留空。"
            "只能回傳候選中的 ID；metadata 不能證明未列出的事實。\n"
            f"需求判斷：{state['scope'].model_dump_json()}\n"
            f"候選：{json.dumps([item.model_dump() for item in state['metadata']], ensure_ascii=False)}"
        ),
    )
    known_ids = {item.sampleId for item in state["metadata"]}
    proposed = choice.sampleIds or ([choice.sampleId] if choice.sampleId else [])
    scope = state["scope"]
    limit = min(
        scope.requestedCount + (2 if scope.sourceRequirement == "required" and scope.outputMode != "single" else 0),
        MAX_CASES_PER_DOCUMENT,
    )
    sample_ids = [item for item in dict.fromkeys(proposed) if item in known_ids][:limit]
    if set(proposed) - known_ids:
        logger.warning("open sample agent selected unknown sample_ids=%s", sorted(set(proposed) - known_ids))
    return {
        "sample_id": sample_ids[0] if sample_ids else "",
        "sample_ids": sample_ids, "traces": traces,
        "selection": _empty_selection(
            state["scope"], choice.reason if not sample_ids else state["selection"].reason,
        ),
    }


def _candidate_route(state: OpenSampleState) -> Literal["read", "end"]:
    return "read" if state.get("sample_ids") else "end"


def _read_candidate(state: OpenSampleState) -> OpenSampleState:
    samples: list[tuple[str, DocumentTypeSample]] = []
    usages = list(state["tool_usages"])
    for sample_id in state["sample_ids"]:
        request = {"sample_id": sample_id}
        status: Literal["success", "error"] = "success"
        try:
            response = read_document_sample.invoke(request)
            sample = DocumentTypeSample.model_validate_json(response)
            samples.append((sample_id, sample))
        except Exception as error:
            logger.exception("open sample agent: read_document_sample failed sample_id=%s", sample_id)
            status = "error"
            response = json.dumps({"error": str(error)}, ensure_ascii=False)
        usages.append(ReportToolUsage(
            toolName="read_document_sample", sampleId=sample_id, status=status,
            requestJson=json.dumps(request, ensure_ascii=False), responseJson=response,
        ))
    result: OpenSampleState = {
        "sample": samples[0][1] if samples else None,
        "samples": samples, "tool_usages": usages,
    }
    if not samples:
        result["selection"] = _empty_selection(state["scope"], "候選案例讀取失敗；改依大綱撰寫。")
    return result


def _sample_route(state: OpenSampleState) -> Literal["decide", "end"]:
    return "decide" if state.get("samples") else "end"


def _decide_adoption(state: OpenSampleState) -> OpenSampleState:
    traces = list(state["traces"])
    samples = state["samples"]
    decision = _invoke_report_structured(
        model=state["model"], schema=AdoptionChoice,
        operation="general_document.decide_open_sample_use", traces=traces,
        prompt=(
            "你是文件案例採用 Agent。已讀取完整 JSON，決定其用途。"
            "逐份判斷：adoptedSampleIds 列出能作為文件具體選項或比較對象的案例；"
            "referenceSampleIds 列出只能提供部分內容或方法的案例；"
            "兩者不可重複，只能使用已讀取的 ID。"
            "mode=adopt 表示至少一份可作為明示選項；mode=reference 表示僅有參考；"
            "mode=none 表示沒有實質可用內容。mode=adopt 時必須明列採用的案例 ID；"
            "mode=reference 時 adoptedSampleIds 必須留空，不要只填 mode。"
            "single 最多採用一份；multiple 應提供不同的選項；compare 應對應不同"
            "比較對象，不能把一份案例重複當成多份。"
            "outputCoverage 每筆表示一個有資料支撐的輸出項目："
            "outputIndex 從 1 開始、label 是選項或比較對象名稱、sampleId 必須在"
            "adoptedSampleIds 中。只列案例 JSON 有實質資料支援的項目。"
            "若 compare 有 comparisonSubjects，對應項目的 label 必須使用需求中"
            "指定對象的原字串；不同項目不能使用相同 label。"
            "同一案例只有明確涵蓋多個不同項目時，才可在 outputCoverage 中出現多次。"
            "adoptedSampleIds 最多列 requestedCount 份，其他可用案例列為 reference。"
            "案例須符合使用者固定條件，否則只能列為 reference 或捨棄。"
            "即使可用案例少於要求數量，也不要捏造其他案例。"
            "案例是測試／參考資料，不可把未核實的真實世界資訊當成已查證事實。"
            "對於開放型旅遊，可採用案例所描述的示例行程；"
            "若地點為虛構地名，必須作為示例，不得冒充真實旅遊目的地。\n"
            f"需求判斷：{state['scope'].model_dump_json()}\n"
            f"案例：{json.dumps([{'sampleId': sample_id, **sample.model_dump()} for sample_id, sample in samples], ensure_ascii=False)}"
        ),
    )
    known_ids = {sample_id for sample_id, _ in samples}
    adopted = [item for item in dict.fromkeys(decision.adoptedSampleIds) if item in known_ids]
    references = [
        item for item in dict.fromkeys(decision.referenceSampleIds)
        if item in known_ids and item not in adopted
    ]
    if decision.mode == "none":
        adopted, references = [], []
    elif decision.mode == "reference":
        references = list(dict.fromkeys([*references, *adopted]))
        adopted = []
    requested_subjects = {
        subject.strip().casefold(): subject
        for subject in state["scope"].comparisonSubjects
    }
    if state["scope"].outputMode != "single":
        mapped_ids = [
            item.sampleId for item in sorted(
                decision.outputCoverage, key=lambda entry: entry.outputIndex
            )
            if item.sampleId in adopted
            and item.outputIndex <= state["scope"].requestedCount
        ]
        adopted = list(dict.fromkeys([*mapped_ids, *adopted]))
    adoption_limit = min(state["scope"].requestedCount, MAX_CASES_PER_DOCUMENT)
    references = list(dict.fromkeys([*references, *adopted[adoption_limit:]]))
    adopted = adopted[:adoption_limit]
    coverage: list[ReportOutputCoverage] = []
    covered_indices: set[int] = set()
    covered_labels: set[str] = set()
    if state["scope"].outputMode != "single":
        for item in decision.outputCoverage:
            label = item.label.strip()
            if state["scope"].outputMode == "compare":
                direct_match = requested_subjects.get(label.casefold())
                if direct_match:
                    label = direct_match
                else:
                    compatible = [
                        subject for key, subject in requested_subjects.items()
                        if key in label.casefold() or label.casefold() in key
                    ]
                    if len(compatible) == 1:
                        label = compatible[0]
                if requested_subjects and label.casefold() not in requested_subjects:
                    continue
            label_key = label.casefold()
            if (
                item.sampleId in adopted
                and item.outputIndex <= state["scope"].requestedCount
                and item.outputIndex not in covered_indices
                and label_key not in covered_labels
            ):
                coverage.append(ReportOutputCoverage(
                    outputIndex=item.outputIndex, label=label, sampleId=item.sampleId,
                ))
                covered_indices.add(item.outputIndex)
                covered_labels.add(label_key)
    coverage_required = (
        state["scope"].outputMode != "single"
        and state["scope"].sourceRequirement == "required"
        and state["scope"].requiredSource in ("case", "any")
        and not state["scope"].sourceProvided
    )
    coverage_reason = ""
    if coverage and coverage_required:
        review = _invoke_report_structured(
            model=state["model"], schema=CoverageReview,
            operation="general_document.review_required_case_coverage",
            traces=traces,
            prompt=(
                "你是必要案例資料的覆蓋核對器。逐項檢查 outputCoverage 的 label"
                "是否真的受到其 sampleId 對應的完整 JSON 內容實質支援。"
                "允許語意相近和同一案例支援多個不同項目，但該案例必須分別提供"
                "各項目的具體內容；只有文件種類相同、僅有一般方法或憑空命名選項不算支援。"
                "案例有清楚對應的實質內容時應通過，不要求文字逐字相同，"
                "也不要求案例獨自涵蓋整份文件的所有章節。"
                "不能把不符合使用者固定條件的案例當成該項目的資料。"
                "supportedOutputIndexes 只列能確認有支援的 outputIndex，不重複；"
                "reason 簡述未通過者的原因或全部通過。不得推測 JSON 未列出的事實。\n"
                f"需求：{state['scope'].model_dump_json()}\n"
                f"覆蓋宣告：{json.dumps([item.model_dump() for item in coverage], ensure_ascii=False)}\n"
                f"完整案例：{json.dumps([{'sampleId': sample_id, **sample.model_dump()} for sample_id, sample in samples], ensure_ascii=False)}"
            ),
        )
        supported = set(review.supportedOutputIndexes)
        coverage = [item for item in coverage if item.outputIndex in supported]
        coverage_reason = review.reason
    if state["scope"].outputMode != "single":
        covered_ids = {item.sampleId for item in coverage}
        references = list(dict.fromkeys([
            *references, *(item for item in adopted if item not in covered_ids),
        ]))
        adopted = [item for item in adopted if item in covered_ids]
    adoption_unmapped = decision.mode == "adopt" and not adopted
    single_review_reason = ""
    scope = state["scope"]
    sample_by_id = dict(samples)
    needs_single_review = (
        scope.outputMode == "single"
        and scope.sourceRequirement == "required"
        and (
            scope.requiredSource == "case"
            or (scope.requiredSource == "any" and not scope.sourceProvided)
        )
    )
    if adopted and needs_single_review:
        sample_id = adopted[0]
        review = _invoke_report_structured(
            model=state["model"], schema=SingleCaseReview,
            operation="general_document.review_required_single_case",
            traces=traces,
            prompt=(
                "你是單一文件必要案例來源的獨立複核器。請根據完整案例 JSON、"
                "使用者最新需求與固定條件，判斷這份案例是否真的可以作為文件的"
                "具體主題或對象。canAdopt=true 表示案例有足夠的實質內容支援"
                "使用者指定的核心主題，或開放需求可合理選定的具體方案；"
                "不要求它涵蓋整份文件所有章節，也不要求文字逐字一致。"
                "明確指定的菜色、地點、公司、期間或其他不可替換條件若與案例"
                "衝突，且案例只能提供方法或結構，canAdopt=false。"
                "案例額外的地點、人數、預算與偏好，若使用者沒有明確限制，"
                "不視為衝突。canReference=true 表示即使無法採用為具體方案，"
                "仍能支援重要章節或提供可借鑑的方法。"
                "只有文件種類相同而沒有實質相關內容時兩者都應為 false。"
                "不得推測 JSON 未列出的事實，也不得把測試案例說成已查證資料。"
                "reason 簡述案例可支援的內容、固定條件的符合或衝突情況。\n"
                f"需求：{scope.model_dump_json()}\n"
                f"對話：{json.dumps([item.model_dump() for item in state['request'].messages], ensure_ascii=False)}\n"
                f"待採用案例：{json.dumps({'sampleId': sample_id, **sample_by_id[sample_id].model_dump()}, ensure_ascii=False)}"
            ),
        )
        single_review_reason = review.reason
        if not review.canAdopt:
            adopted = []
            if review.canReference:
                references = list(dict.fromkeys([*references, sample_id]))
    coverage.sort(key=lambda item: item.outputIndex)
    selected_ids = [sample_id for sample_id, _ in samples if sample_id in {*adopted, *references}]
    subjects = [sample_by_id[item].subject for item in adopted]
    mode: Literal["adopt", "reference", "none"] = (
        "adopt" if adopted else "reference" if selected_ids else "none"
    )
    selection = ReportSampleSelection(
        mode=mode,
        route=state["scope"].route,
        outputMode=state["scope"].outputMode,
        requestedCount=state["scope"].requestedCount,
        comparisonSubjects=state["scope"].comparisonSubjects,
        outputCoverage=coverage,
        sourceRequirement=state["scope"].sourceRequirement,
        requiredSource=state["scope"].requiredSource,
        sourceProvided=state["scope"].sourceProvided,
        sourceReason=state["scope"].sourceReason,
        sampleId=adopted[0] if adopted else selected_ids[0] if selected_ids else None,
        sampleIds=selected_ids,
        adoptedSampleIds=adopted,
        chosenSubject="、".join(subjects)[:150],
        chosenSubjects=subjects,
        reason="；".join([
            decision.reason,
            *([f"覆蓋核對：{coverage_reason}"] if coverage_reason else []),
            *([f"必要單例複核：{single_review_reason}"] if single_review_reason else []),
            *(["未提供有效的採用案例 ID 或輸出項目對應，未自動採用已讀案例。"]
              if adoption_unmapped else []),
        ]),
    )
    return {"selection": selection, "traces": traces}


_builder = StateGraph(OpenSampleState)
_builder.add_node("classify_sample_route", _classify_scope)
_builder.add_node("reuse_sample", _reuse_selection)
_builder.add_node("list_document_samples", _list_metadata)
_builder.add_node("choose_candidate", _choose_candidate)
_builder.add_node("read_document_sample", _read_candidate)
_builder.add_node("decide_sample_use", _decide_adoption)
_builder.add_edge(START, "classify_sample_route")
_builder.add_conditional_edges("classify_sample_route", _scope_route, {
    "list": "list_document_samples", "reuse": "reuse_sample", "end": END,
})
_builder.add_conditional_edges("list_document_samples", _metadata_route, {
    "choose": "choose_candidate", "end": END,
})
_builder.add_conditional_edges("choose_candidate", _candidate_route, {
    "read": "read_document_sample", "end": END,
})
_builder.add_conditional_edges("read_document_sample", _sample_route, {
    "decide": "decide_sample_use", "end": END,
})
_builder.add_conditional_edges("reuse_sample", _reuse_route, {
    "list": "list_document_samples", "end": END,
})
_builder.add_edge("decide_sample_use", END)
OPEN_SAMPLE_AGENT_GRAPH = _builder.compile()


def choose_open_sample(
    *, request: ReportOutlineRequest, purposes: list[DocumentPurpose],
    model: Any, traces: list[ReportLLMTrace],
    fallback_document_type_id: str | None = None,
    allow_tools: bool = True,
) -> tuple[ReportSampleSelection, list[ReportLLMTrace], list[ReportToolUsage]]:
    """選定開放需求的具體案例；找不到時保留一般大綱路線。"""
    result = OPEN_SAMPLE_AGENT_GRAPH.invoke({
        "request": request, "purposes": purposes, "model": model,
        "fallback_document_type_id": fallback_document_type_id,
        "allow_tools": allow_tools,
        "traces": traces, "tool_usages": [],
        "selection": ReportSampleSelection(),
    })
    return result["selection"], result["traces"], result["tool_usages"]
