"""Typed localhost API contracts owned by Python.

These models describe the wire vocabulary without importing FastAPI or any
concrete storage adapter. Persisted artifact formats remain separately
versioned contracts.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CollectionSummary(ContractModel):
    collection_id: str
    source_label: str


class AppSummary(ContractModel):
    schema_version: Literal[1] = 1
    active_library_id: str | None
    default_library_id: str | None
    last_library_id: str | None


class KnownLibrarySummary(ContractModel):
    library_id: str
    name: str
    store_mode: Literal["managed", "adopted"]
    collection_count: int = Field(ge=0)
    last_opened_at: str | None
    status: Literal["ready", "unavailable", "integrity_error"]
    status_detail: str | None
    is_default: bool
    is_active: bool


class KnownLibraryList(ContractModel):
    schema_version: Literal[1] = 1
    items: list[KnownLibrarySummary]


class LibraryCollection(ContractModel):
    collection_id: str
    source_label: str
    available: bool


class LibraryDetail(ContractModel):
    schema_version: Literal[1] = 1
    library: KnownLibrarySummary
    collections: list[LibraryCollection]
    collection_selection: Literal["trusted_cli_or_native"] = "trusted_cli_or_native"
    collection_preflight_kinds: list[str]


class LibraryActivation(ContractModel):
    schema_version: Literal[1] = 1
    active_library_id: str


class WorkspaceSummary(ContractModel):
    schema_version: Literal[1] = 1
    library_id: str
    library_name: str
    product_version: str
    config_hash: str
    catalog_inventory_run_id: str | None
    catalog_created_at: str | None
    collections: list[CollectionSummary]
    document_count: int = Field(ge=0)
    source_occurrence_count: int = Field(ge=0)


class SourceOccurrence(ContractModel):
    collection_id: str
    relative_path: str
    size_bytes: int = Field(ge=0)
    modified_ns: int = Field(ge=0)
    observed_at: str


class DocumentSummary(ContractModel):
    document_id: str
    source_path_hint: str
    media_type: str
    size_bytes: int = Field(ge=0)
    page_count: int | None = Field(default=None, ge=0)
    inventory_status: str
    extraction_status: str
    duplicate_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)


class DocumentPage(ContractModel):
    items: list[DocumentSummary]
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
    total: int = Field(ge=0)


class DuplicateGroup(ContractModel):
    kind: Literal["byte", "normalized_text"]
    group_key: str
    member_count: int = Field(ge=1)


class DocumentDetail(DocumentSummary):
    content_sha256: str
    sources: list[SourceOccurrence]
    pdf_metadata: dict[str, str]
    warnings: list[str]
    duplicate_groups: list[DuplicateGroup]


class SearchHit(ContractModel):
    document_id: str
    page: int = Field(ge=1)
    source_path_hint: str
    snippet: str
    score: float | None


class SearchPage(ContractModel):
    query: str
    mode: Literal["literal", "fts"]
    items: list[SearchHit]
    limit: int = Field(ge=1)


class RawArtifact(ContractModel):
    artifact_id: str
    label: str
    media_type: str
    size_bytes: int = Field(ge=0)


class ExtractorRun(ContractModel):
    run_ref: str
    extractor_id: str
    category: Literal["native_text", "ocr_preprocessing", "layout_parser", "other"]
    representation: Literal["normalized_page_text"] = "normalized_page_text"
    status: str
    run_id: str
    run_key: str
    version_label: str
    descriptor: dict[str, Any]
    warnings: list[str]
    runtime_seconds: float | None = Field(default=None, ge=0)
    page_count: int = Field(ge=0)
    table_count: int | None = Field(default=None, ge=0)
    raw_artifacts: list[RawArtifact]


class RunList(ContractModel):
    document_id: str
    items: list[ExtractorRun]


class BenchmarkAssertion(ContractModel):
    suite_id: str
    benchmark_run_id: str
    extractor_id: str
    assertion_id: str
    kind: str
    expected: Any
    actual: Any
    manually_verified: bool
    passed: bool


class OutputGroup(ContractModel):
    group_id: str
    exact_text_sha256: str
    representative_run_ref: str
    text: str
    runs: list[ExtractorRun]


class PageGroups(ContractModel):
    document_id: str
    page: int = Field(ge=1)
    page_count: int = Field(ge=1)
    normalization_version: Literal["normalized_extraction_v1"] = (
        "normalized_extraction_v1"
    )
    groups: list[OutputGroup]
    assertions: list[BenchmarkAssertion]


class PageSummary(ContractModel):
    document_id: str
    page: int = Field(ge=1)
    page_count: int = Field(ge=1)
    media_type: str
    render_available: bool


class DiffToken(ContractModel):
    text: str
    kind: Literal["word", "numeric", "whitespace", "punctuation"]


class DiffSegment(ContractModel):
    index: int = Field(ge=0)
    operation: Literal["equal", "insert", "delete", "replace"]
    left: list[DiffToken]
    right: list[DiffToken]
    contains_numeric: bool


class NumericDiscrepancy(ContractModel):
    segment_index: int = Field(ge=0)
    left_values: list[str]
    right_values: list[str]


class ComparisonRequest(ContractModel):
    document_id: str
    page: int = Field(ge=1)
    left_run_ref: str
    right_run_ref: str


class ComparisonResult(ContractModel):
    document_id: str
    page: int = Field(ge=1)
    left_run_ref: str
    right_run_ref: str
    normalization_version: Literal["normalized_extraction_v1"] = (
        "normalized_extraction_v1"
    )
    comparison_algorithm_version: Literal["word_numeric_diff_v1"] = (
        "word_numeric_diff_v1"
    )
    options: dict[str, Any]
    equivalent: bool
    segments: list[DiffSegment]
    numeric_discrepancies: list[NumericDiscrepancy]


class ExtractorDependency(ContractModel):
    name: str
    available: bool
    version: str | None
    reason: str | None


class ExtractorCapability(ContractModel):
    extractor_id: str
    display_name: str
    category: Literal["native_text", "ocr_preprocessing", "layout_parser", "other"]
    supported_media_types: list[str]
    dependencies: list[ExtractorDependency]
    available: bool
    unavailable_reason: str | None
    version_label: str | None
    resource_class: Literal["light", "ocr", "model_heavy"]
    settings_schema: dict[str, Any]
    default_timeout_seconds: int = Field(ge=1)
    deterministic: bool
    output_kinds: list[str]
    document_supported: bool | None
    cached: bool | None
    run_key: str | None
    run_id: str | None
    recommended: bool


class ExtractorCapabilityList(ContractModel):
    schema_version: Literal[1] = 1
    document_id: str | None
    items: list[ExtractorCapability]


JobStateContract = Literal[
    "queued",
    "starting",
    "running",
    "cancelling",
    "succeeded",
    "failed",
    "cancelled",
    "interrupted",
]


class ExtractionJobRequest(ContractModel):
    document_id: str = Field(min_length=1, max_length=100)
    extractor_id: str = Field(min_length=1, max_length=100)
    settings: dict[str, Any] = Field(default_factory=dict)
    execution_mode: Literal["reuse_or_execute", "fresh_verification"] = (
        "reuse_or_execute"
    )


class ExtractionBatchRequest(ContractModel):
    document_ids: list[str] = Field(min_length=1, max_length=200)
    extractor_ids: list[str] = Field(min_length=1, max_length=5)
    settings: dict[str, dict[str, Any]] = Field(default_factory=dict)
    execution_mode: Literal["reuse_or_execute", "fresh_verification"] = (
        "reuse_or_execute"
    )
    confirmed: bool


class JobSummary(ContractModel):
    job_id: str
    library_id: str
    batch_id: str | None
    document_id: str
    extractor_id: str
    settings: dict[str, Any]
    execution_mode: Literal["reuse_or_execute", "fresh_verification"]
    run_key: str | None
    priority: int
    resource_class: Literal["light", "ocr", "model_heavy"]
    state: JobStateContract
    outcome: str | None
    queue_reason: str | None
    retry_count: int = Field(ge=0)
    automatic_retry_count: int = Field(ge=0, le=1)
    cancellation_requested: bool
    active_attempt_id: str | None
    result_run_id: str | None
    failure_class: str | None
    error_summary: str | None
    created_at: str
    queued_at: str
    started_at: str | None
    completed_at: str | None
    updated_at: str


class JobAttempt(ContractModel):
    attempt_id: str
    attempt_number: int = Field(ge=1)
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


class JobDetail(ContractModel):
    schema_version: Literal[1] = 1
    job: JobSummary
    attempts: list[JobAttempt]


class JobCounts(ContractModel):
    queued: int = Field(ge=0)
    active: int = Field(ge=0)
    failed: int = Field(ge=0)


class JobPage(ContractModel):
    schema_version: Literal[1] = 1
    items: list[JobSummary]
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
    total: int = Field(ge=0)
    counts: JobCounts


class JobCreationResponse(ContractModel):
    schema_version: Literal[1] = 1
    disposition: Literal["created", "coalesced", "idempotent", "cache_hit"]
    job: JobSummary


class JobEvent(ContractModel):
    sequence: int = Field(ge=1)
    event_type: str
    stage: str
    progress_current: int | None = Field(default=None, ge=0)
    progress_total: int | None = Field(default=None, ge=0)
    detail: dict[str, Any]
    created_at: str


class JobEventPage(ContractModel):
    schema_version: Literal[1] = 1
    job_id: str
    after: int = Field(ge=0)
    items: list[JobEvent]


class JobBatchSummary(ContractModel):
    batch_id: str
    library_id: str
    selection: dict[str, Any]
    policy: dict[str, Any]
    status: str
    requested_count: int = Field(ge=0)
    child_count: int = Field(ge=0)
    cache_hit_count: int = Field(ge=0)
    succeeded_count: int = Field(ge=0)
    failed_count: int = Field(ge=0)
    cancelled_count: int = Field(ge=0)
    created_at: str
    started_at: str | None
    completed_at: str | None


class JobBatchCreationResponse(ContractModel):
    schema_version: Literal[1] = 1
    disposition: Literal["created", "idempotent"]
    batch: JobBatchSummary
    jobs: list[JobSummary]


class JobBatchPage(ContractModel):
    schema_version: Literal[1] = 1
    items: list[JobBatchSummary]
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
    total: int = Field(ge=0)


class DiagnosticCheck(ContractModel):
    name: str
    status: Literal["ok", "warning", "error"]
    detail: str


class Diagnostics(ContractModel):
    schema_version: Literal[1] = 1
    checks: list[DiagnosticCheck]
    catalog_metadata: dict[str, str]


class ApiProblem(ContractModel):
    code: str
    message: str
