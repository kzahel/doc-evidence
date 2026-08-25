"""Read-only SQLite/artifact adapter for an explicitly configured workspace."""

from __future__ import annotations

import json
import mimetypes
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Literal

from doc_evidence import __version__
from doc_evidence.app_home import legacy_library_id
from doc_evidence.application.library import BinaryArtifact, RunPages
from doc_evidence.config import AppConfig
from doc_evidence.contracts.api import (
    BenchmarkAssertion,
    CollectionSummary,
    DiagnosticCheck,
    Diagnostics,
    DocumentDetail,
    DocumentPage,
    DocumentSummary,
    DuplicateGroup,
    ExtractorRun,
    RawArtifact,
    SearchHit,
    SearchPage,
    SourceOccurrence,
    WorkspaceSummary,
)
from doc_evidence.errors import CatalogError, NotFoundError, RequestError
from doc_evidence.persistence import ensure_library_database
from doc_evidence.platform_paths import extended_length_path, ordinary_windows_path
from doc_evidence.rendering import PageRenderer
from doc_evidence.util import hash_file, hash_json


class LocalWorkspace:
    def __init__(
        self,
        config: AppConfig,
        library_id: str | None = None,
        library_name: str | None = None,
    ):
        self.config = config
        self.library_id = library_id or legacy_library_id(config.path)
        self.library_name = (
            library_name or config.path.parent.name or "Document Library"
        )
        self.store = config.filesystem_store.resolve()
        self.catalog_path = ensure_library_database(
            config,
            library_id=self.library_id,
        ).path
        if not self.catalog_path.is_file():
            raise CatalogError(
                f"catalog does not exist: {self.catalog_path}; run inventory first"
            )
        self._artifact_paths: dict[str, Path] = {}
        self._renderer: PageRenderer | None = None

    def _connect(self) -> sqlite3.Connection:
        sqlite_path = ordinary_windows_path(self.catalog_path)
        try:
            connection = sqlite3.connect(
                f"file:{sqlite_path.as_posix()}?mode=ro", uri=True
            )
        except sqlite3.Error as error:
            raise CatalogError(f"cannot open catalog: {error}") from error
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        return connection

    @staticmethod
    def _source_hint(row: sqlite3.Row) -> str:
        return f"{row['collection_id']}:{row['relative_path']}"

    def _summary_query(self) -> str:
        return """
            SELECT d.*,
                   first_source.collection_id,
                   first_source.relative_path,
                   (SELECT COUNT(*) - 1 FROM source_occurrences all_sources
                    WHERE all_sources.generation_id = active.active_generation_id
                      AND all_sources.content_sha256 = d.content_sha256)
                   +
                   (SELECT COUNT(DISTINCT peers.content_sha256)
                    FROM duplicate_members mine
                    JOIN duplicate_members peers
                      ON peers.generation_id = mine.generation_id
                     AND peers.kind = mine.kind
                     AND peers.group_key = mine.group_key
                    WHERE mine.generation_id = active.active_generation_id
                      AND mine.content_sha256 = d.content_sha256
                      AND peers.content_sha256 != d.content_sha256)
                   AS duplicate_count
            FROM content_objects d
            JOIN library_metadata active ON active.singleton = 1
            JOIN source_occurrences first_source
              ON first_source.rowid = (
                  SELECT source.rowid FROM source_occurrences source
                  WHERE source.generation_id = active.active_generation_id
                    AND source.content_sha256 = d.content_sha256
                  ORDER BY source.collection_id, source.relative_path
                  LIMIT 1
              )
            WHERE EXISTS (
                SELECT 1 FROM generation_documents member
                WHERE member.generation_id = active.active_generation_id
                  AND member.content_sha256 = d.content_sha256
            )
        """

    def _document_summary(self, row: sqlite3.Row) -> DocumentSummary:
        warnings = json.loads(row["warnings_json"])
        return DocumentSummary(
            document_id=row["document_id"],
            source_path_hint=self._source_hint(row),
            media_type=row["media_type"],
            size_bytes=row["size_bytes"],
            page_count=row["page_count"],
            inventory_status=row["inventory_status"],
            extraction_status=row["extraction_status"],
            duplicate_count=max(0, int(row["duplicate_count"] or 0)),
            warning_count=len(warnings),
        )

    def _catalog_metadata(self, connection: sqlite3.Connection) -> dict[str, str]:
        row = connection.execute(
            """
            SELECT m.*, g.inventory_run_id, g.completed_at, g.summary_json,
                   g.selected_collections_json
            FROM library_metadata m
            LEFT JOIN inventory_generations g
              ON g.generation_id = m.active_generation_id
            WHERE m.singleton = 1
            """
        ).fetchone()
        if row is None:
            return {}
        return {
            "schema_version": "1",
            "library_id": str(row["library_id"]),
            "config_hash": str(row["config_hash"]),
            "fts_enabled": str(row["fts_enabled"]),
            "inventory_run_id": str(row["inventory_run_id"] or ""),
            "created_at": str(row["completed_at"] or ""),
            "selected_collections": str(row["selected_collections_json"] or "[]"),
            "summary": str(row["summary_json"] or "{}"),
        }

    def workspace(self) -> WorkspaceSummary:
        connection = self._connect()
        try:
            metadata = self._catalog_metadata(connection)
            generation_id = connection.execute(
                "SELECT active_generation_id FROM library_metadata WHERE singleton = 1"
            ).fetchone()[0]
            document_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM generation_documents WHERE generation_id = ?",
                    (generation_id,),
                ).fetchone()[0]
            )
            source_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM source_occurrences WHERE generation_id = ?",
                    (generation_id,),
                ).fetchone()[0]
            )
        finally:
            connection.close()
        return WorkspaceSummary(
            library_id=self.library_id,
            library_name=self.library_name,
            product_version=__version__,
            config_hash=self.config.config_hash,
            catalog_inventory_run_id=metadata.get("inventory_run_id"),
            catalog_created_at=metadata.get("created_at"),
            collections=[
                CollectionSummary(
                    collection_id=collection.id,
                    source_label=collection.source.name or collection.id,
                )
                for collection in self.config.collections
            ],
            document_count=document_count,
            source_occurrence_count=source_count,
        )

    def documents(self, *, offset: int, limit: int) -> DocumentPage:
        connection = self._connect()
        try:
            total = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM generation_documents
                    WHERE generation_id = (
                        SELECT active_generation_id FROM library_metadata
                        WHERE singleton = 1
                    )
                    """
                ).fetchone()[0]
            )
            rows = connection.execute(
                self._summary_query()
                + " ORDER BY lower(first_source.relative_path), d.document_id "
                + " LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        except sqlite3.Error as error:
            raise CatalogError(f"cannot list documents: {error}") from error
        finally:
            connection.close()
        return DocumentPage(
            items=[self._document_summary(row) for row in rows],
            offset=offset,
            limit=limit,
            total=total,
        )

    def document(self, document_id: str) -> DocumentDetail:
        connection = self._connect()
        try:
            row = connection.execute(
                self._summary_query() + " AND d.document_id = ?",
                (document_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"document was not found: {document_id}")
            source_rows = connection.execute(
                """
                SELECT collection_id, relative_path, size_bytes, modified_ns,
                       observed_at
                FROM source_occurrences
                WHERE generation_id = (
                    SELECT active_generation_id FROM library_metadata WHERE singleton = 1
                ) AND content_sha256 = ?
                ORDER BY collection_id, relative_path
                """,
                (document_id.removeprefix("sha256:"),),
            ).fetchall()
            duplicate_rows = connection.execute(
                """
                SELECT kind, group_key, COUNT(*) AS member_count
                FROM duplicate_members
                WHERE generation_id = (
                    SELECT active_generation_id FROM library_metadata WHERE singleton = 1
                ) AND (kind, group_key) IN (
                    SELECT kind, group_key FROM duplicate_members
                    WHERE generation_id = (
                        SELECT active_generation_id FROM library_metadata WHERE singleton = 1
                    ) AND content_sha256 = ?
                )
                GROUP BY kind, group_key
                ORDER BY kind, group_key
                """,
                (document_id.removeprefix("sha256:"),),
            ).fetchall()
        except sqlite3.Error as error:
            raise CatalogError(f"cannot read document: {error}") from error
        finally:
            connection.close()
        summary = self._document_summary(row)
        return DocumentDetail(
            **summary.model_dump(),
            content_sha256=row["content_sha256"],
            sources=[
                SourceOccurrence(
                    collection_id=item["collection_id"],
                    relative_path=item["relative_path"],
                    size_bytes=item["size_bytes"],
                    modified_ns=item["modified_ns"],
                    observed_at=item["observed_at"],
                )
                for item in source_rows
            ],
            pdf_metadata=json.loads(row["pdf_metadata_json"] or "{}"),
            warnings=json.loads(row["warnings_json"]),
            duplicate_groups=[
                DuplicateGroup(
                    kind=item["kind"],
                    group_key=item["group_key"],
                    member_count=item["member_count"],
                )
                for item in duplicate_rows
            ],
        )

    def search(
        self, *, query: str, mode: Literal["literal", "fts"], limit: int
    ) -> SearchPage:
        connection = self._connect()
        try:
            if mode == "literal":
                rows = connection.execute(
                    """
                    SELECT p.document_id, p.page_number, p.text,
                           first_source.collection_id,
                           first_source.relative_path
                    FROM (
                        SELECT c.document_id, rp.content_sha256, rp.page_number,
                               rp.text, er.extractor_id,
                               ROW_NUMBER() OVER (
                                   PARTITION BY rp.content_sha256, rp.page_number
                                   ORDER BY CASE WHEN er.extractor_id = 'poppler'
                                                 THEN 0 ELSE 1 END,
                                            er.extractor_id, er.run_id
                               ) AS representation_rank
                        FROM run_pages rp
                        JOIN extraction_runs er
                          ON er.content_sha256 = rp.content_sha256
                         AND er.run_id = rp.run_id
                        JOIN content_objects c
                          ON c.content_sha256 = rp.content_sha256
                        JOIN generation_documents member
                          ON member.content_sha256 = rp.content_sha256
                         AND member.generation_id = (
                             SELECT active_generation_id FROM library_metadata
                             WHERE singleton = 1
                         )
                        WHERE er.status = 'ok'
                          AND instr(lower(rp.text), lower(?)) > 0
                    ) p
                    JOIN source_occurrences first_source
                      ON first_source.rowid = (
                          SELECT source.rowid FROM source_occurrences source
                          WHERE source.generation_id = (
                              SELECT active_generation_id FROM library_metadata
                              WHERE singleton = 1
                          ) AND source.content_sha256 = p.content_sha256
                          ORDER BY source.collection_id, source.relative_path
                          LIMIT 1
                      )
                    WHERE p.representation_rank = 1
                    ORDER BY p.document_id, p.page_number
                    LIMIT ?
                    """,
                    (query, limit),
                ).fetchall()
                items = [
                    SearchHit(
                        document_id=row["document_id"],
                        page=row["page_number"],
                        source_path_hint=self._source_hint(row),
                        snippet=self._literal_snippet(row["text"], query),
                        score=None,
                    )
                    for row in rows
                ]
            else:
                enabled = connection.execute(
                    "SELECT fts_enabled FROM library_metadata WHERE singleton = 1"
                ).fetchone()
                if enabled is None or enabled["fts_enabled"] != 1:
                    raise RequestError("this catalog was built without SQLite FTS")
                try:
                    rows = connection.execute(
                        """
                        SELECT 'sha256:' || f.content_sha256 AS document_id,
                               f.page_number,
                               snippet(pages_fts, 4, '[', ']', ' … ', 24) AS snippet,
                               bm25(pages_fts) AS score,
                               first_source.collection_id,
                               first_source.relative_path
                        FROM pages_fts f
                        JOIN generation_documents member
                          ON member.content_sha256 = f.content_sha256
                         AND member.generation_id = (
                             SELECT active_generation_id FROM library_metadata
                             WHERE singleton = 1
                         )
                        JOIN source_occurrences first_source
                          ON first_source.rowid = (
                              SELECT source.rowid FROM source_occurrences source
                              WHERE source.generation_id = member.generation_id
                                AND source.content_sha256 = f.content_sha256
                              ORDER BY source.collection_id, source.relative_path
                              LIMIT 1
                          )
                        WHERE pages_fts MATCH ?
                        ORDER BY score
                        LIMIT ?
                        """,
                        (query, limit),
                    ).fetchall()
                except sqlite3.Error as error:
                    raise RequestError(f"invalid FTS query: {error}") from error
                items = [
                    SearchHit(
                        document_id=row["document_id"],
                        page=row["page_number"],
                        source_path_hint=self._source_hint(row),
                        snippet=row["snippet"],
                        score=float(row["score"]),
                    )
                    for row in rows
                ]
        except sqlite3.Error as error:
            raise CatalogError(f"catalog search failed: {error}") from error
        finally:
            connection.close()
        return SearchPage(query=query, mode=mode, items=items, limit=limit)

    @staticmethod
    def _literal_snippet(text: str, query: str, radius: int = 110) -> str:
        position = max(text.casefold().find(query.casefold()), 0)
        start = max(0, position - radius)
        end = min(len(text), position + len(query) + radius)
        result = " ".join(text[start:end].split())
        return ("… " if start else "") + result + (" …" if end < len(text) else "")

    @staticmethod
    def _extractor_category(
        extractor_id: str,
    ) -> Literal["native_text", "ocr_preprocessing", "layout_parser", "other"]:
        if extractor_id == "poppler":
            return "native_text"
        if extractor_id == "ocrmypdf-tesseract":
            return "ocr_preprocessing"
        if extractor_id in {"docling-standard", "marker-fast"}:
            return "layout_parser"
        return "other"

    @staticmethod
    def _version_label(extractor_id: str, descriptor: dict[str, Any]) -> str:
        if descriptor.get("version"):
            return str(descriptor["version"])
        if extractor_id == "ocrmypdf-tesseract":
            return (
                " / ".join(
                    str(descriptor[key])
                    for key in ("ocrmypdf_version", "tesseract_version")
                    if descriptor.get(key)
                )
                or "version unavailable"
            )
        if extractor_id == "poppler":
            return str(
                descriptor.get("pdftotext_version")
                or descriptor.get("pdfinfo_version")
                or "version unavailable"
            )
        return "version unavailable"

    def _safe_artifact(self, run_dir: Path, candidate: Path) -> Path | None:
        try:
            resolved_run = run_dir.resolve()
            resolved = candidate.resolve()
            resolved.relative_to(resolved_run)
            resolved.relative_to(self.store)
        except (OSError, ValueError):
            return None
        return resolved if resolved.is_file() and not resolved.is_symlink() else None

    def _register_artifacts(
        self, document_id: str, run_dir: Path, values: dict[str, Any]
    ) -> list[RawArtifact]:
        output: list[RawArtifact] = []
        seen: set[Path] = set()
        for label, raw_relative in sorted(values.items()):
            if not isinstance(raw_relative, str):
                continue
            target = run_dir / raw_relative
            candidates = (
                sorted(target.rglob("*"))[:100] if target.is_dir() else [target]
            )
            for candidate in candidates:
                safe = self._safe_artifact(run_dir, candidate)
                if safe is None or safe in seen:
                    continue
                seen.add(safe)
                relative = safe.relative_to(self.store).as_posix()
                artifact_id = "artifact:" + hash_json(
                    {"document_id": document_id, "relative_path": relative}
                )
                self._artifact_paths[artifact_id] = safe
                suffix = safe.relative_to(target).as_posix() if target.is_dir() else ""
                output.append(
                    RawArtifact(
                        artifact_id=artifact_id,
                        label=f"{label}/{suffix}" if suffix else label,
                        media_type=mimetypes.guess_type(safe.name)[0]
                        or "application/octet-stream",
                        size_bytes=safe.stat().st_size,
                    )
                )
        return output

    @staticmethod
    def _page_texts(run_dir: Path, extractor_id: str) -> dict[int, str]:
        normalized_path = run_dir / "normalized.json"
        if normalized_path.is_file():
            normalized = json.loads(normalized_path.read_text(encoding="utf-8"))
            return {
                int(item["page_number"]): str(item["text"])
                for item in normalized.get("pages", [])
            }
        if extractor_id == "poppler":
            text = (run_dir / "text.txt").read_text(encoding="utf-8")
            rows = json.loads((run_dir / "pages.json").read_text(encoding="utf-8"))
            return {
                int(item["page_number"]): text[
                    int(item["start_offset"]) : int(item["end_offset"])
                ]
                for item in rows
            }
        return {}

    def run_pages(self, document_id: str) -> list[RunPages]:
        document = self.document(document_id)
        blob_dir = (
            self.store / "blobs" / document.content_sha256[:2] / document.content_sha256
        )
        output: list[RunPages] = []
        for run_path in sorted(blob_dir.glob("runs/*/*/run.json")):
            run_dir = run_path.parent
            extractor_id = run_dir.parent.name
            if extractor_id == "page-render":
                continue
            try:
                run = json.loads(run_path.read_text(encoding="utf-8"))
                descriptor = run.get("descriptor")
                if not isinstance(descriptor, dict):
                    descriptor = {}
                page_texts = self._page_texts(run_dir, extractor_id)
                raw_values = run.get("raw_artifacts") or run.get("raw_outputs") or {}
                if not isinstance(raw_values, dict):
                    raw_values = {}
                relative_run = run_dir.relative_to(self.store).as_posix()
                run_ref = "run:" + hash_json(
                    {"document_id": document_id, "relative_run": relative_run}
                )
                table_count: int | None = None
                normalized_path = run_dir / "normalized.json"
                if normalized_path.is_file():
                    normalized = json.loads(normalized_path.read_text(encoding="utf-8"))
                    raw_table_count = normalized.get("table_count")
                    if isinstance(raw_table_count, int):
                        table_count = raw_table_count
                output.append(
                    RunPages(
                        run=ExtractorRun(
                            run_ref=run_ref,
                            extractor_id=extractor_id,
                            category=self._extractor_category(extractor_id),
                            status=str(run.get("status", "unknown")),
                            run_id=str(run.get("run_id", f"{extractor_id}:unknown")),
                            run_key=str(run.get("run_key", run_dir.name)),
                            version_label=self._version_label(extractor_id, descriptor),
                            descriptor=descriptor,
                            warnings=[str(item) for item in run.get("warnings", [])],
                            runtime_seconds=(
                                float(run["runtime_seconds"])
                                if isinstance(run.get("runtime_seconds"), (int, float))
                                else None
                            ),
                            page_count=len(page_texts),
                            table_count=table_count,
                            raw_artifacts=self._register_artifacts(
                                document_id, run_dir, raw_values
                            ),
                        ),
                        pages=page_texts,
                    )
                )
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValueError,
            ):
                continue
        output.sort(
            key=lambda item: (
                item.run.category,
                item.run.extractor_id,
                item.run.run_ref,
            )
        )
        return output

    def benchmark_assertions(
        self, document_id: str, page: int
    ) -> list[BenchmarkAssertion]:
        output: list[BenchmarkAssertion] = []
        benchmark_root = self.store / "benchmarks"
        if not benchmark_root.is_dir():
            return output
        for pointer_path in sorted(benchmark_root.glob("*/latest-run.json")):
            try:
                pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
                report_path = self._safe_artifact(
                    benchmark_root, self.store / str(pointer["report"])
                )
                if report_path is None:
                    continue
                report = json.loads(report_path.read_text(encoding="utf-8"))
                for document in report.get("documents", []):
                    if document.get("document_id") != document_id:
                        continue
                    for extractor_id, assertions in document.get(
                        "assertions", {}
                    ).items():
                        for assertion in assertions:
                            assertion_page = assertion.get("page")
                            if assertion_page is not None and assertion_page != page:
                                continue
                            output.append(
                                BenchmarkAssertion(
                                    suite_id=str(report["suite_id"]),
                                    benchmark_run_id=str(report["benchmark_run_id"]),
                                    extractor_id=str(extractor_id),
                                    assertion_id=str(assertion["assertion_id"]),
                                    kind=str(assertion["kind"]),
                                    expected=assertion.get("expected"),
                                    actual=assertion.get("actual"),
                                    manually_verified=bool(
                                        assertion.get("manually_verified")
                                    ),
                                    passed=bool(assertion.get("passed")),
                                )
                            )
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValueError,
            ):
                continue
        return output

    def _resolve_source(self, document: DocumentDetail) -> Path:
        roots = {
            collection.id: extended_length_path(collection.source).resolve()
            for collection in self.config.collections
        }
        for source in document.sources:
            root = roots.get(source.collection_id)
            if root is None:
                continue
            try:
                candidate = (root / source.relative_path).resolve()
                candidate.relative_to(root)
            except (OSError, ValueError):
                continue
            if not candidate.is_file():
                continue
            try:
                if hash_file(candidate).content_sha256 == document.content_sha256:
                    return candidate
            except OSError:
                continue
        raise NotFoundError("no unchanged configured source occurrence is available")

    def render_page(self, document_id: str, page: int) -> BinaryArtifact:
        document = self.document(document_id)
        source = self._resolve_source(document)
        if self._renderer is None:
            self._renderer = PageRenderer(self.store)
        result = self._renderer.render(
            source=source,
            source_sha256=document.content_sha256,
            page=page,
        )
        return BinaryArtifact(
            path=result.path,
            media_type=result.media_type,
            filename=result.path.name,
        )

    def artifact(self, artifact_id: str) -> BinaryArtifact:
        path = self._artifact_paths.get(artifact_id)
        if path is None:
            connection = self._connect()
            try:
                ids = [
                    row["document_id"]
                    for row in connection.execute(
                        """
                    SELECT c.document_id
                    FROM content_objects c
                    JOIN generation_documents member
                      ON member.content_sha256 = c.content_sha256
                     AND member.generation_id = (
                         SELECT active_generation_id FROM library_metadata
                         WHERE singleton = 1
                     )
                    ORDER BY c.document_id
                    """
                    )
                ]
            finally:
                connection.close()
            for document_id in ids:
                self.run_pages(document_id)
                path = self._artifact_paths.get(artifact_id)
                if path is not None:
                    break
        if path is None or not path.is_file():
            raise NotFoundError("artifact was not found")
        try:
            path.resolve().relative_to(self.store)
        except ValueError as error:
            raise NotFoundError("artifact was not found") from error
        return BinaryArtifact(
            path=path,
            media_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            filename=path.name,
        )

    def diagnostics(self) -> Diagnostics:
        checks: list[DiagnosticCheck] = []
        connection = self._connect()
        try:
            metadata = self._catalog_metadata(connection)
            checks.append(
                DiagnosticCheck(name="catalog", status="ok", detail="readable")
            )
        except CatalogError as error:
            metadata = {}
            checks.append(
                DiagnosticCheck(name="catalog", status="error", detail=str(error))
            )
        finally:
            connection.close()
        renderer = shutil.which("pdftoppm")
        checks.append(
            DiagnosticCheck(
                name="page_renderer",
                status="ok" if renderer else "warning",
                detail=renderer or "pdftoppm is unavailable",
            )
        )
        checks.append(
            DiagnosticCheck(
                name="network_boundary",
                status="ok",
                detail="no remote adapters are enabled",
            )
        )
        return Diagnostics(checks=checks, catalog_metadata=metadata)
