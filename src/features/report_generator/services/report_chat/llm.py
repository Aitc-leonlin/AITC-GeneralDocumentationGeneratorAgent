"""結構化 LLM 呼叫與請求、回應紀錄。"""

import json
from typing import TypeVar

from pydantic import BaseModel

from src.features.report_generator.services.domain_report_service import (
    ReportLLMTrace, _raw_llm_response,
)

StructuredT = TypeVar("StructuredT", bound=BaseModel)


def _json_text(value) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json", exclude_none=True)
    return json.dumps(value, ensure_ascii=False, indent=2, default=str)


def _invoke_report_structured(
    *,
    model,
    schema: type[StructuredT],
    prompt: str,
    operation: str,
    traces: list[ReportLLMTrace],
) -> StructuredT:
    """記錄實際 Prompt、JSON Schema 與 LangChain 回傳的原始 AIMessage。"""
    structured_model = model.with_structured_output(schema, include_raw=True)
    schema_json = schema.model_json_schema()
    retry_prompt = (
        prompt + "\n\n前次輸出未通過結構驗證，請依下列 JSON Schema 重新輸出：\n"
        + _json_text(schema_json)
    )
    last_error: Exception | None = None
    for attempt, current_prompt in enumerate((prompt, retry_prompt), start=1):
        request_json = _json_text({
            "captureLevel": "LangChain invoke input; provider HTTP body may add parameters",
            "operation": operation,
            "attempt": attempt,
            "model": getattr(model, "model_name", None),
            "method": "with_structured_output",
            "messages": [{"role": "user", "content": current_prompt}],
            "response_schema": schema_json,
        })
        recorded = False
        try:
            result = structured_model.invoke(current_prompt)
            if not isinstance(result, dict) or "raw" not in result:
                raise RuntimeError("LLM 未回傳可記錄的原始訊息")
            raw = result["raw"]
            parsed = result.get("parsed")
            parsing_error = result.get("parsing_error")
            response_json = _json_text({
                "captureLevel": "LangChain raw AIMessage and structured parser output",
                "raw": _raw_llm_response(raw),
                "parsed": parsed.model_dump(mode="json") if isinstance(parsed, BaseModel) else parsed,
                "parsing_error": str(parsing_error) if parsing_error else None,
            })
            traces.append(ReportLLMTrace(
                stage=f"{operation}（第 {attempt} 次）",
                requestJson=request_json,
                responseJson=response_json,
            ))
            recorded = True
            if parsing_error:
                raise RuntimeError(str(parsing_error))
            return parsed if isinstance(parsed, schema) else schema.model_validate(parsed)
        except Exception as error:
            last_error = error
            if not recorded:
                traces.append(ReportLLMTrace(
                    stage=f"{operation}（第 {attempt} 次）",
                    requestJson=request_json,
                    responseJson=_json_text({"error": str(error), "raw": None}),
                ))
    raise last_error or RuntimeError(f"{operation} 未取得有效回應")
