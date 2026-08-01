import { create } from "zustand";

type DiffMode = "differences" | "full";

interface WorkspaceState {
  selectedDocumentId: string | null;
  page: number;
  baselineGroupId: string | null;
  comparisonGroupId: string | null;
  diffMode: DiffMode;
  numericIndex: number;
  searchQuery: string;
  searchMode: "literal" | "fts";
  documentOffset: number;
  selectDocument: (documentId: string | null, page?: number) => void;
  setPage: (page: number) => void;
  setComparisonGroups: (baseline: string | null, comparison: string | null) => void;
  setDiffMode: (mode: DiffMode) => void;
  setNumericIndex: (index: number) => void;
  setSearch: (query: string, mode: "literal" | "fts") => void;
  setDocumentOffset: (offset: number) => void;
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  selectedDocumentId: null,
  page: 1,
  baselineGroupId: null,
  comparisonGroupId: null,
  diffMode: "differences",
  numericIndex: 0,
  searchQuery: "",
  searchMode: "literal",
  documentOffset: 0,
  selectDocument: (documentId, page = 1) =>
    set({
      selectedDocumentId: documentId,
      page,
      baselineGroupId: null,
      comparisonGroupId: null,
      numericIndex: 0,
    }),
  setPage: (page) =>
    set({ page, baselineGroupId: null, comparisonGroupId: null, numericIndex: 0 }),
  setComparisonGroups: (baselineGroupId, comparisonGroupId) =>
    set({ baselineGroupId, comparisonGroupId, numericIndex: 0 }),
  setDiffMode: (diffMode) => set({ diffMode }),
  setNumericIndex: (numericIndex) => set({ numericIndex }),
  setSearch: (searchQuery, searchMode) => set({ searchQuery, searchMode }),
  setDocumentOffset: (documentOffset) => set({ documentOffset }),
}));
