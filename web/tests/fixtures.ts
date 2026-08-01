import type {
  AttemptDiagnostics,
  ComparisonResult,
  DocumentDetail,
  DocumentPage,
  ExtractorRun,
  ExtractorCapabilityList,
  JobDetail,
  JobEventPage,
  JobPage,
  JobSummary,
  OutputGroup,
  PageGroups,
  WorkspaceSummary,
} from "../src/api/runtime";

export const documentId = `sha256:${"a".repeat(64)}`;

export const workspace: WorkspaceSummary = {
  schema_version: 1,
  library_id: "fixture-library",
  library_name: "Fixture Library",
  product_version: "0.4.0",
  config_hash: "fixture",
  catalog_inventory_run_id: "inventory",
  catalog_created_at: "2026-08-01T00:00:00Z",
  collections: [{ collection_id: "fixture", source_label: "documents" }],
  document_count: 1,
  source_occurrence_count: 1,
};

export const documents: DocumentPage = {
  offset: 0,
  limit: 40,
  total: 1,
  items: [
    {
      document_id: documentId,
      source_path_hint: "fixture:hybrid.pdf",
      media_type: "application/pdf",
      size_bytes: 1200,
      page_count: 1,
      inventory_status: "ok",
      extraction_status: "embedded_text",
      duplicate_count: 0,
      warning_count: 0,
    },
  ],
};

export const detail: DocumentDetail = {
  ...documents.items[0]!,
  content_sha256: "a".repeat(64),
  sources: [
    {
      collection_id: "fixture",
      relative_path: "hybrid.pdf",
      size_bytes: 1200,
      modified_ns: 1,
      observed_at: "2026-08-01T00:00:00Z",
    },
  ],
  pdf_metadata: { Pages: "1" },
  warnings: [],
  duplicate_groups: [],
};

function run(
  runRef: string,
  extractorId: string,
  category: ExtractorRun["category"],
): ExtractorRun {
  return {
    run_ref: runRef,
    extractor_id: extractorId,
    category,
    representation: "normalized_page_text",
    status: "ok",
    run_id: `${extractorId}:fixture`,
    run_key: `${extractorId}-fixture-key`,
    version_label: "fixture 1",
    descriptor: { version: "fixture 1" },
    warnings: [],
    runtime_seconds: 0.1,
    page_count: 1,
    table_count: 0,
    raw_artifacts: [],
  };
}

export const groups: OutputGroup[] = [
  {
    group_id: "group:native",
    exact_text_sha256: "one",
    representative_run_ref: "run:native",
    text: "Balance 123 and year 2023",
    runs: [
      run("run:native", "poppler", "native_text"),
      run("run:ocr", "ocrmypdf-tesseract", "ocr_preprocessing"),
    ],
  },
  {
    group_id: "group:layout",
    exact_text_sha256: "two",
    representative_run_ref: "run:layout",
    text: "Balance 128 and year 2024",
    runs: [run("run:layout", "docling-standard", "layout_parser")],
  },
];

export const pageGroups: PageGroups = {
  document_id: documentId,
  page: 1,
  page_count: 1,
  normalization_version: "normalized_extraction_v1",
  groups,
  assertions: [],
};

export const comparison: ComparisonResult = {
  document_id: documentId,
  page: 1,
  left_run_ref: "run:native",
  right_run_ref: "run:layout",
  normalization_version: "normalized_extraction_v1",
  comparison_algorithm_version: "word_numeric_diff_v1",
  options: { sequence_matcher_autojunk: false },
  equivalent: false,
  segments: [
    {
      index: 0,
      operation: "equal",
      left: [{ text: "Balance ", kind: "word" }],
      right: [{ text: "Balance ", kind: "word" }],
      contains_numeric: false,
    },
    {
      index: 1,
      operation: "replace",
      left: [{ text: "123", kind: "numeric" }],
      right: [{ text: "128", kind: "numeric" }],
      contains_numeric: true,
    },
    {
      index: 2,
      operation: "equal",
      left: [{ text: " and year ", kind: "whitespace" }],
      right: [{ text: " and year ", kind: "whitespace" }],
      contains_numeric: false,
    },
    {
      index: 3,
      operation: "replace",
      left: [{ text: "2023", kind: "numeric" }],
      right: [{ text: "2024", kind: "numeric" }],
      contains_numeric: true,
    },
  ],
  numeric_discrepancies: [
    { segment_index: 1, left_values: ["123"], right_values: ["128"] },
    { segment_index: 3, left_values: ["2023"], right_values: ["2024"] },
  ],
};

export const equivalentComparison: ComparisonResult = {
  ...comparison,
  left_run_ref: "run:layout",
  equivalent: true,
  segments: [
    {
      index: 0,
      operation: "equal",
      left: [{ text: "Balance 128 and year 2024", kind: "word" }],
      right: [{ text: "Balance 128 and year 2024", kind: "word" }],
      contains_numeric: true,
    },
  ],
  numeric_discrepancies: [],
};

