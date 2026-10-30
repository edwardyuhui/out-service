from typing import Annotated, Any, TypeVar
from uuid import UUID

from algorithms.agent.llm import LlmUnavailableError
from fastapi import APIRouter, Depends, File, Form, Path, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.core.db import database_is_ready, get_session, redis_is_ready
from app.core.errors import AppError
from app.schemas.benchmark import BenchmarkData, BenchmarkRequest
from app.schemas.common import ErrorEnvelope, SuccessEnvelope
from app.schemas.copilot import (
    ArxStructureValidationData,
    ArxStructureValidationRequest,
    CopilotChatData,
    CopilotChatRequest,
    CopilotConfirmData,
    CopilotConfirmRequest,
    CopilotEvaluateModelExecuteData,
    CopilotEvaluateModelExecuteRequest,
    CopilotExecutionSnapshotData,
    CopilotOptimizePipelineExecuteData,
    FeatureSelectionValidationData,
    FeatureSelectionValidationRequest,
    LagOverrideValidationData,
    LagOverrideValidationRequest,
    OptimizePipelineExecuteRequest,
)
from app.schemas.dashboard import DashboardLeaderboardData
from app.schemas.datasets import (
    CollinearitySourceVersionsData,
    DatasetConfigData,
    DatasetConfigRequest,
    DatasetDeleteData,
    DatasetDetail,
    DatasetListData,
    DatasetProfile,
    DatasetUploadData,
    DatasetVersionPreviewData,
    DatasetVersionPreviewPageSize,
    DatasetVersionsData,
    DelaySourceVersionsData,
)
from app.schemas.diagnostics import GeneralizationDiagnosticsData
from app.schemas.modeling import (
    ArxFitData,
    ArxFitRequest,
)
from app.schemas.optimization import (
    OptimizationStartData,
    OptimizationStartRequest,
    OptimizationStatusData,
)
from app.schemas.preprocessing import (
    CleanData,
    CleaningVersionCompareChannelsData,
    CleaningVersionCompareData,
    CleanRequest,
    CollinearityData,
    CollinearityRequest,
    DelayData,
    DelayRequest,
    FeatureSelectionApplyRequest,
    LagCompensationRequest,
    SegmentData,
    SegmentRequest,
    VersionApplyData,
)
from app.schemas.reporting import (
    DeliveryStudyListData,
    ExportDatasetData,
    ExportDatasetRequest,
    ReportData,
    ReportRequest,
)
from app.schemas.simulation import SimulationGenerateData, SimulationGenerateRequest
from app.schemas.system import (
    AgentLlmConfigData,
    AgentLlmConfigUpdate,
    AgentLlmConnectionData,
    LivenessData,
    ReadinessData,
    SystemInfoData,
)
from app.schemas.tasks import CancelTaskData
from app.services.agent_arx_modeling_service import (
    ArxStructureError,
    approve_and_execute_arx_step,
    is_arx_fit_step,
    validate_arx_structure,
)
from app.services.agent_execution_service import (
    ExecutionStateError,
    approve_step,
    get_execution,
    reject_step,
    to_copilot_execution_snapshot,
)
from app.services.agent_feature_selection_service import (
    FeatureSelectionError,
    approve_and_execute_feature_step,
    is_feature_apply_step,
    validate_feature_selection,
)
from app.services.agent_lag_apply_service import (
    LagOverrideError,
    approve_and_execute_lag_step,
    is_lag_apply_step,
    validate_lag_overrides,
)
from app.services.agent_service import (
    AgentDomainError,
    continue_agent_execution,
    execute_approved_export_step,
    execute_approved_optimization_step,
    execute_pending_evaluation_step,
    run_copilot,
)
from app.services.agent_tool_adapter import AgentToolAdapterError
from app.services.benchmark_service import BenchmarkDomainError, run_benchmark
from app.services.cleaning_service import CleaningDomainError, clean_dataset_version
from app.services.cleaning_version_compare_service import (
    CleaningVersionCompareError,
    compare_cleaning_versions,
    get_cleaning_version_compare_channels,
)
from app.services.contract_stubs import completed_task, queued_task
from app.services.dashboard_service import get_dashboard_leaderboard
from app.services.dataset_service import (
    DatasetDomainError,
    configure_dataset_columns,
    delete_dataset_asset,
    get_dataset_detail,
    get_dataset_download,
    get_dataset_version_preview,
    list_dataset_summaries,
    register_simulation_dataset,
    upload_csv_dataset,
)
from app.services.dataset_service import (
    get_dataset_profile as get_dataset_profile_service,
)
from app.services.dataset_service import (
    get_dataset_versions as get_dataset_versions_service,
)
from app.services.generalization_diagnostics_service import get_generalization_diagnostics
from app.services.llm_runtime_config_service import (
    get_agent_llm_config_data,
    reset_agent_llm_config,
    test_agent_llm_connection,
    update_agent_llm_config,
)
from app.services.modeling_service import ModelingDomainError, fit_arx_on_version
from app.services.optimization_service import (
    OptimizationDomainError,
    get_optimization_status,
    start_optimization_study,
)
from app.services.preprocessing_analysis_service import (
    AnalysisDomainError,
    get_collinearity_source_versions,
    get_delay_source_versions,
    get_latest_collinearity_result,
    get_latest_delay_result,
    run_collinearity_analysis,
    run_delay_estimation,
)
from app.services.report_service import (
    ReportDomainError,
    export_optimised_dataset,
    generate_report,
    get_export_artifact,
    list_delivery_studies,
)
from app.services.segment_service import SegmentDomainError, select_dynamic_segments
from app.services.simulation_service import generate_simulation as generate_simulation_service
from app.services.version_data import VersionDataError
from app.services.versioned_preprocessing_service import (
    VersionedPreprocessingError,
    apply_feature_selection,
    apply_lag_compensation,
)

