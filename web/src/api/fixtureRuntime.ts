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
}
