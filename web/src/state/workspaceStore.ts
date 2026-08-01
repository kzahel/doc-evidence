import { create } from "zustand";

import type { TextPresentationMode } from "../presentation/textPresentation";

type DiffMode = "differences" | "full";
export type FontScale = 1 | 1.2 | 1.3;
export type ReviewMode = "focused" | "stacked" | "compare";
export type ComparisonView = "diff" | "raw";

interface WorkspaceState {
  activeLibraryId: string | null;
  selectedDocumentId: string | null;
  page: number;
  baselineGroupId: string | null;
  comparisonGroupId: string | null;
  activeGroupId: string | null;
  diffMode: DiffMode;
  reviewMode: ReviewMode;
  comparisonView: ComparisonView;
  numericIndex: number;
  searchQuery: string;
  searchMode: "literal" | "fts";
  documentOffset: number;
  fontScale: FontScale;
  libraryCollapsed: boolean;
  sourcePanePercent: number;
  textPresentationMode: TextPresentationMode;
  selectLibrary: (libraryId: string | null) => void;
  selectDocument: (documentId: string | null, page?: number) => void;
  setPage: (page: number) => void;
  setComparisonGroups: (baseline: string | null, comparison: string | null) => void;
  setActiveGroupId: (groupId: string | null) => void;
  setDiffMode: (mode: DiffMode) => void;
  setReviewMode: (mode: ReviewMode) => void;
  setComparisonView: (view: ComparisonView) => void;
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
  libraryId: string | null;
  documentId: string | null;
  page: number;
} {
  const params = new URLSearchParams(search);
  const libraryId = params.get("library");
  const documentId = params.get("document");
  const parsedPage = Number(params.get("page") ?? "1");
  return {
    libraryId: libraryId && /^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,127}$/.test(libraryId) ? libraryId : null,
    documentId: documentId && /^sha256:[0-9a-f]{64}$/.test(documentId) ? documentId : null,
    page: Number.isSafeInteger(parsedPage) && parsedPage > 0 ? parsedPage : 1,
  };
}

const initialNavigation = navigationFromSearch(
  typeof window === "undefined" ? "" : window.location.search,
);

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  activeLibraryId: initialNavigation.libraryId,
  selectedDocumentId: initialNavigation.documentId,
  page: initialNavigation.page,
  baselineGroupId: null,
  comparisonGroupId: null,
  activeGroupId: null,
  diffMode: "differences",
  reviewMode: "focused",
  comparisonView: "diff",
  numericIndex: 0,
  searchQuery: "",
  searchMode: "literal",
  documentOffset: 0,
  fontScale: 1.2,
  libraryCollapsed: false,
  sourcePanePercent: DEFAULT_SOURCE_PANE_PERCENT,
  textPresentationMode: "auto",
  selectLibrary: (activeLibraryId) =>
    set({
      activeLibraryId,
      selectedDocumentId: null,
      page: 1,
      searchQuery: "",
      documentOffset: 0,
      baselineGroupId: null,
      comparisonGroupId: null,
      activeGroupId: null,
      numericIndex: 0,
    }),
  selectDocument: (documentId, page = 1) =>
    set({
      selectedDocumentId: documentId,
      page,
      baselineGroupId: null,
      comparisonGroupId: null,
      activeGroupId: null,
      numericIndex: 0,
    }),
  setPage: (page) =>
    set({
      page,
      baselineGroupId: null,
      comparisonGroupId: null,
      activeGroupId: null,
      numericIndex: 0,
    }),
  setComparisonGroups: (baselineGroupId, comparisonGroupId) =>
    set({
      baselineGroupId,
      comparisonGroupId:
        baselineGroupId !== null && baselineGroupId === comparisonGroupId
          ? null
          : comparisonGroupId,
      numericIndex: 0,
    }),
  setActiveGroupId: (activeGroupId) => set({ activeGroupId }),
  setDiffMode: (diffMode) => set({ diffMode }),
  setReviewMode: (reviewMode) => set({ reviewMode }),
  setComparisonView: (comparisonView) => set({ comparisonView }),
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
