"""Framework-independent durable extraction-job contracts and service port."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from doc_evidence.extractor_registry import ResourceClass

JobState = Literal[
    "queued",
    "starting",
    "running",
    "cancelling",
    "succeeded",
    "failed",
    "cancelled",
    "interrupted",
]
ExecutionMode = Literal["reuse_or_execute", "fresh_verification"]
TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})
ACTIVE_STATES = frozenset({"queued", "starting", "running", "cancelling"})


@dataclass(frozen=True)
class JobSpec:
    library_id: str
    document_id: str
    content_sha256: str
    extractor_id: str
    cache_key: str
    settings: dict[str, Any]
    execution: dict[str, Any]
    execution_mode: ExecutionMode
    run_key: str
    priority: int
    resource_class: ResourceClass
    idempotency_key: str | None = None
    batch_id: str | None = None


@dataclass(frozen=True)
class CachedResult:
    run_id: str
    artifact_path: str


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    library_id: str
    batch_id: str | None
    idempotency_key: str | None
    document_id: str
    content_sha256: str
    extractor_id: str
    cache_key: str
    settings: dict[str, Any]
    execution: dict[str, Any]
    execution_mode: ExecutionMode
    run_key: str | None
    priority: int
    resource_class: ResourceClass
    state: JobState
    outcome: str | None
    queue_reason: str | None
    retry_count: int
    automatic_retry_count: int
    cancellation_requested: bool
    active_attempt_id: str | None
    result_run_id: str | None
    result_artifact_path: str | None
    failure_class: str | None
    error_summary: str | None
    created_at: str
    queued_at: str
    started_at: str | None
    completed_at: str | None
    updated_at: str


@dataclass(frozen=True)
class JobCreation:
    job: JobRecord
    disposition: Literal["created", "coalesced", "idempotent", "cache_hit"]


@dataclass(frozen=True)
class ClaimedJob:
    job: JobRecord
    attempt_id: str
    attempt_number: int
    deadline_at: str


@dataclass(frozen=True)
class JobEventRecord:
    sequence: int
    event_type: str
    stage: str
    progress_current: int | None
    progress_total: int | None
    detail: dict[str, Any]
    created_at: str


@dataclass(frozen=True)
class ActiveAttemptRecord:
    job_id: str
    attempt_id: str
    worker_pid: int | None
    process_group_id: int | None
    heartbeat_at: str | None
    deadline_at: str


@dataclass(frozen=True)
class JobAttemptRecord:
    attempt_id: str
    attempt_number: int
    state: str
    scheduler_instance_id: str
    worker_pid: int | None
    process_group_id: int | None
    heartbeat_at: str | None
    deadline_at: str
    exit_code: int | None
    publication_outcome: str | None
    artifact_manifest_sha256: str | None
    failure_class: str | None
    error_summary: str | None
    started_at: str
    completed_at: str | None


@dataclass(frozen=True)
class JobBatchRecord:
    batch_id: str
    library_id: str
    selection: dict[str, Any]
    policy: dict[str, Any]
    status: str
    requested_count: int
    child_count: int
    cache_hit_count: int
    succeeded_count: int
    failed_count: int
    cancelled_count: int
    created_at: str
    started_at: str | None
    completed_at: str | None


@dataclass(frozen=True)
class BatchCreation:
    batch: JobBatchRecord
    jobs: tuple[JobRecord, ...]
    disposition: Literal["created", "idempotent"]


@dataclass(frozen=True)
class ExtractorDependencyRecord:
    name: str
    available: bool
    version: str | None
    reason: str | None


@dataclass(frozen=True)
class ExtractorCapabilityRecord:
    extractor_id: str
    display_name: str
    category: str
    supported_media_types: tuple[str, ...]
    dependencies: tuple[ExtractorDependencyRecord, ...]
    available: bool
    unavailable_reason: str | None
    version_label: str | None
    resource_class: ResourceClass
    settings_schema: dict[str, Any]
    default_timeout_seconds: int
    deterministic: bool
    output_kinds: tuple[str, ...]
    document_supported: bool | None
    cached: bool | None
    run_key: str | None
    run_id: str | None
    recommended: bool


@dataclass(frozen=True)
class JobCountRecord:
    queued: int
    active: int
    failed: int


class JobService(Protocol):
    library_id: str

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
    ) -> JobCreation: ...

    def get(self, job_id: str) -> JobRecord: ...

    def list(
        self,
        *,
        states: tuple[JobState, ...] = (),
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[JobRecord], int]: ...

    def events(
        self, job_id: str, *, after: int = 0, limit: int = 200
    ) -> list[JobEventRecord]: ...

    def attempts(self, job_id: str) -> tuple[JobAttemptRecord, ...]: ...

    def cancel(self, job_id: str) -> JobRecord: ...

    def retry(self, job_id: str) -> JobRecord: ...

    def enqueue_batch(
        self,
        *,
        document_ids: list[str],
        extractor_ids: list[str],
        settings: dict[str, dict[str, Any]] | None = None,
        execution_mode: ExecutionMode = "reuse_or_execute",
        confirmed: bool,
        idempotency_key: str | None = None,
    ) -> BatchCreation: ...

    def batch(self, batch_id: str) -> JobBatchRecord: ...

    def batches(
        self, *, offset: int = 0, limit: int = 50
    ) -> tuple[list[JobBatchRecord], int]: ...

    def capabilities(
        self, *, document_id: str | None = None
    ) -> tuple[ExtractorCapabilityRecord, ...]: ...

    def counts(self) -> JobCountRecord: ...
