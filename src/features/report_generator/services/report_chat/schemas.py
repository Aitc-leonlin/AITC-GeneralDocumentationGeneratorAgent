"""報告對話、大綱與產生文件使用的資料結構。"""

from typing import Literal

from pydantic import BaseModel, Field

from src.features.report_generator.services.domain_report_service import ReportLLMTrace


class InvalidReportRequest(ValueError):
    """使用者要求不符合大綱或確認流程。"""


class ReportChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class DocumentTypeTemplate(BaseModel):
    id: str = Field(pattern=r"^D(?:0[1-9]|[12][0-9]|30)$")
    name: str = Field(min_length=1, max_length=100)
    category: str = Field(min_length=1, max_length=100)
    purpose: str = Field(min_length=1, max_length=300)
    requiredSectionIds: list[str] = Field(min_length=1)
    optionalSectionIds: list[str] = Field(default_factory=list)
    suggestedSections: list[str] = Field(default_factory=list)


class ContentTypeTemplate(BaseModel):
    id: str = Field(pattern=r"^C(?:0[1-9]|1[0-9]|20)$")
    name: str = Field(min_length=1, max_length=100)
    nature: Literal["呈現", "分析", "證據", "程序", "建議"]
    description: str = Field(min_length=1, max_length=300)
    requiredCapabilities: list[str] = Field(min_length=1)


class SectionTypeTemplate(BaseModel):
    id: str = Field(pattern=r"^S(?:0[1-9]|1[0-9]|20)$")
    name: str = Field(min_length=1, max_length=100)
    purpose: str = Field(min_length=1, max_length=300)
    suggestedContentTypeIds: list[str] = Field(min_length=1)
    commonDocuments: list[str] = Field(min_length=1)


class DocumentSectionPlan(BaseModel):
    documentTemplate: DocumentTypeTemplate
    requiredSections: list[SectionTypeTemplate]
    optionalSections: list[SectionTypeTemplate]


class PlannedSection(BaseModel):
    sectionId: str = Field(pattern=r"^S(?:0[1-9]|1[0-9]|20)$")
    isRequired: bool
    contentTypeIds: list[str] = Field(default_factory=list)


class GeneralDocumentPlan(BaseModel):
    documentTypeId: str = Field(pattern=r"^D(?:0[1-9]|[12][0-9]|30)$")
    sections: list[PlannedSection] = Field(min_length=1)


class GeneralOutlineContent(BaseModel):
    contentTypeId: str
    name: str
    description: str


class GeneralOutlineSection(BaseModel):
    sectionId: str
    heading: str
    focus: str = Field(min_length=1, max_length=500)
    isRequired: bool
    contents: list[GeneralOutlineContent] = Field(min_length=1)


class GeneralDocumentOutline(BaseModel):
    documentTypeId: str = Field(pattern=r"^D(?:0[1-9]|[12][0-9]|30)$")
    documentTypeName: str
    title: str = Field(min_length=1, max_length=150)
    subject: str = Field(min_length=1, max_length=150)
    period: str = Field(min_length=1, max_length=100)
    objective: str = Field(min_length=1, max_length=800)
    sections: list[GeneralOutlineSection] = Field(min_length=1)
    sourcePlan: str = Field(min_length=1, max_length=1000)


class DocumentPurpose(BaseModel):
    """從使用者需求辨識的用途；D 範本只是可選參考。"""
    purposeId: str = Field(pattern=r"^P[1-9][0-9]*$")
    description: str = Field(min_length=1, max_length=300)
    planningMode: Literal["analysis", "procedure", "proposal", "explanation", "mixed"] = "mixed"
    referenceTemplateIds: list[str] = Field(default_factory=list)


class PurposePlannedSection(BaseModel):
    sectionKey: str = Field(min_length=1, max_length=40)
    heading: str = Field(min_length=1, max_length=100)
    focusHint: str = Field(min_length=1, max_length=500)
    purposeIds: list[str] = Field(min_length=1)
    referenceSectionIds: list[str] = Field(default_factory=list)
    contentTypeIds: list[str] = Field(default_factory=list)


