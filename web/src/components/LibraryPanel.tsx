import { useState, type FormEvent } from "react";

import type { DocumentPage, SearchPage, WorkspaceSummary } from "../api/runtime";
import { useWorkspaceStore } from "../state/workspaceStore";
import { EmptyState } from "./AsyncState";
import styles from "./LibraryPanel.module.css";

interface Props {
  workspace: WorkspaceSummary;
  documents: DocumentPage;
  search: SearchPage | null;
  searching: boolean;
}

export function LibraryPanel({ workspace, documents, search, searching }: Props) {
  const selectedDocumentId = useWorkspaceStore((state) => state.selectedDocumentId);
  const selectDocument = useWorkspaceStore((state) => state.selectDocument);
  const committedQuery = useWorkspaceStore((state) => state.searchQuery);
  const committedMode = useWorkspaceStore((state) => state.searchMode);
  const setSearch = useWorkspaceStore((state) => state.setSearch);
  const offset = useWorkspaceStore((state) => state.documentOffset);
  const setOffset = useWorkspaceStore((state) => state.setDocumentOffset);
  const [query, setQuery] = useState(committedQuery);
  const [mode, setMode] = useState<"literal" | "fts">(committedMode);

  function submit(event: FormEvent) {
    event.preventDefault();
    setSearch(query.trim(), mode);
  }

  const isSearch = Boolean(committedQuery);
  const rows = search?.items ?? [];
  return (
    <aside className={styles.panel} aria-label="Document library">
      <div className={styles.heading}>
        <div>
          <p className={styles.eyebrow}>Cached library</p>
          <h1>{workspace.document_count} documents</h1>
        </div>
        <span className={styles.sourceCount}>{workspace.source_occurrence_count} sources</span>
      </div>
      <form className={styles.search} onSubmit={submit}>
        <label htmlFor="library-search">Search extracted text</label>
        <div className={styles.searchRow}>
          <input
            id="library-search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Balance, institution, date…"
          />
          <button type="submit">Search</button>
        </div>
        <div className={styles.searchOptions}>
          <label>
            <input
              type="radio"
              checked={mode === "literal"}
              onChange={() => setMode("literal")}
            />
            Literal
          </label>
          <label>
            <input type="radio" checked={mode === "fts"} onChange={() => setMode("fts")} />
            FTS syntax
          </label>
          {isSearch && (
            <button
              type="button"
              className={styles.clear}
              onClick={() => {
                setQuery("");
                setSearch("", mode);
              }}
            >
              Clear
            </button>
          )}
        </div>
      </form>
      <div className={styles.resultsHeader}>
        <span>{isSearch ? `${rows.length} search matches` : "Documents"}</span>
        {searching && <span role="status">Searching…</span>}
      </div>
      <div className={styles.list}>
        {isSearch
          ? rows.map((hit) => (
              <button
                type="button"
                className={`${styles.item} ${selectedDocumentId === hit.document_id ? styles.selected : ""}`}
                key={`${hit.document_id}:${hit.page}`}
                onClick={() => selectDocument(hit.document_id, hit.page)}
              >
                <strong>{hit.source_path_hint.split(":").slice(1).join(":")}</strong>
                <span className={styles.path}>Page {hit.page}</span>
                <span className={styles.snippet}>{hit.snippet}</span>
              </button>
            ))
          : documents.items.map((document) => (
              <button
                type="button"
                className={`${styles.item} ${selectedDocumentId === document.document_id ? styles.selected : ""}`}
                key={document.document_id}
                onClick={() => selectDocument(document.document_id)}
              >
                <strong>{document.source_path_hint.split(":").slice(1).join(":")}</strong>
                <span className={styles.path}>
                  {document.media_type.replace("application/", "")} · {document.page_count ?? "—"} pages
                </span>
                <span className={styles.badges}>
                  <span>{document.extraction_status.replaceAll("_", " ")}</span>
                  {document.duplicate_count > 0 && <span>{document.duplicate_count} duplicates</span>}
                  {document.warning_count > 0 && <span>{document.warning_count} warnings</span>}
                </span>
              </button>
            ))}
        {(isSearch ? rows.length === 0 : documents.items.length === 0) && (
          <EmptyState>{isSearch ? "No cached page text matched." : "The catalog is empty."}</EmptyState>
        )}
      </div>
      {!isSearch && documents.total > documents.limit && (
        <nav className={styles.pagination} aria-label="Document pages">
          <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - documents.limit))}>
            Previous
          </button>
          <span>
            {offset + 1}–{Math.min(offset + documents.limit, documents.total)}
          </span>
          <button
            type="button"
            disabled={offset + documents.limit >= documents.total}
            onClick={() => setOffset(offset + documents.limit)}
          >
            Next
          </button>
        </nav>
      )}
    </aside>
  );
}