router = APIRouter()
DataT = TypeVar("DataT")
DatasetId = Annotated[UUID, Path(description="数据集 UUID。")]

ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorEnvelope, "description": "请求参数或领域规则无效。"},
    404: {"model": ErrorEnvelope, "description": "目标资源不存在。"},
    422: {"model": ErrorEnvelope, "description": "请求体或路径参数未通过 Pydantic 校验。"},
    500: {"model": ErrorEnvelope, "description": "未预期的服务端错误。"},
}


def success(request: Request, data: DataT) -> SuccessEnvelope[DataT]:
    """Return the only success envelope used by every v1 endpoint."""

    return SuccessEnvelope(data=data, request_id=UUID(request.state.request_id))


@router.get(
    "/health/live",
    tags=["System"],
    summary="Liveness probe",
    response_model=SuccessEnvelope[LivenessData],
    responses=ERROR_RESPONSES,
)
async def health_live(request: Request) -> SuccessEnvelope[LivenessData]:
    return success(request, LivenessData())


@router.get(
    "/health/ready",
    tags=["System"],
    summary="Readiness probe for PostgreSQL and Redis",
    response_model=SuccessEnvelope[ReadinessData],
    responses={
        **ERROR_RESPONSES,
        503: {"model": ErrorEnvelope, "description": "PostgreSQL 或 Redis 尚不可用。"},
    },
)
async def health_ready(request: Request) -> SuccessEnvelope[ReadinessData]:
    database_ready, redis_ready = await database_is_ready(), await redis_is_ready()
    if not database_ready or not redis_ready:
        raise AppError(
            "SYSTEM_NOT_READY",
            "系统依赖尚未就绪",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            details={"database": database_ready, "redis": redis_ready},
        )
    return success(request, ReadinessData())


@router.get(
    "/system/info",
    tags=["System"],
    summary="Get service and contract metadata",
    response_model=SuccessEnvelope[SystemInfoData],
    responses=ERROR_RESPONSES,
)
async def system_info(request: Request) -> SuccessEnvelope[SystemInfoData]:
    settings = get_settings()
    return success(
        request,
        SystemInfoData(version=settings.app_version, environment=settings.app_env),
    )


@router.get(
    "/system/agent-config",
    tags=["System"],
    summary="Get the effective Agent LLM configuration without exposing its API key",
    response_model=SuccessEnvelope[AgentLlmConfigData],
    responses=ERROR_RESPONSES,
)
async def get_agent_config(request: Request) -> SuccessEnvelope[AgentLlmConfigData]:
    return success(request, get_agent_llm_config_data())


@router.put(
    "/system/agent-config",
    tags=["System"],
    summary="Apply a process-local Agent LLM configuration",
    response_model=SuccessEnvelope[AgentLlmConfigData],
    responses=ERROR_RESPONSES,
)
async def update_agent_config(
    request: Request, payload: AgentLlmConfigUpdate
) -> SuccessEnvelope[AgentLlmConfigData]:
    return success(request, update_agent_llm_config(payload))


@router.delete(
    "/system/agent-config",
    tags=["System"],
    summary="Discard the process-local Agent LLM configuration",
    response_model=SuccessEnvelope[AgentLlmConfigData],
    responses=ERROR_RESPONSES,
)
async def reset_agent_config(request: Request) -> SuccessEnvelope[AgentLlmConfigData]:
    return success(request, reset_agent_llm_config())


@router.post(
    "/system/agent-config/test",
    tags=["System"],
    summary="Send a minimal completion to the effective Agent model service",
    response_model=SuccessEnvelope[AgentLlmConnectionData],
    responses={
        **ERROR_RESPONSES,
        502: {"model": ErrorEnvelope, "description": "模型服务不可用或配置无效。"},
    },
)
async def test_agent_config(request: Request) -> SuccessEnvelope[AgentLlmConnectionData]:
    try:
        result = await run_in_threadpool(test_agent_llm_connection)
    except LlmUnavailableError as error:
        raise AppError(
            "LLM_CONNECTION_FAILED",
            "模型服务连接失败",
            status_code=status.HTTP_502_BAD_GATEWAY,
            details={"reason": str(error)},
        ) from error
    return success(request, result)


