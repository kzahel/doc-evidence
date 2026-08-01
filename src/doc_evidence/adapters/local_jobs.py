"""Local filesystem/SQLite extraction-job composition adapter."""

from __future__ import annotations

import json
import os
import platform
import threading
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from doc_evidence.application.jobs import (
    AttemptDiagnosticsRecord,
    BatchCreation,
    BatchPreflightRecord,
    CachedResult,
    ClaimedJob,
    ExecutionMode,
    ExtractorCapabilityRecord,
    ExtractorDependencyRecord,
    JobAttemptRecord,
    JobBatchRecord,
    JobCountRecord,
    JobCreation,
    JobEventRecord,
    JobRecord,
    JobSpec,
    JobState,
    QueueStateRecord,
)
from doc_evidence.attempts import (
    AttemptPlan,
    AttemptSupervisor,
    AttemptUpdate,
    validate_run,
)
from doc_evidence.config import AppConfig
from doc_evidence.errors import CatalogError, NotFoundError, RequestError
from doc_evidence.extractor_registry import (
    ExtractorExecution,
    ExtractorRegistry,
    PreparedExtraction,
)
from doc_evidence.persistence import LibraryDatabase
from doc_evidence.persistence.jobs import JobRepository
from doc_evidence.util import hash_file, hash_json


@dataclass(frozen=True)
class SourceSnapshot:
    path: Path
    collection_id: str
    relative_path: str
    document_id: str
    content_sha256: str
    media_type: str
    size_bytes: int
    modified_ns: int


