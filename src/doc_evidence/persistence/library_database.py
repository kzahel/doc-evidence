"""Unified per-library SQLite schema, migrations, and catalog generations."""

from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from doc_evidence.app_home import legacy_library_id
from doc_evidence.config import AppConfig
from doc_evidence.errors import CatalogError
from doc_evidence.extraction import NORMALIZED_EXTRACTION_SCHEMA_VERSION
from doc_evidence.platform_paths import ordinary_windows_path
from doc_evidence.util import hash_json, isoformat_z

if TYPE_CHECKING:
    from doc_evidence.inventory import DocumentRecord, InventoryResult

DATABASE_SCHEMA_VERSION = 4
BUSY_TIMEOUT_MS = 5_000
_SQLITE_I64_MIN = -(1 << 63)
_SQLITE_I64_MAX = (1 << 63) - 1
_UNSIGNED_I64_MAX = (1 << 64) - 1


def _sqlite_i64(value: int, label: str) -> int:
    """Represent an unsigned Windows filesystem identity in SQLite INTEGER."""

    if _SQLITE_I64_MIN <= value <= _SQLITE_I64_MAX:
        return value
    if 0 <= value <= _UNSIGNED_I64_MAX:
        return value - (1 << 64)
    raise CatalogError(f"{label} is outside the 64-bit filesystem identity range")


@dataclass(frozen=True)
class ScanFingerprint:
    collection_id: str
    relative_path: str
    resolved_path: str
    device: int
    inode: int
    size_bytes: int
    modified_ns: int
    changed_ns: int
    content_sha256: str


@dataclass(frozen=True)
class InventoryGenerationRecord:
    generation_id: str
    inventory_run_id: str
    status: str
    summary: dict[str, Any] | None
    started_at: str
    completed_at: str | None


def _connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    sqlite_path = ordinary_windows_path(path)
    try:
        if readonly:
            connection = sqlite3.connect(
                f"file:{sqlite_path.resolve().as_posix()}?mode=ro", uri=True
            )
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(sqlite_path)
    except sqlite3.Error as error:
        raise CatalogError(f"cannot open library database {path}: {error}") from error
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    if not readonly:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
    else:
        connection.execute("PRAGMA query_only = ON")
    return connection


