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

export interface SearchInput {
  query: string;
  mode: "literal" | "fts";
  limit?: number;
}

export interface DocEvidenceRuntime {
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
}
