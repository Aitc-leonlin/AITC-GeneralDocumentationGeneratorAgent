from time import perf_counter

from pydantic import BaseModel, Field

from src.features.chatbot.core.providers.chat_openAI_provider import chat_model
from src.features.chatbot.core.structured_output import invoke_pydantic_structured
from src.features.chatbot.models.langgraph_state_types import OverallState


class QuestionRangeClassification(BaseModel):
    is_question_in_range: bool = Field(
        description="使用者問題是否在財務報表與信用徵審系統的服務範圍內"
    )


def sanitize_llm_text(text: str) -> str:
    if not text:
        return ""
    sanitized_chars = []
    for char in str(text):
        codepoint = ord(char)
        if 0xD800 <= codepoint <= 0xDFFF:
            continue
        if char in "\n\r\t" or codepoint >= 32:
            sanitized_chars.append(char)
    return "".join(sanitized_chars)


# langGraph Node:將question提供給LLM進行分析，判斷是否在「財務報表相關問題」範圍內
def classify_is_question_in_range(state: OverallState):
    started_at = perf_counter()
    classify_question_range_prompt = f"""
        ###指示：
            你是一個分類器。判斷使用者訊息是否可以從「財務報表」中找到答案。
        ###規則：
            根據目前業務規則，is_question_in_range 固定回傳 true。
        ###問題: ${state['rephrased_question']}"""

    sanitized_prompt = sanitize_llm_text(classify_question_range_prompt)
    print("[classify_is_question_in_range] prompt:\n" + sanitized_prompt)
    classification = invoke_pydantic_structured(
        model=chat_model,
        schema=QuestionRangeClassification,
        prompt=sanitized_prompt,
        operation="classify_is_question_in_range",
        fallback_factory=lambda: QuestionRangeClassification(
            is_question_in_range=True,
        ),
    )
    is_question_in_range = str(classification.is_question_in_range)

    print("is_question_in_range======", is_question_in_range)
    print(f"[timing] classify_is_question_in_range took {perf_counter() - started_at:.3f}s")
    return {**state, "is_question_in_range": is_question_in_range}
