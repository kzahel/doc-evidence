import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { useRuntime } from "../api/RuntimeProvider";
import { useWorkspaceStore } from "../state/workspaceStore";
import { EmptyState, FailureState, LoadingState } from "./AsyncState";
import { ComparisonPanel } from "./ComparisonPanel";
import { OutputGroups } from "./OutputGroups";
import styles from "./DocumentWorkspace.module.css";

function useBlobUrl(blob: Blob | undefined): string | null {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!blob) {
      setUrl(null);
      return;
    }
    const next = URL.createObjectURL(blob);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [blob]);
  return url;
}

export function DocumentWorkspace({ documentId }: { documentId: string }) {
  const runtime = useRuntime();
  const page = useWorkspaceStore((state) => state.page);
  const setPage = useWorkspaceStore((state) => state.setPage);
  const documentQuery = useQuery({
    queryKey: ["document", documentId],
    queryFn: ({ signal }) => runtime.getDocument(documentId, signal),
  });
  const renderable =
    documentQuery.data?.media_type === "application/pdf" &&
    (documentQuery.data.page_count ?? 0) > 0;
  const groupsQuery = useQuery({
    queryKey: ["page-groups", documentId, page],
    queryFn: ({ signal }) => runtime.getPageGroups(documentId, page, signal),
    enabled: renderable,
  });
  const renderQuery = useQuery({
    queryKey: ["page-render", documentId, page],
    queryFn: ({ signal }) => runtime.getPageRender(documentId, page, signal),
    enabled: renderable,
  });
  const imageUrl = useBlobUrl(renderQuery.data);

  if (documentQuery.isLoading) return <LoadingState label="Opening document" />;
  if (documentQuery.error) return <FailureState title="Document unavailable" error={documentQuery.error} />;
  const document = documentQuery.data;
  if (!document) return <EmptyState>Document metadata was not returned.</EmptyState>;

  const filename = document.source_path_hint.split(":").slice(1).join(":");
  return (
    <main className={styles.workspace}>
      <header className={styles.documentHeader}>
        <div className={styles.title}>
          <p>{document.sources[0]?.collection_id ?? "collection"}</p>
          <h1>{filename}</h1>
          <span>
            {document.media_type} · {(document.size_bytes / 1024).toFixed(1)} KB ·{" "}
            {document.extraction_status.replaceAll("_", " ")} ·{" "}
            <code>{document.content_sha256.slice(0, 16)}…</code>
          </span>
        </div>
        {renderable && (
          <nav className={styles.pageNav} aria-label="Document pages">
            <button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)}>
              ←
            </button>
            <label>
              Page
              <input
                aria-label="Current page"
                min={1}
                max={document.page_count ?? 1}
                type="number"
                value={page}
                onChange={(event) => {
                  const value = Number(event.target.value);
                  if (value >= 1 && value <= (document.page_count ?? 1)) setPage(value);
                }}
              />
              of {document.page_count ?? 1}
            </label>
            <button
              type="button"
              disabled={page >= (document.page_count ?? 1)}
              onClick={() => setPage(page + 1)}
            >
              →
            </button>
          </nav>
        )}
      </header>
      {document.warnings.length > 0 && (
        <details className={styles.warnings}>
          <summary>{document.warnings.length} source or extraction warnings</summary>
          <ul>{document.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul>
        </details>
      )}
      {document.extraction_status === "image_only" && (
        <div className={styles.warnings}>
          This PDF is image-only: its native text layer is empty. Text appears here only after an
          OCR extractor has been run and cached; opening the document does not start OCR.
        </div>
      )}
      {!renderable ? (
        <EmptyState>
          This file is indexed in the library, but Tactical 000 only renders and compares PDF
          pages. Its source occurrence and immutable identity remain available above.
        </EmptyState>
      ) : (
        <section className={styles.inspection}>
          <section className={styles.visual} aria-label="Rendered source page">
            <div className={styles.sectionHeading}>
              <div>
                <p>Representation layer 2</p>
                <h2>Rendered source page</h2>
              </div>
              <span>144 DPI cached PNG</span>
            </div>
            <div className={styles.pageFrame}>
              {renderQuery.isLoading && <LoadingState label="Rendering page" />}
              {renderQuery.error && (
                <FailureState title="Page render failed" error={renderQuery.error} />
              )}
              {imageUrl && <img src={imageUrl} alt={`Rendered page ${page} of ${filename}`} />}
            </div>
            <details className={styles.occurrences}>
              <summary>{document.sources.length} source occurrence(s)</summary>
              <ul>
                {document.sources.map((source) => (
                  <li key={`${source.collection_id}:${source.relative_path}`}>
                    <strong>{source.collection_id}</strong> · {source.relative_path}
                  </li>
                ))}
              </ul>
            </details>
          </section>
          <section className={styles.outputs}>
            {groupsQuery.isLoading && (
              <LoadingState label="Loading extractor representations" />
            )}
            {groupsQuery.error && (
              <FailureState title="Extractor output unavailable" error={groupsQuery.error} />
            )}
            {groupsQuery.data && <OutputGroups data={groupsQuery.data} />}
          </section>
        </section>
      )}
      {groupsQuery.data && (
        <ComparisonPanel documentId={documentId} page={page} groups={groupsQuery.data.groups} />
      )}
    </main>
  );
}
