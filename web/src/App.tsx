import { useEffect } from "react";
import { useQuery } from "@tanstack/react-query";

import { useRuntime } from "./api/RuntimeProvider";
import { EmptyState, FailureState, LoadingState } from "./components/AsyncState";
import { DocumentWorkspace } from "./components/DocumentWorkspace";
import { LibraryPanel } from "./components/LibraryPanel";
import { useWorkspaceStore } from "./state/workspaceStore";
import styles from "./App.module.css";

export function App() {
  const runtime = useRuntime();
  const selectedDocumentId = useWorkspaceStore((state) => state.selectedDocumentId);
  const page = useWorkspaceStore((state) => state.page);
  const selectDocument = useWorkspaceStore((state) => state.selectDocument);
  const offset = useWorkspaceStore((state) => state.documentOffset);
  const searchQuery = useWorkspaceStore((state) => state.searchQuery);
  const searchMode = useWorkspaceStore((state) => state.searchMode);
  const fontScale = useWorkspaceStore((state) => state.fontScale);
  const setFontScale = useWorkspaceStore((state) => state.setFontScale);
  const workspace = useQuery({
    queryKey: ["workspace"],
    queryFn: ({ signal }) => runtime.getWorkspace(signal),
  });
  const documents = useQuery({
    queryKey: ["documents", offset],
    queryFn: ({ signal }) => runtime.listDocuments(offset, 40, signal),
  });
  const search = useQuery({
    queryKey: ["search", searchQuery, searchMode],
    queryFn: ({ signal }) => runtime.search({ query: searchQuery, mode: searchMode }, signal),
    enabled: Boolean(searchQuery),
  });
  const diagnostics = useQuery({
    queryKey: ["diagnostics"],
    queryFn: ({ signal }) => runtime.getDiagnostics(signal),
  });

  useEffect(() => {
    if (!selectedDocumentId && documents.data) {
      const initial =
        documents.data.items.find(
          (document) => document.media_type === "application/pdf" && (document.page_count ?? 0) > 0,
        ) ?? documents.data.items[0];
      if (initial) selectDocument(initial.document_id);
    }
  }, [documents.data, selectDocument, selectedDocumentId]);

  useEffect(() => {
    const url = new URL(window.location.href);
    if (selectedDocumentId) {
      url.searchParams.set("document", selectedDocumentId);
      url.searchParams.set("page", String(page));
    } else {
      url.searchParams.delete("document");
      url.searchParams.delete("page");
    }
    window.history.replaceState(null, "", `${url.pathname}${url.search}`);
  }, [page, selectedDocumentId]);

  useEffect(() => {
    document.documentElement.style.setProperty("--font-scale", String(fontScale));
    return () => {
      document.documentElement.style.removeProperty("--font-scale");
    };
  }, [fontScale]);

  if (workspace.isLoading || documents.isLoading) return <LoadingState />;
  if (workspace.error) return <FailureState title="Workspace unavailable" error={workspace.error} />;
  if (documents.error) return <FailureState title="Document catalog unavailable" error={documents.error} />;
  if (!workspace.data || !documents.data) return <EmptyState>No workspace data was returned.</EmptyState>;

  const failingChecks = diagnostics.data?.checks.filter((check) => check.status !== "ok") ?? [];
  return (
    <div className={styles.app}>
      <header className={styles.topbar}>
        <div className={styles.brand}>
          <span className={styles.mark} aria-hidden="true">de</span>
          <strong>doc-evidence</strong>
          <span>local evidence workbench</span>
        </div>
        <div className={styles.topbarTools}>
          <div className={styles.typography} role="group" aria-label="Global text size">
            <button
              aria-label="Decrease global text size"
              disabled={fontScale <= 0.8}
              type="button"
              onClick={() => setFontScale(fontScale - 0.1)}
            >
              A−
            </button>
            <output aria-label="Current global text size">{Math.round(fontScale * 100)}%</output>
            <button
              aria-label="Increase global text size"
              disabled={fontScale >= 1.5}
              type="button"
              onClick={() => setFontScale(fontScale + 0.1)}
            >
              A+
            </button>
          </div>
          <div className={styles.safety}>
            <span className={styles.localDot} aria-hidden="true" />
            Local · authenticated · source read-only
            {failingChecks.length > 0 && <span className={styles.diagnostic}>{failingChecks.length} diagnostic warning(s)</span>}
          </div>
        </div>
      </header>
      <div className={styles.body}>
        <LibraryPanel
          workspace={workspace.data}
          documents={documents.data}
          search={search.data ?? null}
          searching={search.isFetching}
        />
        {selectedDocumentId ? (
          <DocumentWorkspace documentId={selectedDocumentId} />
        ) : (
          <EmptyState>Select a document to inspect its pages and extractor output.</EmptyState>
        )}
      </div>
    </div>
  );
}
