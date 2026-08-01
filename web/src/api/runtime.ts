import type { components } from "./generated/schema";

export type WorkspaceSummary = components["schemas"]["WorkspaceSummary"];
export type AppSummary = components["schemas"]["AppSummary"];
export type KnownLibraryList = components["schemas"]["KnownLibraryList"];
export type KnownLibrarySummary = components["schemas"]["KnownLibrarySummary"];
export type LibraryDetail = components["schemas"]["LibraryDetail"];
export type LibraryActivation = components["schemas"]["LibraryActivation"];
export type DocumentPage = components["schemas"]["DocumentPage"];
export type DocumentSummary = components["schemas"]["DocumentSummary"];
export type DocumentDetail = components["schemas"]["DocumentDetail"];
export type SearchPage = components["schemas"]["SearchPage"];
export type PageGroups = components["schemas"]["PageGroups"];
export type OutputGroup = components["schemas"]["OutputGroup"];
export type ExtractorRun = components["schemas"]["ExtractorRun"];
export type ComparisonRequest = components["schemas"]["ComparisonRequest"];
export type ComparisonResult = components["schemas"]["ComparisonResult"];
export type DiffToken = components["schemas"]["DiffToken"];
export type Diagnostics = components["schemas"]["Diagnostics"];
export type ExtractorCapabilityList = components["schemas"]["ExtractorCapabilityList"];
export type ExtractorCapability = components["schemas"]["ExtractorCapability"];
export type ExtractionJobRequest = components["schemas"]["ExtractionJobRequest"];
export type ExtractionBatchRequest = components["schemas"]["ExtractionBatchRequest"];
export type ExtractionBatchPreflight = components["schemas"]["ExtractionBatchPreflight"];
export type JobSummary = components["schemas"]["JobSummary"];
export type JobDetail = components["schemas"]["JobDetail"];
export type JobPage = components["schemas"]["JobPage"];
export type JobEventPage = components["schemas"]["JobEventPage"];
export type JobCreationResponse = components["schemas"]["JobCreationResponse"];
export type JobBatchPage = components["schemas"]["JobBatchPage"];
export type JobBatchCreationResponse = components["schemas"]["JobBatchCreationResponse"];
export type JobBatchCancellationResponse = components["schemas"]["JobBatchCancellationResponse"];
export type QueueState = components["schemas"]["QueueState"];
export type AttemptDiagnostics = components["schemas"]["AttemptDiagnostics"];

export interface SearchInput {
  query: string;
  mode: "literal" | "fts";
  limit?: number;
}

export interface HostCapabilities {
  readonly createManagedLibrary: boolean;
  readonly registerExistingLibrary: boolean;
  readonly addCollection: boolean;
}

export interface NativeLibraryOperation {
  readonly outcome: "completed" | "cancelled";
  readonly libraryId: string | null;
  readonly status: "ready" | "unavailable" | "integrity_error" | null;
}

export interface NativeCollectionOperation {
  readonly outcome: "completed" | "cancelled";
  readonly libraryId: string | null;
  readonly changed: boolean;
  readonly preflightKind: string | null;
}

export const unavailableHostCapabilities: HostCapabilities = {
  createManagedLibrary: false,
  registerExistingLibrary: false,
  addCollection: false,
};

export class NativeHostUnavailableError extends Error {}

export interface DocEvidenceRuntime {
  readonly hostCapabilities: HostCapabilities;
  createManagedLibrary(): Promise<NativeLibraryOperation>;
  registerExistingLibrary(): Promise<NativeLibraryOperation>;
  addCollection(libraryId: string): Promise<NativeCollectionOperation>;
  getApp(signal?: AbortSignal): Promise<AppSummary>;
  listLibraries(signal?: AbortSignal): Promise<KnownLibraryList>;
  getLibrary(libraryId: string, signal?: AbortSignal): Promise<LibraryDetail>;
  activateLibrary(libraryId: string, signal?: AbortSignal): Promise<LibraryActivation>;
  getWorkspace(libraryId: string, signal?: AbortSignal): Promise<WorkspaceSummary>;
  listDocuments(libraryId: string, offset: number, limit: number, signal?: AbortSignal): Promise<DocumentPage>;
  getDocument(libraryId: string, documentId: string, signal?: AbortSignal): Promise<DocumentDetail>;
  search(libraryId: string, input: SearchInput, signal?: AbortSignal): Promise<SearchPage>;
  getPageGroups(libraryId: string, documentId: string, page: number, signal?: AbortSignal): Promise<PageGroups>;
  compare(libraryId: string, input: ComparisonRequest, signal?: AbortSignal): Promise<ComparisonResult>;
  getPageRender(libraryId: string, documentId: string, page: number, signal?: AbortSignal): Promise<Blob>;
  getArtifact(libraryId: string, artifactId: string, signal?: AbortSignal): Promise<Blob>;
  getDiagnostics(libraryId: string, signal?: AbortSignal): Promise<Diagnostics>;
  getExtractors(libraryId: string, documentId?: string, signal?: AbortSignal): Promise<ExtractorCapabilityList>;
  createExtraction(libraryId: string, input: ExtractionJobRequest, idempotencyKey?: string, signal?: AbortSignal): Promise<JobCreationResponse>;
  createExtractionBatch(libraryId: string, input: ExtractionBatchRequest, idempotencyKey?: string, signal?: AbortSignal): Promise<JobBatchCreationResponse>;
  preflightImageOnlyOcr(libraryId: string, signal?: AbortSignal): Promise<ExtractionBatchPreflight>;
  listJobs(libraryId: string, state?: string, offset?: number, limit?: number, signal?: AbortSignal): Promise<JobPage>;
  getJob(libraryId: string, jobId: string, signal?: AbortSignal): Promise<JobDetail>;
  getJobEvents(libraryId: string, jobId: string, after?: number, limit?: number, signal?: AbortSignal): Promise<JobEventPage>;
  cancelJob(libraryId: string, jobId: string, signal?: AbortSignal): Promise<JobDetail>;
  retryJob(libraryId: string, jobId: string, signal?: AbortSignal): Promise<JobDetail>;
  repairJobProjection(libraryId: string, jobId: string, signal?: AbortSignal): Promise<JobDetail>;
  getAttemptDiagnostics(libraryId: string, jobId: string, attemptId: string, signal?: AbortSignal): Promise<AttemptDiagnostics>;
  listBatches(libraryId: string, offset?: number, limit?: number, signal?: AbortSignal): Promise<JobBatchPage>;
  cancelBatch(libraryId: string, batchId: string, cancelRunning: boolean, signal?: AbortSignal): Promise<JobBatchCancellationResponse>;
  getQueueState(libraryId: string, signal?: AbortSignal): Promise<QueueState>;
  setQueuePaused(libraryId: string, paused: boolean, signal?: AbortSignal): Promise<QueueState>;
}