class LocalExtractionJobs:
    """Validate intent, resolve cache identity, and execute claimed attempts."""

    def __init__(
        self,
        *,
        library_id: str,
        config: AppConfig,
        database: LibraryDatabase,
        registry: ExtractorRegistry | None = None,
        supervisor: AttemptSupervisor | None = None,
    ):
        self.library_id = library_id
        self.config = config
        self.database = database
        self.repository = JobRepository(database)
        self.registry = registry or ExtractorRegistry()
        self.supervisor = supervisor or AttemptSupervisor()

    def source(self, document_id: str) -> SourceSnapshot:
        content_sha256 = document_id.removeprefix("sha256:")
        connection = self.database.connect(readonly=True)
        try:
            document = connection.execute(
                """
                SELECT c.document_id, c.content_sha256, c.media_type
                FROM content_objects c
                JOIN generation_documents member
                  ON member.content_sha256 = c.content_sha256
                 AND member.generation_id = (
                    SELECT active_generation_id FROM library_metadata
                    WHERE singleton = 1
                 )
                WHERE c.document_id = ? AND c.content_sha256 = ?
                """,
                (document_id, content_sha256),
            ).fetchone()
            occurrences = connection.execute(
                """
                SELECT collection_id, relative_path
                FROM source_occurrences
                WHERE generation_id = (
                    SELECT active_generation_id FROM library_metadata
                    WHERE singleton = 1
                ) AND content_sha256 = ?
                ORDER BY collection_id, relative_path
                """,
                (content_sha256,),
            ).fetchall()
        finally:
            connection.close()
        if document is None:
            raise NotFoundError("document was not found in the active library scope")
        collections = {item.id: item for item in self.config.collections}
        failures: list[str] = []
        for occurrence in occurrences:
            collection_id = str(occurrence["collection_id"])
            collection = collections.get(collection_id)
            if collection is None:
                failures.append(f"collection {collection_id} is no longer configured")
                continue
            root = collection.source.resolve()
            path = (root / str(occurrence["relative_path"])).resolve()
            if not path.is_relative_to(root):
                failures.append(f"source occurrence escaped collection {collection_id}")
                continue
            try:
                observed = hash_file(path)
            except OSError as error:
                failures.append(str(error))
                continue
            if observed.content_sha256 != content_sha256:
                failures.append(f"source content changed: {collection_id}")
                continue
            return SourceSnapshot(
                path=path,
                collection_id=collection_id,
                relative_path=str(occurrence["relative_path"]),
                document_id=str(document["document_id"]),
                content_sha256=content_sha256,
                media_type=str(document["media_type"]),
                size_bytes=observed.size_bytes,
                modified_ns=observed.modified_ns,
            )
        detail = failures[0] if failures else "no source occurrence is available"
        raise RequestError(f"document source cannot be verified: {detail}")

    def prepare(
        self,
        *,
        document_id: str,
        extractor_id: str,
        settings: dict[str, Any],
    ) -> tuple[SourceSnapshot, PreparedExtraction]:
        source = self.source(document_id)
        prepared = self.registry.prepare(
            extractor_id=extractor_id,
            media_type=source.media_type,
            settings=settings,
            extraction_config_hash=self.config.extraction_config_hash,
            default_languages=self.config.languages,
        )
        return source, prepared

    def _cached(
        self,
        *,
        source: SourceSnapshot,
        prepared: PreparedExtraction,
    ) -> CachedResult | None:
        run_dir = (
            self.config.store
            / "blobs"
            / source.content_sha256[:2]
            / source.content_sha256
            / "runs"
            / prepared.execution.extractor_id
            / prepared.run_key
        )
        if not run_dir.is_dir():
            return None
        try:
            validate_run(
                run_dir,
                extractor_id=prepared.execution.extractor_id,
                source_sha256=source.content_sha256,
                run_key=prepared.run_key,
            )
            self.database.register_run_sidecars(
                store=self.config.store,
                content_sha256=source.content_sha256,
                expected_run_id=prepared.run_id,
            )
        except (OSError, ValueError, CatalogError):
            return None
        return CachedResult(
            run_id=prepared.run_id,
            artifact_path=run_dir.relative_to(self.config.store).as_posix(),
        )

    @staticmethod
    def _execution_payload(
        source: SourceSnapshot,
        prepared: PreparedExtraction,
        *,
        canonical_present_at_enqueue: bool,
    ) -> dict[str, Any]:
        execution = prepared.execution
        return {
            "extractor_id": execution.extractor_id,
            "settings": execution.settings,
            "timeout_seconds": execution.timeout_seconds,
            "resource_class": execution.resource_class,
            "deterministic": execution.deterministic,
            "descriptor": prepared.descriptor,
            "run_key": prepared.run_key,
            "run_id": prepared.run_id,
            "canonical_present_at_enqueue": canonical_present_at_enqueue,
            "source": {
                "collection_id": source.collection_id,
                "relative_path": source.relative_path,
                "content_sha256": source.content_sha256,
                "size_bytes": source.size_bytes,
                "modified_ns": source.modified_ns,
            },
        }

    def enqueue(
        self,
        *,
        document_id: str,
        extractor_id: str,
        settings: dict[str, Any] | None = None,
        execution_mode: ExecutionMode = "reuse_or_execute",
        priority: int = 100,
        idempotency_key: str | None = None,
        batch_id: str | None = None,
    ) -> JobCreation:
        if execution_mode not in {"reuse_or_execute", "fresh_verification"}:
            raise RequestError("unknown extraction execution mode")
        if priority < -100 or priority > 1_000:
            raise RequestError("job priority is outside its allowed bounds")
        if idempotency_key is not None and not 1 <= len(idempotency_key) <= 200:
            raise RequestError("idempotency key is outside its allowed bounds")
        source, prepared = self.prepare(
            document_id=document_id,
            extractor_id=extractor_id,
            settings=settings or {},
        )
        cache_key = hash_json(
            {
                "source_sha256": source.content_sha256,
                "extractor_id": extractor_id,
                "run_key": prepared.run_key,
            }
        )
        observed_cached = self._cached(source=source, prepared=prepared)
        cached = observed_cached if execution_mode == "reuse_or_execute" else None
        return self.repository.create(
            JobSpec(
                library_id=self.library_id,
                document_id=source.document_id,
                content_sha256=source.content_sha256,
                extractor_id=extractor_id,
                cache_key=cache_key,
                settings=prepared.execution.settings,
                execution=self._execution_payload(
                    source,
                    prepared,
                    canonical_present_at_enqueue=observed_cached is not None,
                ),
                execution_mode=execution_mode,
                run_key=prepared.run_key,
                priority=priority,
                resource_class=prepared.execution.resource_class,
                idempotency_key=idempotency_key,
                batch_id=batch_id,
            ),
            cached=cached,
        )

    def execute_claimed(
        self,
        claimed: ClaimedJob,
        *,
        cancel: threading.Event,
    ) -> JobRecord:
        job = claimed.job
        source = self.source(job.document_id)
        payload = job.execution
        if (
            job.run_key is None
            or payload.get("run_key") != job.run_key
            or payload.get("run_id") != f"{job.extractor_id}:{job.run_key}"
            or payload.get("extractor_id") != job.extractor_id
            or source.content_sha256 != job.content_sha256
        ):
            raise RequestError("persisted job execution identity is inconsistent")
        execution = ExtractorExecution(
            extractor_id=job.extractor_id,
            settings=dict(job.settings),
            timeout_seconds=int(payload["timeout_seconds"]),
            resource_class=job.resource_class,
            deterministic=bool(payload["deterministic"]),
        )
        blob_dir = (
            self.config.store
            / "blobs"
            / source.content_sha256[:2]
            / source.content_sha256
        )
        plan = AttemptPlan(
            attempt_id=claimed.attempt_id,
            execution=execution,
            expected_run_id=str(payload["run_id"]),
            expected_run_key=job.run_key,
            source_path=source.path,
            source_sha256=source.content_sha256,
            expected_size_bytes=source.size_bytes,
            expected_modified_ns=source.modified_ns,
            store_root=self.config.store,
            blob_dir=blob_dir,
            extraction_config_hash=self.config.extraction_config_hash,
            fresh_verification=job.execution_mode == "fresh_verification",
        )

        def update(value: AttemptUpdate) -> None:
            self.repository.attempt_update(
                job_id=job.job_id,
                attempt_id=claimed.attempt_id,
                worker_pid=value.worker_pid,
                process_group_id=(
                    value.worker_pid
                    if os.name == "posix" and value.worker_pid is not None
                    else None
                ),
                heartbeat_at=value.heartbeat_at,
                stage=value.stage,
            )

        result = self.supervisor.execute(plan, cancel=cancel, on_update=update)
        projection_failure: str | None = None
        if result.outcome in {
            "executed",
            "concurrent_cache_win",
            "verified_cache_match",
        }:
            try:
                assert result.run_id is not None
                self.database.register_run_sidecars(
                    store=self.config.store,
                    content_sha256=source.content_sha256,
                    expected_run_id=result.run_id,
                )
            except (AssertionError, CatalogError, OSError, ValueError) as error:
                projection_failure = str(error)
        return self.repository.finish(
            job_id=job.job_id,
            attempt_id=claimed.attempt_id,
            result=result,
            projection_failure=projection_failure,
        )

    def get(self, job_id: str) -> JobRecord:
        return self.repository.get(job_id)

    def list(
        self,
        *,
        states: tuple[JobState, ...] = (),
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[JobRecord], int]:
        return self.repository.list(states=states, offset=offset, limit=limit)

    def events(
        self, job_id: str, *, after: int = 0, limit: int = 200
    ) -> list[JobEventRecord]:
        return self.repository.events(job_id, after=after, limit=limit)

    def attempts(self, job_id: str) -> tuple[JobAttemptRecord, ...]:
        now = datetime.now(UTC)
        records: list[JobAttemptRecord] = []
        for record in self.repository.attempts(job_id):
            process_alive: bool | None = None
            if record.worker_pid is not None:
                if record.state in {"starting", "running", "cancelling"}:
                    try:
                        os.kill(record.worker_pid, 0)
                    except ProcessLookupError:
                        process_alive = False
                    except PermissionError:
                        process_alive = True
                    else:
                        process_alive = True
                else:
                    process_alive = False
            heartbeat_age: float | None = None
            if record.heartbeat_at is not None:
                try:
                    heartbeat_age = max(
                        0.0,
                        (
                            now
                            - datetime.fromisoformat(record.heartbeat_at).astimezone(
                                UTC
                            )
                        ).total_seconds(),
                    )
                except ValueError:
                    heartbeat_age = None
            try:
                deadline_expired = (
                    datetime.fromisoformat(record.deadline_at).astimezone(UTC) < now
                )
            except ValueError:
                deadline_expired = False
            records.append(
                replace(
                    record,
                    process_alive=process_alive,
                    heartbeat_age_seconds=heartbeat_age,
                    deadline_expired=deadline_expired,
                )
            )
        return tuple(records)

    def attempt_diagnostics(
        self, job_id: str, attempt_id: str
    ) -> AttemptDiagnosticsRecord:
        job = self.get(job_id)
        attempts = {item.attempt_id: item for item in self.attempts(job_id)}
        attempt = attempts.get(attempt_id)
        if attempt is None:
            raise NotFoundError("job attempt was not found")
        relative = self.repository.attempt_path(job_id, attempt_id)
        if relative is None:
            relative = (
                Path("blobs")
                / job.content_sha256[:2]
                / job.content_sha256
                / "attempts"
                / attempt_id
            ).as_posix()
        root = self.config.store.resolve()
        attempt_dir = (root / relative).resolve()
        if not attempt_dir.is_relative_to(root):
            raise CatalogError("attempt diagnostics path escaped the artifact store")

        def tail(name: str, limit: int = 16_384) -> str:
            path = attempt_dir / name
            try:
                with path.open("rb") as source:
                    source.seek(0, os.SEEK_END)
                    size = source.tell()
                    source.seek(max(0, size - limit))
                    return source.read(limit).decode("utf-8", errors="replace")
            except OSError:
                return ""

        result: dict[str, Any] = {}
        try:
            loaded = json.loads((attempt_dir / "attempt.json").read_text("utf-8"))
            if isinstance(loaded, dict):
                result = loaded
        except (OSError, UnicodeError, json.JSONDecodeError):
            pass
        published = job.result_artifact_path is not None
        return AttemptDiagnosticsRecord(
            attempt_id=attempt_id,
            retained=attempt_dir.is_dir(),
            stdout_tail=tail("worker.stdout.log"),
            stderr_tail=tail("worker.stderr.log"),
            stdout_truncated_bytes=int(result.get("stdout_truncated_bytes", 0) or 0),
            stderr_truncated_bytes=int(result.get("stderr_truncated_bytes", 0) or 0),
            extractor_descriptor=dict(job.execution.get("descriptor", {})),
            settings=dict(job.settings),
            environment={
                "python": platform.python_version(),
                "platform": platform.system(),
                "machine": platform.machine(),
            },
            staging_status=(
                "retained"
                if attempt_dir.is_dir()
                else "removed by retention or not created"
            ),
            validation_status=(
                "passed"
                if attempt.publication_outcome
                in {"executed", "concurrent_cache_win", "verified_cache_match"}
                else ("failed" if attempt.completed_at else "pending")
            ),
            publication_status=attempt.publication_outcome or "pending",
            projection_status=(
                "repair required"
                if job.outcome == "published_projection_failed"
                else ("registered" if published else "not published")
            ),
        )

    def cancel(self, job_id: str) -> JobRecord:
        return self.repository.request_cancel(job_id)

    def retry(self, job_id: str) -> JobRecord:
        return self.repository.retry(job_id)

    def repair_projection(self, job_id: str) -> JobRecord:
        job = self.get(job_id)
        if not (
            job.state == "failed"
            and job.outcome == "published_projection_failed"
            and job.result_artifact_path is not None
            and job.result_run_id is not None
            and job.run_key is not None
        ):
            raise RequestError("job does not have a repairable catalog projection")
        root = self.config.store.resolve()
        run_dir = (root / job.result_artifact_path).resolve()
        if not run_dir.is_relative_to(root):
            raise CatalogError("published artifact path escaped the library store")
        validate_run(
            run_dir,
            extractor_id=job.extractor_id,
            source_sha256=job.content_sha256,
            run_key=job.run_key,
        )
        self.database.register_run_sidecars(
            store=self.config.store,
            content_sha256=job.content_sha256,
            expected_run_id=job.result_run_id,
        )
        return self.repository.projection_repaired(job_id)

    def enqueue_batch(
        self,
        *,
        document_ids: list[str],
        extractor_ids: list[str],
        settings: dict[str, dict[str, Any]] | None = None,
        execution_mode: ExecutionMode = "reuse_or_execute",
        confirmed: bool,
        idempotency_key: str | None = None,
    ) -> BatchCreation:
        if not confirmed:
            raise RequestError("batch extraction requires explicit confirmation")
        if not 1 <= len(document_ids) <= 200:
            raise RequestError("batch document selection must contain 1 to 200 items")
        if not 1 <= len(extractor_ids) <= 5:
            raise RequestError("batch extractor selection must contain 1 to 5 items")
        if len(set(document_ids)) != len(document_ids):
            raise RequestError("batch document selection contains duplicates")
        if len(set(extractor_ids)) != len(extractor_ids):
            raise RequestError("batch extractor selection contains duplicates")
        requested_count = len(document_ids) * len(extractor_ids)
        if requested_count > 500:
            raise RequestError("batch would create more than 500 requests")
        selected_settings = settings or {}
        if set(selected_settings) - set(extractor_ids):
            raise RequestError("batch settings name an unselected extractor")
        if idempotency_key is not None and not 1 <= len(idempotency_key) <= 200:
            raise RequestError("idempotency key is outside its allowed bounds")
        for document_id in document_ids:
            for extractor_id in extractor_ids:
                self.prepare(
                    document_id=document_id,
                    extractor_id=extractor_id,
                    settings=selected_settings.get(extractor_id, {}),
                )
        batch, disposition = self.repository.create_batch(
            library_id=self.library_id,
            selection={
                "document_ids": document_ids,
                "extractor_ids": extractor_ids,
            },
            policy={
                "execution_mode": execution_mode,
                "settings": selected_settings,
                "priority": 10,
            },
            requested_count=requested_count,
            idempotency_key=idempotency_key,
        )
        if disposition == "idempotent":
            return BatchCreation(
                batch=self.repository.batch(batch.batch_id),
                jobs=self.repository.batch_jobs(batch.batch_id),
                disposition="idempotent",
            )
        children: list[JobRecord] = []
        for document_id in document_ids:
            for extractor_id in extractor_ids:
                creation = self.enqueue(
                    document_id=document_id,
                    extractor_id=extractor_id,
                    settings=selected_settings.get(extractor_id, {}),
                    execution_mode=execution_mode,
                    priority=10,
                    batch_id=batch.batch_id,
                )
                self.repository.attach_batch_job(
                    batch_id=batch.batch_id,
                    job_id=creation.job.job_id,
                    ordinal=len(children),
                )
                children.append(creation.job)
        return BatchCreation(
            batch=self.repository.batch(batch.batch_id),
            jobs=tuple(children),
            disposition="created",
        )

    def preflight_image_only_ocr(self) -> BatchPreflightRecord:
        connection = self.database.connect(readonly=True)
        try:
            rows = connection.execute(
                """
                SELECT content.document_id
                FROM content_objects content
                JOIN generation_documents member
                  ON member.content_sha256 = content.content_sha256
                 AND member.generation_id = (
                    SELECT active_generation_id FROM library_metadata
                    WHERE singleton = 1
                 )
                WHERE content.extraction_status = 'image_only'
                  AND content.media_type = 'application/pdf'
                ORDER BY content.document_id LIMIT 200
                """
            ).fetchall()
            candidate_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM content_objects content
                    JOIN generation_documents member
                      ON member.content_sha256 = content.content_sha256
                     AND member.generation_id = (
                        SELECT active_generation_id FROM library_metadata
                        WHERE singleton = 1
                     )
                    WHERE content.extraction_status = 'image_only'
                      AND content.media_type = 'application/pdf'
                    """
                ).fetchone()[0]
            )
            unsupported_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*) FROM content_objects content
                    JOIN generation_documents member
                      ON member.content_sha256 = content.content_sha256
                     AND member.generation_id = (
                        SELECT active_generation_id FROM library_metadata
                        WHERE singleton = 1
                     )
                    WHERE content.extraction_status = 'image_only'
                      AND content.media_type != 'application/pdf'
                    """
                ).fetchone()[0]
            )
        finally:
            connection.close()
        capability = self.registry.capability("ocrmypdf-tesseract")
        selected: list[str] = []
        cache_hits = 0
        unsupported = unsupported_count
        for row in rows:
            document_id = str(row["document_id"])
            if not capability.available:
                selected.append(document_id)
                continue
            try:
                source, prepared = self.prepare(
                    document_id=document_id,
                    extractor_id="ocrmypdf-tesseract",
                    settings={},
                )
            except (NotFoundError, RequestError):
                unsupported += 1
                continue
            if self._cached(source=source, prepared=prepared) is not None:
                cache_hits += 1
            else:
                selected.append(document_id)
        return BatchPreflightRecord(
            policy="image_only_pdf_missing_ocr",
            extractor_id="ocrmypdf-tesseract",
            document_ids=tuple(selected),
            candidate_count=candidate_count,
            cache_hit_count=cache_hits,
            execution_count=len(selected) if capability.available else 0,
            unsupported_count=unsupported,
            missing_dependency_count=(len(rows) if not capability.available else 0),
            resource_class="ocr",
            concurrency_limit=1,
            maximum_batch_size=200,
            over_limit_count=max(0, candidate_count - 200),
        )

    def batch(self, batch_id: str) -> JobBatchRecord:
        return self.repository.batch(batch_id)

    def batch_jobs(self, batch_id: str) -> tuple[JobRecord, ...]:
        return self.repository.batch_jobs(batch_id)

    def batches(
        self, *, offset: int = 0, limit: int = 50
    ) -> tuple[list[JobBatchRecord], int]:
        return self.repository.batches(offset=offset, limit=limit)

    def counts(self) -> JobCountRecord:
        return self.repository.counts()

    def queue_state(self) -> QueueStateRecord:
        return self.repository.queue_state()

    def set_queue_paused(self, paused: bool) -> QueueStateRecord:
        return self.repository.set_queue_paused(paused)

    def capabilities(
        self, *, document_id: str | None = None
    ) -> tuple[ExtractorCapabilityRecord, ...]:
        source = self.source(document_id) if document_id is not None else None
        image_only = False
        if source is not None:
            connection = self.database.connect(readonly=True)
            try:
                image_only = (
                    int(
                        connection.execute(
                            """
                            SELECT non_whitespace_character_count
                            FROM content_objects WHERE content_sha256 = ?
                            """,
                            (source.content_sha256,),
                        ).fetchone()[0]
                    )
                    == 0
                )
            finally:
                connection.close()
        records: list[ExtractorCapabilityRecord] = []
        for capability in self.registry.capabilities():
            spec = capability.spec
            default_settings = self.registry.default_settings(
                extractor_id=spec.extractor_id,
                default_languages=self.config.languages,
            )
            document_supported = (
                source.media_type in spec.supported_media_types
                if source is not None
                else None
            )
            prepared: PreparedExtraction | None = None
            cached: bool | None = None
            if source is not None and document_supported and capability.available:
                prepared = self.registry.prepare(
                    extractor_id=spec.extractor_id,
                    media_type=source.media_type,
                    settings={},
                    extraction_config_hash=self.config.extraction_config_hash,
                    default_languages=self.config.languages,
                )
                cached = self._cached(source=source, prepared=prepared) is not None
            unavailable = [
                item.reason
                for item in capability.dependencies
                if not item.available and item.reason
            ]
            records.append(
                ExtractorCapabilityRecord(
                    extractor_id=spec.extractor_id,
                    display_name=spec.display_name,
                    category=spec.category,
                    supported_media_types=spec.supported_media_types,
                    dependencies=tuple(
                        ExtractorDependencyRecord(
                            name=item.name,
                            available=item.available,
                            version=item.version,
                            reason=item.reason,
                        )
                        for item in capability.dependencies
                    ),
                    available=capability.available,
                    unavailable_reason="; ".join(unavailable) or None,
                    version_label=capability.version_label,
                    resource_class=spec.resource_class,
                    settings_schema=spec.settings_schema,
                    default_settings=default_settings,
                    default_timeout_seconds=spec.default_timeout_seconds,
                    deterministic=spec.deterministic,
                    output_kinds=spec.output_kinds,
                    document_supported=document_supported,
                    cached=cached,
                    run_key=prepared.run_key if prepared is not None else None,
                    run_id=prepared.run_id if prepared is not None else None,
                    recommended=(
                        source is not None
                        and (
                            (
                                source.media_type.startswith("image/")
                                and spec.extractor_id == "tesseract-raster"
                            )
                            or (
                                source.media_type == "application/pdf"
                                and image_only
                                and spec.extractor_id == "ocrmypdf-tesseract"
                            )
                        )
                    ),
                )
            )
        return tuple(records)

    def reconcile(self) -> list[JobRecord]:
        """Resolve stale active rows after the previous scheduler disappeared."""

        recovered: list[JobRecord] = []
        for job in self.repository.active_jobs():
            if job.run_key is not None:
                run_dir = (
                    self.config.store
                    / "blobs"
                    / job.content_sha256[:2]
                    / job.content_sha256
                    / "runs"
                    / job.extractor_id
                    / job.run_key
                )
                try:
                    validate_run(
                        run_dir,
                        extractor_id=job.extractor_id,
                        source_sha256=job.content_sha256,
                        run_key=job.run_key,
                    )
                except (OSError, ValueError):
                    pass
                else:
                    canonical_predated_attempt = bool(
                        job.execution.get(
                            "canonical_present_at_enqueue",
                            job.execution_mode == "fresh_verification",
                        )
                    )
                    if canonical_predated_attempt and not self._publication_evidence(
                        job
                    ):
                        recovered.append(
                            self.repository.interrupt(
                                job.job_id,
                                detail=(
                                    "scheduler disappeared before the fresh attempt "
                                    "recorded publication evidence"
                                ),
                            )
                        )
                        continue
                    run_id = str(job.execution["run_id"])
                    artifact_path = run_dir.relative_to(self.config.store).as_posix()
                    projection_failure: str | None = None
                    try:
                        self.database.register_run_sidecars(
                            store=self.config.store,
                            content_sha256=job.content_sha256,
                            expected_run_id=run_id,
                        )
                    except (CatalogError, OSError, ValueError) as error:
                        projection_failure = str(error)
                    recovered.append(
                        self.repository.reconcile_published(
                            job.job_id,
                            run_id=run_id,
                            artifact_path=artifact_path,
                            projection_failure=projection_failure,
                        )
                    )
                    continue
            recovered.append(
                self.repository.interrupt(
                    job.job_id,
                    detail="scheduler disappeared while the attempt was active",
                )
            )
        succeeded, _total = self.repository.list(states=("succeeded",), limit=200)
        for job in succeeded:
            if job.run_key is None or job.result_artifact_path is None:
                recovered.append(
                    self.repository.integrity_failure(
                        job.job_id,
                        detail="successful job does not retain a canonical artifact identity",
                    )
                )
                continue
            run_dir = self.config.store / job.result_artifact_path
            try:
                validate_run(
                    run_dir,
                    extractor_id=job.extractor_id,
                    source_sha256=job.content_sha256,
                    run_key=job.run_key,
                )
            except (OSError, ValueError) as error:
                recovered.append(
                    self.repository.integrity_failure(
                        job.job_id,
                        detail=f"successful artifact is invalid: {error}",
                    )
                )
        return recovered

    def _publication_evidence(self, job: JobRecord) -> bool:
        if job.active_attempt_id is None or job.run_key is None:
            return False
        attempt_dir = (
            self.config.store
            / "blobs"
            / job.content_sha256[:2]
            / job.content_sha256
            / "attempts"
            / job.active_attempt_id
        )
        for name in ("publication.json", "attempt.json"):
            try:
                value = json.loads((attempt_dir / name).read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
            if not isinstance(value, dict):
                continue
            if (
                value.get("attempt_id") == job.active_attempt_id
                and value.get("run_id") == job.execution.get("run_id")
                and value.get("run_key") == job.run_key
                and value.get("outcome")
                in {"executed", "concurrent_cache_win", "verified_cache_match"}
            ):
                return True
        return False

    def recovered_process_groups(self) -> set[int]:
        """Recover process groups even when a crash preceded the SQLite PID update."""

        groups: set[int] = set()
        root = self.config.store.resolve()
        for job in self.repository.active_jobs():
            if job.active_attempt_id is None:
                continue
            identity_path = (
                root
                / "blobs"
                / job.content_sha256[:2]
                / job.content_sha256
                / "attempts"
                / job.active_attempt_id
                / "worker.json"
            ).resolve()
            if not identity_path.is_relative_to(root):
                continue
            try:
                if identity_path.stat().st_size > 4_096:
                    continue
                value = json.loads(identity_path.read_text(encoding="utf-8"))
                if not isinstance(value, dict):
                    continue
                if value.get("attempt_id") != job.active_attempt_id:
                    continue
                process_group_id = value.get("process_group_id")
                if isinstance(process_group_id, int) and process_group_id > 1:
                    groups.add(process_group_id)
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
        return groups
