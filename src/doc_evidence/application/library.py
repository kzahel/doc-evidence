"""Read-only library and comparison use cases independent of HTTP/storage."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from doc_evidence.comparisons import word_numeric_diff
from doc_evidence.contracts.api import (
    BenchmarkAssertion,
    ComparisonRequest,
    ComparisonResult,
    Diagnostics,
    DocumentDetail,
    DocumentPage,
    ExtractorRun,
    OutputGroup,
    PageGroups,
    PageSummary,
    RunList,
    SearchPage,
    WorkspaceSummary,
)
from doc_evidence.errors import NotFoundError, RequestError
from doc_evidence.util import hash_json


@dataclass(frozen=True)
class RunPages:
    run: ExtractorRun
    pages: dict[int, str]


@dataclass(frozen=True)
class BinaryArtifact:
    path: Path
    media_type: str
    filename: str


class LibraryPort(Protocol):
    def workspace(self) -> WorkspaceSummary: ...

    def documents(self, *, offset: int, limit: int) -> DocumentPage: ...

    def document(self, document_id: str) -> DocumentDetail: ...

    def search(
        self, *, query: str, mode: Literal["literal", "fts"], limit: int
    ) -> SearchPage: ...

    def run_pages(self, document_id: str) -> list[RunPages]: ...

    def benchmark_assertions(
        self, document_id: str, page: int
    ) -> list[BenchmarkAssertion]: ...

    def render_page(self, document_id: str, page: int) -> BinaryArtifact: ...

    def artifact(self, artifact_id: str) -> BinaryArtifact: ...

    def diagnostics(self) -> Diagnostics: ...


class LibraryApplication:
    """Coordinate bounded library reads and reproducible comparisons."""

    def __init__(self, port: LibraryPort):
        self.port = port

    def workspace(self) -> WorkspaceSummary:
        return self.port.workspace()

    def documents(self, *, offset: int = 0, limit: int = 40) -> DocumentPage:
        if offset < 0:
            raise RequestError("document offset may not be negative")
        if limit < 1 or limit > 100:
            raise RequestError("document limit must be between 1 and 100")
        return self.port.documents(offset=offset, limit=limit)

    def document(self, document_id: str) -> DocumentDetail:
        return self.port.document(document_id)

    def search(
        self,
        *,
        query: str,
        mode: Literal["literal", "fts"],
        limit: int = 40,
    ) -> SearchPage:
        query = query.strip()
        if not query:
            raise RequestError("search query may not be empty")
        if len(query) > 500:
            raise RequestError("search query may not exceed 500 characters")
        if mode not in {"literal", "fts"}:
            raise RequestError("search mode must be literal or fts")
        if limit < 1 or limit > 100:
            raise RequestError("search limit must be between 1 and 100")
        return self.port.search(query=query, mode=mode, limit=limit)

    def runs(self, document_id: str) -> RunList:
        return RunList(
            document_id=document_id,
            items=[record.run for record in self.port.run_pages(document_id)],
        )

    def page(self, document_id: str, page: int) -> PageSummary:
        document = self.port.document(document_id)
        page_count = document.page_count or 0
        if document.media_type != "application/pdf" or page_count < 1:
            raise RequestError("document does not have renderable PDF pages")
        if page < 1 or page > page_count:
            raise NotFoundError(f"page {page} is outside document range 1-{page_count}")
        return PageSummary(
            document_id=document_id,
            page=page,
            page_count=page_count,
            media_type=document.media_type,
            render_available=True,
        )

    def page_groups(self, document_id: str, page: int) -> PageGroups:
        page_summary = self.page(document_id, page)
        records = self.port.run_pages(document_id)
        grouped: dict[tuple[str, str], list[RunPages]] = {}
        for record in records:
            run = record.run
            status = run.status
            run_ref = run.run_ref
            text = record.pages.get(page, "")
            key = ("ok", text) if status == "ok" else (run_ref, text)
            grouped.setdefault(key, []).append(record)

        groups: list[OutputGroup] = []
        for key, members in grouped.items():
            text = members[0].pages.get(page, "")
            runs = sorted(
                [member.run for member in members],
                key=lambda run: (
                    {
                        "native_text": 0,
                        "ocr_preprocessing": 1,
                        "layout_parser": 2,
                        "other": 3,
                    }[run.category],
                    run.extractor_id,
                    run.run_ref,
                ),
            )
            exact_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
            group_id = "group:" + hash_json(
                {
                    "document_id": document_id,
                    "page": page,
                    "key": key,
                    "run_refs": [run.run_ref for run in runs],
                }
            )
            groups.append(
                OutputGroup(
                    group_id=group_id,
                    exact_text_sha256=exact_hash,
                    representative_run_ref=runs[0].run_ref,
                    text=text,
                    runs=runs,
                )
            )
        groups.sort(
            key=lambda group: (
                -len(group.runs),
                group.runs[0].category,
                group.runs[0].extractor_id,
                group.group_id,
            )
        )
        return PageGroups(
            document_id=document_id,
            page=page,
            page_count=page_summary.page_count,
            groups=groups,
            assertions=self.port.benchmark_assertions(document_id, page),
        )

    def compare(self, request: ComparisonRequest) -> ComparisonResult:
        self.page(request.document_id, request.page)
        by_ref = {
            record.run.run_ref: record
            for record in self.port.run_pages(request.document_id)
        }
        try:
            left = by_ref[request.left_run_ref]
            right = by_ref[request.right_run_ref]
        except KeyError as error:
            raise NotFoundError("comparison extractor run was not found") from error
        try:
            return word_numeric_diff(
                document_id=request.document_id,
                page=request.page,
                left_run_ref=request.left_run_ref,
                right_run_ref=request.right_run_ref,
                left_text=left.pages.get(request.page, ""),
                right_text=right.pages.get(request.page, ""),
            )
        except ValueError as error:
            raise RequestError(str(error)) from error

    def render_page(self, document_id: str, page: int) -> BinaryArtifact:
        self.page(document_id, page)
        return self.port.render_page(document_id, page)

    def artifact(self, artifact_id: str) -> BinaryArtifact:
        return self.port.artifact(artifact_id)

    def diagnostics(self) -> Diagnostics:
        return self.port.diagnostics()