export const extractorCapabilities: ExtractorCapabilityList = {
  schema_version: 1,
  document_id: documentId,
  items: [
    {
      extractor_id: "poppler",
      display_name: "Poppler native text",
      category: "native_text",
      supported_media_types: ["application/pdf"],
      dependencies: [
        { name: "pdftotext", available: true, version: "24.0", reason: null },
      ],
      available: true,
      unavailable_reason: null,
      version_label: "24.0",
      resource_class: "light",
      settings_schema: { type: "object", properties: {} },
      default_timeout_seconds: 240,
      deterministic: true,
      output_kinds: ["normalized_page_text"],
      document_supported: true,
      cached: true,
      run_key: "poppler-fixture-key",
      run_id: "poppler:fixture",
      recommended: false,
    },
    {
      extractor_id: "ocrmypdf-tesseract",
      display_name: "OCRmyPDF + Tesseract",
      category: "ocr_preprocessing",
      supported_media_types: ["application/pdf"],
      dependencies: [
        { name: "ocrmypdf", available: false, version: null, reason: "ocrmypdf is not installed" },
      ],
      available: false,
      unavailable_reason: "ocrmypdf is not installed",
      version_label: null,
      resource_class: "ocr",
      settings_schema: { type: "object", properties: { languages: { type: "array" } } },
      default_timeout_seconds: 1_200,
      deterministic: true,
      output_kinds: ["normalized_page_text"],
      document_supported: true,
      cached: false,
      run_key: null,
      run_id: null,
      recommended: true,
    },
  ],
};

function job(overrides: Partial<JobSummary> = {}): JobSummary {
  return {
    job_id: "job-running",
    library_id: workspace.library_id,
    batch_id: null,
    document_id: documentId,
    extractor_id: "poppler",
    settings: {},
    execution_mode: "fresh_verification",
    run_key: "poppler-fixture-key",
    priority: 100,
    resource_class: "light",
    state: "running",
    outcome: null,
    queue_reason: null,
    retry_count: 0,
    automatic_retry_count: 0,
    cancellation_requested: false,
    active_attempt_id: "attempt-one",
    result_run_id: null,
    failure_class: null,
    error_summary: null,
    created_at: "2026-08-01T00:00:00Z",
    queued_at: "2026-08-01T00:00:00Z",
    started_at: "2026-08-01T00:00:01Z",
    completed_at: null,
    updated_at: "2026-08-01T00:00:02Z",
    ...overrides,
  };
}

export const runningJob = job();
export const failedJob = job({
  job_id: "job-failed",
  extractor_id: "docling-standard",
  resource_class: "model_heavy",
  state: "failed",
  outcome: "failed",
  active_attempt_id: null,
  failure_class: "dependency_unavailable",
  error_summary: "Docling dependency is unavailable",
  completed_at: "2026-08-01T00:00:03Z",
});

export const jobPage: JobPage = {
  schema_version: 1,
  items: [runningJob, failedJob],
  offset: 0,
  limit: 50,
  total: 2,
  counts: { active: 1, queued: 0, failed: 1 },
};

export const runningJobDetail: JobDetail = {
  schema_version: 1,
  job: runningJob,
  attempts: [
    {
      attempt_id: "attempt-one",
      attempt_number: 1,
      state: "running",
      scheduler_instance_id: "scheduler-fixture",
      worker_pid: 123,
      process_group_id: 123,
      heartbeat_at: "2026-08-01T00:00:02Z",
      deadline_at: "2026-08-01T00:04:02Z",
      exit_code: null,
      publication_outcome: null,
      artifact_manifest_sha256: null,
      failure_class: null,
      error_summary: null,
      started_at: "2026-08-01T00:00:01Z",
      completed_at: null,
      process_alive: true,
      heartbeat_age_seconds: 12,
      deadline_expired: false,
    },
  ],
};

export const runningAttemptDiagnostics: AttemptDiagnostics = {
  schema_version: 1,
  attempt_id: "attempt-one",
  retained: true,
  stdout_tail: "fixture stdout",
  stderr_tail: "fixture stderr",
  stdout_truncated_bytes: 0,
  stderr_truncated_bytes: 0,
  extractor_descriptor: { extractor: "poppler", version: "fixture" },
  settings: {},
  environment: { python: "3.12", platform: "fixture", machine: "fixture" },
  staging_status: "retained",
  validation_status: "pending",
  publication_status: "pending",
  projection_status: "not published",
};

export const runningJobEvents: JobEventPage = {
  schema_version: 1,
  job_id: runningJob.job_id,
  after: 0,
  items: [
    {
      sequence: 1,
      event_type: "queued",
      stage: "queued",
      progress_current: null,
      progress_total: null,
      detail: {},
      created_at: "2026-08-01T00:00:00Z",
    },
    {
      sequence: 2,
      event_type: "heartbeat",
      stage: "running",
      progress_current: null,
      progress_total: null,
      detail: { worker_pid: 123 },
      created_at: "2026-08-01T00:00:02Z",
    },
  ],
};
