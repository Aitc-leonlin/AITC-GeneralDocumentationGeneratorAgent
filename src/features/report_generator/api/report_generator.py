import logging
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from src.features.membership.core.auth_middleware import require_any_permission, require_permission
from src.features.report_generator.services.domain_report_service import (
    DOCX_MIME_TYPE,
)
from src.features.report_generator.services.report_chat_service import (
    ContentTypeTemplate,
    DocumentSectionPlan,
    DocumentTypeSample,
    DocumentTypeTemplate,
    GeneralExecutionResult,
    GeneralReplanRequest,
    GeneralReplanResponse,
    InvalidReportRequest,
    ReportOutlineRequest,
    ReportOutlineResponse,
    ReportQuickStart,
    SectionTypeTemplate,
    create_report_outline,
    execute_general_plan,
    get_document_section_plan,
    load_content_type_templates,
    load_document_type_templates,
    load_document_type_samples,
    load_report_quick_starts,
    load_section_type_templates,
    plan_general_document,
)
from src.features.report_generator.services.report_chat.current_draft import export_current_draft
from src.features.report_generator.services.report_thread_service import (
    GeneralThreadExecuteCommand,
    ReportThreadFinalizeCommand,
    ReportThreadConflict,
    ReportThreadMessageCommand,
    ReportThreadState,
    add_report_thread_message,
    delete_report_thread,
    get_report_thread,
    list_report_threads,
)


report_generator_router = APIRouter(
    tags=["report-generator"],
)
logger = logging.getLogger(__name__)


@report_generator_router.get("/api/report-generator/threads")
def get_report_threads(user: dict = Depends(require_permission("report-generator.create"))):
    return list_report_threads(user["id"])


@report_generator_router.get("/api/report-generator/threads/{thread_id}")
def get_report_thread_item(
    thread_id: str, user: dict = Depends(require_permission("report-generator.create"))
):
    thread = get_report_thread(thread_id, user["id"])
    if thread is None:
        raise HTTPException(status_code=404, detail="報告對話不存在")
    return thread


@report_generator_router.post("/api/report-generator/threads/{thread_id}/messages")
def post_report_thread_message(
    thread_id: str,
    command: ReportThreadMessageCommand,
    user: dict = Depends(require_permission("report-generator.create")),
):
    try:
        return add_report_thread_message(thread_id, user["id"], command)
    except PermissionError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ReportThreadConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except InvalidReportRequest as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        logger.exception("report thread message failed")
        raise HTTPException(status_code=502, detail="報告大綱整理失敗，請重試") from error


@report_generator_router.delete("/api/report-generator/threads/{thread_id}")
def remove_report_thread(
    thread_id: str, user: dict = Depends(require_permission("report-generator.create"))
):
    if not delete_report_thread(thread_id, user["id"]):
        raise HTTPException(status_code=404, detail="報告對話不存在")
    return {"deleted": True}


