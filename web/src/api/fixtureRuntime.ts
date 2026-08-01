import type {
  ComparisonRequest,
  ComparisonResult,
  Diagnostics,
  DocEvidenceRuntime,
  DocumentDetail,
  DocumentPage,
  PageGroups,
  SearchInput,
  SearchPage,
  WorkspaceSummary,
  AppSummary,
  KnownLibraryList,
  LibraryDetail,
  LibraryActivation,
  ExtractorCapabilityList,
  ExtractionJobRequest,
  ExtractionBatchRequest,
  ExtractionBatchPreflight,
  JobCreationResponse,
  JobBatchCreationResponse,
  JobPage,
  JobDetail,
  JobEventPage,
  JobBatchPage,
  QueueState,
  AttemptDiagnostics,
  JobBatchCancellationResponse,
} from "./runtime";

export interface FixtureRuntimeData {
  workspace: WorkspaceSummary;
  documents: DocumentPage;
  details?: Record<string, DocumentDetail>;
  groups?: Record<string, PageGroups>;
  comparisons?: Record<string, ComparisonResult>;
  diagnostics?: Diagnostics;
  render?: Blob;
  error?: Error;
  app?: AppSummary;
  libraries?: KnownLibraryList;
  libraryDetails?: Record<string, LibraryDetail>;
  extractors?: ExtractorCapabilityList;
  jobs?: JobPage;
  jobDetails?: Record<string, JobDetail>;
  jobEvents?: Record<string, JobEventPage>;
  batches?: JobBatchPage;
  jobCreation?: JobCreationResponse;
  batchCreation?: JobBatchCreationResponse;
  queueState?: QueueState;
  batchPreflight?: ExtractionBatchPreflight;
  attemptDiagnostics?: Record<string, AttemptDiagnostics>;
  batchCancellation?: JobBatchCancellationResponse;
}

export function comparisonKey(input: ComparisonRequest): string {
  return [input.document_id, input.page, input.left_run_ref, input.right_run_ref].join("|");
}

export class FixtureRuntime implements DocEvidenceRuntime {
  constructor(private readonly data: FixtureRuntimeData) {}

  private check(): void {
    if (this.data.error) throw this.data.error;
  }

  async getApp(): Promise<AppSummary> {
    this.check();
    return this.data.app ?? {
      schema_version: 1,
      active_library_id: this.data.workspace.library_id,
      default_library_id: this.data.workspace.library_id,
      last_library_id: this.data.workspace.library_id,
    };
  }

  async listLibraries(): Promise<KnownLibraryList> {
    this.check();
    return this.data.libraries ?? {
      schema_version: 1,
      items: [{
        library_id: this.data.workspace.library_id,
        name: this.data.workspace.library_name,
        store_mode: "adopted",
        collection_count: this.data.workspace.collections.length,
        last_opened_at: "2026-08-01T00:00:00Z",
        status: "ready",
        status_detail: null,
        is_default: true,
        is_active: true,
      }],
    };
  }

  async getLibrary(libraryId: string): Promise<LibraryDetail> {
    this.check();
    const configured = this.data.libraryDetails?.[libraryId];
    if (configured) return configured;
    const summary = (await this.listLibraries()).items.find((item) => item.library_id === libraryId);
    if (!summary) throw new Error("Fixture library not found");
    return {
      schema_version: 1,
      library: summary,
      collections: this.data.workspace.collections.map((collection) => ({
        ...collection,
        available: true,
      })),
      collection_selection: "trusted_cli_or_native",
      collection_preflight_kinds: ["add_sibling", "replace_children", "already_covered", "same_root", "store_overlap", "unavailable"],
    };
  }

  async activateLibrary(libraryId: string): Promise<LibraryActivation> {
    await this.getLibrary(libraryId);
    return { schema_version: 1, active_library_id: libraryId };
  }

  async getWorkspace(_libraryId: string): Promise<WorkspaceSummary> {
    this.check();
    return this.data.workspace;
  }

  async listDocuments(): Promise<DocumentPage> {
    this.check();
    return this.data.documents;
  }

  async getDocument(_libraryId: string, documentId: string): Promise<DocumentDetail> {
    this.check();
    const value = this.data.details?.[documentId];
    if (!value) throw new Error("Fixture document not found");
    return value;
  }

  async search(_libraryId: string, input: SearchInput): Promise<SearchPage> {
    this.check();
    return {
      query: input.query,
      mode: input.mode,
      limit: input.limit ?? 40,
      items: [],
    };
  }

