import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useRuntime } from "./api/RuntimeProvider";
import { useJobsQuery } from "./api/jobQueries";
import { EmptyState, FailureState, LoadingState } from "./components/AsyncState";
import { DocumentWorkspace } from "./components/DocumentWorkspace";
import { ActivityCenter } from "./components/ActivityCenter";
import { LibraryPanel } from "./components/LibraryPanel";
import { useWorkspaceStore } from "./state/workspaceStore";
import styles from "./App.module.css";

export function App() {
  const runtime = useRuntime();
  const queryClient = useQueryClient();
  const activeLibraryId = useWorkspaceStore((state) => state.activeLibraryId);
  const selectLibrary = useWorkspaceStore((state) => state.selectLibrary);
  const selectedDocumentId = useWorkspaceStore((state) => state.selectedDocumentId);
  const page = useWorkspaceStore((state) => state.page);
  const selectDocument = useWorkspaceStore((state) => state.selectDocument);
  const offset = useWorkspaceStore((state) => state.documentOffset);
  const searchQuery = useWorkspaceStore((state) => state.searchQuery);
  const searchMode = useWorkspaceStore((state) => state.searchMode);
  const fontScale = useWorkspaceStore((state) => state.fontScale);
  const setFontScale = useWorkspaceStore((state) => state.setFontScale);
  const libraryCollapsed = useWorkspaceStore((state) => state.libraryCollapsed);
  const setLibraryCollapsed = useWorkspaceStore((state) => state.setLibraryCollapsed);
  const appSummary = useQuery({
    queryKey: ["app"],
    queryFn: ({ signal }) => runtime.getApp(signal),
  });
  const libraries = useQuery({
    queryKey: ["libraries"],
    queryFn: ({ signal }) => runtime.listLibraries(signal),
  });
  const libraryDetail = useQuery({
    queryKey: ["library", activeLibraryId, "detail"],
    queryFn: ({ signal }) => runtime.getLibrary(activeLibraryId!, signal),
    enabled: activeLibraryId !== null,
  });
  const workspace = useQuery({
    queryKey: ["library", activeLibraryId, "workspace"],
    queryFn: ({ signal }) => runtime.getWorkspace(activeLibraryId!, signal),
    enabled: activeLibraryId !== null,
  });
  const documents = useQuery({
    queryKey: ["library", activeLibraryId, "documents", offset],
    queryFn: ({ signal }) => runtime.listDocuments(activeLibraryId!, offset, 40, signal),
    enabled: activeLibraryId !== null,
  });
  const search = useQuery({
    queryKey: ["library", activeLibraryId, "search", searchQuery, searchMode],
    queryFn: ({ signal }) => runtime.search(activeLibraryId!, { query: searchQuery, mode: searchMode }, signal),
    enabled: activeLibraryId !== null && Boolean(searchQuery),
  });
  const diagnostics = useQuery({
    queryKey: ["library", activeLibraryId, "diagnostics"],
    queryFn: ({ signal }) => runtime.getDiagnostics(activeLibraryId!, signal),
    enabled: activeLibraryId !== null,
  });
  const jobs = useJobsQuery(activeLibraryId);
  const latestInventory = jobs.data?.items.find((job) => job.request_kind === "inventory") ?? null;
  const activation = useMutation({
    mutationFn: (libraryId: string) => runtime.activateLibrary(libraryId),
    onSuccess: async (result) => {
      selectLibrary(result.active_library_id);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["app"] }),
        queryClient.invalidateQueries({ queryKey: ["libraries"] }),
      ]);
    },
  });
  const refreshNativeLibrary = async (result: {
    outcome: "completed" | "cancelled";
    libraryId: string | null;
    status: "ready" | "unavailable" | "integrity_error" | null;
  }) => {
    if (result.outcome !== "completed") return;
    if (result.libraryId && result.status === "ready") {
      selectLibrary(result.libraryId);
    }
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["app"] }),
      queryClient.invalidateQueries({ queryKey: ["libraries"] }),
    ]);
  };
  const createManagedLibrary = useMutation({
    mutationFn: () => runtime.createManagedLibrary(),
    onSuccess: async (result) => {
      await refreshNativeLibrary(result);
      if (result.outcome === "completed" && result.libraryId && result.status === "ready") {
        inventory.mutate({ libraryId: result.libraryId, fullHashVerification: false });
      }
    },
  });
  const registerExistingLibrary = useMutation({
    mutationFn: () => runtime.registerExistingLibrary(),
    onSuccess: refreshNativeLibrary,
  });
  const addCollection = useMutation({
    mutationFn: (libraryId: string) => runtime.addCollection(libraryId),
    onSuccess: async (result) => {
      if (result.outcome !== "completed" || !result.libraryId) return;
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["libraries"] }),
        queryClient.invalidateQueries({ queryKey: ["library", result.libraryId] }),
      ]);
      if (result.changed) {
        inventory.mutate({ libraryId: result.libraryId, fullHashVerification: false });
      }
    },
  });
  const inventory = useMutation({
    mutationFn: ({
      libraryId,
      fullHashVerification,
    }: {
      libraryId: string;
      fullHashVerification: boolean;
    }) =>
      runtime.createInventory(libraryId, {
        full_hash_verification: fullHashVerification,
      }),
    onSuccess: async (result) => {
      await queryClient.invalidateQueries({
        queryKey: ["library", result.job.library_id, "jobs"],
      });
    },
  });
  const nativeOperationError =
    createManagedLibrary.error ?? registerExistingLibrary.error ?? addCollection.error;
  const nativeOperationPending =
    createManagedLibrary.isPending ||
    registerExistingLibrary.isPending ||
    addCollection.isPending;

  useEffect(() => {
    if (!appSummary.data || !libraries.data || activeLibraryId) return;
    const known = libraries.data.items;
    const preferred =
      known.find((item) => item.library_id === appSummary.data.active_library_id && item.status === "ready") ??
      known.find((item) => item.status === "ready");
    if (preferred) selectLibrary(preferred.library_id);
  }, [activeLibraryId, appSummary.data, libraries.data, selectLibrary]);

  useEffect(() => {
    if (activeLibraryId && !selectedDocumentId && documents.data) {
      const initial =
        documents.data.items.find(
          (document) => document.media_type === "application/pdf" && (document.page_count ?? 0) > 0,
        ) ?? documents.data.items[0];
      if (initial) selectDocument(initial.document_id);
    }
  }, [activeLibraryId, documents.data, selectDocument, selectedDocumentId]);

  useEffect(() => {
    if (!activeLibraryId || !latestInventory) return;
    if (!["succeeded", "failed", "cancelled", "interrupted"].includes(latestInventory.state)) return;
    if (latestInventory.state === "succeeded") selectDocument(null);
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: ["library", activeLibraryId, "workspace"] }),
      queryClient.invalidateQueries({ queryKey: ["library", activeLibraryId, "documents"] }),
      queryClient.invalidateQueries({ queryKey: ["library", activeLibraryId, "search"] }),
      queryClient.invalidateQueries({ queryKey: ["library", activeLibraryId, "diagnostics"] }),
      queryClient.invalidateQueries({ queryKey: ["library", activeLibraryId, "detail"] }),
    ]);
  }, [
    activeLibraryId,
    latestInventory?.job_id,
    latestInventory?.state,
    latestInventory?.updated_at,
    queryClient,
    selectDocument,
  ]);

  useEffect(() => {
    const url = new URL(window.location.href);
    if (activeLibraryId) url.searchParams.set("library", activeLibraryId);
    else url.searchParams.delete("library");
    if (selectedDocumentId) {
      url.searchParams.set("document", selectedDocumentId);
      url.searchParams.set("page", String(page));
    } else {
      url.searchParams.delete("document");
      url.searchParams.delete("page");
    }
    window.history.replaceState(null, "", `${url.pathname}${url.search}`);
  }, [activeLibraryId, page, selectedDocumentId]);

  useEffect(() => {
    document.documentElement.style.setProperty("--font-scale", String(fontScale));
    return () => {
      document.documentElement.style.removeProperty("--font-scale");
    };
  }, [fontScale]);

  if (appSummary.isLoading || libraries.isLoading) return <LoadingState label="Loading libraries" />;
  if (appSummary.error) return <FailureState title="Application state unavailable" error={appSummary.error} />;
  if (libraries.error) return <FailureState title="Libraries unavailable" error={libraries.error} />;
  if (!libraries.data || libraries.data.items.length === 0) {
    return (
      <EmptyState>
        <strong>No libraries are registered.</strong>
        {runtime.hostCapabilities.createManagedLibrary ||
        runtime.hostCapabilities.registerExistingLibrary ? (
          <span className={styles.nativeActions}>
            {runtime.hostCapabilities.createManagedLibrary && (
              <button
                disabled={nativeOperationPending}
                type="button"
                onClick={() => createManagedLibrary.mutate()}
              >
                New library…
              </button>
            )}
            {runtime.hostCapabilities.registerExistingLibrary && (
              <button
                disabled={nativeOperationPending}
                type="button"
                onClick={() => registerExistingLibrary.mutate()}
              >
                Open existing…
              </button>
            )}
          </span>
        ) : (
          <span>
            Run doc-evidence library-register --config PATH, then restart. Native
            folder selection is available in the desktop application.
          </span>
        )}
        {nativeOperationError && <span role="alert">{nativeOperationError.message}</span>}
      </EmptyState>
    );
  }
  if (!activeLibraryId) {
    return (
      <EmptyState>
        <strong>No registered library is ready to open.</strong>
        <span>Inspect the library status below or register an inventoried library.</span>
      </EmptyState>
    );
  }
  if (libraryDetail.error) return <FailureState title="Library unavailable" error={libraryDetail.error} />;
  if (workspace.isLoading || documents.isLoading || libraryDetail.isLoading) return <LoadingState />;
  if (workspace.error) return <FailureState title="Workspace unavailable" error={workspace.error} />;
  if (documents.error) return <FailureState title="Document catalog unavailable" error={documents.error} />;
  if (!workspace.data || !documents.data) return <EmptyState>No workspace data was returned.</EmptyState>;

  const failingChecks = diagnostics.data?.checks.filter((check) => check.status !== "ok") ?? [];
  const activeLibrary = libraries.data.items.find((item) => item.library_id === activeLibraryId);
  return (
    <div className={styles.app}>
      <header className={styles.topbar}>
        <div className={styles.brand}>
          <span className={styles.mark} aria-hidden="true">de</span>
          <strong>doc-evidence</strong>
          <span>{activeLibrary?.name ?? workspace.data.library_name}</span>
        </div>
        <div className={styles.topbarTools}>
          <label className={styles.librarySelector}>
            <span>Library</span>
            <select
              aria-label="Active library"
              disabled={activation.isPending}
              value={activeLibraryId}
              onChange={(event) => activation.mutate(event.target.value)}
            >
              {libraries.data.items.map((library) => (
                <option
                  disabled={library.status !== "ready"}
                  key={library.library_id}
                  value={library.library_id}
                >
                  {library.name}{library.status === "ready" ? "" : ` — ${library.status}`}
                </option>
              ))}
            </select>
          </label>
          <ActivityCenter libraryId={activeLibraryId} />
          <div className={styles.typography} role="group" aria-label="Global text size">
            <button
              aria-pressed={fontScale === 1}
              className={fontScale === 1 ? styles.activeTypography : ""}
              type="button"
              onClick={() => setFontScale(1)}
            >
              Small
            </button>
            <button
              aria-pressed={fontScale === 1.2}
              className={fontScale === 1.2 ? styles.activeTypography : ""}
              type="button"
              onClick={() => setFontScale(1.2)}
            >
              Normal
            </button>
            <button
              aria-pressed={fontScale === 1.3}
              className={fontScale === 1.3 ? styles.activeTypography : ""}
              type="button"
              onClick={() => setFontScale(1.3)}
            >
              Large
            </button>
          </div>
          <div className={styles.safety}>
            <span className={styles.localDot} aria-hidden="true" />
            Local · authenticated · source read-only
            {failingChecks.length > 0 && <span className={styles.diagnostic}>{failingChecks.length} diagnostic warning(s)</span>}
          </div>
          {activation.error && <span className={styles.diagnostic}>{activation.error.message}</span>}
          {nativeOperationError && <span className={styles.diagnostic}>{nativeOperationError.message}</span>}
        </div>
      </header>
      {libraryDetail.data && (
        <details className={styles.librarySettings}>
          <summary>Library settings · {libraryDetail.data.collections.length} collection(s)</summary>
          <div>
            <section aria-label="Known libraries" className={styles.knownLibraries}>
              <h2>Known libraries</h2>
              <ul>
                {libraries.data.items.map((library) => (
                  <li key={library.library_id}>
                    <button
                      aria-current={library.library_id === activeLibraryId ? "true" : undefined}
                      disabled={library.status !== "ready" || activation.isPending}
                      type="button"
                      onClick={() => activation.mutate(library.library_id)}
                    >
                      <strong>{library.name}</strong>
                      <span>
                        {library.collection_count} collection(s) · {library.store_mode} store · {library.status}
                      </span>
                      <span>
                        {library.last_opened_at ? `Last opened ${library.last_opened_at}` : "Not opened yet"}
                      </span>
                      {library.status_detail && <span>{library.status_detail}</span>}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
            <strong>Active collection scope</strong>
            {libraryDetail.data.collections.map((collection) => (
              <span key={collection.collection_id}>
                {collection.collection_id} · {collection.source_label} · {collection.available ? "available" : "unavailable"}
              </span>
            ))}
            <p>
              Collection changes require a trusted CLI or native folder selection.
              Preflight distinguishes sibling additions, parent expansion, covered children,
              and source/store overlap without accepting browser-supplied paths.
            </p>
            <span>
              Index status · {latestInventory
                ? `${latestInventory.state}${latestInventory.outcome ? ` · ${latestInventory.outcome.replaceAll("_", " ")}` : ""}`
                : workspace.data.catalog_inventory_run_id
                  ? "ready"
                  : "not scanned"}
            </span>
            <span className={styles.nativeActions}>
              <button
                disabled={inventory.isPending || ["queued", "starting", "running", "cancelling"].includes(latestInventory?.state ?? "")}
                type="button"
                onClick={() => inventory.mutate({ libraryId: activeLibraryId, fullHashVerification: false })}
              >
                {inventory.isPending ? "Queueing scan…" : "Scan now"}
              </button>
              <button
                disabled={inventory.isPending || ["queued", "starting", "running", "cancelling"].includes(latestInventory?.state ?? "")}
                type="button"
                onClick={() => {
                  if (window.confirm("Re-read and hash every source file? This may take substantially longer.")) {
                    inventory.mutate({ libraryId: activeLibraryId, fullHashVerification: true });
                  }
                }}
              >
                Verify all file hashes…
              </button>
            </span>
            {inventory.error && <span role="alert">{inventory.error.message}</span>}
            {runtime.hostCapabilities.addCollection && activeLibrary?.store_mode === "managed" && (
              <span className={styles.nativeActions}>
                <button
                  disabled={nativeOperationPending}
                  type="button"
                  onClick={() => addCollection.mutate(activeLibraryId)}
                >
                  Add collection…
                </button>
              </span>
            )}
          </div>
        </details>
      )}
      <div className={`${styles.body} ${libraryCollapsed ? styles.bodyCollapsed : ""}`}>
        <LibraryPanel
          workspace={workspace.data}
          documents={documents.data}
          search={search.data ?? null}
          searching={search.isFetching}
          collapsed={libraryCollapsed}
          onCollapsedChange={setLibraryCollapsed}
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
