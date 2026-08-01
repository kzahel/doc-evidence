"""Framework-independent extraction job use cases and attempt execution."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
from doc_evidence.persistence.jobs import (
    CachedResult,
    ClaimedJob,
    ExecutionMode,
    JobCreation,
    JobEventRecord,
    JobRecord,
    JobRepository,
    JobSpec,
    JobState,
)
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


class ExtractionJobApplication:
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
        source: SourceSnapshot, prepared: PreparedExtraction
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
        cached = (
            self._cached(source=source, prepared=prepared)
            if execution_mode == "reuse_or_execute"
            else None
        )
        return self.repository.create(
            JobSpec(
                library_id=self.library_id,
                document_id=source.document_id,
                content_sha256=source.content_sha256,
                extractor_id=extractor_id,
                cache_key=cache_key,
                settings=prepared.execution.settings,
                execution=self._execution_payload(source, prepared),
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
            payload.get("run_key") != job.run_key
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

    def cancel(self, job_id: str) -> JobRecord:
        return self.repository.request_cancel(job_id)

    def retry(self, job_id: str) -> JobRecord:
        return self.repository.retry(job_id)

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