  async getPageGroups(_libraryId: string, documentId: string, page: number): Promise<PageGroups> {
    this.check();
    const value = this.data.groups?.[`${documentId}|${page}`];
    if (!value) throw new Error("Fixture page groups not found");
    return value;
  }

  async compare(_libraryId: string, input: ComparisonRequest): Promise<ComparisonResult> {
    this.check();
    const value = this.data.comparisons?.[comparisonKey(input)];
    if (!value) throw new Error("Fixture comparison not found");
    return value;
  }

  async getPageRender(): Promise<Blob> {
    this.check();
    return this.data.render ?? new Blob(["fixture"], { type: "image/png" });
  }

  async getArtifact(): Promise<Blob> {
    this.check();
    return new Blob(["fixture artifact"], { type: "text/plain" });
  }

  async getDiagnostics(): Promise<Diagnostics> {
    this.check();
    return this.data.diagnostics ?? { schema_version: 1, checks: [], catalog_metadata: {} };
  }

  async getExtractors(_libraryId: string, documentId?: string): Promise<ExtractorCapabilityList> {
    this.check();
    return this.data.extractors ?? { schema_version: 1, document_id: documentId ?? null, items: [] };
  }

  async createExtraction(_libraryId: string, _input: ExtractionJobRequest): Promise<JobCreationResponse> {
    this.check();
    if (!this.data.jobCreation) throw new Error("Fixture job creation not configured");
    return this.data.jobCreation;
  }

  async createExtractionBatch(_libraryId: string, _input: ExtractionBatchRequest): Promise<JobBatchCreationResponse> {
    this.check();
    if (!this.data.batchCreation) throw new Error("Fixture batch creation not configured");
    return this.data.batchCreation;
  }

  async preflightImageOnlyOcr(): Promise<ExtractionBatchPreflight> {
    this.check();
    return this.data.batchPreflight ?? {
      schema_version: 1,
      policy: "image_only_pdf_missing_ocr",
      extractor_id: "ocrmypdf-tesseract",
      document_ids: [],
      candidate_count: 0,
      cache_hit_count: 0,
      execution_count: 0,
      unsupported_count: 0,
      missing_dependency_count: 0,
      resource_class: "ocr",
      concurrency_limit: 1,
      maximum_batch_size: 200,
      over_limit_count: 0,
    };
  }

  async listJobs(): Promise<JobPage> {
    this.check();
    return this.data.jobs ?? {
      schema_version: 1,
      items: [],
      offset: 0,
      limit: 50,
      total: 0,
      counts: { queued: 0, active: 0, failed: 0 },
    };
  }

  async getJob(_libraryId: string, jobId: string): Promise<JobDetail> {
    this.check();
    const value = this.data.jobDetails?.[jobId];
    if (!value) throw new Error("Fixture job not found");
    return value;
  }

  async getJobEvents(_libraryId: string, jobId: string): Promise<JobEventPage> {
    this.check();
    return this.data.jobEvents?.[jobId] ?? { schema_version: 1, job_id: jobId, after: 0, items: [] };
  }

  async cancelJob(_libraryId: string, jobId: string): Promise<JobDetail> {
    return this.getJob(_libraryId, jobId);
  }

  async retryJob(_libraryId: string, jobId: string): Promise<JobDetail> {
    return this.getJob(_libraryId, jobId);
  }

  async repairJobProjection(_libraryId: string, jobId: string): Promise<JobDetail> {
    return this.getJob(_libraryId, jobId);
  }

  async getAttemptDiagnostics(
    _libraryId: string,
    _jobId: string,
    attemptId: string,
  ): Promise<AttemptDiagnostics> {
    this.check();
    const value = this.data.attemptDiagnostics?.[attemptId];
    if (!value) throw new Error("Fixture attempt diagnostics not found");
    return value;
  }

  async listBatches(): Promise<JobBatchPage> {
    this.check();
    return this.data.batches ?? { schema_version: 1, items: [], offset: 0, limit: 50, total: 0 };
  }

  async cancelBatch(
    _libraryId: string,
    _batchId: string,
    _cancelRunning: boolean,
  ): Promise<JobBatchCancellationResponse> {
    this.check();
    if (!this.data.batchCancellation) {
      throw new Error("Fixture batch cancellation not configured");
    }
    return this.data.batchCancellation;
  }

  async getQueueState(): Promise<QueueState> {
    this.check();
    return this.data.queueState ?? {
      schema_version: 1,
      paused: false,
      scheduler_instance_id: null,
      acquired_at: null,
      heartbeat_at: null,
    };
  }

  async setQueuePaused(_libraryId: string, paused: boolean): Promise<QueueState> {
    this.check();
    return { ...(await this.getQueueState()), paused };
  }
}
