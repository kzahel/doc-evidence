"""Rebuildable SQLite catalog and exact/full-text search."""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from doc_evidence.errors import CatalogError

if TYPE_CHECKING:
    from doc_evidence.inventory import DocumentRecord, InventoryResult


CATALOG_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SearchResult:
    document_id: str
    page_number: int
    paths: tuple[str, ...]
    snippet: str
    score: float | None


def _connect(path: Path) -> sqlite3.Connection:
    try:
        connection = sqlite3.connect(path)
    except sqlite3.Error as error:
        raise CatalogError(f"cannot open catalog {path}: {error}") from error
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _create_schema(connection: sqlite3.Connection, enable_fts: bool) -> None:
    connection.executescript(
        """
        CREATE TABLE catalog_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE documents (
            document_id TEXT PRIMARY KEY,
            content_sha256 TEXT NOT NULL UNIQUE,
            size_bytes INTEGER NOT NULL,
            media_type TEXT NOT NULL,
            page_count INTEGER,
            inventory_status TEXT NOT NULL,
            extraction_status TEXT NOT NULL,
            extraction_run_id TEXT,
            artifact_path TEXT NOT NULL,
            pdf_metadata_json TEXT,
            warnings_json TEXT NOT NULL,
            normalized_text_hash TEXT,
            character_count INTEGER NOT NULL,
            non_whitespace_character_count INTEGER NOT NULL
        );

        CREATE TABLE sources (
            collection_id TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            document_id TEXT NOT NULL REFERENCES documents(document_id)
                ON DELETE CASCADE,
            size_bytes INTEGER NOT NULL,
            modified_ns INTEGER NOT NULL,
            observed_at TEXT NOT NULL,
            PRIMARY KEY (collection_id, relative_path)
        );

        CREATE INDEX sources_document_id_idx ON sources(document_id);
        CREATE INDEX documents_normalized_text_hash_idx
            ON documents(normalized_text_hash);

        CREATE TABLE extraction_runs (
            document_id TEXT NOT NULL REFERENCES documents(document_id)
                ON DELETE CASCADE,
            run_id TEXT NOT NULL,
            extractor TEXT NOT NULL,
            status TEXT NOT NULL,
            artifact_path TEXT NOT NULL,
            cache_hit INTEGER NOT NULL,
            PRIMARY KEY (document_id, run_id)
        );

        CREATE TABLE pages (
            document_id TEXT NOT NULL REFERENCES documents(document_id)
                ON DELETE CASCADE,
            run_id TEXT NOT NULL,
            page_number INTEGER NOT NULL,
            text TEXT NOT NULL,
            character_count INTEGER NOT NULL,
            non_whitespace_character_count INTEGER NOT NULL,
            PRIMARY KEY (document_id, run_id, page_number)
        );

        CREATE INDEX pages_document_page_idx
            ON pages(document_id, page_number);

        CREATE TABLE duplicate_members (
            kind TEXT NOT NULL,
            group_key TEXT NOT NULL,
            document_id TEXT NOT NULL REFERENCES documents(document_id)
                ON DELETE CASCADE,
            PRIMARY KEY (kind, group_key, document_id)
        );
        """
    )
    if enable_fts:
        try:
            connection.execute(
                """
                CREATE VIRTUAL TABLE pages_fts USING fts5(
                    document_id UNINDEXED,
                    page_number UNINDEXED,
                    text,
                    tokenize = 'unicode61'
                )
                """
            )
        except sqlite3.Error as error:
            raise CatalogError(
                f"SQLite FTS5 is unavailable but search.sqlite_fts is enabled: {error}"
            ) from error


