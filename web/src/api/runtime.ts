import type { components } from "./generated/schema";

export type WorkspaceSummary = components["schemas"]["WorkspaceSummary"];
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
  getWorkspace(signal?: AbortSignal): Promise<WorkspaceSummary>;
  listDocuments(offset: number, limit: number, signal?: AbortSignal): Promise<DocumentPage>;
  getDocument(documentId: string, signal?: AbortSignal): Promise<DocumentDetail>;
  search(input: SearchInput, signal?: AbortSignal): Promise<SearchPage>;
  getPageGroups(documentId: string, page: number, signal?: AbortSignal): Promise<PageGroups>;
  compare(input: ComparisonRequest, signal?: AbortSignal): Promise<ComparisonResult>;
  getPageRender(documentId: string, page: number, signal?: AbortSignal): Promise<Blob>;
  getArtifact(artifactId: string, signal?: AbortSignal): Promise<Blob>;
  getDiagnostics(signal?: AbortSignal): Promise<Diagnostics>;
}