def _migration_1(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        BEGIN IMMEDIATE;

        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        );

        CREATE TABLE library_metadata (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            library_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            config_path TEXT NOT NULL,
            config_hash TEXT NOT NULL,
            fts_enabled INTEGER NOT NULL CHECK (fts_enabled IN (0, 1)),
            active_generation_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE content_objects (
            content_sha256 TEXT PRIMARY KEY,
            document_id TEXT NOT NULL UNIQUE,
            size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
            media_type TEXT NOT NULL,
            page_count INTEGER,
            inventory_status TEXT NOT NULL,
            extraction_status TEXT NOT NULL,
            artifact_path TEXT NOT NULL,
            pdf_metadata_json TEXT NOT NULL,
            warnings_json TEXT NOT NULL,
            normalized_text_hash TEXT,
            character_count INTEGER NOT NULL CHECK (character_count >= 0),
            non_whitespace_character_count INTEGER NOT NULL
                CHECK (non_whitespace_character_count >= 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX content_objects_normalized_text_idx
            ON content_objects(normalized_text_hash);

        CREATE TABLE extraction_runs (
            content_sha256 TEXT NOT NULL REFERENCES content_objects(content_sha256),
            run_id TEXT NOT NULL,
            extractor_id TEXT NOT NULL,
            run_key TEXT NOT NULL,
            status TEXT NOT NULL,
            artifact_path TEXT NOT NULL,
            descriptor_json TEXT NOT NULL,
            warnings_json TEXT NOT NULL,
            runtime_seconds REAL,
            page_count INTEGER NOT NULL CHECK (page_count >= 0),
            table_count INTEGER,
            output_schema_version INTEGER NOT NULL,
            registered_at TEXT NOT NULL,
            PRIMARY KEY (content_sha256, run_id),
            UNIQUE (content_sha256, extractor_id, run_key)
        );

        CREATE TABLE run_pages (
            content_sha256 TEXT NOT NULL,
            run_id TEXT NOT NULL,
            page_number INTEGER NOT NULL CHECK (page_number >= 1),
            text TEXT NOT NULL,
            character_count INTEGER NOT NULL CHECK (character_count >= 0),
            non_whitespace_character_count INTEGER NOT NULL
                CHECK (non_whitespace_character_count >= 0),
            PRIMARY KEY (content_sha256, run_id, page_number),
            FOREIGN KEY (content_sha256, run_id)
                REFERENCES extraction_runs(content_sha256, run_id)
                ON DELETE CASCADE
        );
        CREATE INDEX run_pages_document_page_idx
            ON run_pages(content_sha256, page_number);

        CREATE VIRTUAL TABLE pages_fts USING fts5(
            content_sha256 UNINDEXED,
            run_id UNINDEXED,
            extractor_id UNINDEXED,
            page_number UNINDEXED,
            text,
            tokenize = 'unicode61'
        );

        CREATE TABLE registered_artifacts (
            artifact_id TEXT PRIMARY KEY,
            content_sha256 TEXT NOT NULL,
            run_id TEXT NOT NULL,
            label TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            media_type TEXT NOT NULL,
            size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
            FOREIGN KEY (content_sha256, run_id)
                REFERENCES extraction_runs(content_sha256, run_id)
                ON DELETE CASCADE,
            UNIQUE (content_sha256, run_id, relative_path)
        );

        CREATE TABLE inventory_generations (
            generation_id TEXT PRIMARY KEY,
            inventory_run_id TEXT NOT NULL UNIQUE,
            config_hash TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN ('building', 'active', 'superseded', 'failed')
            ),
            full_hash_verification INTEGER NOT NULL CHECK (
                full_hash_verification IN (0, 1)
            ),
            selected_collections_json TEXT NOT NULL,
            summary_json TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT
        );

        CREATE TABLE collection_snapshots (
            generation_id TEXT NOT NULL
                REFERENCES inventory_generations(generation_id) ON DELETE CASCADE,
            collection_id TEXT NOT NULL,
            source_path TEXT NOT NULL,
            include_json TEXT NOT NULL,
            exclude_json TEXT NOT NULL,
            PRIMARY KEY (generation_id, collection_id)
        );

        CREATE TABLE source_occurrences (
            generation_id TEXT NOT NULL
                REFERENCES inventory_generations(generation_id) ON DELETE CASCADE,
            collection_id TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            content_sha256 TEXT NOT NULL
                REFERENCES content_objects(content_sha256),
            size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
            modified_ns INTEGER NOT NULL,
            observed_at TEXT NOT NULL,
            PRIMARY KEY (generation_id, collection_id, relative_path)
        );
        CREATE INDEX source_occurrences_content_idx
            ON source_occurrences(generation_id, content_sha256);

        CREATE TABLE generation_documents (
            generation_id TEXT NOT NULL
                REFERENCES inventory_generations(generation_id) ON DELETE CASCADE,
            content_sha256 TEXT NOT NULL
                REFERENCES content_objects(content_sha256),
            PRIMARY KEY (generation_id, content_sha256)
        );

        CREATE TABLE duplicate_members (
            generation_id TEXT NOT NULL
                REFERENCES inventory_generations(generation_id) ON DELETE CASCADE,
            kind TEXT NOT NULL CHECK (kind IN ('byte', 'normalized_text')),
            group_key TEXT NOT NULL,
            content_sha256 TEXT NOT NULL
                REFERENCES content_objects(content_sha256),
            PRIMARY KEY (generation_id, kind, group_key, content_sha256)
        );

        CREATE TABLE scan_fingerprints (
            collection_id TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            resolved_path TEXT NOT NULL,
            device INTEGER NOT NULL,
            inode INTEGER NOT NULL,
            size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
            modified_ns INTEGER NOT NULL,
            changed_ns INTEGER NOT NULL,
            content_sha256 TEXT NOT NULL
                REFERENCES content_objects(content_sha256),
            last_seen_generation_id TEXT NOT NULL
                REFERENCES inventory_generations(generation_id),
            PRIMARY KEY (collection_id, relative_path)
        );

        CREATE TABLE scheduler_lease (
            singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
            library_id TEXT NOT NULL,
            scheduler_instance_id TEXT,
            acquired_at TEXT,
            heartbeat_at TEXT,
            queue_paused INTEGER NOT NULL DEFAULT 0 CHECK (queue_paused IN (0, 1))
        );

        INSERT INTO schema_migrations (version, applied_at)
        VALUES (1, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
        PRAGMA user_version = 1;
        COMMIT;
        """
    )


def _migration_2(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        BEGIN IMMEDIATE;

        CREATE TABLE job_batches (
            batch_id TEXT PRIMARY KEY,
            library_id TEXT NOT NULL,
            selection_json TEXT NOT NULL,
            policy_json TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN (
                    'preflighting', 'queued', 'running', 'succeeded',
                    'partially_failed', 'failed', 'cancelled'
                )
            ),
            requested_count INTEGER NOT NULL CHECK (requested_count >= 0),
            child_count INTEGER NOT NULL DEFAULT 0 CHECK (child_count >= 0),
            cache_hit_count INTEGER NOT NULL DEFAULT 0
                CHECK (cache_hit_count >= 0),
            succeeded_count INTEGER NOT NULL DEFAULT 0
                CHECK (succeeded_count >= 0),
            failed_count INTEGER NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
            cancelled_count INTEGER NOT NULL DEFAULT 0
                CHECK (cancelled_count >= 0),
            created_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT
        );

        CREATE TABLE jobs (
            job_id TEXT PRIMARY KEY,
            library_id TEXT NOT NULL,
            batch_id TEXT REFERENCES job_batches(batch_id) ON DELETE SET NULL,
            idempotency_key TEXT,
            request_kind TEXT NOT NULL CHECK (request_kind = 'extraction'),
            document_id TEXT NOT NULL,
            content_sha256 TEXT NOT NULL
                REFERENCES content_objects(content_sha256),
            extractor_id TEXT NOT NULL,
            cache_key TEXT NOT NULL,
            settings_json TEXT NOT NULL,
            execution_json TEXT NOT NULL,
            execution_mode TEXT NOT NULL CHECK (
                execution_mode IN ('reuse_or_execute', 'fresh_verification')
            ),
            run_key TEXT,
            priority INTEGER NOT NULL,
            resource_class TEXT NOT NULL CHECK (
                resource_class IN ('light', 'ocr', 'model_heavy')
            ),
            state TEXT NOT NULL CHECK (
                state IN (
                    'queued', 'starting', 'running', 'cancelling',
                    'succeeded', 'failed', 'cancelled', 'interrupted'
                )
            ),
            outcome TEXT,
            queue_reason TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
            automatic_retry_count INTEGER NOT NULL DEFAULT 0
                CHECK (automatic_retry_count BETWEEN 0 AND 1),
            cancellation_requested INTEGER NOT NULL DEFAULT 0
                CHECK (cancellation_requested IN (0, 1)),
            active_attempt_id TEXT,
            result_run_id TEXT,
            result_artifact_path TEXT,
            failure_class TEXT,
            error_summary TEXT,
            created_at TEXT NOT NULL,
            queued_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE UNIQUE INDEX jobs_idempotency_idx
            ON jobs(library_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL;
        CREATE INDEX jobs_queue_idx
            ON jobs(state, priority DESC, queued_at, job_id);
        CREATE INDEX jobs_content_idx
            ON jobs(content_sha256, extractor_id, created_at DESC);
        CREATE INDEX jobs_cache_idx
            ON jobs(cache_key, execution_mode, created_at DESC);

        CREATE TABLE job_request_keys (
            library_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
            request_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (library_id, idempotency_key)
        );

        CREATE TABLE job_attempts (
            attempt_id TEXT PRIMARY KEY,
            job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
            attempt_number INTEGER NOT NULL CHECK (attempt_number >= 1),
            state TEXT NOT NULL CHECK (
                state IN (
                    'starting', 'running', 'succeeded', 'failed',
                    'cancelled', 'timeout', 'interrupted'
                )
            ),
            scheduler_instance_id TEXT NOT NULL,
            worker_pid INTEGER,
            process_group_id INTEGER,
            heartbeat_at TEXT,
            deadline_at TEXT NOT NULL,
            execution_json TEXT NOT NULL,
            attempt_path TEXT,
            exit_code INTEGER,
            publication_outcome TEXT,
            artifact_manifest_sha256 TEXT,
            failure_class TEXT,
            error_summary TEXT,
            started_at TEXT NOT NULL,
            completed_at TEXT,
            UNIQUE(job_id, attempt_number)
        );
        CREATE INDEX job_attempts_active_idx
            ON job_attempts(state, heartbeat_at);

        CREATE TABLE job_events (
            job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
            sequence INTEGER NOT NULL CHECK (sequence >= 1),
            event_type TEXT NOT NULL,
            stage TEXT NOT NULL,
            progress_current INTEGER,
            progress_total INTEGER,
            detail_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (job_id, sequence)
        );

        INSERT INTO schema_migrations (version, applied_at)
        VALUES (2, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
        PRAGMA user_version = 2;
        COMMIT;
        """
    )


def _migration_3(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        BEGIN IMMEDIATE;
        ALTER TABLE job_batches ADD COLUMN idempotency_key TEXT;
        ALTER TABLE job_batches ADD COLUMN request_hash TEXT;
        CREATE UNIQUE INDEX job_batches_idempotency_idx
            ON job_batches(library_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL;
        CREATE TABLE job_batch_members (
            batch_id TEXT NOT NULL
                REFERENCES job_batches(batch_id) ON DELETE CASCADE,
            job_id TEXT NOT NULL REFERENCES jobs(job_id) ON DELETE CASCADE,
            ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
            PRIMARY KEY (batch_id, job_id),
            UNIQUE (batch_id, ordinal)
        );
        INSERT INTO job_batch_members (batch_id, job_id, ordinal)
        SELECT batch_id, job_id,
               ROW_NUMBER() OVER (
                   PARTITION BY batch_id ORDER BY created_at, job_id
               ) - 1
        FROM jobs WHERE batch_id IS NOT NULL;
        INSERT INTO schema_migrations (version, applied_at)
        VALUES (3, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
        PRAGMA user_version = 3;
        COMMIT;
        """
    )


def _migration_4(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        PRAGMA foreign_keys = OFF;
        BEGIN IMMEDIATE;

        CREATE TABLE jobs_v4 (
            job_id TEXT PRIMARY KEY,
            library_id TEXT NOT NULL,
            batch_id TEXT REFERENCES job_batches(batch_id) ON DELETE SET NULL,
            idempotency_key TEXT,
            request_kind TEXT NOT NULL CHECK (
                request_kind IN ('extraction', 'inventory')
            ),
            document_id TEXT,
            content_sha256 TEXT REFERENCES content_objects(content_sha256),
            extractor_id TEXT,
            cache_key TEXT NOT NULL,
            settings_json TEXT NOT NULL,
            execution_json TEXT NOT NULL,
            execution_mode TEXT NOT NULL CHECK (
                execution_mode IN ('reuse_or_execute', 'fresh_verification')
            ),
            run_key TEXT,
            priority INTEGER NOT NULL,
            resource_class TEXT NOT NULL CHECK (
                resource_class IN ('light', 'ocr', 'model_heavy')
            ),
            state TEXT NOT NULL CHECK (
                state IN (
                    'queued', 'starting', 'running', 'cancelling',
                    'succeeded', 'failed', 'cancelled', 'interrupted'
                )
            ),
            outcome TEXT,
            queue_reason TEXT,
            retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
            automatic_retry_count INTEGER NOT NULL DEFAULT 0
                CHECK (automatic_retry_count BETWEEN 0 AND 1),
            cancellation_requested INTEGER NOT NULL DEFAULT 0
                CHECK (cancellation_requested IN (0, 1)),
            active_attempt_id TEXT,
            result_run_id TEXT,
            result_artifact_path TEXT,
            failure_class TEXT,
            error_summary TEXT,
            created_at TEXT NOT NULL,
            queued_at TEXT NOT NULL,
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT NOT NULL,
            CHECK (
                request_kind != 'extraction'
                OR (
                    document_id IS NOT NULL
                    AND content_sha256 IS NOT NULL
                    AND extractor_id IS NOT NULL
                )
            )
        );
        INSERT INTO jobs_v4 SELECT * FROM jobs;
        DROP TABLE jobs;
        ALTER TABLE jobs_v4 RENAME TO jobs;

        CREATE UNIQUE INDEX jobs_idempotency_idx
            ON jobs(library_id, idempotency_key)
            WHERE idempotency_key IS NOT NULL;
        CREATE INDEX jobs_queue_idx
            ON jobs(state, priority DESC, queued_at, job_id);
        CREATE INDEX jobs_content_idx
            ON jobs(content_sha256, extractor_id, created_at DESC);
        CREATE INDEX jobs_cache_idx
            ON jobs(cache_key, execution_mode, created_at DESC);

        INSERT INTO schema_migrations (version, applied_at)
        VALUES (4, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
        PRAGMA user_version = 4;
        COMMIT;
        PRAGMA foreign_keys = ON;
        """
    )


def _migrate(connection: sqlite3.Connection) -> None:
    version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if version > DATABASE_SCHEMA_VERSION:
        raise CatalogError(
            f"library database schema {version} is newer than supported "
            f"schema {DATABASE_SCHEMA_VERSION}"
        )
    if version == 0:
        try:
            _migration_1(connection)
        except sqlite3.Error as error:
            if connection.in_transaction:
                connection.rollback()
            raise CatalogError(f"cannot migrate library database: {error}") from error
        version = 1
    if version == 1:
        try:
            _migration_2(connection)
        except sqlite3.Error as error:
            if connection.in_transaction:
                connection.rollback()
            raise CatalogError(f"cannot migrate library database: {error}") from error
        version = 2
    if version == 2:
        try:
            _migration_3(connection)
        except sqlite3.Error as error:
            if connection.in_transaction:
                connection.rollback()
            raise CatalogError(f"cannot migrate library database: {error}") from error
        version = 3
    if version == 3:
        try:
            _migration_4(connection)
        except sqlite3.Error as error:
            if connection.in_transaction:
                connection.rollback()
            connection.execute("PRAGMA foreign_keys = ON")
            raise CatalogError(f"cannot migrate library database: {error}") from error


def _metadata(
    connection: sqlite3.Connection,
    *,
    library_id: str,
    name: str,
    config: AppConfig,
) -> None:
    row = connection.execute(
        "SELECT library_id FROM library_metadata WHERE singleton = 1"
    ).fetchone()
    now = isoformat_z()
    if row is None:
        connection.execute(
            """
            INSERT INTO library_metadata (
                singleton, library_id, name, config_path, config_hash,
                fts_enabled, active_generation_id, created_at, updated_at
            ) VALUES (1, ?, ?, ?, ?, ?, NULL, ?, ?)
            """,
            (
                library_id,
                name,
                str(config.path),
                config.config_hash,
                int(config.search.sqlite_fts),
                now,
                now,
            ),
        )
        connection.execute(
            "INSERT INTO scheduler_lease (singleton, library_id) VALUES (1, ?)",
            (library_id,),
        )
    elif row["library_id"] != library_id:
        raise CatalogError(
            "library descriptor and database identity disagree: "
            f"descriptor={library_id}, database={row['library_id']}"
        )
    else:
        connection.execute(
            """
            UPDATE library_metadata
            SET name = ?, config_path = ?, config_hash = ?, fts_enabled = ?,
                updated_at = ?
            WHERE singleton = 1
            """,
            (
                name,
                str(config.path),
                config.config_hash,
                int(config.search.sqlite_fts),
                now,
            ),
        )


def _json_mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _integer(value: object, field: str) -> int:
    if not isinstance(value, int):
        raise TypeError(f"{field} is not an integer")
    return value


def _read_sidecar_pages(
    run_dir: Path, extractor_id: str
) -> tuple[list[dict[str, object]], int | None]:
    normalized_path = run_dir / "normalized.json"
    if normalized_path.is_file():
        normalized = json.loads(normalized_path.read_text(encoding="utf-8"))
        raw_pages = normalized.get("pages", [])
        if not isinstance(raw_pages, list):
            raise ValueError("normalized pages are not a list")
        pages = [item for item in raw_pages if isinstance(item, dict)]
        table_count = normalized.get("table_count")
        return pages, table_count if isinstance(table_count, int) else None
    if extractor_id == "poppler":
        text = (run_dir / "text.txt").read_text(encoding="utf-8")
        raw_rows = json.loads((run_dir / "pages.json").read_text(encoding="utf-8"))
        if not isinstance(raw_rows, list):
            raise ValueError("Poppler pages are not a list")
        return (
            [
                {
                    "page_number": int(item["page_number"]),
                    "text": text[int(item["start_offset"]) : int(item["end_offset"])],
                    "character_count": int(item["character_count"]),
                    "non_whitespace_character_count": int(
                        item["non_whitespace_character_count"]
                    ),
                }
                for item in raw_rows
                if isinstance(item, dict)
            ],
            None,
        )
    return [], None


def _register_run_sidecars(
    connection: sqlite3.Connection,
    *,
    store: Path,
    content_sha256: str,
) -> None:
    blob_dir = store / "blobs" / content_sha256[:2] / content_sha256
    for run_path in sorted(blob_dir.glob("runs/*/*/run.json")):
        run_dir = run_path.parent
        extractor_id = run_dir.parent.name
        if extractor_id == "page-render":
            continue
        try:
            run = json.loads(run_path.read_text(encoding="utf-8"))
            if not isinstance(run, dict):
                continue
            run_key = str(run.get("run_key", run_dir.name))
            run_id = str(run.get("run_id", f"{extractor_id}:{run_key}"))
            descriptor = _json_mapping(run.get("descriptor"))
            pages, table_count = _read_sidecar_pages(run_dir, extractor_id)
            warnings = run.get("warnings", [])
            if not isinstance(warnings, list):
                warnings = []
            runtime = run.get("runtime_seconds")
            relative = run_dir.relative_to(store).as_posix()
            connection.execute(
                """
                INSERT INTO extraction_runs (
                    content_sha256, run_id, extractor_id, run_key, status,
                    artifact_path, descriptor_json, warnings_json,
                    runtime_seconds, page_count, table_count,
                    output_schema_version, registered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(content_sha256, run_id) DO UPDATE SET
                    status = excluded.status,
                    artifact_path = excluded.artifact_path,
                    descriptor_json = excluded.descriptor_json,
                    warnings_json = excluded.warnings_json,
                    runtime_seconds = excluded.runtime_seconds,
                    page_count = excluded.page_count,
                    table_count = excluded.table_count
                """,
                (
                    content_sha256,
                    run_id,
                    extractor_id,
                    run_key,
                    str(run.get("status", "unknown")),
                    relative,
                    json.dumps(descriptor, sort_keys=True),
                    json.dumps(warnings, ensure_ascii=False),
                    float(runtime) if isinstance(runtime, (int, float)) else None,
                    len(pages),
                    table_count,
                    int(
                        run.get("schema_version", NORMALIZED_EXTRACTION_SCHEMA_VERSION)
                    ),
                    isoformat_z(),
                ),
            )
            connection.execute(
                "DELETE FROM run_pages WHERE content_sha256 = ? AND run_id = ?",
                (content_sha256, run_id),
            )
            connection.execute(
                "DELETE FROM pages_fts WHERE content_sha256 = ? AND run_id = ?",
                (content_sha256, run_id),
            )
            for page in pages:
                page_number = _integer(page.get("page_number"), "page_number")
                text = str(page.get("text", ""))
                character_count = _integer(
                    page.get("character_count", len(text)), "character_count"
                )
                non_whitespace = _integer(
                    page.get(
                        "non_whitespace_character_count",
                        sum(not character.isspace() for character in text),
                    ),
                    "non_whitespace_character_count",
                )
                connection.execute(
                    """
                    INSERT INTO run_pages (
                        content_sha256, run_id, page_number, text,
                        character_count, non_whitespace_character_count
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        content_sha256,
                        run_id,
                        page_number,
                        text,
                        character_count,
                        non_whitespace,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO pages_fts (
                        content_sha256, run_id, extractor_id, page_number, text
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (content_sha256, run_id, extractor_id, page_number, text),
                )
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
            sqlite3.Error,
        ):
            continue


def _upsert_content(
    connection: sqlite3.Connection, document: DocumentRecord, now: str
) -> None:
    connection.execute(
        """
        INSERT INTO content_objects (
            content_sha256, document_id, size_bytes, media_type, page_count,
            inventory_status, extraction_status, artifact_path,
            pdf_metadata_json, warnings_json, normalized_text_hash,
            character_count, non_whitespace_character_count,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(content_sha256) DO UPDATE SET
            size_bytes = excluded.size_bytes,
            media_type = excluded.media_type,
            page_count = excluded.page_count,
            inventory_status = excluded.inventory_status,
            extraction_status = excluded.extraction_status,
            artifact_path = excluded.artifact_path,
            pdf_metadata_json = excluded.pdf_metadata_json,
            warnings_json = excluded.warnings_json,
            normalized_text_hash = excluded.normalized_text_hash,
            character_count = excluded.character_count,
            non_whitespace_character_count =
                excluded.non_whitespace_character_count,
            updated_at = excluded.updated_at
        """,
        (
            document.content_sha256,
            document.document_id,
            document.size_bytes,
            document.media_type,
            document.page_count,
            document.inventory_status,
            document.extraction_status,
            document.artifact_path,
            json.dumps(document.pdf_metadata, sort_keys=True),
            json.dumps(list(document.warnings), ensure_ascii=False),
            document.normalized_text_hash,
            document.character_count,
            document.non_whitespace_character_count,
            now,
            now,
        ),
    )


class LibraryDatabase:
    def __init__(self, path: Path, library_id: str):
        self.path = path
        self.library_id = library_id

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        return _connect(self.path, readonly=readonly)

    def active_generation_id(self) -> str | None:
        connection = self.connect(readonly=True)
        try:
            row = connection.execute(
                "SELECT active_generation_id FROM library_metadata WHERE singleton = 1"
            ).fetchone()
            return str(row[0]) if row is not None and row[0] is not None else None
        finally:
            connection.close()

    def register_run_sidecars(
        self,
        *,
        store: Path,
        content_sha256: str,
        expected_run_id: str,
    ) -> None:
        """Project one already-published canonical run into stable tables."""

        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            _register_run_sidecars(
                connection,
                store=store,
                content_sha256=content_sha256,
            )
            row = connection.execute(
                """
                SELECT status FROM extraction_runs
                WHERE content_sha256 = ? AND run_id = ?
                """,
                (content_sha256, expected_run_id),
            ).fetchone()
            if row is None or str(row["status"]) != "ok":
                raise CatalogError("published extraction run could not be projected")
            connection.commit()
        except (sqlite3.Error, CatalogError) as error:
            connection.rollback()
            if isinstance(error, CatalogError):
                raise
            raise CatalogError(f"cannot register extraction run: {error}") from error
        finally:
            connection.close()

    def begin_generation(
        self,
        *,
        run_id: str,
        config_hash: str,
        selected_collections: Iterable[str],
        started_at: str,
        full_hash_verification: bool,
    ) -> str:
        generation_id = str(uuid.uuid4())
        connection = self.connect()
        try:
            connection.execute(
                """
                INSERT INTO inventory_generations (
                    generation_id, inventory_run_id, config_hash, status,
                    full_hash_verification, selected_collections_json,
                    started_at
                ) VALUES (?, ?, ?, 'building', ?, ?, ?)
                """,
                (
                    generation_id,
                    run_id,
                    config_hash,
                    int(full_hash_verification),
                    json.dumps(list(selected_collections)),
                    started_at,
                ),
            )
            connection.commit()
        except sqlite3.Error as error:
            connection.rollback()
            raise CatalogError(f"cannot begin inventory generation: {error}") from error
        finally:
            connection.close()
        return generation_id

    def inventory_generation(self, run_id: str) -> InventoryGenerationRecord | None:
        connection = self.connect(readonly=True)
        try:
            row = connection.execute(
                """
                SELECT generation_id, inventory_run_id, status, summary_json,
                       started_at, completed_at
                FROM inventory_generations WHERE inventory_run_id = ?
                """,
                (run_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        return InventoryGenerationRecord(
            generation_id=str(row["generation_id"]),
            inventory_run_id=str(row["inventory_run_id"]),
            status=str(row["status"]),
            summary=(
                json.loads(str(row["summary_json"]))
                if row["summary_json"] is not None
                else None
            ),
            started_at=str(row["started_at"]),
            completed_at=(
                str(row["completed_at"]) if row["completed_at"] is not None else None
            ),
        )

    def fail_generation(self, *, generation_id: str, error_summary: str) -> None:
        connection = self.connect()
        try:
            connection.execute(
                """
                UPDATE inventory_generations
                SET status = 'failed', summary_json = ?, completed_at = ?
                WHERE generation_id = ? AND status = 'building'
                """,
                (
                    json.dumps(
                        {"error_summary": error_summary[:1_000]}, sort_keys=True
                    ),
                    isoformat_z(),
                    generation_id,
                ),
            )
            connection.commit()
        except sqlite3.Error as error:
            connection.rollback()
            raise CatalogError(f"cannot fail inventory generation: {error}") from error
        finally:
            connection.close()

    def cached_fingerprint(
        self,
        *,
        collection_id: str,
        relative_path: str,
        resolved_path: Path,
        device: int,
        inode: int,
        size_bytes: int,
        modified_ns: int,
        changed_ns: int,
    ) -> str | None:
        connection = self.connect(readonly=True)
        try:
            row = connection.execute(
                """
                SELECT content_sha256
                FROM scan_fingerprints
                WHERE collection_id = ? AND relative_path = ?
                  AND resolved_path = ? AND device = ? AND inode = ?
                  AND size_bytes = ? AND modified_ns = ? AND changed_ns = ?
                """,
                (
                    collection_id,
                    relative_path,
                    str(resolved_path),
                    _sqlite_i64(device, "filesystem device"),
                    _sqlite_i64(inode, "filesystem inode"),
                    size_bytes,
                    modified_ns,
                    changed_ns,
                ),
            ).fetchone()
            return str(row[0]) if row is not None else None
        finally:
            connection.close()

    def publish_generation(
        self,
        *,
        result: InventoryResult,
        generation_id: str,
        config: AppConfig,
        fingerprints: Iterable[ScanFingerprint],
    ) -> None:
        connection = self.connect()
        now = isoformat_z()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM inventory_generations WHERE generation_id = ?",
                (generation_id,),
            ).fetchone()
            if row is None or row["status"] != "building":
                raise CatalogError("inventory generation is not publishable")
            selected = {item.id: item for item in config.collections}
            for collection_id in result.collection_ids:
                collection = selected[collection_id]
                connection.execute(
                    """
                    INSERT INTO collection_snapshots (
                        generation_id, collection_id, source_path,
                        include_json, exclude_json
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        generation_id,
                        collection.id,
                        str(collection.source),
                        json.dumps(collection.include),
                        json.dumps(collection.exclude),
                    ),
                )
            for document in result.documents:
                _upsert_content(connection, document, now)
                connection.execute(
                    "INSERT INTO generation_documents VALUES (?, ?)",
                    (generation_id, document.content_sha256),
                )
                for source in document.sources:
                    connection.execute(
                        """
                        INSERT INTO source_occurrences (
                            generation_id, collection_id, relative_path,
                            content_sha256, size_bytes, modified_ns, observed_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            generation_id,
                            source.collection_id,
                            source.relative_path,
                            document.content_sha256,
                            source.size_bytes,
                            source.modified_ns,
                            source.observed_at,
                        ),
                    )
                _register_run_sidecars(
                    connection,
                    store=config.store,
                    content_sha256=document.content_sha256,
                )
            for kind, groups in (
                ("byte", result.byte_duplicate_groups),
                ("normalized_text", result.normalized_text_duplicate_groups),
            ):
                for group in groups:
                    for document_id in group["document_ids"]:
                        connection.execute(
                            """
                            INSERT INTO duplicate_members (
                                generation_id, kind, group_key, content_sha256
                            ) VALUES (?, ?, ?, ?)
                            """,
                            (
                                generation_id,
                                kind,
                                group["group_key"],
                                str(document_id).removeprefix("sha256:"),
                            ),
                        )
            for fingerprint in fingerprints:
                connection.execute(
                    """
                    INSERT INTO scan_fingerprints (
                        collection_id, relative_path, resolved_path, device,
                        inode, size_bytes, modified_ns, changed_ns,
                        content_sha256, last_seen_generation_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(collection_id, relative_path) DO UPDATE SET
                        resolved_path = excluded.resolved_path,
                        device = excluded.device,
                        inode = excluded.inode,
                        size_bytes = excluded.size_bytes,
                        modified_ns = excluded.modified_ns,
                        changed_ns = excluded.changed_ns,
                        content_sha256 = excluded.content_sha256,
                        last_seen_generation_id = excluded.last_seen_generation_id
                    """,
                    (
                        fingerprint.collection_id,
                        fingerprint.relative_path,
                        fingerprint.resolved_path,
                        _sqlite_i64(fingerprint.device, "filesystem device"),
                        _sqlite_i64(fingerprint.inode, "filesystem inode"),
                        fingerprint.size_bytes,
                        fingerprint.modified_ns,
                        fingerprint.changed_ns,
                        fingerprint.content_sha256,
                        generation_id,
                    ),
                )
            count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM generation_documents WHERE generation_id = ?",
                    (generation_id,),
                ).fetchone()[0]
            )
            if count != len(result.documents):
                raise CatalogError("inventory generation validation count disagrees")
            previous = connection.execute(
                "SELECT active_generation_id FROM library_metadata WHERE singleton = 1"
            ).fetchone()[0]
            if previous is not None:
                connection.execute(
                    """
                    UPDATE inventory_generations SET status = 'superseded'
                    WHERE generation_id = ? AND status = 'active'
                    """,
                    (previous,),
                )
            connection.execute(
                """
                UPDATE inventory_generations
                SET status = 'active', summary_json = ?, completed_at = ?
                WHERE generation_id = ?
                """,
                (
                    json.dumps(result.summary, sort_keys=True),
                    result.completed_at,
                    generation_id,
                ),
            )
            connection.execute(
                """
                UPDATE library_metadata
                SET active_generation_id = ?, config_hash = ?, updated_at = ?
                WHERE singleton = 1
                """,
                (generation_id, result.config_hash, now),
            )
            connection.commit()
        except (sqlite3.Error, CatalogError, KeyError) as error:
            connection.rollback()
            if isinstance(error, CatalogError):
                raise
            raise CatalogError(
                f"cannot publish inventory generation: {error}"
            ) from error
        finally:
            connection.close()

    def integrity_check(self) -> None:
        connection = self.connect(readonly=True)
        try:
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            if integrity != "ok" or foreign_keys:
                raise CatalogError(
                    f"library database integrity failed: {integrity}; "
                    f"foreign-key errors={len(foreign_keys)}"
                )
        finally:
            connection.close()


def _import_legacy_catalog(
    database: LibraryDatabase,
    *,
    config: AppConfig,
) -> None:
    legacy = config.store / "catalog.sqlite"
    if not legacy.is_file() or database.active_generation_id() is not None:
        return
    source = _connect(legacy, readonly=True)
    target = database.connect()
    generation_id = str(uuid.uuid4())
    now = isoformat_z()
    try:
        metadata = {
            str(row["key"]): str(row["value"])
            for row in source.execute("SELECT key, value FROM catalog_metadata")
        }
        target.execute("BEGIN IMMEDIATE")
        target.execute(
            """
            INSERT INTO inventory_generations (
                generation_id, inventory_run_id, config_hash, status,
                full_hash_verification, selected_collections_json,
                summary_json, started_at, completed_at
            ) VALUES (?, ?, ?, 'active', 1, ?, ?, ?, ?)
            """,
            (
                generation_id,
                metadata.get("inventory_run_id", f"legacy-{generation_id}"),
                metadata.get("config_hash", config.config_hash),
                metadata.get("selected_collections", "[]"),
                metadata.get("summary", "{}"),
                metadata.get("created_at", now),
                metadata.get("created_at", now),
            ),
        )
        for collection in config.collections:
            target.execute(
                "INSERT INTO collection_snapshots VALUES (?, ?, ?, ?, ?)",
                (
                    generation_id,
                    collection.id,
                    str(collection.source),
                    json.dumps(collection.include),
                    json.dumps(collection.exclude),
                ),
            )
        documents = source.execute("SELECT * FROM documents ORDER BY document_id")
        for row in documents:
            content_sha256 = str(row["content_sha256"])
            target.execute(
                """
                INSERT INTO content_objects VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    content_sha256,
                    row["document_id"],
                    row["size_bytes"],
                    row["media_type"],
                    row["page_count"],
                    row["inventory_status"],
                    row["extraction_status"],
                    row["artifact_path"],
                    row["pdf_metadata_json"] or "{}",
                    row["warnings_json"],
                    row["normalized_text_hash"],
                    row["character_count"],
                    row["non_whitespace_character_count"],
                    now,
                    now,
                ),
            )
            target.execute(
                "INSERT INTO generation_documents VALUES (?, ?)",
                (generation_id, content_sha256),
            )
            _register_run_sidecars(
                target,
                store=config.store,
                content_sha256=content_sha256,
            )
        for row in source.execute("SELECT * FROM sources"):
            content = source.execute(
                "SELECT content_sha256 FROM documents WHERE document_id = ?",
                (row["document_id"],),
            ).fetchone()[0]
            target.execute(
                "INSERT INTO source_occurrences VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    generation_id,
                    row["collection_id"],
                    row["relative_path"],
                    content,
                    row["size_bytes"],
                    row["modified_ns"],
                    row["observed_at"],
                ),
            )
        for row in source.execute("SELECT * FROM duplicate_members"):
            content = source.execute(
                "SELECT content_sha256 FROM documents WHERE document_id = ?",
                (row["document_id"],),
            ).fetchone()[0]
            target.execute(
                "INSERT INTO duplicate_members VALUES (?, ?, ?, ?)",
                (generation_id, row["kind"], row["group_key"], content),
            )
        target.execute(
            "UPDATE library_metadata SET active_generation_id = ?, updated_at = ?",
            (generation_id, now),
        )
        target.commit()
    except (sqlite3.Error, OSError, UnicodeError, json.JSONDecodeError) as error:
        target.rollback()
        raise CatalogError(f"cannot import legacy catalog: {error}") from error
    finally:
        source.close()
        target.close()


def ensure_library_database(
    config: AppConfig,
    *,
    library_id: str | None = None,
    name: str | None = None,
    import_legacy: bool = True,
) -> LibraryDatabase:
    resolved_id = library_id or legacy_library_id(config.path)
    path = config.store / "doc-evidence.sqlite"
    connection = _connect(path)
    try:
        _migrate(connection)
        connection.execute("BEGIN IMMEDIATE")
        _metadata(
            connection,
            library_id=resolved_id,
            name=name or config.path.parent.name or "Document Library",
            config=config,
        )
        connection.commit()
    except (sqlite3.Error, CatalogError) as error:
        connection.rollback()
        if isinstance(error, CatalogError):
            raise
        raise CatalogError(f"cannot initialize library database: {error}") from error
    finally:
        connection.close()
    database = LibraryDatabase(path, resolved_id)
    if import_legacy:
        _import_legacy_catalog(database, config=config)
    database.integrity_check()
    return database


def run_projection_identity(
    *, content_sha256: str, run_id: str, artifact_path: str
) -> str:
    return hash_json(
        {
            "content_sha256": content_sha256,
            "run_id": run_id,
            "artifact_path": artifact_path,
        }
    )
