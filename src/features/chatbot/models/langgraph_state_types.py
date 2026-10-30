from sqlalchemy import Boolean
from typing_extensions import TypedDict, NotRequired
from typing import Any
from langgraph.graph import MessagesState


class AppliedExpertKnowledgeItem(TypedDict):
    title: str
    dataSource: str
    industry: str
    companyLabel: str
    anchorDescription: str
    systemPrompt: str
    createdAt: str
    updatedAt: str


class AppliedWarehouseDataItem(TypedDict):
    category: str
    title: str
    industry: str
    companyLabel: str
    companyPromptValue: str
    source: str
    url: str
    summary: str
    recordUpdatedAt: str
    createdAt: str
    updatedAt: str


class OverallState(TypedDict):
    messages: MessagesState
    is_question_in_range: str
    original_question: NotRequired[str]
    user_input: str
    user_id: NotRequired[str]
    use_expert_knowledge: NotRequired[bool]
    use_warehouse_data: NotRequired[bool]
    use_external_data: NotRequired[bool]
    request_source: NotRequired[str]
    conversation_id: NotRequired[str]
    needs_external_data: NotRequired[bool]
    awaiting_external_data_confirmation: NotRequired[bool]
    external_data_query_text: NotRequired[str]
    external_data_decision: NotRequired[str]
    external_data_result: NotRequired[dict[str, Any]]
    external_data_response: NotRequired[str]
    external_data_response_prompt: NotRequired[str]
    applied_expert_knowledge: NotRequired[list[AppliedExpertKnowledgeItem]]
    applied_warehouse_data: NotRequired[list[AppliedWarehouseDataItem]]
    semantic_plan: NotRequired[dict[str, Any]]
    semantic_plan_error: NotRequired[str]
    needs_expert_knowledge: NotRequired[bool]
    selected_applied_expert_knowledge: NotRequired[list[AppliedExpertKnowledgeItem]]
    expert_knowledge_selection_result: NotRequired[dict[str, Any]]
    needs_warehouse_data: NotRequired[bool]
    selected_applied_warehouse_data: NotRequired[list[AppliedWarehouseDataItem]]
    warehouse_data_selection_result: NotRequired[dict[str, Any]]
    rephrased_question: str
    semantic_workflow_category: NotRequired[str]
    semantic_workflow_category_confidence: NotRequired[float]
    semantic_workflow_category_reason: NotRequired[str]
    semantic_workflow_category_result: NotRequired[dict[str, Any]]
    semantic_workflow_guidance: NotRequired[dict[str, list[str]]]
    semantic_workflow_node: NotRequired[str]
    semantic_workflow_status: NotRequired[str]
    semantic_workflow_template: NotRequired[dict[str, Any]]
    deep_agent_result: NotRequired[dict[str, Any]]
    statement_type: str
    statement_types: list[str]
    statement_type_result: dict[str, Any]
    reference_data: any
    answer: str
    final_answer: NotRequired[str]
    post_analysis_answer: NotRequired[str]
    rag_context: NotRequired[str]
    retrieval_results: NotRequired[list[dict[str, Any]]]
