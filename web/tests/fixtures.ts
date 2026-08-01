import type {
  ComparisonResult,
  DocumentDetail,
  DocumentPage,
  ExtractorRun,
  OutputGroup,
  PageGroups,
  WorkspaceSummary,
} from "../src/api/runtime";

export const documentId = `sha256:${"a".repeat(64)}`;

export const workspace: WorkspaceSummary = {
  schema_version: 1,
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