def _insert_document(
    connection: sqlite3.Connection,
    document: DocumentRecord,
    enable_fts: bool,
) -> None:
    connection.execute(
        """
        INSERT INTO documents (
            document_id, content_sha256, size_bytes, media_type, page_count,
            inventory_status, extraction_status, extraction_run_id,
            artifact_path, pdf_metadata_json, warnings_json,
            normalized_text_hash, character_count,
            non_whitespace_character_count
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document.document_id,
            document.content_sha256,
            document.size_bytes,
            document.media_type,
            document.page_count,
            document.inventory_status,
            document.extraction_status,
            document.extraction_run_id,
            document.artifact_path,
            json.dumps(document.pdf_metadata, sort_keys=True),
            json.dumps(list(document.warnings), ensure_ascii=False),
            document.normalized_text_hash,
            document.character_count,
            document.non_whitespace_character_count,
        ),
    )
    for source in document.sources:
        connection.execute(
            """
            INSERT INTO sources (
                collection_id, relative_path, document_id, size_bytes,
                modified_ns, observed_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                source.collection_id,
                source.relative_path,
                document.document_id,
                source.size_bytes,
                source.modified_ns,
                source.observed_at,
            ),
        )

    if document.extraction_run_id is not None:
        connection.execute(
            """
            INSERT INTO extraction_runs (
                document_id, run_id, extractor, status, artifact_path, cache_hit
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                document.document_id,
                document.extraction_run_id,
                "poppler",
                "error" if document.extraction_status == "error" else "ok",
                document.extraction_artifact_path or document.artifact_path,
                int(document.cache_hit),
            ),
        )

    for page in document.pages:
        connection.execute(
            """
            INSERT INTO pages (
                document_id, run_id, page_number, text, character_count,
                non_whitespace_character_count
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                document.document_id,
                document.extraction_run_id,
                page.page_number,
                page.text,
                page.character_count,
                page.non_whitespace_character_count,
            ),
        )
        if enable_fts:
            connection.execute(
                "INSERT INTO pages_fts (document_id, page_number, text) "
                "VALUES (?, ?, ?)",
                (document.document_id, page.page_number, page.text),
            )


def build_catalog(result: InventoryResult, path: Path, enable_fts: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        connection = _connect(temporary_path)
        try:
            _create_schema(connection, enable_fts)
            metadata = {
                "schema_version": str(CATALOG_SCHEMA_VERSION),
                "inventory_run_id": result.run_id,
                "config_hash": result.config_hash,
                "created_at": result.completed_at,
                "fts_enabled": "1" if enable_fts else "0",
                "selected_collections": json.dumps(result.collection_ids),
                "summary": json.dumps(result.summary, sort_keys=True),
            }
            connection.executemany(
                "INSERT INTO catalog_metadata (key, value) VALUES (?, ?)",
                metadata.items(),
            )
            for document in result.documents:
                _insert_document(connection, document, enable_fts)
            for kind, groups in (
                ("byte", result.byte_duplicate_groups),
                ("normalized_text", result.normalized_text_duplicate_groups),
            ):
                for group in groups:
                    for document_id in group["document_ids"]:
                        connection.execute(
                            "INSERT INTO duplicate_members "
                            "(kind, group_key, document_id) VALUES (?, ?, ?)",
                            (kind, group["group_key"], document_id),
                        )
            connection.commit()
        finally:
            connection.close()
        os.replace(temporary_path, path)
    except (OSError, sqlite3.Error) as error:
        raise CatalogError(f"cannot build catalog {path}: {error}") from error
    finally:
        temporary_path.unlink(missing_ok=True)


def _catalog_path(store: Path) -> Path:
    unified = store / "doc-evidence.sqlite"
    if unified.is_file():
        return unified
    legacy = store / "catalog.sqlite"
    if not legacy.is_file():
        raise CatalogError(
            f"catalog does not exist below {store}; run doc-evidence inventory first"
        )
    return legacy


def _is_unified(connection: sqlite3.Connection) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'library_metadata'"
    ).fetchone()
    return row is not None


def _active_generation(connection: sqlite3.Connection) -> str:
    row = connection.execute(
        "SELECT active_generation_id FROM library_metadata WHERE singleton = 1"
    ).fetchone()
    if row is None or row[0] is None:
        raise CatalogError("library does not have an active inventory generation")
    return str(row[0])


