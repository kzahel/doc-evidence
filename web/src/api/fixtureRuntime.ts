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
}

export function comparisonKey(input: ComparisonRequest): string {
  return [input.document_id, input.page, input.left_run_ref, input.right_run_ref].join("|");
}

export class FixtureRuntime implements DocEvidenceRuntime {
  constructor(private readonly data: FixtureRuntimeData) {}

  private check(): void {
    if (this.data.error) throw this.data.error;
  }

  async getWorkspace(): Promise<WorkspaceSummary> {
    this.check();
    return this.data.workspace;
  }

  async listDocuments(): Promise<DocumentPage> {
    this.check();
    return this.data.documents;
  }

  async getDocument(documentId: string): Promise<DocumentDetail> {
    this.check();
    const value = this.data.details?.[documentId];
    if (!value) throw new Error("Fixture document not found");
    return value;
  }

  async search(input: SearchInput): Promise<SearchPage> {
    this.check();
    return {
      query: input.query,
      mode: input.mode,
      limit: input.limit ?? 40,
      items: [],
    };
  }

  async getPageGroups(documentId: string, page: number): Promise<PageGroups> {
    this.check();
    const value = this.data.groups?.[`${documentId}|${page}`];
    if (!value) throw new Error("Fixture page groups not found");
    return value;
  }

  async compare(input: ComparisonRequest): Promise<ComparisonResult> {
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
}
