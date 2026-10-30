import json
from collections.abc import Callable
from typing import TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel


StructuredOutputT = TypeVar("StructuredOutputT", bound=BaseModel)


def invoke_pydantic_structured(
    *,
    model: BaseChatModel,
    schema: type[StructuredOutputT],
    prompt: str,
    operation: str,
    fallback_factory: Callable[[], StructuredOutputT] | None = None,
    log_io: bool = False,
) -> StructuredOutputT:
    """Invoke an LLM and validate every structured result with Pydantic."""
    structured_model = model.with_structured_output(schema)
    prompts = [prompt, _build_retry_prompt(prompt, schema)]
    last_error: Exception | None = None

    for attempt, current_prompt in enumerate(prompts, start=1):
        if log_io:
            print(
                f"[{operation}] LLM REQUEST attempt {attempt}:\n"
                + json.dumps(
                    {
                        "prompt": current_prompt,
                        "response_schema": schema.model_json_schema(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                flush=True,
            )
        try:
            result = structured_model.invoke(current_prompt)
            if log_io:
                response_payload = (
                    result.model_dump() if isinstance(result, BaseModel) else result
                )
                print(
                    f"[{operation}] LLM RESPONSE attempt {attempt}:\n"
                    + json.dumps(
                        response_payload, ensure_ascii=False, indent=2, default=str
                    ),
                    flush=True,
                )
            if isinstance(result, schema):
                return result
            return schema.model_validate(result)
        except Exception as exc:
            last_error = exc
            print(
                f"[{operation}] Pydantic structured output attempt "
                f"{attempt}/{len(prompts)} failed: {exc}"
            )

    if fallback_factory is not None:
        fallback = fallback_factory()
        print(f"[{operation}] using validated Pydantic fallback: {fallback.model_dump()}")
        if log_io:
            print(
                f"[{operation}] LLM FALLBACK RESPONSE:\n"
                + json.dumps(fallback.model_dump(), ensure_ascii=False, indent=2),
                flush=True,
            )
        return fallback

    if last_error is None:
        raise RuntimeError(f"[{operation}] structured output failed without an exception")
    raise last_error


def _build_retry_prompt(prompt: str, schema: type[BaseModel]) -> str:
    schema_json = json.dumps(
        schema.model_json_schema(),
        ensure_ascii=False,
        indent=2,
    )
    return (
        prompt
        + "\n\n### 結構化輸出修正要求\n"
        + "前一次輸出未通過 Pydantic 驗證。請重新輸出符合下列 JSON Schema 的資料，"
        + "不要加入 schema 以外的說明文字。\n"
        + schema_json
    )
