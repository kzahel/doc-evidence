"""Phase 1 deterministic inventory and Poppler extraction orchestration."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from doc_evidence.config import AppConfig, CollectionConfig
from doc_evidence.discovery import discover_files
from doc_evidence.media import detect_media_type
from doc_evidence.persistence import ensure_library_database
from doc_evidence.persistence.library_database import LibraryDatabase, ScanFingerprint
from doc_evidence.poppler import PageText, PdfExtraction, PopplerExtractor
from doc_evidence.util import (
    atomic_write_json,
    atomic_write_text,
    compact_timestamp,
    hash_file,
    hash_json,
    isoformat_z,
    normalized_text_hash,
)

MANIFEST_SCHEMA_VERSION = 1
INVENTORY_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SourceAlias:
    collection_id: str
    relative_path: str
    path: Path
    size_bytes: int
    modified_ns: int
    observed_at: str

    def manifest_value(self) -> dict[str, object]:
        return {
            "collection_id": self.collection_id,
            "path": self.relative_path,
            "size_bytes": self.size_bytes,
            "modified_ns": self.modified_ns,
            "observed_at": self.observed_at,
        }


@dataclass(frozen=True)
class DocumentRecord:
    document_id: str
    content_sha256: str
    size_bytes: int
    media_type: str
    sources: tuple[SourceAlias, ...]
    page_count: int | None
    pdf_metadata: dict[str, str]
    inventory_status: str
    extraction_status: str
    extraction_run_id: str | None
    extraction_artifact_path: str | None
    artifact_path: str
    warnings: tuple[str, ...]
    normalized_text_hash: str | None
    character_count: int
    non_whitespace_character_count: int
    pages: tuple[PageText, ...]
    cache_hit: bool

    def manifest_value(self) -> dict[str, object]:
        return {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "document_id": self.document_id,
            "content_sha256": self.content_sha256,
            "size_bytes": self.size_bytes,
            "media_type": self.media_type,
            "sources": [source.manifest_value() for source in self.sources],
            "page_count": self.page_count,
            "pdf_metadata": self.pdf_metadata or None,
            "inventory_status": self.inventory_status,
            "extraction_status": self.extraction_status,
            "extraction_run_id": self.extraction_run_id,
            "artifact_path": self.artifact_path,
            "extraction_artifact_path": self.extraction_artifact_path,
            "warnings": list(self.warnings),
            "normalized_text_hash": self.normalized_text_hash,
            "character_count": self.character_count,
            "non_whitespace_character_count": self.non_whitespace_character_count,
        }


@dataclass(frozen=True)
class InventoryResult:
    run_id: str
    config_hash: str
    collection_ids: list[str]
    started_at: str
    completed_at: str
    documents: tuple[DocumentRecord, ...]
    byte_duplicate_groups: list[dict[str, Any]]
    normalized_text_duplicate_groups: list[dict[str, Any]]
    errors: list[dict[str, str]]
    warnings: list[dict[str, str]]
    summary: dict[str, Any]
    manifest_path: Path
    catalog_path: Path
    generation_id: str


@dataclass(frozen=True)
class InventoryPlan:
    config: AppConfig
    selected: tuple[CollectionConfig, ...]
    started_at: str
    run_id: str
    database: LibraryDatabase
    generation_id: str
    full_hash_verification: bool


class InventoryCancelled(Exception):
    """Raised when a durable inventory attempt receives cancellation."""


def prepare_inventory(
    config: AppConfig,
    requested_collections: list[str] | tuple[str, ...] = (),
    *,
    library_id: str | None = None,
    library_name: str | None = None,
    full_hash_verification: bool = False,
) -> InventoryPlan:
    selected = config.select_collections(requested_collections)
    started_at = isoformat_z()
    run_key = hash_json(
        {
            "config_hash": config.config_hash,
            "collections": [collection.id for collection in selected],
            "inventory_schema_version": INVENTORY_SCHEMA_VERSION,
        }
    )
    run_id = f"{compact_timestamp()}-{run_key[:12]}"
    config.store.mkdir(parents=True, exist_ok=True)
    database = ensure_library_database(
        config,
        library_id=library_id,
        name=library_name,
    )
    generation_id = database.begin_generation(
        run_id=run_id,
        config_hash=config.config_hash,
        selected_collections=(collection.id for collection in selected),
        started_at=started_at,
        full_hash_verification=full_hash_verification,
    )
    return InventoryPlan(
        config=config,
        selected=selected,
        started_at=started_at,
        run_id=run_id,
        database=database,
        generation_id=generation_id,
        full_hash_verification=full_hash_verification,
    )


def _blob_dir(store: Path, content_sha256: str) -> Path:
    return store / "blobs" / content_sha256[:2] / content_sha256


def _stable_source(sources: list[SourceAlias]) -> SourceAlias | None:
    for source in sources:
        try:
            stat = source.path.stat()
        except OSError:
            continue
        if (stat.st_size, stat.st_mtime_ns) == (
            source.size_bytes,
            source.modified_ns,
        ):
            return source
    return None


def _failure_extraction(
    message: str,
    artifact_path: str,
) -> PdfExtraction:
    return PdfExtraction(
        run_id="poppler:unavailable-source",
        run_key="unavailable-source",
        artifact_path=artifact_path,
        status="error",
        page_count=None,
        pdf_metadata={},
        text="",
        pages=(),
        character_count=0,
        non_whitespace_character_count=0,
        warnings=(message,),
        cache_hit=False,
    )


def _build_document(
    content_sha256: str,
    sources: list[SourceAlias],
    store: Path,
    poppler: PopplerExtractor,
    calculate_normalized_text_hash: bool,
) -> DocumentRecord:
    sources.sort(key=lambda item: (item.collection_id, item.relative_path))
    stable_source = _stable_source(sources)
    blob_dir = _blob_dir(store, content_sha256)
    artifact_path = blob_dir.relative_to(store).as_posix()
    warnings: list[str] = []
    inventory_status = "ok"
    media_type = "application/octet-stream"

    if stable_source is None:
        inventory_status = "error"
        warnings.append("no unchanged source alias remained available for inspection")
    else:
        try:
            media_type = detect_media_type(stable_source.path)
        except OSError as error:
            inventory_status = "error"
            warnings.append(f"cannot classify media type: {error}")

    extraction: PdfExtraction | None = None
    extraction_status = "not_supported_phase_1"
    if media_type == "application/pdf":
        if stable_source is None:
            extraction = _failure_extraction(warnings[-1], artifact_path)
        else:
            try:
                extraction = poppler.extract(
                    stable_source.path,
                    blob_dir,
                    content_sha256,
                    store,
                    stable_source.size_bytes,
                    stable_source.modified_ns,
                )
            except OSError as error:
                extraction = _failure_extraction(
                    f"source or derived store became unavailable: {error}",
                    artifact_path,
                )
        warnings.extend(extraction.warnings)
        if extraction.status == "error":
            extraction_status = "error"
        elif extraction.non_whitespace_character_count == 0:
            extraction_status = "image_only"
        else:
            extraction_status = "embedded_text"

    text_hash = None
    if (
        extraction is not None
        and extraction.status == "ok"
        and calculate_normalized_text_hash
    ):
        text_hash = normalized_text_hash(extraction.text)

    document = DocumentRecord(
        document_id=f"sha256:{content_sha256}",
        content_sha256=content_sha256,
        size_bytes=sources[0].size_bytes,
        media_type=media_type,
        sources=tuple(sources),
        page_count=extraction.page_count if extraction else None,
        pdf_metadata=extraction.pdf_metadata if extraction else {},
        inventory_status=inventory_status,
        extraction_status=extraction_status,
        extraction_run_id=extraction.run_id if extraction else None,
        extraction_artifact_path=extraction.artifact_path if extraction else None,
        artifact_path=artifact_path,
        warnings=tuple(dict.fromkeys(warnings)),
        normalized_text_hash=text_hash,
        character_count=extraction.character_count if extraction else 0,
        non_whitespace_character_count=(
            extraction.non_whitespace_character_count if extraction else 0
        ),
        pages=extraction.pages if extraction else (),
        cache_hit=extraction.cache_hit if extraction else False,
    )
    atomic_write_json(
        blob_dir / "metadata.json",
        {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "document_id": document.document_id,
            "content_sha256": content_sha256,
            "size_bytes": document.size_bytes,
            "media_type": document.media_type,
            "page_count": document.page_count,
            "inventory_status": document.inventory_status,
            "extraction_status": document.extraction_status,
            "extraction_run_id": document.extraction_run_id,
            "extraction_artifact_path": document.extraction_artifact_path,
            "normalized_text_hash": document.normalized_text_hash,
            "character_count": document.character_count,
            "non_whitespace_character_count": (document.non_whitespace_character_count),
            "warnings": list(document.warnings),
        },
    )
    return document


def _duplicate_groups(
    documents: list[DocumentRecord],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    byte_groups = []
    for document in documents:
        if len(document.sources) > 1:
            byte_groups.append(
                {
                    "group_key": document.content_sha256,
                    "document_ids": [document.document_id],
                    "sources": [
                        f"{source.collection_id}:{source.relative_path}"
                        for source in document.sources
                    ],
                }
            )

    by_text_hash: dict[str, list[DocumentRecord]] = defaultdict(list)
    for document in documents:
        if document.normalized_text_hash:
            by_text_hash[document.normalized_text_hash].append(document)
    text_groups = []
    for group_key, members in sorted(by_text_hash.items()):
        if len(members) < 2:
            continue
        text_groups.append(
            {
                "group_key": group_key,
                "document_ids": [member.document_id for member in members],
                "sources": [
                    f"{source.collection_id}:{source.relative_path}"
                    for member in members
                    for source in member.sources
                ],
            }
        )
    return byte_groups, text_groups


def _summary(
    documents: list[DocumentRecord],
    discovered_count: int,
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
    byte_groups: list[dict[str, Any]],
    text_groups: list[dict[str, Any]],
) -> dict[str, Any]:
    source_count = sum(len(document.sources) for document in documents)
    unique_pdfs = [
        document for document in documents if document.media_type == "application/pdf"
    ]
    pdf_source_count = sum(len(document.sources) for document in unique_pdfs)
    unique_pdf_pages = sum(document.page_count or 0 for document in unique_pdfs)
    pdf_source_pages = sum(
        (document.page_count or 0) * len(document.sources) for document in unique_pdfs
    )
    return {
        "discovered_files": discovered_count,
        "indexed_source_files": source_count,
        "unique_documents": len(documents),
        "non_pdf_source_files": source_count - pdf_source_count,
        "pdf_source_files": pdf_source_count,
        "unique_pdf_documents": len(unique_pdfs),
        "pdf_source_pages": pdf_source_pages,
        "unique_pdf_pages": unique_pdf_pages,
        "embedded_text_pdf_documents": sum(
            document.extraction_status == "embedded_text" for document in unique_pdfs
        ),
        "image_only_pdf_documents": sum(
            document.extraction_status == "image_only" for document in unique_pdfs
        ),
        "failed_pdf_extractions": sum(
            document.extraction_status == "error" for document in unique_pdfs
        ),
        "poppler_cache_hits": sum(document.cache_hit for document in unique_pdfs),
        "poppler_cache_misses": sum(not document.cache_hit for document in unique_pdfs),
        "byte_duplicate_groups": len(byte_groups),
        "normalized_text_duplicate_groups": len(text_groups),
        "path_errors": sum(error.get("kind") == "path" for error in errors),
        "extraction_errors": sum(error.get("kind") == "extraction" for error in errors),
        "discovery_warnings": len(warnings),
    }


def _execute_inventory_unchecked(
    plan: InventoryPlan,
    *,
    on_progress: Callable[[str, int | None, int | None], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> InventoryResult:
    config = plan.config
    selected = plan.selected
    started_at = plan.started_at
    run_id = plan.run_id
    database = plan.database
    generation_id = plan.generation_id
    full_hash_verification = plan.full_hash_verification

    def check_cancelled() -> None:
        if cancelled is not None and cancelled():
            raise InventoryCancelled("inventory was cancelled")

    def progress(stage: str, current: int | None, total: int | None) -> None:
        if on_progress is not None:
            on_progress(stage, current, total)

    discovery_warnings: list[dict[str, str]] = []
    discovered = []
    progress("discovering", 0, None)
    for collection in selected:
        check_cancelled()
        discovered.extend(discover_files(collection, discovery_warnings))
    discovered.sort(key=lambda item: (item.collection_id, item.relative_path))
    progress("hashing", 0, len(discovered))

    errors: list[dict[str, str]] = []
    grouped_sources: dict[str, list[SourceAlias]] = defaultdict(list)
    fingerprints: list[ScanFingerprint] = []
    fingerprint_cache_hits = 0
    for index, item in enumerate(discovered, start=1):
        check_cancelled()
        try:
            observed_at = isoformat_z()
            before = item.path.stat()
            cached_sha256 = None
            if not full_hash_verification:
                cached_sha256 = database.cached_fingerprint(
                    collection_id=item.collection_id,
                    relative_path=item.relative_path,
                    resolved_path=item.path.resolve(),
                    device=before.st_dev,
                    inode=before.st_ino,
                    size_bytes=before.st_size,
                    modified_ns=before.st_mtime_ns,
                    changed_ns=before.st_ctime_ns,
                )
            if cached_sha256 is None:
                file_hash = hash_file(item.path)
                content_sha256 = file_hash.content_sha256
                size_bytes = file_hash.size_bytes
                modified_ns = file_hash.modified_ns
            else:
                fingerprint_cache_hits += 1
                content_sha256 = cached_sha256
                size_bytes = before.st_size
                modified_ns = before.st_mtime_ns
            after = item.path.stat()
            if (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ):
                raise OSError(f"file changed while inventorying: {item.path}")
            source = SourceAlias(
                collection_id=item.collection_id,
                relative_path=item.relative_path,
                path=item.path,
                size_bytes=size_bytes,
                modified_ns=modified_ns,
                observed_at=observed_at,
            )
            grouped_sources[content_sha256].append(source)
            fingerprints.append(
                ScanFingerprint(
                    collection_id=item.collection_id,
                    relative_path=item.relative_path,
                    resolved_path=str(item.path.resolve()),
                    device=after.st_dev,
                    inode=after.st_ino,
                    size_bytes=after.st_size,
                    modified_ns=after.st_mtime_ns,
                    changed_ns=after.st_ctime_ns,
                    content_sha256=content_sha256,
                )
            )
        except OSError as error:
            errors.append(
                {
                    "kind": "path",
                    "collection_id": item.collection_id,
                    "path": item.relative_path,
                    "error": str(error),
                }
            )
        progress("hashing", index, len(discovered))

    poppler = PopplerExtractor(config.extraction_config_hash)
    documents: list[DocumentRecord] = []
    progress("extracting", 0, len(grouped_sources))
    for index, (content_sha256, sources) in enumerate(
        sorted(grouped_sources.items()), start=1
    ):
        check_cancelled()
        documents.append(
            _build_document(
                content_sha256,
                sources,
                config.store,
                poppler,
                config.extraction.normalized_text_duplicates,
            )
        )
        progress("extracting", index, len(grouped_sources))
    documents.sort(key=lambda item: item.document_id)
    for document in documents:
        if document.extraction_status == "error":
            first_source = document.sources[0]
            errors.append(
                {
                    "kind": "extraction",
                    "collection_id": first_source.collection_id,
                    "path": first_source.relative_path,
                    "error": "; ".join(document.warnings)
                    or "PDF extraction failed without a diagnostic",
                }
            )
    byte_groups, text_groups = _duplicate_groups(documents)
    completed_at = isoformat_z()
    summary = _summary(
        documents,
        len(discovered),
        errors,
        discovery_warnings,
        byte_groups,
        text_groups,
    )
    summary["fingerprint_cache_hits"] = fingerprint_cache_hits
    summary["full_hash_verification"] = full_hash_verification

    manifest_dir = config.store / "manifests" / run_id
    manifest_path = manifest_dir / "manifest.jsonl"
    manifest_text = "".join(
        json.dumps(document.manifest_value(), ensure_ascii=False, sort_keys=True) + "\n"
        for document in documents
    )
    duplicate_report = {
        "schema_version": 1,
        "byte_duplicate_groups": byte_groups,
        "normalized_text_duplicate_groups": text_groups,
    }
    run_record = {
        "schema_version": INVENTORY_SCHEMA_VERSION,
        "run_id": run_id,
        "generation_id": generation_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "config_path": str(config.path),
        "config_hash": config.config_hash,
        "collection_ids": [collection.id for collection in selected],
        "summary": summary,
        "full_hash_verification": full_hash_verification,
        "poppler": poppler.descriptor,
    }
    errors_text = "".join(
        json.dumps(error, ensure_ascii=False, sort_keys=True) + "\n" for error in errors
    )

    check_cancelled()
    progress("publishing", None, None)
    atomic_write_text(manifest_path, manifest_text)
    atomic_write_json(manifest_dir / "run.json", run_record)
    atomic_write_json(manifest_dir / "summary.json", summary)
    atomic_write_json(manifest_dir / "duplicates.json", duplicate_report)
    atomic_write_text(manifest_dir / "errors.jsonl", errors_text)
    atomic_write_json(manifest_dir / "discovery-warnings.json", discovery_warnings)
    atomic_write_text(config.store / "manifests" / "latest.jsonl", manifest_text)
    atomic_write_json(config.store / "manifests" / "latest-run.json", run_record)
    atomic_write_json(config.store / "manifests" / "latest-summary.json", summary)
    atomic_write_json(
        config.store / "manifests" / "latest-duplicates.json", duplicate_report
    )

    catalog_path = database.path
    result = InventoryResult(
        run_id=run_id,
        config_hash=config.config_hash,
        collection_ids=[collection.id for collection in selected],
        started_at=started_at,
        completed_at=completed_at,
        documents=tuple(documents),
        byte_duplicate_groups=byte_groups,
        normalized_text_duplicate_groups=text_groups,
        errors=errors,
        warnings=discovery_warnings,
        summary=summary,
        manifest_path=manifest_path,
        catalog_path=catalog_path,
        generation_id=generation_id,
    )
    database.publish_generation(
        result=result,
        generation_id=generation_id,
        config=config,
        fingerprints=fingerprints,
    )
    progress("completed", len(documents), len(documents))
    return result


def execute_inventory(
    plan: InventoryPlan,
    *,
    on_progress: Callable[[str, int | None, int | None], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> InventoryResult:
    try:
        return _execute_inventory_unchecked(
            plan,
            on_progress=on_progress,
            cancelled=cancelled,
        )
    except Exception as error:
        plan.database.fail_generation(
            generation_id=plan.generation_id,
            error_summary=str(error),
        )
        raise


def run_inventory(
    config: AppConfig,
    requested_collections: list[str] | tuple[str, ...] = (),
    *,
    library_id: str | None = None,
    library_name: str | None = None,
    full_hash_verification: bool = False,
) -> InventoryResult:
    plan = prepare_inventory(
        config,
        requested_collections,
        library_id=library_id,
        library_name=library_name,
        full_hash_verification=full_hash_verification,
    )
    return execute_inventory(plan)