@router.get(
    "/dashboard/leaderboard",
    tags=["Dashboard"],
    summary="List real completed optimisation studies ranked by validation free-run FIT",
    response_model=SuccessEnvelope[DashboardLeaderboardData],
    responses=ERROR_RESPONSES,
)
async def dashboard_leaderboard(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[DashboardLeaderboardData]:
    return success(request, await get_dashboard_leaderboard(session))


@router.post(
    "/simulation/generate",
    tags=["Simulation"],
    summary="Generate and register an S1-S6 benchmark dataset",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessEnvelope[SimulationGenerateData],
    responses=ERROR_RESPONSES,
)
async def generate_simulation(
    request: Request,
    payload: SimulationGenerateRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[SimulationGenerateData]:
    generated = generate_simulation_service(payload, artifact_root=get_settings().artifact_root)
    try:
        registered = await register_simulation_dataset(
            session,
            generated=generated,
            request=payload,
            artifact_root=get_settings().artifact_root,
        )
    except DatasetDomainError as error:
        raise AppError(error.code, error.message, status_code=error.status_code, details=error.details) from error
    return success(request, registered)


@router.post(
    "/datasets/upload",
    tags=["Datasets"],
    summary="Upload a CSV dataset for asynchronous parsing",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SuccessEnvelope[DatasetUploadData],
    responses={**ERROR_RESPONSES, 413: {"model": ErrorEnvelope, "description": "文件超过限制。"}},
)
async def upload_dataset(
    request: Request,
    file: Annotated[UploadFile, File(description="CSV 文件。")],
    session: Annotated[AsyncSession, Depends(get_session)],
    name: Annotated[str | None, Form(max_length=120)] = None,
) -> SuccessEnvelope[DatasetUploadData]:
    """Synchronously validate a CSV while retaining the phase-1 async response envelope."""

    try:
        uploaded = await upload_csv_dataset(
            session,
            upload=file,
            display_name=name,
            artifact_root=get_settings().artifact_root,
        )
    except DatasetDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=413 if error.code == "DATASET_FILE_TOO_LARGE" else error.status_code,
            details=error.details,
        ) from error
    return success(
        request,
        DatasetUploadData(
            dataset=uploaded.summary,
            parse_task=completed_task(
                stage="parse_upload",
                message="CSV 已完成校验、持久化和质量画像计算。",
            ),
            deduplicated=uploaded.deduplicated,
        ),
    )


@router.get(
    "/datasets",
    tags=["Datasets"],
    summary="List datasets",
    response_model=SuccessEnvelope[DatasetListData],
    responses=ERROR_RESPONSES,
)
async def list_datasets(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> SuccessEnvelope[DatasetListData]:
    return success(request, await list_dataset_summaries(session, page=page, page_size=page_size))


@router.post(
    "/datasets/{dataset_id}/config",
    tags=["Datasets"],
    summary="Confirm time/input/output column roles and recompute the profile",
    response_model=SuccessEnvelope[DatasetConfigData],
    responses=ERROR_RESPONSES,
)
async def configure_dataset(
    request: Request,
    dataset_id: DatasetId,
    payload: DatasetConfigRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[DatasetConfigData]:
    try:
        data = await configure_dataset_columns(
            session,
            dataset_id=dataset_id,
            payload=payload,
            artifact_root=get_settings().artifact_root,
        )
    except DatasetDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/datasets/{dataset_id}",
    tags=["Datasets"],
    summary="Get a dataset and its parsed column metadata",
    response_model=SuccessEnvelope[DatasetDetail],
    responses=ERROR_RESPONSES,
)
async def get_dataset(
    request: Request,
    dataset_id: DatasetId,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[DatasetDetail]:
    try:
        data = await get_dataset_detail(
            session,
            dataset_id=dataset_id,
            artifact_root=get_settings().artifact_root,
        )
    except DatasetDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/datasets/{dataset_id}/download",
    tags=["Datasets"],
    summary="Download the active or explicitly requested immutable CSV version",
    responses={404: {"model": ErrorEnvelope, "description": "数据集或 CSV 产物不存在。"}},
)
async def download_dataset(
    dataset_id: DatasetId,
    session: Annotated[AsyncSession, Depends(get_session)],
    version_id: Annotated[UUID | None, Query(description="可选的 DatasetVersion UUID。")] = None,
) -> FileResponse:
    try:
        path, filename = await get_dataset_download(
            session, dataset_id=dataset_id, version_id=version_id, artifact_root=get_settings().artifact_root
        )
    except DatasetDomainError as error:
        raise AppError(
            error.code, error.message, status_code=error.status_code, details=error.details
        ) from error
    return FileResponse(path, media_type="text/csv", filename=filename)


@router.delete(
    "/datasets/{dataset_id}",
    tags=["Datasets"],
    summary="Cascade-delete a dataset's database records",
    response_model=SuccessEnvelope[DatasetDeleteData],
    responses=ERROR_RESPONSES,
)
async def delete_dataset(
    request: Request,
    dataset_id: DatasetId,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[DatasetDeleteData]:
    try:
        await delete_dataset_asset(session, dataset_id=dataset_id)
    except DatasetDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, DatasetDeleteData(dataset_id=dataset_id))


@router.get(
    "/datasets/{dataset_id}/profile",
    tags=["Datasets"],
    summary="Get the quality profile for the active dataset version",
    response_model=SuccessEnvelope[DatasetProfile],
    responses=ERROR_RESPONSES,
)
async def get_dataset_profile(
    request: Request,
    dataset_id: DatasetId,
    session: Annotated[AsyncSession, Depends(get_session)],
    version_id: Annotated[UUID | None, Query(description="可选的 DatasetVersion UUID。")] = None,
) -> SuccessEnvelope[DatasetProfile]:
    try:
        data = await get_dataset_profile_service(
            session, dataset_id=dataset_id, version_id=version_id
        )
    except DatasetDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/datasets/{dataset_id}/versions",
    tags=["Datasets"],
    summary="Get the immutable data-version lineage DAG",
    response_model=SuccessEnvelope[DatasetVersionsData],
    responses=ERROR_RESPONSES,
)
async def get_dataset_versions(
    request: Request,
    dataset_id: DatasetId,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[DatasetVersionsData]:
    try:
        data = await get_dataset_versions_service(
            session,
            dataset_id=dataset_id,
            artifact_root=get_settings().artifact_root,
        )
    except DatasetDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.post(
    "/preprocessing/clean",
    tags=["Preprocessing"],
    summary="Queue time alignment, interpolation and anomaly cleaning",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SuccessEnvelope[CleanData],
    responses=ERROR_RESPONSES,
)
async def clean_data(
    request: Request,
    payload: CleanRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[CleanData]:
    """Run the real cleaning pipeline and register an immutable derived version."""

    try:
        data = await clean_dataset_version(
            session,
            payload=payload,
            artifact_root=get_settings().artifact_root,
        )
    except CleaningDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.post(
    "/preprocessing/segment",
    tags=["Preprocessing"],
    summary="Queue dynamic-response segment identification",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SuccessEnvelope[SegmentData],
    responses=ERROR_RESPONSES,
)
async def segment_data(
    request: Request,
    payload: SegmentRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[SegmentData]:
    """Gate candidate windows on quality, then select by D-optimal information gain."""

    try:
        data = await select_dynamic_segments(
            session,
            payload=payload,
            artifact_root=get_settings().artifact_root,
        )
    except SegmentDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.post(
    "/preprocessing/delay",
    tags=["Preprocessing"],
    summary="Queue multi-variable lag-correlation analysis",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SuccessEnvelope[DelayData],
    responses=ERROR_RESPONSES,
)
async def estimate_delay(
    request: Request,
    payload: DelayRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[DelayData]:
    """Prewhitened cross-correlation candidates, refined on the validation split."""

    try:
        data = await run_delay_estimation(
            session,
            payload=payload,
            artifact_root=get_settings().artifact_root,
        )
    except AnalysisDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/datasets/{dataset_id}/delay-sources",
    tags=["Datasets"],
    summary="List Cleaning versions and their persisted delay-analysis states",
    response_model=SuccessEnvelope[DelaySourceVersionsData],
    responses=ERROR_RESPONSES,
)
async def get_delay_sources(
    request: Request,
    dataset_id: DatasetId,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[DelaySourceVersionsData]:
    """Read-only selector data; this endpoint never runs or persists analysis."""

    try:
        data = await get_delay_source_versions(session, dataset_id=dataset_id)
    except AnalysisDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/datasets/{dataset_id}/collinearity-sources",
    tags=["Datasets"],
    summary="List Lag Compensation versions and their persisted collinearity-analysis states",
    response_model=SuccessEnvelope[CollinearitySourceVersionsData],
    responses=ERROR_RESPONSES,
)
async def get_collinearity_sources(
    request: Request,
    dataset_id: DatasetId,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[CollinearitySourceVersionsData]:
    """Read-only selector data; this endpoint never runs or persists analysis."""

    try:
        data = await get_collinearity_source_versions(session, dataset_id=dataset_id)
    except AnalysisDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/preprocessing/delay/latest",
    tags=["Preprocessing"],
    summary="Load the latest complete persisted lag-correlation analysis",
    response_model=SuccessEnvelope[DelayData],
    responses=ERROR_RESPONSES,
)
async def get_latest_delay(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    version_id: Annotated[UUID, Query(description="源 DatasetVersion UUID。")],
    dataset_id: Annotated[UUID | None, Query(description="可选的 Dataset UUID 校验。")] = None,
) -> SuccessEnvelope[DelayData]:
    """Read a persisted delay result; this endpoint never re-runs analysis."""

    try:
        data = await get_latest_delay_result(
            session,
            version_id=version_id,
            dataset_id=dataset_id,
        )
    except AnalysisDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/datasets/{dataset_id}/versions/{version_id}/preview",
    tags=["Datasets"],
    summary="Get a paginated preview of one immutable dataset version",
    response_model=SuccessEnvelope[DatasetVersionPreviewData],
    responses=ERROR_RESPONSES,
)
async def get_dataset_version_preview_page(
    request: Request,
    dataset_id: DatasetId,
    version_id: Annotated[UUID, Path(description="DatasetVersion UUID。")],
    session: Annotated[AsyncSession, Depends(get_session)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[
        DatasetVersionPreviewPageSize, Query()
    ] = DatasetVersionPreviewPageSize.ROWS_100,
) -> SuccessEnvelope[DatasetVersionPreviewData]:
    try:
        data = await get_dataset_version_preview(
            session,
            dataset_id=dataset_id,
            version_id=version_id,
            page=page,
            page_size=int(page_size),
            artifact_root=get_settings().artifact_root,
        )
    except DatasetDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/datasets/{dataset_id}/cleaning-version-compare/channels",
    tags=["Datasets"],
    summary="List common numeric channels for two Cleaning-eligible versions",
    response_model=SuccessEnvelope[CleaningVersionCompareChannelsData],
    responses={
        **ERROR_RESPONSES,
        409: {"model": ErrorEnvelope, "description": "Artifact integrity conflict。"},
    },
)
async def list_cleaning_version_compare_channels(
    request: Request,
    dataset_id: DatasetId,
    session: Annotated[AsyncSession, Depends(get_session)],
    baseline_version_id: Annotated[UUID, Query(description="Baseline DatasetVersion UUID。")],
    compare_version_id: Annotated[UUID, Query(description="Compare DatasetVersion UUID。")],
) -> SuccessEnvelope[CleaningVersionCompareChannelsData]:
    try:
        data = await get_cleaning_version_compare_channels(
            session,
            dataset_id=dataset_id,
            baseline_version_id=baseline_version_id,
            compare_version_id=compare_version_id,
            artifact_root=get_settings().artifact_root,
        )
    except CleaningVersionCompareError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/datasets/{dataset_id}/cleaning-version-compare",
    tags=["Datasets"],
    summary="Compare two immutable Cleaning-eligible dataset versions",
    response_model=SuccessEnvelope[CleaningVersionCompareData],
    responses={
        **ERROR_RESPONSES,
        409: {"model": ErrorEnvelope, "description": "Artifact integrity or lineage conflict。"},
    },
)
async def get_clean_version_compare(
    request: Request,
    dataset_id: DatasetId,
    session: Annotated[AsyncSession, Depends(get_session)],
    baseline_version_id: Annotated[UUID, Query(description="Baseline DatasetVersion UUID。")],
    compare_version_id: Annotated[UUID, Query(description="Compare DatasetVersion UUID。")],
    channel: Annotated[str, Query(min_length=1, max_length=255)],
    max_points: Annotated[int, Query(ge=2, le=10_000)] = 10_000,
) -> SuccessEnvelope[CleaningVersionCompareData]:
    try:
        data = await compare_cleaning_versions(
            session,
            dataset_id=dataset_id,
            baseline_version_id=baseline_version_id,
            compare_version_id=compare_version_id,
            channel=channel,
            max_points=max_points,
            artifact_root=get_settings().artifact_root,
        )
    except CleaningVersionCompareError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.post(
    "/preprocessing/delay/apply",
    tags=["Preprocessing"],
    summary="Apply confirmed lag compensation and create an immutable DatasetVersion",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessEnvelope[VersionApplyData],
    responses=ERROR_RESPONSES,
)
async def apply_delay_compensation(
    request: Request,
    payload: LagCompensationRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[VersionApplyData]:
    try:
        data = await apply_lag_compensation(
            session, payload=payload, artifact_root=get_settings().artifact_root
        )
    except VersionedPreprocessingError as error:
        raise AppError(error.code, error.message, status_code=error.status_code, details=error.details) from error
    return success(request, data)


@router.get(
    "/preprocessing/collinearity/latest",
    tags=["Preprocessing"],
    summary="Load the latest complete persisted collinearity analysis",
    response_model=SuccessEnvelope[CollinearityData],
    responses=ERROR_RESPONSES,
)
async def get_latest_collinearity(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    version_id: Annotated[UUID, Query(description="源 DatasetVersion UUID。")],
    dataset_id: Annotated[UUID | None, Query(description="可选的 Dataset UUID 校验。")] = None,
) -> SuccessEnvelope[CollinearityData]:
    """Read a persisted collinearity result; this endpoint never recomputes it."""

    try:
        data = await get_latest_collinearity_result(
            session,
            version_id=version_id,
            dataset_id=dataset_id,
        )
    except AnalysisDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.post(
    "/preprocessing/collinearity",
    tags=["Preprocessing"],
    summary="Queue Pearson and VIF collinearity diagnostics",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SuccessEnvelope[CollinearityData],
    responses=ERROR_RESPONSES,
)
async def analyze_collinearity(
    request: Request,
    payload: CollinearityRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[CollinearityData]:
    """Pearson, Spearman, VIF and condition number with advisory recommendations."""

    try:
        data = await run_collinearity_analysis(
            session,
            payload=payload,
            artifact_root=get_settings().artifact_root,
        )
    except AnalysisDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.post(
    "/preprocessing/features/apply",
    tags=["Preprocessing"],
    summary="Drop confirmed redundant inputs and create an immutable DatasetVersion",
    status_code=status.HTTP_201_CREATED,
    response_model=SuccessEnvelope[VersionApplyData],
    responses=ERROR_RESPONSES,
)
async def apply_features(
    request: Request,
    payload: FeatureSelectionApplyRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[VersionApplyData]:
    try:
        data = await apply_feature_selection(
            session, payload=payload, artifact_root=get_settings().artifact_root
        )
    except VersionedPreprocessingError as error:
        raise AppError(error.code, error.message, status_code=error.status_code, details=error.details) from error
    return success(request, data)


@router.post(
    "/modeling/arx/fit",
    tags=["Modeling"],
    summary="Run MISO ARX identification and chronological partitioned evaluation",
    response_model=SuccessEnvelope[ArxFitData],
    responses=ERROR_RESPONSES,
)
async def fit_arx(
    request: Request,
    payload: ArxFitRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[ArxFitData]:
    """Identify ARX only on trusted Lag lineage and apply the formal model checks."""

    try:
        data = await fit_arx_on_version(
            session,
            payload=payload,
            artifact_root=get_settings().artifact_root,
            require_lag_provenance=True,
        )
    except ModelingDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.post(
    "/optimization/optuna/start",
    tags=["Optimization"],
    summary="Start a cancellable Optuna pipeline-optimization study",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SuccessEnvelope[OptimizationStartData],
    responses=ERROR_RESPONSES,
)
async def start_optimization(
    request: Request,
    payload: OptimizationStartRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[OptimizationStartData]:
    """Run the closed loop: gate, select, identify, score on free-run FIT, repeat."""

    try:
        data = await start_optimization_study(
            session,
            payload=payload,
            artifact_root=get_settings().artifact_root,
        )
    except OptimizationDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/optimization/optuna/{study_id}/status",
    tags=["Optimization"],
    summary="Get Optuna trial progress, convergence curve and parameter importance",
    response_model=SuccessEnvelope[OptimizationStatusData],
    responses=ERROR_RESPONSES,
)
async def optimization_status(
    request: Request,
    study_id: Annotated[UUID, Path(description="Optuna study UUID。")],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[OptimizationStatusData]:
    try:
        data = await get_optimization_status(session, study_id=study_id)
    except OptimizationDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/optimization/optuna/{study_id}/diagnostics",
    tags=["Optimization"],
    summary="Replay the validation-selected winner for read-only generalization diagnostics",
    response_model=SuccessEnvelope[GeneralizationDiagnosticsData],
    responses=ERROR_RESPONSES,
)
async def optimization_diagnostics(
    request: Request,
    study_id: Annotated[UUID, Path(description="Optuna study UUID。")],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[GeneralizationDiagnosticsData]:
    """Inspect the fixed winner without running a new Optuna trial or changing the study."""

    try:
        data = await get_generalization_diagnostics(
            session, study_id=study_id, artifact_root=get_settings().artifact_root
        )
    except OptimizationDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.post(
    "/tasks/{task_id}/cancel",
    tags=["Tasks"],
    summary="Request cooperative cancellation of an asynchronous task",
    response_model=SuccessEnvelope[CancelTaskData],
    responses=ERROR_RESPONSES,
)
async def cancel_task(
    request: Request, task_id: Annotated[UUID, Path(description="后台任务 UUID。")]
) -> SuccessEnvelope[CancelTaskData]:
    return success(
        request,
        CancelTaskData(task_id=task_id, task=queued_task(status="cancelled", stage="cancelled")),
    )


@router.post(
    "/copilot/chat",
    tags=["Copilot"],
    summary="Create a validated, whitelisted copilot execution-plan DAG",
    response_model=SuccessEnvelope[CopilotChatData],
    responses=ERROR_RESPONSES,
)
async def copilot_chat(
    request: Request,
    payload: CopilotChatRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[CopilotChatData]:
    """Plan from natural language, verify statically, then execute whitelisted tools."""

    try:
        data = await run_copilot(
            session,
            payload=payload,
            artifact_root=get_settings().artifact_root,
        )
    except AgentDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/copilot/executions/{execution_id}",
    tags=["Copilot"],
    summary="Read one persisted copilot execution snapshot",
    response_model=SuccessEnvelope[CopilotExecutionSnapshotData],
    responses=ERROR_RESPONSES,
)
async def get_copilot_execution(
    request: Request,
    execution_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[CopilotExecutionSnapshotData]:
    """Return durable execution state without dispatching a tool or mutating workflow state."""

    try:
        execution = await get_execution(session, execution_id=execution_id)
    except ExecutionStateError as error:
        raise AppError(
            "AGENT_EXECUTION_NOT_FOUND",
            "未找到指定的 Agent 执行记录。",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"execution_id": str(execution_id)},
        ) from error
    return success(request, to_copilot_execution_snapshot(execution))

@router.post(
    "/copilot/arx-structure/validate",
    tags=["Copilot"],
    summary="Validate controlled ARX na/nb overrides without persisting a model",
    response_model=SuccessEnvelope[ArxStructureValidationData],
    responses={**ERROR_RESPONSES, 409: {"model": ErrorEnvelope}},
)
async def validate_copilot_arx_structure(
    request: Request,
    payload: ArxStructureValidationRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[ArxStructureValidationData]:
    try:
        data = await validate_arx_structure(
            session,
            execution_id=payload.execution_id,
            step_id=payload.step_id,
            manual_overrides=payload.manual_overrides,
            artifact_root=get_settings().artifact_root,
        )
    except ExecutionStateError as error:
        raise AppError(
            "AGENT_EXECUTION_STATE_CONFLICT",
            "当前执行步骤不可校验 ARX 结构。",
            status_code=status.HTTP_409_CONFLICT,
            details={"reason": str(error)},
        ) from error
    except ArxStructureError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)

@router.post(
    "/copilot/feature-selection/validate",
    tags=["Copilot"],
    summary="Validate a controlled Feature Selection without executing a tool",
    response_model=SuccessEnvelope[FeatureSelectionValidationData],
    responses={**ERROR_RESPONSES, 409: {"model": ErrorEnvelope}},
)
async def validate_copilot_feature_selection(
    request: Request,
    payload: FeatureSelectionValidationRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[FeatureSelectionValidationData]:
    try:
        data = await validate_feature_selection(
            session,
            execution_id=payload.execution_id,
            step_id=payload.step_id,
            drop_columns=payload.drop_columns,
        )
    except ExecutionStateError as error:
        raise AppError(
            "AGENT_EXECUTION_STATE_CONFLICT",
            "当前执行步骤不可校验变量选择。",
            status_code=status.HTTP_409_CONFLICT,
            details={"reason": str(error)},
        ) from error
    except FeatureSelectionError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.post(
    "/copilot/lag-overrides/validate",
    tags=["Copilot"],
    summary="Validate controlled manual lag overrides without executing a tool",
    response_model=SuccessEnvelope[LagOverrideValidationData],
    responses={**ERROR_RESPONSES, 409: {"model": ErrorEnvelope}},
)
async def validate_copilot_lag_overrides(
    request: Request,
    payload: LagOverrideValidationRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[LagOverrideValidationData]:
    try:
        data = await validate_lag_overrides(
            session,
            execution_id=payload.execution_id,
            step_id=payload.step_id,
            manual_overrides=payload.manual_overrides,
        )
    except ExecutionStateError as error:
        raise AppError(
            "AGENT_EXECUTION_STATE_CONFLICT",
            "当前执行步骤不可校验时滞覆盖。",
            status_code=status.HTTP_409_CONFLICT,
            details={"reason": str(error)},
        ) from error
    except LagOverrideError as error:
        raise AppError(error.code, error.message, status_code=error.status_code, details=error.details) from error
    return success(request, data)


@router.post(
    "/copilot/confirm",
    tags=["Copilot"],
    summary="Persist a human confirmation decision for an Agent execution step",
    response_model=SuccessEnvelope[CopilotConfirmData],
    responses={
        **ERROR_RESPONSES,
        409: {"model": ErrorEnvelope, "description": "执行状态不允许该确认操作。"},
    },
)
async def copilot_confirm(
    request: Request,
    payload: CopilotConfirmRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[CopilotConfirmData]:
    if payload.execution_id is None or payload.step_id is None:
        raise AppError(
            "AGENT_EXECUTION_REFERENCE_REQUIRED",
            "持久确认需要 execution_id 和 step_id。",
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )

    validation: LagOverrideValidationData | None = None
    feature_validation: FeatureSelectionValidationData | None = None
    arx_validation: ArxStructureValidationData | None = None
    resume_after_confirmation = False
    try:
        if not payload.approved:
            execution = await reject_step(
                session, execution_id=payload.execution_id, step_id=payload.step_id
            )
        elif await is_lag_apply_step(
            session, execution_id=payload.execution_id, step_id=payload.step_id
        ):
            outcome = await approve_and_execute_lag_step(
                session,
                execution_id=payload.execution_id,
                step_id=payload.step_id,
                manual_overrides=payload.manual_overrides,
                warning_acknowledged=payload.warning_acknowledged,
                artifact_root=get_settings().artifact_root,
            )
            execution, validation = outcome.execution, outcome.validation
            resume_after_confirmation = True
        elif await is_feature_apply_step(
            session, execution_id=payload.execution_id, step_id=payload.step_id
        ):
            feature_outcome = await approve_and_execute_feature_step(
                session,
                execution_id=payload.execution_id,
                step_id=payload.step_id,
                drop_columns=payload.feature_drop_columns,
                artifact_root=get_settings().artifact_root,
            )
            execution = feature_outcome.execution
            feature_validation = feature_outcome.validation
            resume_after_confirmation = True
        elif await is_arx_fit_step(
            session, execution_id=payload.execution_id, step_id=payload.step_id
        ):
            arx_outcome = await approve_and_execute_arx_step(
                session,
                execution_id=payload.execution_id,
                step_id=payload.step_id,
                manual_overrides=payload.arx_structure_overrides,
                artifact_root=get_settings().artifact_root,
            )
            execution = arx_outcome.execution
            arx_validation = arx_outcome.validation
            resume_after_confirmation = True
        else:
            execution = await approve_step(
                session, execution_id=payload.execution_id, step_id=payload.step_id
            )
            approved_step = next(
                item for item in execution.step_runs if item.step_id == payload.step_id
            )
            if approved_step.tool_name == "optimize_pipeline":
                execution = await execute_approved_optimization_step(
                    session,
                    execution_id=execution.id,
                    artifact_root=get_settings().artifact_root,
                )
                resume_after_confirmation = True
            elif approved_step.tool_name == "export_dataset":
                execution = await execute_approved_export_step(
                    session,
                    execution_id=execution.id,
                    step_id=approved_step.step_id,
                    artifact_root=get_settings().artifact_root,
                )
                resume_after_confirmation = True
        if resume_after_confirmation:
            execution = await continue_agent_execution(
                session,
                execution_id=execution.id,
                artifact_root=get_settings().artifact_root,
            )
    except ExecutionStateError as error:
        raise AppError(
            "AGENT_EXECUTION_STATE_CONFLICT",
            "当前执行状态不允许该确认操作。",
            status_code=status.HTTP_409_CONFLICT,
            details={"reason": str(error)},
        ) from error
    except (LagOverrideError, FeatureSelectionError, ArxStructureError) as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    except (AgentToolAdapterError, VersionDataError, VersionedPreprocessingError) as error:
        raise AppError(
            getattr(error, "code", "AGENT_CONFIRMED_TOOL_FAILED"),
            getattr(error, "message", str(error)),
            status_code=getattr(error, "status_code", status.HTTP_400_BAD_REQUEST),
            details=getattr(error, "details", {}),
        ) from error

    step = next(item for item in execution.step_runs if item.step_id == payload.step_id)
    return success(
        request,
        CopilotConfirmData(
            copilot_run_id=payload.copilot_run_id,
            confirmation_id=payload.confirmation_id,
            decision="approved" if payload.approved else "rejected",
            execution_id=execution.id,
            workflow_status=execution.workflow_status,
            current_version_id=execution.current_version_id,
            current_step_id=execution.current_step_id,
            pending_confirmation_step_id=execution.pending_confirmation_step_id,
            step_id=step.step_id,
            step_status=step.status,
            confirmation_status=step.confirmation_status,
            result_version_id=step.result_version_id,
            result_payload=step.result_payload,
            lag_override_validation=validation,
            feature_selection_validation=feature_validation,
            arx_structure_validation=arx_validation,
        ),
    )
@router.post(
    "/copilot/optimize-pipeline/execute",
    tags=["Copilot"],
    summary="Execute the approved agent optimization step",
    response_model=SuccessEnvelope[CopilotOptimizePipelineExecuteData],
    responses={
        **ERROR_RESPONSES,
        409: {"model": ErrorEnvelope, "description": "执行状态不允许模型寻优。"},
    },
)
async def execute_copilot_optimize_pipeline(
    request: Request,
    payload: OptimizePipelineExecuteRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[CopilotOptimizePipelineExecuteData]:
    """Execute exactly one already-approved optimize_pipeline step synchronously."""

    try:
        execution = await execute_approved_optimization_step(
            session,
            execution_id=payload.execution_id,
            artifact_root=get_settings().artifact_root,
        )
        if execution.workflow_status == "RUNNING":
            execution = await continue_agent_execution(
                session,
                execution_id=execution.id,
                artifact_root=get_settings().artifact_root,
            )
    except ExecutionStateError as error:
        raise AppError(
            "AGENT_EXECUTION_STATE_CONFLICT",
            "当前执行状态不允许模型寻优。",
            status_code=status.HTTP_409_CONFLICT,
            details={"reason": str(error)},
        ) from error
    except AgentDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error

    step = next(item for item in execution.step_runs if item.tool_name == "optimize_pipeline")
    return success(
        request,
        CopilotOptimizePipelineExecuteData(
            execution_id=execution.id,
            workflow_status=execution.workflow_status,
            current_version_id=execution.current_version_id,
            step_id=step.step_id,
            step_status=step.status,
            result_payload=step.result_payload,
            error_code=step.error_code,
            error_message=step.error_message,
            processing_run_ids=step.processing_run_ids,
        ),
    )

@router.post(
    "/copilot/evaluate-model/execute",
    tags=["Copilot"],
    summary="Execute the pending saved-model evaluation step",
    response_model=SuccessEnvelope[CopilotEvaluateModelExecuteData],
    responses={
        **ERROR_RESPONSES,
        409: {"model": ErrorEnvelope, "description": "执行状态不允许模型评价。"},
    },
)
async def execute_copilot_evaluate_model(
    request: Request,
    payload: CopilotEvaluateModelExecuteRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[CopilotEvaluateModelExecuteData]:
    try:
        execution = await execute_pending_evaluation_step(session, execution_id=payload.execution_id, artifact_root=get_settings().artifact_root)
        if execution.workflow_status == "RUNNING":
            execution = await continue_agent_execution(
                session,
                execution_id=execution.id,
                artifact_root=get_settings().artifact_root,
            )
    except ExecutionStateError as error:
        raise AppError("AGENT_EXECUTION_STATE_CONFLICT", "当前执行状态不允许模型评价。", status_code=status.HTTP_409_CONFLICT, details={"reason": str(error)}) from error
    except AgentDomainError as error:
        raise AppError(error.code, error.message, status_code=error.status_code, details=error.details) from error

    step = next(item for item in execution.step_runs if item.tool_name == "evaluate_model")
    return success(request, CopilotEvaluateModelExecuteData(
        execution_id=execution.id,
        workflow_status=execution.workflow_status,
        current_version_id=execution.current_version_id,
        step_id=step.step_id,
        step_status=step.status,
        result_payload=step.result_payload,
        error_code=step.error_code,
        error_message=step.error_message,
        processing_run_ids=step.processing_run_ids,
    ))

@router.post(
    "/reports/generate",
    tags=["Delivery"],
    summary="Generate a provenance-bound report where every number cites its run",
    response_model=SuccessEnvelope[ReportData],
    responses=ERROR_RESPONSES,
)
async def generate_report_route(
    request: Request,
    payload: ReportRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[ReportData]:
    """Compose from persisted runs; a draft with a bare numeral is rejected, not rendered."""

    try:
        data = await generate_report(
            session,
            payload=payload,
            artifact_root=get_settings().artifact_root,
        )
    except ReportDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/delivery/studies",
    tags=["Delivery"],
    summary="List successful Studies with a strictly verifiable Best result",
    response_model=SuccessEnvelope[DeliveryStudyListData],
    responses=ERROR_RESPONSES,
)
async def delivery_studies_route(
    request: Request,
    dataset_id: Annotated[UUID, Query()],
    version_id: Annotated[UUID, Query()],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[DeliveryStudyListData]:
    data = await list_delivery_studies(
        session,
        dataset_id=dataset_id,
        version_id=version_id,
        artifact_root=get_settings().artifact_root,
    )
    return success(request, data)


@router.post(
    "/delivery/export",
    tags=["Delivery"],
    summary="Export the closed-loop selected rows as CSV plus a provenance manifest",
    response_model=SuccessEnvelope[ExportDatasetData],
    responses=ERROR_RESPONSES,
)
async def export_dataset_route(
    request: Request,
    payload: ExportDatasetRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[ExportDatasetData]:
    try:
        data = await export_optimised_dataset(
            session,
            payload=payload,
            artifact_root=get_settings().artifact_root,
        )
    except ReportDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)


@router.get(
    "/delivery/exports/{export_id}/csv",
    tags=["Delivery"],
    summary="Download a persisted optimised dataset CSV",
    responses={404: {"model": ErrorEnvelope, "description": "导出记录或 CSV 不存在。"}},
)
async def download_export_csv(
    export_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    try:
        path, filename, media_type = await get_export_artifact(
            session,
            export_id=export_id,
            artifact_root=get_settings().artifact_root,
            kind="csv",
        )
    except ReportDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return FileResponse(path, media_type=media_type, filename=filename)


@router.get(
    "/delivery/exports/{export_id}/manifest",
    tags=["Delivery"],
    summary="Download a persisted optimised dataset provenance manifest",
    responses={404: {"model": ErrorEnvelope, "description": "导出记录或 Manifest 不存在。"}},
)
async def download_export_manifest(
    export_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> FileResponse:
    try:
        path, filename, media_type = await get_export_artifact(
            session,
            export_id=export_id,
            artifact_root=get_settings().artifact_root,
            kind="manifest",
        )
    except ReportDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return FileResponse(path, media_type=media_type, filename=filename)


@router.post(
    "/benchmark/run",
    tags=["Delivery"],
    summary="Run the built-in ablation suite and return freshly measured results",
    response_model=SuccessEnvelope[BenchmarkData],
    responses=ERROR_RESPONSES,
)
async def run_benchmark_route(
    request: Request,
    payload: BenchmarkRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SuccessEnvelope[BenchmarkData]:
    """Every number is computed during this request; nothing is cached or hard-coded."""

    try:
        data = await run_benchmark(
            session,
            payload=payload,
            artifact_root=get_settings().artifact_root,
        )
    except BenchmarkDomainError as error:
        raise AppError(
            error.code,
            error.message,
            status_code=error.status_code,
            details=error.details,
        ) from error
    return success(request, data)