@report_generator_router.post("/api/report-generator/threads/{thread_id}/generate")
def generate_report_thread_document(
    thread_id: str,
    command: ReportThreadFinalizeCommand,
    user: dict = Depends(require_permission("report-generator.create")),
):
    try:
        thread = get_report_thread(thread_id, user["id"])
        if thread is None:
            raise HTTPException(status_code=404, detail="報告對話不存在")
        state = ReportThreadState.model_validate(thread)
        report_bytes, filename = export_current_draft(
            document_type_id=state.documentTypeId,
            plan=state.generalPlan,
            outline=state.generalOutline,
            purpose_plan=state.purposePlan,
            purpose_outline=state.purposeOutline,
            messages=state.messages,
            use_sample_data=state.sourceMode != "user_data",
        )
    except (InvalidReportRequest, ValueError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("report thread generation failed")
        raise HTTPException(status_code=502, detail="報告產生失敗，請確認服務設定後重試") from error
    return Response(
        content=report_bytes,
        media_type=DOCX_MIME_TYPE,
        headers={"Content-Disposition": content_disposition(filename)},
    )


@report_generator_router.post(
    "/api/report-generator/threads/{thread_id}/execute-general",
    response_model=GeneralExecutionResult,
)
def execute_report_thread_plan(
    thread_id: str,
    command: GeneralThreadExecuteCommand,
    user: dict = Depends(require_permission("report-generator.create")),
):
    thread = get_report_thread(thread_id, user["id"])
    if thread is None:
        raise HTTPException(status_code=404, detail="報告對話不存在")
    state = ReportThreadState.model_validate(thread)
    if state.generalPlan is None and state.purposePlan is None:
        raise HTTPException(status_code=422, detail="請先完成通用文件規劃")
    try:
        return execute_general_plan(
            state.purposePlan or state.generalPlan,
            state.messages[-30:],
            user_id=user["id"],
            chat_id=command.chatId,
            use_sample_data=command.useSampleData,
            section_id=command.sectionId,
            content_type_id=command.contentTypeId,
            capability=command.capability,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        logger.exception("general document execution failed")
        raise HTTPException(status_code=502, detail="通用文件工具執行失敗") from error


def content_disposition(filename: str) -> str:
    encoded_filename = quote(filename)
    return f"attachment; filename=\"report.docx\"; filename*=UTF-8''{encoded_filename}"


@report_generator_router.post(
    "/api/report-generator/draft",
    response_model=ReportOutlineResponse,
    dependencies=[Depends(require_permission("report-generator.create"))],
)
def draft_report(request: ReportOutlineRequest, response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return create_report_outline(request)
    except InvalidReportRequest as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        logger.exception("report outline generation failed")
        raise HTTPException(status_code=502, detail="報告大綱整理失敗，請確認 AI 服務設定後重試") from error


@report_generator_router.post(
    "/api/report-generator/general-documents/replan",
    response_model=GeneralReplanResponse,
    dependencies=[Depends(require_permission("report-generator.create"))],
)
def replan_general_document(request: GeneralReplanRequest):
    from src.features.chatbot.core.providers.chat_openAI_provider import chat_model

    try:
        plan, outline, traces = plan_general_document(
            document_type_id=request.documentTypeId,
            messages=request.messages,
            model=chat_model,
            traces=[],
            start_at=request.startAt,
            current_plan=request.currentPlan,
            current_outline=request.currentOutline,
        )
        return GeneralReplanResponse(plan=plan, outline=outline, llmTraces=traces)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        logger.exception("general document replanning failed")
        raise HTTPException(status_code=502, detail="通用文件規劃失敗") from error


@report_generator_router.get(
    "/api/report-generator/section-types",
    response_model=list[SectionTypeTemplate],
    dependencies=[Depends(require_permission("report-generator.create"))],
)
def get_section_types(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return list(load_section_type_templates().values())


@report_generator_router.get(
    "/api/report-generator/content-types",
    response_model=list[ContentTypeTemplate],
    dependencies=[Depends(require_permission("report-generator.create"))],
)
def get_content_types(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return list(load_content_type_templates().values())


@report_generator_router.get(
    "/api/report-generator/document-types",
    response_model=list[DocumentTypeTemplate],
    dependencies=[Depends(require_permission("report-generator.create"))],
)
def get_document_types(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return list(load_document_type_templates().values())


@report_generator_router.get(
    "/api/report-generator/document-types/{document_type_id}/sections",
    response_model=DocumentSectionPlan,
    dependencies=[Depends(require_permission("report-generator.create"))],
)
def get_document_type_sections(document_type_id: str, response: Response):
    response.headers["Cache-Control"] = "no-store"
    plan = get_document_section_plan(document_type_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="文件種類不存在")
    return plan


@report_generator_router.get(
    "/api/report-generator/document-types/{document_type_id}/sample",
    response_model=DocumentTypeSample,
    dependencies=[Depends(require_permission("report-generator.create"))],
)
def get_document_type_sample(document_type_id: str, response: Response):
    response.headers["Cache-Control"] = "no-store"
    sample = load_document_type_samples().get(document_type_id)
    if sample is None:
        raise HTTPException(status_code=404, detail="文件測試案例不存在")
    return sample


@report_generator_router.get(
    "/api/report-generator/quick-starts",
    response_model=list[ReportQuickStart],
    dependencies=[Depends(require_permission("report-generator.create"))],
)
def get_report_quick_starts(response: Response):
    response.headers["Cache-Control"] = "no-store"
    try:
        return load_report_quick_starts()
    except Exception as error:
        logger.exception("report quick starts failed to load")
        raise HTTPException(status_code=500, detail="預設報告資料載入失敗") from error


# 舊版財務徵審產生流程暫停使用；歷史資料查詢 API 留供既有報告檢視。
# generate_and_store_credit_report() 保留在 report_generator_service.py 作為舊版參考。


@report_generator_router.get(
    "/api/report-generator/history",
    dependencies=[Depends(require_permission("report-generator.history"))],
)
async def get_report_history(
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=10, ge=1, le=100),
    offset: int | None = Query(default=None, ge=0),
    keyword: str = Query(default=""),
    status: str = Query(default=""),
):
    from src.features.report_generator.services.report_generator_service import list_report_history

    return list_report_history(
        page=page,
        page_size=pageSize,
        offset=offset,
        keyword=keyword,
        status=status,
    )


@report_generator_router.get(
    "/api/report-generator/history/{history_id}/dashboard",
    dependencies=[
        Depends(
            require_any_permission(
                ["report-generator.create", "report-generator.history"]
            )
        )
    ],
)
async def get_report_dashboard_item(history_id: int):
    from src.features.report_generator.services.report_generator_service import get_report_dashboard

    dashboard = get_report_dashboard(history_id)
    if not dashboard:
        raise HTTPException(status_code=404, detail="歷史報告儀表板資料不存在")
    return {"dashboard": dashboard}


# TODO: 歷史報告下載功能尚未完成。
# 雲端部署目前不保存 DOCX 實體檔案，因此先停用下載 API；待串接物件儲存後再恢復。
# @report_generator_router.get(
#     "/api/report-generator/history/{public_id}/download",
#     dependencies=[Depends(require_permission("report-generator.history"))],
# )
# async def download_report(public_id: str):
#     try:
#         file_path, filename = get_report_download_path(public_id)
#     except FileNotFoundError as error:
#         raise HTTPException(status_code=404, detail=str(error)) from error
#
#     return FileResponse(
#         path=file_path,
#         media_type=DOCX_MIME_TYPE,
#         headers={"Content-Disposition": content_disposition(filename)},
#     )
