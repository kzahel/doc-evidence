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
    if (!selectedDocumentId && documents.data?.items[0]) {
      selectDocument(documents.data.items[0].document_id);
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
        <div className={styles.safety}>
          <span className={styles.localDot} aria-hidden="true" />
          Local · authenticated · source read-only
          {failingChecks.length > 0 && <span className={styles.diagnostic}>{failingChecks.length} diagnostic warning(s)</span>}
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
