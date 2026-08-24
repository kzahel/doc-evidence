"""Authenticated, origin-bounded FastAPI adapter."""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from doc_evidence.application.jobs import (
    ExtractorCapabilityRecord,
    JobAttemptRecord,
    JobBatchRecord,
    JobRecord,
    JobState,
)
from doc_evidence.application.libraries import LibraryManager
from doc_evidence.application.library import LibraryApplication
from doc_evidence.application.library_management import DesktopLibraryControl
from doc_evidence.contracts.api import (
    ApiProblem,
    AppSummary,
    AttemptDiagnostics,
    ComparisonRequest,
    ComparisonResult,
    Diagnostics,
    DocumentDetail,
    DocumentPage,
    ExtractionBatchPreflight,
    ExtractionBatchRequest,
    ExtractionJobRequest,
    ExtractorCapability,
    ExtractorCapabilityList,
    ExtractorDependency,
    InventoryJobRequest,
    JobAttempt,
    JobBatchCancellationResponse,
    JobBatchCancelRequest,
    JobBatchCreationResponse,
    JobBatchPage,
    JobBatchSummary,
    JobCounts,
    JobCreationResponse,
    JobDetail,
    JobEvent,
    JobEventPage,
    JobPage,
    JobSummary,
    KnownLibraryList,
    LibraryActivation,
    LibraryDetail,
    PageGroups,
    PageSummary,
    QueueState,
    QueueUpdateRequest,
    RunList,
    SearchPage,
    WorkspaceSummary,
)
from doc_evidence.contracts.desktop import (
    DesktopAddCollectionRequest,
    DesktopCollectionResult,
    DesktopControlHandshake,
    DesktopCreateLibraryRequest,
    DesktopHandshake,
    DesktopLibraryResult,
    DesktopRegisterLibraryRequest,
    create_desktop_handshake,
)
from doc_evidence.errors import (
    DependencyError,
    DocEvidenceError,
    NotFoundError,
    RequestError,
)

_bearer = HTTPBearer(auto_error=False)


def _job_summary(record: JobRecord) -> JobSummary:
    return JobSummary(
        job_id=record.job_id,
        library_id=record.library_id,
        request_kind=record.request_kind,
        batch_id=record.batch_id,
        document_id=record.document_id,
        extractor_id=record.extractor_id,
        settings=record.settings,
        execution_mode=record.execution_mode,
        run_key=record.run_key,
        priority=record.priority,
        resource_class=record.resource_class,
        state=record.state,
        outcome=record.outcome,
        queue_reason=record.queue_reason,
        retry_count=record.retry_count,
        automatic_retry_count=record.automatic_retry_count,
        cancellation_requested=record.cancellation_requested,
        active_attempt_id=record.active_attempt_id,
        result_run_id=record.result_run_id,
        failure_class=record.failure_class,
        error_summary=record.error_summary,
        created_at=record.created_at,
        queued_at=record.queued_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        updated_at=record.updated_at,
    )


def _job_attempt(record: JobAttemptRecord) -> JobAttempt:
    return JobAttempt(**record.__dict__)


def _batch_summary(record: JobBatchRecord) -> JobBatchSummary:
    return JobBatchSummary(**record.__dict__)


def _extractor_capability(record: ExtractorCapabilityRecord) -> ExtractorCapability:
    return ExtractorCapability(
        extractor_id=record.extractor_id,
        display_name=record.display_name,
        category=record.category,  # type: ignore[arg-type]
        supported_media_types=list(record.supported_media_types),
        dependencies=[
            ExtractorDependency(**dependency.__dict__)
            for dependency in record.dependencies
        ],
        available=record.available,
        unavailable_reason=record.unavailable_reason,
        version_label=record.version_label,
        resource_class=record.resource_class,
        settings_schema=record.settings_schema,
        default_settings=record.default_settings,
        default_timeout_seconds=record.default_timeout_seconds,
        deterministic=record.deterministic,
        output_kinds=list(record.output_kinds),
        document_supported=record.document_supported,
        cached=record.cached,
        run_key=record.run_key,
        run_id=record.run_id,
        recommended=record.recommended,
    )


