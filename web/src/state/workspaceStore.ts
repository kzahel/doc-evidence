import { create } from "zustand";

import type { TextPresentationMode } from "../presentation/textPresentation";

type DiffMode = "differences" | "full";
export type FontScale = 1 | 1.2 | 1.3;

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
  fontScale: FontScale;
  libraryCollapsed: boolean;
  sourcePanePercent: number;
  textPresentationMode: TextPresentationMode;
  selectDocument: (documentId: string | null, page?: number) => void;
  setPage: (page: number) => void;
  setComparisonGroups: (baseline: string | null, comparison: string | null) => void;
  setDiffMode: (mode: DiffMode) => void;
  setNumericIndex: (index: number) => void;
  setSearch: (query: string, mode: "literal" | "fts") => void;
  setDocumentOffset: (offset: number) => void;
  setFontScale: (scale: FontScale) => void;
  setLibraryCollapsed: (collapsed: boolean) => void;
  setSourcePanePercent: (percent: number) => void;
  resetSourcePanePercent: () => void;
  setTextPresentationMode: (mode: TextPresentationMode) => void;
}

export const DEFAULT_SOURCE_PANE_PERCENT = 45;

export function clampSourcePanePercent(percent: number): number {
  return Math.min(72, Math.max(28, Math.round(percent * 10) / 10));
}

export function navigationFromSearch(search: string): {
  documentId: string | null;
  page: number;
} {
  const params = new URLSearchParams(search);
  const documentId = params.get("document");
  const parsedPage = Number(params.get("page") ?? "1");
  return {
    documentId: documentId && /^sha256:[0-9a-f]{64}$/.test(documentId) ? documentId : null,
    page: Number.isSafeInteger(parsedPage) && parsedPage > 0 ? parsedPage : 1,
  };
}

const initialNavigation = navigationFromSearch(
  typeof window === "undefined" ? "" : window.location.search,
);

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  selectedDocumentId: initialNavigation.documentId,
  page: initialNavigation.page,
  baselineGroupId: null,
  comparisonGroupId: null,
  diffMode: "differences",
  numericIndex: 0,
  searchQuery: "",
  searchMode: "literal",
  documentOffset: 0,
  fontScale: 1.2,
  libraryCollapsed: false,
  sourcePanePercent: DEFAULT_SOURCE_PANE_PERCENT,
  textPresentationMode: "auto",
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
    set({
      baselineGroupId,
      comparisonGroupId:
        baselineGroupId !== null && baselineGroupId === comparisonGroupId
          ? null
          : comparisonGroupId,
      numericIndex: 0,
    }),
  setDiffMode: (diffMode) => set({ diffMode }),
  setNumericIndex: (numericIndex) => set({ numericIndex }),
  setSearch: (searchQuery, searchMode) => set({ searchQuery, searchMode }),
  setDocumentOffset: (documentOffset) => set({ documentOffset }),
  setFontScale: (fontScale) => set({ fontScale }),
  setLibraryCollapsed: (libraryCollapsed) => set({ libraryCollapsed }),
  setSourcePanePercent: (sourcePanePercent) =>
    set({ sourcePanePercent: clampSourcePanePercent(sourcePanePercent) }),
  resetSourcePanePercent: () => set({ sourcePanePercent: DEFAULT_SOURCE_PANE_PERCENT }),
  setTextPresentationMode: (textPresentationMode) => set({ textPresentationMode }),
}));