def _paths_for_content(
    connection: sqlite3.Connection,
    generation_id: str,
    content_sha256: str,
) -> tuple[str, ...]:
    rows = connection.execute(
        """
        SELECT collection_id, relative_path
        FROM source_occurrences
        WHERE generation_id = ? AND content_sha256 = ?
        ORDER BY collection_id, relative_path
        """,
        (generation_id, content_sha256),
    ).fetchall()
    return tuple(f"{row['collection_id']}:{row['relative_path']}" for row in rows)


def _search_unified(
    connection: sqlite3.Connection,
    query: str,
    mode: str,
    limit: int,
) -> list[SearchResult]:
    generation_id = _active_generation(connection)
    candidates: list[sqlite3.Row]
    if mode == "literal":
        candidates = connection.execute(
            """
            SELECT rp.content_sha256, rp.page_number, rp.text,
                   er.extractor_id, NULL AS snippet, NULL AS score
            FROM run_pages rp
            JOIN extraction_runs er
              ON er.content_sha256 = rp.content_sha256
             AND er.run_id = rp.run_id
            JOIN generation_documents gd
              ON gd.content_sha256 = rp.content_sha256
             AND gd.generation_id = ?
            WHERE er.status = 'ok' AND instr(lower(rp.text), lower(?)) > 0
            ORDER BY rp.content_sha256, rp.page_number,
                     CASE WHEN er.extractor_id = 'poppler' THEN 0 ELSE 1 END,
                     er.extractor_id, er.run_id
            LIMIT ?
            """,
            (generation_id, query, min(5_000, max(limit * 20, limit))),
        ).fetchall()
    elif mode == "fts":
        try:
            candidates = connection.execute(
                """
                SELECT f.content_sha256, f.page_number, f.text,
                       f.extractor_id,
                       snippet(pages_fts, 4, '[', ']', ' … ', 24) AS snippet,
                       bm25(pages_fts) AS score
                FROM pages_fts f
                JOIN generation_documents gd
                  ON gd.content_sha256 = f.content_sha256
                 AND gd.generation_id = ?
                WHERE pages_fts MATCH ?
                ORDER BY score,
                         CASE WHEN f.extractor_id = 'poppler' THEN 0 ELSE 1 END,
                         f.content_sha256, f.page_number
                LIMIT ?
                """,
                (generation_id, query, min(5_000, max(limit * 20, limit))),
            ).fetchall()
        except sqlite3.Error as error:
            raise CatalogError(f"invalid FTS query: {error}") from error
    else:
        raise CatalogError(f"unknown search mode: {mode}")
    output: list[SearchResult] = []
    seen: set[tuple[str, int]] = set()
    for row in candidates:
        content_sha256 = str(row["content_sha256"])
        page_number = int(row["page_number"])
        key = (content_sha256, page_number)
        if key in seen:
            continue
        seen.add(key)
        output.append(
            SearchResult(
                document_id=f"sha256:{content_sha256}",
                page_number=page_number,
                paths=_paths_for_content(connection, generation_id, content_sha256),
                snippet=(
                    str(row["snippet"])
                    if row["snippet"] is not None
                    else _literal_snippet(str(row["text"]), query)
                ),
                score=float(row["score"]) if row["score"] is not None else None,
            )
        )
        if len(output) >= limit:
            break
    return output


def _paths_for_document(
    connection: sqlite3.Connection, document_id: str
) -> tuple[str, ...]:
    rows = connection.execute(
        """
        SELECT collection_id, relative_path
        FROM sources
        WHERE document_id = ?
        ORDER BY collection_id, relative_path
        """,
        (document_id,),
    ).fetchall()
    return tuple(f"{row['collection_id']}:{row['relative_path']}" for row in rows)


def _literal_snippet(text: str, query: str, radius: int = 100) -> str:
    folded_text = text.casefold()
    position = folded_text.find(query.casefold())
    position = max(position, 0)
    start = max(0, position - radius)
    end = min(len(text), position + len(query) + radius)
    snippet = " ".join(text[start:end].split())
    if start:
        snippet = "… " + snippet
    if end < len(text):
        snippet += " …"
    return snippet


