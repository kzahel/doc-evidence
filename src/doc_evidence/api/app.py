"""Authenticated, origin-bounded FastAPI adapter."""

from __future__ import annotations

import hmac
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from doc_evidence.application.library import LibraryApplication
from doc_evidence.contracts.api import (
    ApiProblem,
    ComparisonRequest,
    ComparisonResult,
    Diagnostics,
    DocumentDetail,
    DocumentPage,
    PageGroups,
    PageSummary,
    RunList,
    SearchPage,
    WorkspaceSummary,
)
from doc_evidence.errors import (
    DependencyError,
    DocEvidenceError,
    NotFoundError,
    RequestError,
)

_bearer = HTTPBearer(auto_error=False)


def create_app(
    application: LibraryApplication | None,
    *,
    launch_token: str,
    allowed_origins: set[str] | None = None,
    static_dir: Path | None = None,
    on_started: Callable[[], None] | None = None,
) -> FastAPI:
    origins = frozenset(allowed_origins or set())

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if on_started is not None:
            on_started()
        yield

    app = FastAPI(
        title="doc-evidence local API",
        version="1",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.application = application

    @app.middleware("http")
    async def origin_and_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        origin = request.headers.get("origin")
        is_api = request.url.path.startswith("/api/v1/")
        if is_api and origin and origin not in origins:
            return JSONResponse(
                status_code=403,
                content=ApiProblem(
                    code="origin_not_allowed",
                    message="request origin is not allowed",
                ).model_dump(),
            )
        if is_api and request.method == "OPTIONS":
            response = Response(status_code=204)
            if origin:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Headers"] = (
                "Authorization, Content-Type"
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

    def service(request: Request) -> LibraryApplication:
        value = request.app.state.application
        if value is None:
            raise RuntimeError("contract-only application has no service")
        return value

    router = APIRouter(prefix="/api/v1", dependencies=[Depends(authorize)])

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

    @app.exception_handler(NotFoundError)
    async def not_found(_: Request, error: NotFoundError) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=ApiProblem(code="not_found", message=str(error)).model_dump(),
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

    return create_app(None, launch_token="contract-generation-token")
