"""結構化 LLM 呼叫與請求、回應紀錄。"""

import json
import logging
from typing import TypeVar

from pydantic import BaseModel

from src.features.report_generator.services.domain_report_service import (
    ReportLLMTrace, _raw_llm_response,
)

StructuredT = TypeVar("StructuredT", bound=BaseModel)
logger = logging.getLogger("uvicorn.error")


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
    """串流接收 LLM 回覆並保留 trace；不輸出逐 chunk 的串流日誌。"""
    # with_structured_output(..., include_raw=True) 的解析包裝層會先收完串流，
    # 才交出 raw 訊息；直接串流綁定相同的 response_format 才能即時看到內容。
    streaming_model = model.bind(response_format=schema)
    schema_json = schema.model_json_schema()
    retry_prompt = (
        prompt + "\n\n前次輸出未通過結構驗證，請依下列 JSON Schema 重新輸出：\n"
        + _json_text(schema_json)
    )
    last_error: Exception | None = None
    for attempt, current_prompt in enumerate((prompt, retry_prompt), start=1):
        request_json = _json_text({
            "captureLevel": "LangChain stream input; provider HTTP body may add parameters",
            "operation": operation,
            "attempt": attempt,
            "model": getattr(model, "model_name", None),
            "method": "bind(response_format=schema).stream",
            "stream": True,
            "messages": [{"role": "user", "content": current_prompt}],
            "response_schema": schema_json,
        })
        recorded = False
        raw = None
        parsed = None
        try:
            for raw_chunk in streaming_model.stream(current_prompt):
                raw = raw_chunk if raw is None else raw + raw_chunk
                chunk_parsed = (getattr(raw_chunk, "additional_kwargs", None) or {}).get("parsed")
                if chunk_parsed is not None:
                    parsed = chunk_parsed
            if raw is None:
                raise RuntimeError("LLM 串流結束，但未回傳原始訊息")
            if parsed is None:
                parsed = (getattr(raw, "additional_kwargs", None) or {}).get("parsed")
            if parsed is None:
                parsed = schema.model_validate_json(raw.text)
            validated = parsed if isinstance(parsed, schema) else schema.model_validate(parsed)
            response_json = _json_text({
                "captureLevel": "LangChain merged streamed AIMessage and structured parser output",
                "raw": _raw_llm_response(raw),
                "parsed": validated.model_dump(mode="json"),
                "parsing_error": None,
            })
            traces.append(ReportLLMTrace(
                stage=f"{operation}（第 {attempt} 次）",
                requestJson=request_json,
                responseJson=response_json,
            ))
            recorded = True
            return validated
        except Exception as error:
            last_error = error
            logger.warning(
                "report_llm.error operation=%s attempt=%d error=%s",
                operation, attempt, error,
                exc_info=True,
            )
            if not recorded:
                traces.append(ReportLLMTrace(
                    stage=f"{operation}（第 {attempt} 次）",
                    requestJson=request_json,
                    responseJson=_json_text({
                        "error": str(error),
                        "raw": _raw_llm_response(raw) if raw is not None else None,
                    }),
                ))
    raise last_error or RuntimeError(f"{operation} 未取得有效回應")