class PurposeDocumentPlan(BaseModel):
    purposes: list[DocumentPurpose] = Field(min_length=1)
    sections: list[PurposePlannedSection] = Field(min_length=1)


class PurposeOutlineSection(PurposePlannedSection):
    focus: str = Field(min_length=1, max_length=500)
    contents: list[GeneralOutlineContent] = Field(default_factory=list)


class PurposeDocumentOutline(BaseModel):
    title: str = Field(min_length=1, max_length=150)
    subject: str = Field(min_length=1, max_length=150)
    period: str = Field(min_length=1, max_length=100)
    objective: str = Field(min_length=1, max_length=800)
    purposes: list[DocumentPurpose] = Field(min_length=1)
    sections: list[PurposeOutlineSection] = Field(min_length=1)
    sourcePlan: str = Field(min_length=1, max_length=1000)


class PendingClarification(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    missingDecision: str = Field(min_length=1, max_length=300)
    purposes: list[DocumentPurpose] = Field(default_factory=list)


class GeneralReplanRequest(BaseModel):
    documentTypeId: str = Field(pattern=r"^D(?:0[1-9]|[12][0-9]|30)$")
    messages: list[ReportChatMessage] = Field(min_length=1, max_length=30)
    startAt: Literal["sections", "contents", "outline"]
    currentPlan: GeneralDocumentPlan | None = None
    currentOutline: GeneralDocumentOutline | None = None


class GeneralReplanResponse(BaseModel):
    plan: GeneralDocumentPlan
    outline: GeneralDocumentOutline
    llmTraces: list[ReportLLMTrace] = Field(default_factory=list)


class ReportOutlineRequest(BaseModel):
    messages: list[ReportChatMessage] = Field(min_length=1, max_length=30)
    currentDocumentTypeId: str | None = Field(default=None, pattern=r"^D(?:0[1-9]|[12][0-9]|30)$")
    currentGeneralPlan: GeneralDocumentPlan | None = None
    currentGeneralOutline: GeneralDocumentOutline | None = None
    currentPurposePlan: PurposeDocumentPlan | None = None
    currentPurposeOutline: PurposeDocumentOutline | None = None
    pendingClarification: PendingClarification | None = None
    currentSourceMode: Literal["default_json", "user_data"] | None = None


class ReportOutlineResponse(BaseModel):
    assistantMessage: str = Field(min_length=1, max_length=1000)
    graphNodes: list[str] = Field(default_factory=list)
    documentTemplate: DocumentTypeTemplate | None = None
    generalPlan: GeneralDocumentPlan | None = None
    generalOutline: GeneralDocumentOutline | None = None
    purposePlan: PurposeDocumentPlan | None = None
    purposeOutline: PurposeDocumentOutline | None = None
    pendingClarification: PendingClarification | None = None
    sourceMode: Literal["default_json", "user_data"] | None = None
    llmTraces: list[ReportLLMTrace] = Field(default_factory=list)


class ReportQuestionPlan(BaseModel):
    documentTypeId: str | None = Field(default=None, pattern=r"^D(?:0[1-9]|[12][0-9]|30)$")
    purposes: list[DocumentPurpose] = Field(default_factory=list)
    intent: Literal["create_report", "revise_report", "ask_question", "out_of_scope"]
    sourceMode: Literal["default_json", "user_data", "keep"] = "keep"
    includeAllMetrics: bool = False
    requestedMetrics: list[str] = Field(default_factory=list, max_length=30)
    purpose: str = Field(default="", max_length=300)


class ReportQuickStartDefinition(BaseModel):
    id: str = Field(min_length=1, max_length=50)
    label: str = Field(min_length=1, max_length=100)
    prompt: str = Field(min_length=1, max_length=4000)


class ReportQuickStart(BaseModel):
    id: str
    label: str
    prompt: str