def search_catalog(
    store: Path,
    query: str,
    mode: str = "literal",
    limit: int = 20,
) -> list[SearchResult]:
    if not query:
        raise CatalogError("search query may not be empty")
    connection = _connect(_catalog_path(store))
    try:
        if _is_unified(connection):
            return _search_unified(connection, query, mode, limit)
        results: list[SearchResult] = []
        if mode == "literal":
            rows = connection.execute(
                """
                SELECT document_id, page_number, text
                FROM pages
                WHERE instr(lower(text), lower(?)) > 0
                ORDER BY document_id, page_number
                LIMIT ?
                """,
                (query, limit),
            ).fetchall()
            for row in rows:
                results.append(
                    SearchResult(
                        document_id=row["document_id"],
                        page_number=row["page_number"],
                        paths=_paths_for_document(connection, row["document_id"]),
                        snippet=_literal_snippet(row["text"], query),
                        score=None,
                    )
                )
        elif mode == "fts":
            enabled_row = connection.execute(
                "SELECT value FROM catalog_metadata WHERE key = 'fts_enabled'"
            ).fetchone()
            if enabled_row is None or enabled_row["value"] != "1":
                raise CatalogError("this catalog was built without SQLite FTS")
            try:
                rows = connection.execute(
                    """
                    SELECT document_id, page_number,
                           snippet(pages_fts, 2, '[', ']', ' … ', 24) AS snippet,
                           bm25(pages_fts) AS score
                    FROM pages_fts
                    WHERE pages_fts MATCH ?
                    ORDER BY score
                    LIMIT ?
                    """,
                    (query, limit),
                ).fetchall()
            except sqlite3.Error as error:
                raise CatalogError(f"invalid FTS query: {error}") from error
            for row in rows:
                results.append(
                    SearchResult(
                        document_id=row["document_id"],
                        page_number=int(row["page_number"]),
                        paths=_paths_for_document(connection, row["document_id"]),
                        snippet=row["snippet"],
                        score=float(row["score"]),
                    )
                )
        else:
            raise CatalogError(f"unknown search mode: {mode}")
        return results
    except sqlite3.Error as error:
        raise CatalogError(f"catalog search failed: {error}") from error
    finally:
        connection.close()


def list_duplicate_groups(store: Path) -> list[dict[str, Any]]:
    connection = _connect(_catalog_path(store))
    try:
        if _is_unified(connection):
            generation_id = _active_generation(connection)
            rows = connection.execute(
                """
                SELECT kind, group_key, content_sha256
                FROM duplicate_members
                WHERE generation_id = ?
                ORDER BY kind, group_key, content_sha256
                """,
                (generation_id,),
            ).fetchall()
            grouped: dict[tuple[str, str], list[str]] = {}
            for row in rows:
                grouped.setdefault((row["kind"], row["group_key"]), []).append(
                    row["content_sha256"]
                )
            return [
                {
                    "kind": kind,
                    "group_key": group_key,
                    "members": [
                        {
                            "document_id": f"sha256:{content_sha256}",
                            "paths": list(
                                _paths_for_content(
                                    connection, generation_id, content_sha256
                                )
                            ),
                        }
                        for content_sha256 in content_hashes
                    ],
                }
                for (kind, group_key), content_hashes in grouped.items()
            ]
        rows = connection.execute(
            """
            SELECT kind, group_key, document_id
            FROM duplicate_members
            ORDER BY kind, group_key, document_id
            """
        ).fetchall()
        grouped: dict[tuple[str, str], list[str]] = {}
        for row in rows:
            grouped.setdefault((row["kind"], row["group_key"]), []).append(
                row["document_id"]
            )
        output = []
        for (kind, group_key), document_ids in grouped.items():
            members = []
            for document_id in document_ids:
                members.append(
                    {
                        "document_id": document_id,
                        "paths": list(_paths_for_document(connection, document_id)),
                    }
                )
            output.append(
                {
                    "kind": kind,
                    "group_key": group_key,
                    "members": members,
                }
            )
        return output
    except sqlite3.Error as error:
        raise CatalogError(f"cannot read duplicate groups: {error}") from error
    finally:
        connection.close()