def create_app(
    application: LibraryApplication | None,
    *,
    library_manager: LibraryManager | None = None,
    launch_token: str,
    allowed_origins: set[str] | None = None,
    static_dir: Path | None = None,
    on_started: Callable[[], None] | None = None,
    desktop_handshake: DesktopHandshake | None = None,
    host_control_token: str | None = None,
    desktop_control_handshake: DesktopControlHandshake | None = None,
    desktop_library_control: DesktopLibraryControl | None = None,
) -> FastAPI:
    origins = frozenset(allowed_origins or set())

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if on_started is not None:
            on_started()
        try:
            yield
        finally:
            if library_manager is not None:
                library_manager.shutdown()

    app = FastAPI(
        title="doc-evidence local API",
        version="1",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.application = application
    app.state.library_manager = library_manager

    @app.middleware("http")
    async def origin_and_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        origin = request.headers.get("origin")
        is_api = request.url.path.startswith("/api/v1/")
        is_control = request.url.path.startswith("/desktop-control/v1/")
        is_protected = is_api or is_control
        if is_control and origin:
            return JSONResponse(
                status_code=403,
                content=ApiProblem(
                    code="origin_not_allowed",
                    message="desktop control requests cannot have a browser origin",
                ).model_dump(),
            )
        if is_api and origin and origin not in origins:
            return JSONResponse(
                status_code=403,
                content=ApiProblem(
                    code="origin_not_allowed",
                    message="request origin is not allowed",
                ).model_dump(),
            )
        content_length = request.headers.get("content-length")
        if (
            is_protected
            and content_length is not None
            and content_length.isdecimal()
            and int(content_length) > 262_144
        ):
            response = JSONResponse(
                status_code=413,
                content=ApiProblem(
                    code="request_too_large",
                    message="API request body exceeds 256 KiB",
                ).model_dump(),
            )
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            return response
        if is_api and request.method == "OPTIONS":
            response = Response(status_code=204)
            if origin:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = (
                "Authorization, Content-Type, Idempotency-Key"
            )
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
            response.headers["Access-Control-Max-Age"] = "600"
        else:
            response = await call_next(request)
            if is_api and origin:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Vary"] = "Origin"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def authorize(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ) -> None:
        if (
            credentials is None
            or credentials.scheme.casefold() != "bearer"
            or not hmac.compare_digest(credentials.credentials, launch_token)
        ):
            from fastapi import HTTPException

            raise HTTPException(
                status_code=401,
                detail={
                    "code": "authentication_required",
                    "message": "valid launch authentication is required",
                },
                headers={"WWW-Authenticate": "Bearer"},
            )

    def authorize_control(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ) -> None:
        if (
            host_control_token is None
            or credentials is None
            or credentials.scheme.casefold() != "bearer"
            or not hmac.compare_digest(
                credentials.credentials,
                host_control_token,
            )
        ):
            from fastapi import HTTPException

            raise HTTPException(
                status_code=401,
                detail={
                    "code": "desktop_control_authentication_required",
                    "message": "valid desktop host authentication is required",
                },
                headers={"WWW-Authenticate": "Bearer"},
            )

    def service(request: Request) -> LibraryApplication:
        value = request.app.state.application
        if value is None:
            raise RuntimeError("contract-only application has no service")
        return value

    def manager(request: Request) -> LibraryManager:
        value = request.app.state.library_manager
        if value is None:
            raise RuntimeError("contract-only application has no library manager")
        return value

    def library_service(request: Request, library_id: str) -> LibraryApplication:
        return manager(request).application(library_id)

    def job_service(request: Request, library_id: str):
        return manager(request).jobs(library_id)

    router = APIRouter(prefix="/api/v1", dependencies=[Depends(authorize)])

    @router.get("/desktop/handshake", response_model=DesktopHandshake)
    def desktop_runtime_handshake() -> DesktopHandshake:
        if desktop_handshake is None:
            raise NotFoundError("desktop runtime is not active")
        return desktop_handshake

    @router.get("/app", response_model=AppSummary)
    def app_summary(request: Request) -> AppSummary:
        return manager(request).app_summary()

    @router.get("/libraries", response_model=KnownLibraryList)
    def libraries(request: Request) -> KnownLibraryList:
        return manager(request).libraries()

    @router.get("/libraries/{library_id}", response_model=LibraryDetail)
    def library(request: Request, library_id: str) -> LibraryDetail:
        return manager(request).library(library_id)

    @router.post(
        "/libraries/{library_id}/activate",
        response_model=LibraryActivation,
    )
    def activate_library(request: Request, library_id: str) -> LibraryActivation:
        return manager(request).activate(library_id)

    @router.get(
        "/libraries/{library_id}/extractors",
        response_model=ExtractorCapabilityList,
    )
    def library_extractors(
        request: Request,
        library_id: str,
        document_id: str | None = None,
    ) -> ExtractorCapabilityList:
        records = job_service(request, library_id).capabilities(document_id=document_id)
        return ExtractorCapabilityList(
            document_id=document_id,
            items=[_extractor_capability(record) for record in records],
        )

    @router.post(
        "/libraries/{library_id}/jobs/extractions",
        response_model=JobCreationResponse,
    )
    def create_extraction_job(
        request: Request,
        library_id: str,
        body: ExtractionJobRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JobCreationResponse:
        creation = job_service(request, library_id).enqueue(
            document_id=body.document_id,
            extractor_id=body.extractor_id,
            settings=body.settings,
            execution_mode=body.execution_mode,
            idempotency_key=idempotency_key,
        )
        if creation.job.state == "queued":
            manager(request).start_jobs(library_id)
        return JobCreationResponse(
            disposition=creation.disposition,
            job=_job_summary(creation.job),
        )

    @router.post(
        "/libraries/{library_id}/jobs/inventories",
        response_model=JobCreationResponse,
    )
    def create_inventory_job(
        request: Request,
        library_id: str,
        body: InventoryJobRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JobCreationResponse:
        creation = job_service(request, library_id).enqueue_inventory(
            full_hash_verification=body.full_hash_verification,
            idempotency_key=idempotency_key,
        )
        if creation.job.state == "queued":
            manager(request).start_jobs(library_id)
        return JobCreationResponse(
            disposition=creation.disposition,
            job=_job_summary(creation.job),
        )

    @router.post(
        "/libraries/{library_id}/jobs/extraction-batches",
        response_model=JobBatchCreationResponse,
    )
    def create_extraction_batch(
        request: Request,
        library_id: str,
        body: ExtractionBatchRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> JobBatchCreationResponse:
        creation = job_service(request, library_id).enqueue_batch(
            document_ids=body.document_ids,
            extractor_ids=body.extractor_ids,
            settings=body.settings,
            execution_mode=body.execution_mode,
            confirmed=body.confirmed,
            idempotency_key=idempotency_key,
        )
        if any(job.state == "queued" for job in creation.jobs):
            manager(request).start_jobs(library_id)
        return JobBatchCreationResponse(
            disposition=creation.disposition,
            batch=_batch_summary(creation.batch),
            jobs=[_job_summary(job) for job in creation.jobs],
        )

    @router.get(
        "/libraries/{library_id}/jobs/extraction-batches/preflight",
        response_model=ExtractionBatchPreflight,
    )
    def extraction_batch_preflight(
        request: Request,
        library_id: str,
    ) -> ExtractionBatchPreflight:
        record = job_service(request, library_id).preflight_image_only_ocr()
        return ExtractionBatchPreflight(
            **{
                **record.__dict__,
                "document_ids": list(record.document_ids),
            }
        )

    @router.get(
        "/libraries/{library_id}/jobs/extraction-batches",
        response_model=JobBatchPage,
    )
    def extraction_batches(
        request: Request,
        library_id: str,
        offset: int = 0,
        limit: int = 50,
    ) -> JobBatchPage:
        records, total = job_service(request, library_id).batches(
            offset=offset, limit=limit
        )
        return JobBatchPage(
            items=[_batch_summary(record) for record in records],
            offset=offset,
            limit=limit,
            total=total,
        )

    @router.post(
        "/libraries/{library_id}/jobs/extraction-batches/{batch_id}/cancel",
        response_model=JobBatchCancellationResponse,
    )
    def cancel_extraction_batch(
        request: Request,
        library_id: str,
        batch_id: str,
        body: JobBatchCancelRequest,
    ) -> JobBatchCancellationResponse:
        result = manager(request).cancel_batch(
            library_id,
            batch_id,
            cancel_running=body.cancel_running,
        )
        return JobBatchCancellationResponse(
            batch=_batch_summary(result.batch),
            jobs=[_job_summary(job) for job in result.jobs],
            cancel_running=result.cancel_running,
        )

    @router.get(
        "/libraries/{library_id}/jobs",
        response_model=JobPage,
    )
    def jobs(
        request: Request,
        library_id: str,
        state: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> JobPage:
        allowed: set[str] = {
            "queued",
            "starting",
            "running",
            "cancelling",
            "succeeded",
            "failed",
            "cancelled",
            "interrupted",
        }
        raw_states = tuple(
            item.strip() for item in (state or "").split(",") if item.strip()
        )
        if set(raw_states) - allowed:
            raise RequestError("job state filter contains an unknown state")
        states = cast(tuple[JobState, ...], raw_states)
        service_value = job_service(request, library_id)
        records, total = service_value.list(
            states=states,
            offset=offset,
            limit=limit,
        )
        counts = service_value.counts()
        return JobPage(
            items=[_job_summary(record) for record in records],
            offset=offset,
            limit=limit,
            total=total,
            counts=JobCounts(**counts.__dict__),
        )

    @router.get(
        "/libraries/{library_id}/jobs/queue",
        response_model=QueueState,
    )
    def job_queue(request: Request, library_id: str) -> QueueState:
        record = job_service(request, library_id).queue_state()
        return QueueState(**record.__dict__)

    @router.post(
        "/libraries/{library_id}/jobs/queue",
        response_model=QueueState,
    )
    def update_job_queue(
        request: Request,
        library_id: str,
        body: QueueUpdateRequest,
    ) -> QueueState:
        record = job_service(request, library_id).set_queue_paused(body.paused)
        if not body.paused:
            manager(request).start_jobs(library_id)
        return QueueState(**record.__dict__)

    @router.get(
        "/libraries/{library_id}/jobs/{job_id}",
        response_model=JobDetail,
    )
    def job(
        request: Request,
        library_id: str,
        job_id: str,
    ) -> JobDetail:
        service_value = job_service(request, library_id)
        record = service_value.get(job_id)
        return JobDetail(
            job=_job_summary(record),
            attempts=[
                _job_attempt(attempt) for attempt in service_value.attempts(job_id)
            ],
        )

    @router.get(
        "/libraries/{library_id}/jobs/{job_id}/events",
        response_model=JobEventPage,
    )
    def job_events(
        request: Request,
        library_id: str,
        job_id: str,
        after: int = 0,
        limit: int = 200,
    ) -> JobEventPage:
        records = job_service(request, library_id).events(
            job_id, after=after, limit=limit
        )
        return JobEventPage(
            job_id=job_id,
            after=after,
            items=[JobEvent(**record.__dict__) for record in records],
        )

    @router.get(
        "/libraries/{library_id}/jobs/{job_id}/attempts/{attempt_id}/diagnostics",
        response_model=AttemptDiagnostics,
    )
    def job_attempt_diagnostics(
        request: Request,
        library_id: str,
        job_id: str,
        attempt_id: str,
    ) -> AttemptDiagnostics:
        record = job_service(request, library_id).attempt_diagnostics(
            job_id, attempt_id
        )
        return AttemptDiagnostics(**record.__dict__)

    @router.post(
        "/libraries/{library_id}/jobs/{job_id}/cancel",
        response_model=JobDetail,
    )
    def cancel_job(request: Request, library_id: str, job_id: str) -> JobDetail:
        record = manager(request).cancel_job(library_id, job_id)
        return JobDetail(
            job=_job_summary(record),
            attempts=[
                _job_attempt(attempt)
                for attempt in job_service(request, library_id).attempts(job_id)
            ],
        )

    @router.post(
        "/libraries/{library_id}/jobs/{job_id}/retry",
        response_model=JobDetail,
    )
    def retry_job(request: Request, library_id: str, job_id: str) -> JobDetail:
        service_value = job_service(request, library_id)
        record = service_value.retry(job_id)
        manager(request).start_jobs(library_id)
        return JobDetail(
            job=_job_summary(record),
            attempts=[
                _job_attempt(attempt) for attempt in service_value.attempts(job_id)
            ],
        )

    @router.post(
        "/libraries/{library_id}/jobs/{job_id}/repair-projection",
        response_model=JobDetail,
    )
    def repair_job_projection(
        request: Request, library_id: str, job_id: str
    ) -> JobDetail:
        service_value = job_service(request, library_id)
        record = service_value.repair_projection(job_id)
        return JobDetail(
            job=_job_summary(record),
            attempts=[
                _job_attempt(attempt) for attempt in service_value.attempts(job_id)
            ],
        )

    @router.get(
        "/libraries/{library_id}/workspace",
        response_model=WorkspaceSummary,
    )
    def library_workspace(request: Request, library_id: str) -> WorkspaceSummary:
        return library_service(request, library_id).workspace()

    @router.get(
        "/libraries/{library_id}/documents",
        response_model=DocumentPage,
    )
    def library_documents(
        request: Request,
        library_id: str,
        offset: int = 0,
        limit: int = 40,
    ) -> DocumentPage:
        return library_service(request, library_id).documents(
            offset=offset,
            limit=limit,
        )

    @router.get(
        "/libraries/{library_id}/documents/{document_id}",
        response_model=DocumentDetail,
    )
    def library_document(
        request: Request,
        library_id: str,
        document_id: str,
    ) -> DocumentDetail:
        return library_service(request, library_id).document(document_id)

    @router.get(
        "/libraries/{library_id}/documents/{document_id}/pages/{page}",
        response_model=PageSummary,
    )
    def library_page(
        request: Request,
        library_id: str,
        document_id: str,
        page: int,
    ) -> PageSummary:
        return library_service(request, library_id).page(document_id, page)

    @router.get(
        "/libraries/{library_id}/documents/{document_id}/runs",
        response_model=RunList,
    )
    def library_runs(
        request: Request,
        library_id: str,
        document_id: str,
    ) -> RunList:
        return library_service(request, library_id).runs(document_id)

    @router.get(
        "/libraries/{library_id}/documents/{document_id}/pages/{page}/groups",
        response_model=PageGroups,
    )
    def library_groups(
        request: Request,
        library_id: str,
        document_id: str,
        page: int,
    ) -> PageGroups:
        return library_service(request, library_id).page_groups(document_id, page)

    @router.get("/libraries/{library_id}/documents/{document_id}/pages/{page}/render")
    def library_render(
        request: Request,
        library_id: str,
        document_id: str,
        page: int,
    ) -> FileResponse:
        artifact = library_service(request, library_id).render_page(document_id, page)
        return FileResponse(
            artifact.path,
            media_type=artifact.media_type,
            filename=artifact.filename,
            content_disposition_type="inline",
        )

    @router.get(
        "/libraries/{library_id}/search",
        response_model=SearchPage,
    )
    def library_search(
        request: Request,
        library_id: str,
        query: str,
        mode: Literal["literal", "fts"] = "literal",
        limit: int = 40,
    ) -> SearchPage:
        return library_service(request, library_id).search(
            query=query,
            mode=mode,
            limit=limit,
        )

    @router.post(
        "/libraries/{library_id}/comparisons",
        response_model=ComparisonResult,
    )
    def library_compare(
        request: Request,
        library_id: str,
        body: ComparisonRequest,
    ) -> ComparisonResult:
        return library_service(request, library_id).compare(body)

    @router.get("/libraries/{library_id}/artifacts/{artifact_id}")
    def library_artifact(
        request: Request,
        library_id: str,
        artifact_id: str,
    ) -> FileResponse:
        value = library_service(request, library_id).artifact(artifact_id)
        return FileResponse(
            value.path,
            media_type=value.media_type,
            filename=value.filename,
            content_disposition_type="inline",
        )

    @router.get(
        "/libraries/{library_id}/diagnostics",
        response_model=Diagnostics,
    )
    def library_diagnostics(request: Request, library_id: str) -> Diagnostics:
        return library_service(request, library_id).diagnostics()

    @router.get("/workspace", response_model=WorkspaceSummary)
    def workspace(request: Request) -> WorkspaceSummary:
        return service(request).workspace()

    @router.get("/documents", response_model=DocumentPage)
    def documents(request: Request, offset: int = 0, limit: int = 40) -> DocumentPage:
        return service(request).documents(offset=offset, limit=limit)

    @router.get("/documents/{document_id}", response_model=DocumentDetail)
    def document(request: Request, document_id: str) -> DocumentDetail:
        return service(request).document(document_id)

    @router.get("/documents/{document_id}/pages/{page}", response_model=PageSummary)
    def page(request: Request, document_id: str, page: int) -> PageSummary:
        return service(request).page(document_id, page)

    @router.get("/documents/{document_id}/runs", response_model=RunList)
    def runs(request: Request, document_id: str) -> RunList:
        return service(request).runs(document_id)

    @router.get(
        "/documents/{document_id}/pages/{page}/groups",
        response_model=PageGroups,
    )
    def groups(request: Request, document_id: str, page: int) -> PageGroups:
        return service(request).page_groups(document_id, page)

    @router.get("/documents/{document_id}/pages/{page}/render")
    def render(request: Request, document_id: str, page: int) -> FileResponse:
        artifact = service(request).render_page(document_id, page)
        return FileResponse(
            artifact.path,
            media_type=artifact.media_type,
            filename=artifact.filename,
            content_disposition_type="inline",
        )

    @router.get("/search", response_model=SearchPage)
    def search(
        request: Request,
        query: str,
        mode: Literal["literal", "fts"] = "literal",
        limit: int = 40,
    ) -> SearchPage:
        return service(request).search(query=query, mode=mode, limit=limit)

    @router.post("/comparisons", response_model=ComparisonResult)
    def compare(request: Request, body: ComparisonRequest) -> ComparisonResult:
        return service(request).compare(body)

    @router.get("/artifacts/{artifact_id}")
    def artifact(request: Request, artifact_id: str) -> FileResponse:
        value = service(request).artifact(artifact_id)
        return FileResponse(
            value.path,
            media_type=value.media_type,
            filename=value.filename,
            content_disposition_type="inline",
        )

    @router.get("/diagnostics", response_model=Diagnostics)
    def diagnostics(request: Request) -> Diagnostics:
        return service(request).diagnostics()

    app.include_router(router)

    if desktop_control_handshake is not None:
        control_router = APIRouter(
            prefix="/desktop-control/v1",
            dependencies=[Depends(authorize_control)],
        )

        @control_router.get("/handshake", response_model=DesktopControlHandshake)
        def desktop_host_handshake() -> DesktopControlHandshake:
            return desktop_control_handshake

        @control_router.post(
            "/libraries/register-existing",
            response_model=DesktopLibraryResult,
        )
        def desktop_register_existing(
            body: DesktopRegisterLibraryRequest,
        ) -> DesktopLibraryResult:
            if desktop_library_control is None:
                raise NotFoundError("desktop library control is not active")
            return desktop_library_control.register_existing(body)

        @control_router.post(
            "/libraries/create-managed",
            response_model=DesktopLibraryResult,
        )
        def desktop_create_managed(
            body: DesktopCreateLibraryRequest,
        ) -> DesktopLibraryResult:
            if desktop_library_control is None:
                raise NotFoundError("desktop library control is not active")
            return desktop_library_control.create_managed(body)

        @control_router.post(
            "/libraries/add-collection",
            response_model=DesktopCollectionResult,
        )
        def desktop_add_collection(
            body: DesktopAddCollectionRequest,
        ) -> DesktopCollectionResult:
            if desktop_library_control is None:
                raise NotFoundError("desktop library control is not active")
            return desktop_library_control.add_collection(body)

        app.include_router(control_router)

    @app.exception_handler(NotFoundError)
    async def not_found(_: Request, error: NotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=ApiProblem(code="not_found", message=str(error)).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_contract(
        _: Request, error: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=ApiProblem(
                code="invalid_request",
                message=f"request payload or parameters are invalid ({len(error.errors())} error(s))",
            ).model_dump(),
        )

    @app.exception_handler(RequestError)
    async def invalid_request(_: Request, error: RequestError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content=ApiProblem(code="invalid_request", message=str(error)).model_dump(),
        )

    @app.exception_handler(DependencyError)
    async def dependency_error(_: Request, error: DependencyError) -> JSONResponse:
        return JSONResponse(
            status_code=503,
            content=ApiProblem(
                code="dependency_unavailable", message=str(error)
            ).model_dump(),
        )

    @app.exception_handler(DocEvidenceError)
    async def operational_error(_: Request, error: DocEvidenceError) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content=ApiProblem(
                code="operation_failed", message=str(error)
            ).model_dump(),
        )

    if static_dir is not None:
        resolved_static = static_dir.resolve()
        if not (resolved_static / "index.html").is_file():
            raise RequestError(
                f"frontend build is missing at {resolved_static}; run npm run build --prefix web"
            )
        app.mount("/", StaticFiles(directory=resolved_static, html=True), name="web")
    return app


def create_contract_app() -> FastAPI:
    """Create the route graph used for deterministic OpenAPI generation."""

    return create_app(
        None,
        launch_token="contract-generation-token",
        desktop_handshake=create_desktop_handshake(
            platform="macos",
            architecture="arm64",
            application_home_source="desktop_host",
            baseline_pack=None,
        ),
    )
