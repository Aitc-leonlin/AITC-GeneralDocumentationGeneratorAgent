"""結構化 LLM 呼叫與請求、回應紀錄。"""

import json
import logging
from time import monotonic
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
    """串流接收 LLM 回覆，並記錄 Prompt、原始訊息與接收進度。"""
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
        chunk_count = 0
        content_chars = 0
        tool_chars = 0
        saw_content = False
        pending_content: list[str] = []
        pending_tool_content: list[str] = []
        pending_chars = 0
        started_at = monotonic()
        last_log_at = started_at
        last_output_log_at = started_at
        logger.info(
            "report_llm_stream.start operation=%s attempt=%d model=%s",
            operation, attempt, getattr(model, "model_name", None),
        )
        try:
            for raw_chunk in streaming_model.stream(current_prompt):
                raw = raw_chunk if raw is None else raw + raw_chunk
                chunk_parsed = (getattr(raw_chunk, "additional_kwargs", None) or {}).get("parsed")
                if chunk_parsed is not None:
                    parsed = chunk_parsed
                chunk_count += 1
                chunk_text = raw_chunk.text
                content_chars += len(chunk_text)
                tool_text = "".join(
                    str(item.get("args") or "")
                    for item in (getattr(raw_chunk, "tool_call_chunks", None) or [])
                )
                tool_chars += len(tool_text)
                if chunk_text:
                    pending_content.append(chunk_text)
                if tool_text:
                    pending_tool_content.append(tool_text)
                pending_chars += len(chunk_text) + len(tool_text)
                now = monotonic()
                first_content = not saw_content and bool(chunk_text or tool_text)
                saw_content = saw_content or first_content
                if chunk_count == 1 or first_content or now - last_log_at >= 10:
                    logger.info(
                        "report_llm_stream.receiving operation=%s attempt=%d "
                        "elapsed_s=%.1f chunks=%d content_chars=%d tool_chars=%d",
                        operation, attempt, now - started_at,
                        chunk_count, content_chars, tool_chars,
                    )
                    last_log_at = now
                if pending_chars and (
                    first_content or pending_chars >= 2000 or now - last_output_log_at >= 5
                ):
                    if pending_content:
                        logger.info(
                            "report_llm_stream.output operation=%s attempt=%d\n%s",
                            operation, attempt, "".join(pending_content),
                        )
                    if pending_tool_content:
                        logger.info(
                            "report_llm_stream.tool_output operation=%s attempt=%d\n%s",
                            operation, attempt, "".join(pending_tool_content),
                        )
                    pending_content.clear()
                    pending_tool_content.clear()
                    pending_chars = 0
                    last_output_log_at = now
            if pending_content:
                logger.info(
                    "report_llm_stream.output operation=%s attempt=%d\n%s",
                    operation, attempt, "".join(pending_content),
                )
            if pending_tool_content:
                logger.info(
                    "report_llm_stream.tool_output operation=%s attempt=%d\n%s",
                    operation, attempt, "".join(pending_tool_content),
                )
            if raw is None:
                raise RuntimeError("LLM 串流結束，但未回傳原始訊息")
            if parsed is None:
                parsed = (getattr(raw, "additional_kwargs", None) or {}).get("parsed")
            if parsed is None:
                parsed = schema.model_validate_json(raw.text)
            validated = parsed if isinstance(parsed, schema) else schema.model_validate(parsed)
            logger.info(
                "report_llm_stream.parsed operation=%s attempt=%d\n%s",
                operation, attempt, _json_text(validated),
            )
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
            logger.info(
                "report_llm_stream.done operation=%s attempt=%d elapsed_s=%.1f "
                "chunks=%d content_chars=%d tool_chars=%d finish_reason=%s output_tokens=%s",
                operation, attempt, monotonic() - started_at,
                chunk_count, content_chars, tool_chars,
                (getattr(raw, "response_metadata", None) or {}).get("finish_reason"),
                (getattr(raw, "usage_metadata", None) or {}).get("output_tokens"),
            )
            return validated
        except Exception as error:
            last_error = error
            logger.warning(
                "report_llm_stream.error operation=%s attempt=%d elapsed_s=%.1f "
                "chunks=%d content_chars=%d tool_chars=%d error=%s",
                operation, attempt, monotonic() - started_at,
                chunk_count, content_chars, tool_chars, error,
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
