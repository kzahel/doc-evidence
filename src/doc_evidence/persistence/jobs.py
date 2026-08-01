"""SQLite repository for durable extraction jobs, attempts, and events."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from doc_evidence.application.jobs import (
    ActiveAttemptRecord,
    CachedResult,
    ClaimedJob,
    JobAttemptRecord,
    JobBatchRecord,
    JobCountRecord,
    JobCreation,
    JobEventRecord,
    JobRecord,
    JobSpec,
    JobState,
    QueueStateRecord,
)
from doc_evidence.attempts import AttemptResult
from doc_evidence.errors import CatalogError, NotFoundError, RequestError
from doc_evidence.extractor_registry import ResourceClass
from doc_evidence.persistence.library_database import LibraryDatabase
from doc_evidence.util import hash_json, isoformat_z

MAX_EVENTS_PER_JOB = 500


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def _record(row: sqlite3.Row) -> JobRecord:
    return JobRecord(
        job_id=str(row["job_id"]),
        library_id=str(row["library_id"]),
        batch_id=str(row["batch_id"]) if row["batch_id"] is not None else None,
        idempotency_key=(
            str(row["idempotency_key"]) if row["idempotency_key"] is not None else None
        ),
        document_id=str(row["document_id"]),
        content_sha256=str(row["content_sha256"]),
        extractor_id=str(row["extractor_id"]),
        cache_key=str(row["cache_key"]),
        settings=json.loads(str(row["settings_json"])),
        execution=json.loads(str(row["execution_json"])),
        execution_mode=str(row["execution_mode"]),  # type: ignore[arg-type]
        run_key=str(row["run_key"]) if row["run_key"] is not None else None,
        priority=int(row["priority"]),
        resource_class=str(row["resource_class"]),  # type: ignore[arg-type]
        state=str(row["state"]),  # type: ignore[arg-type]
        outcome=str(row["outcome"]) if row["outcome"] is not None else None,
        queue_reason=(
            str(row["queue_reason"]) if row["queue_reason"] is not None else None
        ),
        retry_count=int(row["retry_count"]),
        automatic_retry_count=int(row["automatic_retry_count"]),
        cancellation_requested=bool(row["cancellation_requested"]),
        active_attempt_id=(
            str(row["active_attempt_id"])
            if row["active_attempt_id"] is not None
            else None
        ),
        result_run_id=(
            str(row["result_run_id"]) if row["result_run_id"] is not None else None
        ),
        result_artifact_path=(
            str(row["result_artifact_path"])
            if row["result_artifact_path"] is not None
            else None
        ),
        failure_class=(
            str(row["failure_class"]) if row["failure_class"] is not None else None
        ),
        error_summary=(
            str(row["error_summary"]) if row["error_summary"] is not None else None
        ),
        created_at=str(row["created_at"]),
        queued_at=str(row["queued_at"]),
        started_at=str(row["started_at"]) if row["started_at"] is not None else None,
        completed_at=(
            str(row["completed_at"]) if row["completed_at"] is not None else None
        ),
        updated_at=str(row["updated_at"]),
    )


def _batch_record(row: sqlite3.Row) -> JobBatchRecord:
    return JobBatchRecord(
        batch_id=str(row["batch_id"]),
        library_id=str(row["library_id"]),
        selection=json.loads(str(row["selection_json"])),
        policy=json.loads(str(row["policy_json"])),
        status=str(row["status"]),
        requested_count=int(row["requested_count"]),
        child_count=int(row["child_count"]),
        cache_hit_count=int(row["cache_hit_count"]),
        succeeded_count=int(row["succeeded_count"]),
        failed_count=int(row["failed_count"]),
        cancelled_count=int(row["cancelled_count"]),
        created_at=str(row["created_at"]),
        started_at=str(row["started_at"]) if row["started_at"] is not None else None,
        completed_at=(
            str(row["completed_at"]) if row["completed_at"] is not None else None
        ),
    )


class JobRepository:
    """Persist job transitions in short transactions with bounded events."""

    def __init__(self, database: LibraryDatabase):
        self.database = database

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        *,
        job_id: str,
        event_type: str,
        stage: str,
        detail: dict[str, Any] | None = None,
        progress_current: int | None = None,
        progress_total: int | None = None,
        created_at: str | None = None,
    ) -> None:
        sequence = int(
            connection.execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM job_events WHERE job_id = ?",
                (job_id,),
            ).fetchone()[0]
        )
        connection.execute(
            """
            INSERT INTO job_events (
                job_id, sequence, event_type, stage, progress_current,
                progress_total, detail_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                sequence,
                event_type,
                stage,
                progress_current,
                progress_total,
                json.dumps(detail or {}, sort_keys=True),
                created_at or isoformat_z(),
            ),
        )
        connection.execute(
            """
            DELETE FROM job_events
            WHERE job_id = ? AND sequence <= ?
            """,
            (job_id, sequence - MAX_EVENTS_PER_JOB),
        )

    def create(
        self,
        spec: JobSpec,
        *,
        cached: CachedResult | None = None,
    ) -> JobCreation:
        now = isoformat_z()
        request_hash = hash_json(
            {
                "cache_key": spec.cache_key,
                "execution_mode": spec.execution_mode,
                "priority": spec.priority,
                "batch_id": spec.batch_id,
            }
        )
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if spec.idempotency_key is not None:
                keyed = connection.execute(
                    """
                    SELECT request_hash, job_id FROM job_request_keys
                    WHERE library_id = ? AND idempotency_key = ?
                    """,
                    (spec.library_id, spec.idempotency_key),
                ).fetchone()
                if keyed is not None:
                    existing = connection.execute(
                        "SELECT * FROM jobs WHERE job_id = ?", (keyed["job_id"],)
                    ).fetchone()
                    assert existing is not None
                    record = _record(existing)
                    if str(keyed["request_hash"]) != request_hash:
                        raise RequestError(
                            "idempotency key was already used for a different request"
                        )
                    connection.commit()
                    return JobCreation(record, "idempotent")
            active = connection.execute(
                """
                SELECT * FROM jobs
                WHERE library_id = ? AND cache_key = ? AND execution_mode = ?
                  AND state IN ('queued', 'starting', 'running', 'cancelling')
                ORDER BY created_at, job_id LIMIT 1
                """,
                (spec.library_id, spec.cache_key, spec.execution_mode),
            ).fetchone()
            if active is not None:
                if spec.idempotency_key is not None:
                    connection.execute(
                        """
                        INSERT INTO job_request_keys (
                            library_id, idempotency_key, job_id,
                            request_hash, created_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            spec.library_id,
                            spec.idempotency_key,
                            active["job_id"],
                            request_hash,
                            now,
                        ),
                    )
                connection.commit()
                return JobCreation(_record(active), "coalesced")
            job_id = str(uuid.uuid4())
            state = "succeeded" if cached is not None else "queued"
            outcome = "cache_hit" if cached is not None else None
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id, library_id, batch_id, idempotency_key, request_kind,
                    document_id, content_sha256, extractor_id, cache_key,
                    settings_json, execution_json, execution_mode, run_key,
                    priority, resource_class, state, outcome, result_run_id,
                    result_artifact_path, created_at, queued_at, completed_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, 'extraction', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                          ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    spec.library_id,
                    spec.batch_id,
                    spec.idempotency_key,
                    spec.document_id,
                    spec.content_sha256,
                    spec.extractor_id,
                    spec.cache_key,
                    json.dumps(spec.settings, sort_keys=True),
                    json.dumps(spec.execution, sort_keys=True),
                    spec.execution_mode,
                    spec.run_key,
                    spec.priority,
                    spec.resource_class,
                    state,
                    outcome,
                    cached.run_id if cached is not None else None,
                    cached.artifact_path if cached is not None else None,
                    now,
                    now,
                    now if cached is not None else None,
                    now,
                ),
            )
            if spec.idempotency_key is not None:
                connection.execute(
                    """
                    INSERT INTO job_request_keys (
                        library_id, idempotency_key, job_id,
                        request_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        spec.library_id,
                        spec.idempotency_key,
                        job_id,
                        request_hash,
                        now,
                    ),
                )
            self._append_event(
                connection,
                job_id=job_id,
                event_type="cache_hit" if cached is not None else "queued",
                stage="completed" if cached is not None else "queued",
                detail={"run_id": cached.run_id} if cached is not None else {},
                created_at=now,
            )
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            connection.commit()
            assert row is not None
            return JobCreation(
                _record(row), "cache_hit" if cached is not None else "created"
            )
        except (sqlite3.Error, RequestError) as error:
            connection.rollback()
            if isinstance(error, RequestError):
                raise
            raise CatalogError(f"cannot create extraction job: {error}") from error
        finally:
            connection.close()

    def create_batch(
        self,
        *,
        library_id: str,
        selection: dict[str, Any],
        policy: dict[str, Any],
        requested_count: int,
        idempotency_key: str | None,
    ) -> tuple[JobBatchRecord, Literal["created", "idempotent"]]:
        if requested_count < 1 or requested_count > 500:
            raise RequestError("batch request count is outside its allowed bounds")
        request_hash = hash_json(
            {
                "selection": selection,
                "policy": policy,
                "requested_count": requested_count,
            }
        )
        now = isoformat_z()
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if idempotency_key is not None:
                existing = connection.execute(
                    """
                    SELECT * FROM job_batches
                    WHERE library_id = ? AND idempotency_key = ?
                    """,
                    (library_id, idempotency_key),
                ).fetchone()
                if existing is not None:
                    if str(existing["request_hash"]) != request_hash:
                        raise RequestError(
                            "idempotency key was already used for a different batch"
                        )
                    connection.commit()
                    return _batch_record(existing), "idempotent"
            batch_id = str(uuid.uuid4())
            connection.execute(
                """
                INSERT INTO job_batches (
                    batch_id, library_id, selection_json, policy_json, status,
                    requested_count, created_at, idempotency_key, request_hash
                ) VALUES (?, ?, ?, ?, 'preflighting', ?, ?, ?, ?)
                """,
                (
                    batch_id,
                    library_id,
                    json.dumps(selection, sort_keys=True),
                    json.dumps(policy, sort_keys=True),
                    requested_count,
                    now,
                    idempotency_key,
                    request_hash,
                ),
            )
            row = connection.execute(
                "SELECT * FROM job_batches WHERE batch_id = ?", (batch_id,)
            ).fetchone()
            connection.commit()
            assert row is not None
            return _batch_record(row), "created"
        except (sqlite3.Error, RequestError) as error:
            connection.rollback()
            if isinstance(error, RequestError):
                raise
            raise CatalogError(f"cannot create extraction batch: {error}") from error
        finally:
            connection.close()

    @staticmethod
    def _refresh_batch_row(
        connection: sqlite3.Connection, batch_id: str
    ) -> sqlite3.Row:
        batch = connection.execute(
            "SELECT * FROM job_batches WHERE batch_id = ?", (batch_id,)
        ).fetchone()
        if batch is None:
            raise NotFoundError("job batch was not found")
        counts = connection.execute(
            """
            SELECT COUNT(*) AS child_count,
                   SUM(CASE WHEN outcome = 'cache_hit' THEN 1 ELSE 0 END)
                       AS cache_hits,
                   SUM(CASE WHEN state = 'succeeded' THEN 1 ELSE 0 END)
                       AS succeeded,
                   SUM(CASE WHEN state IN ('failed', 'interrupted') THEN 1 ELSE 0 END)
                       AS failed,
                   SUM(CASE WHEN state = 'cancelled' THEN 1 ELSE 0 END)
                       AS cancelled,
                   SUM(CASE WHEN state = 'queued' THEN 1 ELSE 0 END) AS queued,
                   SUM(CASE WHEN state IN ('starting', 'running', 'cancelling')
                            THEN 1 ELSE 0 END) AS active
            FROM jobs
            JOIN job_batch_members member ON member.job_id = jobs.job_id
            WHERE member.batch_id = ?
            """,
            (batch_id,),
        ).fetchone()
        assert counts is not None
        child_count = int(counts["child_count"] or 0)
        succeeded = int(counts["succeeded"] or 0)
        failed = int(counts["failed"] or 0)
        cancelled = int(counts["cancelled"] or 0)
        queued = int(counts["queued"] or 0)
        active = int(counts["active"] or 0)
        terminal = succeeded + failed + cancelled
        if child_count == 0:
            status = "preflighting"
        elif active:
            status = "running"
        elif queued:
            status = "queued"
        elif failed and terminal == failed:
            status = "failed"
        elif cancelled and terminal == cancelled:
            status = "cancelled"
        elif failed or cancelled:
            status = "partially_failed"
        else:
            status = "succeeded"
        now = isoformat_z()
        completed_at = now if terminal == child_count and child_count else None
        started_at = (
            str(batch["started_at"])
            if batch["started_at"] is not None
            else (now if active or terminal else None)
        )
        connection.execute(
            """
            UPDATE job_batches SET status = ?, child_count = ?,
                cache_hit_count = ?, succeeded_count = ?, failed_count = ?,
                cancelled_count = ?, started_at = ?, completed_at = ?
            WHERE batch_id = ?
            """,
            (
                status,
                child_count,
                int(counts["cache_hits"] or 0),
                succeeded,
                failed,
                cancelled,
                started_at,
                completed_at,
                batch_id,
            ),
        )
        refreshed = connection.execute(
            "SELECT * FROM job_batches WHERE batch_id = ?", (batch_id,)
        ).fetchone()
        assert refreshed is not None
        return refreshed

    def batch(self, batch_id: str) -> JobBatchRecord:
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = self._refresh_batch_row(connection, batch_id)
            connection.commit()
            return _batch_record(row)
        except (sqlite3.Error, NotFoundError) as error:
            connection.rollback()
            if isinstance(error, NotFoundError):
                raise
            raise CatalogError(f"cannot read extraction batch: {error}") from error
        finally:
            connection.close()

    def batches(
        self, *, offset: int = 0, limit: int = 50
    ) -> tuple[list[JobBatchRecord], int]:
        if offset < 0 or limit < 1 or limit > 100:
            raise RequestError("batch pagination is outside its allowed bounds")
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            total = int(
                connection.execute("SELECT COUNT(*) FROM job_batches").fetchone()[0]
            )
            identifiers = [
                str(row[0])
                for row in connection.execute(
                    """
                    SELECT batch_id FROM job_batches
                    ORDER BY created_at DESC, batch_id DESC LIMIT ? OFFSET ?
                    """,
                    (limit, offset),
                ).fetchall()
            ]
            rows = [self._refresh_batch_row(connection, item) for item in identifiers]
            connection.commit()
            return [_batch_record(row) for row in rows], total
        except (sqlite3.Error, NotFoundError) as error:
            connection.rollback()
            if isinstance(error, NotFoundError):
                raise
            raise CatalogError(f"cannot list extraction batches: {error}") from error
        finally:
            connection.close()

    def batch_jobs(self, batch_id: str) -> tuple[JobRecord, ...]:
        self.batch(batch_id)
        connection = self.database.connect(readonly=True)
        try:
            rows = connection.execute(
                """
                SELECT jobs.* FROM jobs
                JOIN job_batch_members member ON member.job_id = jobs.job_id
                WHERE member.batch_id = ? ORDER BY member.ordinal
                """,
                (batch_id,),
            ).fetchall()
        finally:
            connection.close()
        return tuple(_record(row) for row in rows)

    def attach_batch_job(self, *, batch_id: str, job_id: str, ordinal: int) -> None:
        connection = self.database.connect()
        try:
            connection.execute(
                """
                INSERT INTO job_batch_members (batch_id, job_id, ordinal)
                VALUES (?, ?, ?)
                ON CONFLICT(batch_id, job_id) DO NOTHING
                """,
                (batch_id, job_id, ordinal),
            )
            connection.commit()
        except sqlite3.Error as error:
            connection.rollback()
            raise CatalogError(f"cannot attach batch child job: {error}") from error
        finally:
            connection.close()

    def get(self, job_id: str) -> JobRecord:
        connection = self.database.connect(readonly=True)
        try:
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise NotFoundError("job was not found")
        return _record(row)

    def list(
        self,
        *,
        states: tuple[JobState, ...] = (),
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[JobRecord], int]:
        if offset < 0 or limit < 1 or limit > 200:
            raise RequestError("job pagination is outside its allowed bounds")
        where = ""
        parameters: list[object] = []
        if states:
            where = " WHERE state IN (" + ",".join("?" for _ in states) + ")"
            parameters.extend(states)
        connection = self.database.connect(readonly=True)
        try:
            total = int(
                connection.execute(
                    "SELECT COUNT(*) FROM jobs" + where, parameters
                ).fetchone()[0]
            )
            rows = connection.execute(
                "SELECT * FROM jobs"
                + where
                + " ORDER BY created_at DESC, job_id DESC LIMIT ? OFFSET ?",
                [*parameters, limit, offset],
            ).fetchall()
        finally:
            connection.close()
        return [_record(row) for row in rows], total

    def events(
        self, job_id: str, *, after: int = 0, limit: int = 200
    ) -> list[JobEventRecord]:
        if after < 0 or limit < 1 or limit > 500:
            raise RequestError("job event pagination is outside its allowed bounds")
        self.get(job_id)
        connection = self.database.connect(readonly=True)
        try:
            rows = connection.execute(
                """
                SELECT * FROM job_events
                WHERE job_id = ? AND sequence > ?
                ORDER BY sequence LIMIT ?
                """,
                (job_id, after, limit),
            ).fetchall()
        finally:
            connection.close()
        return [
            JobEventRecord(
                sequence=int(row["sequence"]),
                event_type=str(row["event_type"]),
                stage=str(row["stage"]),
                progress_current=(
                    int(row["progress_current"])
                    if row["progress_current"] is not None
                    else None
                ),
                progress_total=(
                    int(row["progress_total"])
                    if row["progress_total"] is not None
                    else None
                ),
                detail=json.loads(str(row["detail_json"])),
                created_at=str(row["created_at"]),
            )
            for row in rows
        ]

    def attempts(self, job_id: str) -> tuple[JobAttemptRecord, ...]:
        self.get(job_id)
        connection = self.database.connect(readonly=True)
        try:
            rows = connection.execute(
                """
                SELECT * FROM job_attempts
                WHERE job_id = ? ORDER BY attempt_number
                """,
                (job_id,),
            ).fetchall()
        finally:
            connection.close()
        return tuple(
            JobAttemptRecord(
                attempt_id=str(row["attempt_id"]),
                attempt_number=int(row["attempt_number"]),
                state=str(row["state"]),
                scheduler_instance_id=str(row["scheduler_instance_id"]),
                worker_pid=(
                    int(row["worker_pid"]) if row["worker_pid"] is not None else None
                ),
                process_group_id=(
                    int(row["process_group_id"])
                    if row["process_group_id"] is not None
                    else None
                ),
                heartbeat_at=(
                    str(row["heartbeat_at"])
                    if row["heartbeat_at"] is not None
                    else None
                ),
                deadline_at=str(row["deadline_at"]),
                exit_code=(
                    int(row["exit_code"]) if row["exit_code"] is not None else None
                ),
                publication_outcome=(
                    str(row["publication_outcome"])
                    if row["publication_outcome"] is not None
                    else None
                ),
                artifact_manifest_sha256=(
                    str(row["artifact_manifest_sha256"])
                    if row["artifact_manifest_sha256"] is not None
                    else None
                ),
                failure_class=(
                    str(row["failure_class"])
                    if row["failure_class"] is not None
                    else None
                ),
                error_summary=(
                    str(row["error_summary"])
                    if row["error_summary"] is not None
                    else None
                ),
                started_at=str(row["started_at"]),
                completed_at=(
                    str(row["completed_at"])
                    if row["completed_at"] is not None
                    else None
                ),
            )
            for row in rows
        )

    def attempt_path(self, job_id: str, attempt_id: str) -> str | None:
        self.get(job_id)
        connection = self.database.connect(readonly=True)
        try:
            row = connection.execute(
                """
                SELECT attempt_path FROM job_attempts
                WHERE job_id = ? AND attempt_id = ?
                """,
                (job_id, attempt_id),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise NotFoundError("job attempt was not found")
        return str(row["attempt_path"]) if row["attempt_path"] is not None else None

    def claim_next(
        self,
        *,
        scheduler_instance_id: str,
        resource_classes: set[ResourceClass],
    ) -> ClaimedJob | None:
        if not resource_classes:
            return None
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            lease = connection.execute(
                "SELECT scheduler_instance_id, queue_paused FROM scheduler_lease "
                "WHERE singleton = 1"
            ).fetchone()
            if (
                lease is None
                or lease["scheduler_instance_id"] != scheduler_instance_id
                or bool(lease["queue_paused"])
            ):
                connection.rollback()
                return None
            placeholders = ",".join("?" for _ in resource_classes)
            row = connection.execute(
                """
                SELECT * FROM jobs
                WHERE state = 'queued' AND cancellation_requested = 0
                  AND julianday(queued_at) <= julianday('now')
                  AND resource_class IN ("""
                + placeholders
                + """)
                ORDER BY (
                    priority + MIN(
                        50,
                        CAST((julianday('now') - julianday(queued_at)) * 24 AS INTEGER)
                    )
                ) DESC, queued_at, job_id
                LIMIT 1
                """,
                sorted(resource_classes),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            job_id = str(row["job_id"])
            attempt_number = int(
                connection.execute(
                    "SELECT COUNT(*) + 1 FROM job_attempts WHERE job_id = ?",
                    (job_id,),
                ).fetchone()[0]
            )
            attempt_id = str(uuid.uuid4())
            execution = json.loads(str(row["execution_json"]))
            timeout_seconds = int(execution["timeout_seconds"])
            started_at = isoformat_z()
            deadline_at = (
                datetime.now(UTC) + timedelta(seconds=timeout_seconds)
            ).isoformat()
            connection.execute(
                """
                INSERT INTO job_attempts (
                    attempt_id, job_id, attempt_number, state,
                    scheduler_instance_id, deadline_at, execution_json, started_at
                ) VALUES (?, ?, ?, 'starting', ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    job_id,
                    attempt_number,
                    scheduler_instance_id,
                    deadline_at,
                    row["execution_json"],
                    started_at,
                ),
            )
            connection.execute(
                """
                UPDATE jobs SET state = 'starting', active_attempt_id = ?,
                    queue_reason = NULL, started_at = COALESCE(started_at, ?),
                    updated_at = ? WHERE job_id = ? AND state = 'queued'
                """,
                (attempt_id, started_at, started_at, job_id),
            )
            self._append_event(
                connection,
                job_id=job_id,
                event_type="claimed",
                stage="starting",
                detail={
                    "attempt_id": attempt_id,
                    "attempt_number": attempt_number,
                    "scheduler_instance_id": scheduler_instance_id,
                },
                created_at=started_at,
            )
            claimed_row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            connection.commit()
            assert claimed_row is not None
            return ClaimedJob(
                _record(claimed_row), attempt_id, attempt_number, deadline_at
            )
        except (sqlite3.Error, KeyError, TypeError, ValueError) as error:
            connection.rollback()
            raise CatalogError(f"cannot claim queued job: {error}") from error
        finally:
            connection.close()

    def attempt_update(
        self,
        *,
        job_id: str,
        attempt_id: str,
        worker_pid: int | None,
        process_group_id: int | None,
        heartbeat_at: str,
        stage: str,
    ) -> None:
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT state FROM jobs WHERE job_id = ? AND active_attempt_id = ?",
                (job_id, attempt_id),
            ).fetchone()
            if row is None or str(row["state"]) not in {
                "starting",
                "running",
                "cancelling",
            }:
                connection.rollback()
                return
            next_state = (
                "cancelling" if str(row["state"]) == "cancelling" else "running"
            )
            connection.execute(
                """
                UPDATE job_attempts SET state = ?, worker_pid = ?,
                    process_group_id = ?, heartbeat_at = ?
                WHERE attempt_id = ? AND job_id = ?
                """,
                (
                    "running",
                    worker_pid,
                    process_group_id,
                    heartbeat_at,
                    attempt_id,
                    job_id,
                ),
            )
            connection.execute(
                "UPDATE jobs SET state = ?, updated_at = ? WHERE job_id = ?",
                (next_state, heartbeat_at, job_id),
            )
            self._append_event(
                connection,
                job_id=job_id,
                event_type="heartbeat" if stage == "running" else stage,
                stage=stage,
                detail={"attempt_id": attempt_id, "worker_pid": worker_pid},
                created_at=heartbeat_at,
            )
            connection.commit()
        except sqlite3.Error as error:
            connection.rollback()
            raise CatalogError(f"cannot update job attempt: {error}") from error
        finally:
            connection.close()

    def finish(
        self,
        *,
        job_id: str,
        attempt_id: str,
        result: AttemptResult,
        projection_failure: str | None = None,
    ) -> JobRecord:
        if result.attempt_id != attempt_id:
            raise RequestError("attempt result identity disagrees with the job")
        if projection_failure is not None:
            state: JobState = "failed"
            outcome = "published_projection_failed"
            failure_class = "projection_failed"
            error_summary = projection_failure[:1_000]
        elif result.outcome in {
            "executed",
            "concurrent_cache_win",
            "verified_cache_match",
        }:
            state = "succeeded"
            outcome = result.outcome
            failure_class = None
            error_summary = None
        elif result.outcome == "cancelled":
            state = "cancelled"
            outcome = "cancelled"
            failure_class = result.failure_class
            error_summary = result.message
        else:
            state = "failed"
            outcome = result.outcome
            failure_class = result.failure_class
            error_summary = result.message
        completed_at = result.completed_at
        attempt_state = {
            "cancelled": "cancelled",
            "timeout": "timeout",
            "executed": "succeeded",
            "concurrent_cache_win": "succeeded",
            "verified_cache_match": "succeeded",
        }.get(result.outcome, "failed")
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT state FROM jobs WHERE job_id = ? AND active_attempt_id = ?",
                (job_id, attempt_id),
            ).fetchone()
            if row is None or str(row["state"]) not in {
                "starting",
                "running",
                "cancelling",
            }:
                raise RequestError("job is not awaiting this attempt result")
            connection.execute(
                """
                UPDATE job_attempts SET state = ?, worker_pid = ?,
                    process_group_id = ?, heartbeat_at = ?, attempt_path = ?,
                    exit_code = ?, publication_outcome = ?,
                    artifact_manifest_sha256 = ?, failure_class = ?,
                    error_summary = ?, completed_at = ?
                WHERE attempt_id = ? AND job_id = ?
                """,
                (
                    attempt_state,
                    result.worker_pid,
                    result.process_group_id,
                    completed_at,
                    result.attempt_path,
                    result.exit_code,
                    result.outcome,
                    result.artifact_manifest_sha256,
                    result.failure_class,
                    result.message,
                    completed_at,
                    attempt_id,
                    job_id,
                ),
            )
            connection.execute(
                """
                UPDATE jobs SET state = ?, outcome = ?, active_attempt_id = NULL,
                    result_run_id = ?, result_artifact_path = ?,
                    failure_class = ?, error_summary = ?, completed_at = ?,
                    updated_at = ? WHERE job_id = ?
                """,
                (
                    state,
                    outcome,
                    result.run_id,
                    result.canonical_artifact_path,
                    failure_class,
                    error_summary,
                    completed_at,
                    completed_at,
                    job_id,
                ),
            )
            self._append_event(
                connection,
                job_id=job_id,
                event_type=outcome,
                stage="completed",
                detail={
                    "attempt_id": attempt_id,
                    "run_id": result.run_id,
                    "failure_class": failure_class,
                    "message": error_summary,
                },
                created_at=completed_at,
            )
            final = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            connection.commit()
            assert final is not None
            return _record(final)
        except (sqlite3.Error, RequestError) as error:
            connection.rollback()
            if isinstance(error, RequestError):
                raise
            raise CatalogError(f"cannot finish job attempt: {error}") from error
        finally:
            connection.close()

    def request_cancel(self, job_id: str) -> JobRecord:
        now = isoformat_z()
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("job was not found")
            state = str(row["state"])
            if state == "queued":
                connection.execute(
                    """
                    UPDATE jobs SET state = 'cancelled', outcome = 'cancelled',
                        cancellation_requested = 1, completed_at = ?, updated_at = ?
                    WHERE job_id = ?
                    """,
                    (now, now, job_id),
                )
                next_state = "cancelled"
            elif state in {"starting", "running"}:
                connection.execute(
                    """
                    UPDATE jobs SET state = 'cancelling',
                        cancellation_requested = 1, updated_at = ? WHERE job_id = ?
                    """,
                    (now, job_id),
                )
                next_state = "cancelling"
            else:
                connection.commit()
                return _record(row)
            self._append_event(
                connection,
                job_id=job_id,
                event_type="cancellation_requested",
                stage=next_state,
                created_at=now,
            )
            final = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            connection.commit()
            assert final is not None
            return _record(final)
        except (sqlite3.Error, NotFoundError) as error:
            connection.rollback()
            if isinstance(error, NotFoundError):
                raise
            raise CatalogError(f"cannot cancel job: {error}") from error
        finally:
            connection.close()

    def retry(self, job_id: str) -> JobRecord:
        now = isoformat_z()
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("job was not found")
            if str(row["state"]) not in {"failed", "interrupted"}:
                raise RequestError("only failed or interrupted jobs may be retried")
            connection.execute(
                """
                UPDATE jobs SET state = 'queued', outcome = NULL,
                    queue_reason = NULL, retry_count = retry_count + 1,
                    cancellation_requested = 0, active_attempt_id = NULL,
                    failure_class = NULL, error_summary = NULL, queued_at = ?,
                    completed_at = NULL, updated_at = ? WHERE job_id = ?
                """,
                (now, now, job_id),
            )
            self._append_event(
                connection,
                job_id=job_id,
                event_type="retry_queued",
                stage="queued",
                created_at=now,
            )
            final = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            connection.commit()
            assert final is not None
            return _record(final)
        except (sqlite3.Error, NotFoundError, RequestError) as error:
            connection.rollback()
            if isinstance(error, (NotFoundError, RequestError)):
                raise
            raise CatalogError(f"cannot retry job: {error}") from error
        finally:
            connection.close()

    def projection_repaired(self, job_id: str) -> JobRecord:
        now = isoformat_z()
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("job was not found")
            if not (
                str(row["state"]) == "failed"
                and str(row["outcome"]) == "published_projection_failed"
                and row["result_run_id"] is not None
                and row["result_artifact_path"] is not None
            ):
                raise RequestError("job does not have a repairable catalog projection")
            connection.execute(
                """
                UPDATE jobs SET state = 'succeeded', outcome = 'projection_repaired',
                    failure_class = NULL, error_summary = NULL, updated_at = ?
                WHERE job_id = ?
                """,
                (now, job_id),
            )
            self._append_event(
                connection,
                job_id=job_id,
                event_type="projection_repaired",
                stage="completed",
                detail={"run_id": str(row["result_run_id"])},
                created_at=now,
            )
            final = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            connection.commit()
            assert final is not None
            return _record(final)
        except (sqlite3.Error, NotFoundError, RequestError) as error:
            connection.rollback()
            if isinstance(error, (NotFoundError, RequestError)):
                raise
            raise CatalogError(f"cannot record projection repair: {error}") from error
        finally:
            connection.close()

    def schedule_automatic_retry(
        self, job_id: str, *, delay_seconds: float = 1.0
    ) -> JobRecord:
        now = datetime.now(UTC)
        queued_at = isoformat_z(now + timedelta(seconds=max(0.0, delay_seconds)))
        updated_at = isoformat_z(now)
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("job was not found")
            if str(row["state"]) != "failed" or int(row["automatic_retry_count"]) >= 1:
                connection.commit()
                return _record(row)
            connection.execute(
                """
                UPDATE jobs SET state = 'queued', outcome = NULL,
                    queue_reason = 'delayed automatic retry',
                    automatic_retry_count = automatic_retry_count + 1,
                    active_attempt_id = NULL, failure_class = NULL,
                    error_summary = NULL, queued_at = ?, completed_at = NULL,
                    updated_at = ? WHERE job_id = ?
                """,
                (queued_at, updated_at, job_id),
            )
            self._append_event(
                connection,
                job_id=job_id,
                event_type="automatic_retry_queued",
                stage="queued",
                detail={"not_before": queued_at},
                created_at=updated_at,
            )
            final = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            connection.commit()
            assert final is not None
            return _record(final)
        except (sqlite3.Error, NotFoundError) as error:
            connection.rollback()
            if isinstance(error, NotFoundError):
                raise
            raise CatalogError(f"cannot schedule automatic retry: {error}") from error
        finally:
            connection.close()

    def acquire_lease(
        self,
        scheduler_instance_id: str,
        *,
        stale_after_seconds: float,
    ) -> bool:
        now = isoformat_z()
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM scheduler_lease WHERE singleton = 1"
            ).fetchone()
            if row is None:
                raise CatalogError("scheduler lease row is missing")
            owner = row["scheduler_instance_id"]
            heartbeat = row["heartbeat_at"]
            stale = (
                heartbeat is None
                or (datetime.now(UTC) - _utc(str(heartbeat))).total_seconds()
                > stale_after_seconds
            )
            if owner not in {None, scheduler_instance_id} and not stale:
                connection.rollback()
                return False
            connection.execute(
                """
                UPDATE scheduler_lease SET scheduler_instance_id = ?,
                    acquired_at = CASE WHEN scheduler_instance_id = ?
                                       THEN acquired_at ELSE ? END,
                    heartbeat_at = ? WHERE singleton = 1
                """,
                (scheduler_instance_id, scheduler_instance_id, now, now),
            )
            connection.commit()
            return True
        except (sqlite3.Error, ValueError) as error:
            connection.rollback()
            if isinstance(error, CatalogError):
                raise
            raise CatalogError(f"cannot acquire scheduler lease: {error}") from error
        finally:
            connection.close()

    def heartbeat_lease(self, scheduler_instance_id: str) -> bool:
        connection = self.database.connect()
        try:
            cursor = connection.execute(
                """
                UPDATE scheduler_lease SET heartbeat_at = ?
                WHERE singleton = 1 AND scheduler_instance_id = ?
                """,
                (isoformat_z(), scheduler_instance_id),
            )
            connection.commit()
            return cursor.rowcount == 1
        finally:
            connection.close()

    def release_lease(self, scheduler_instance_id: str) -> None:
        connection = self.database.connect()
        try:
            connection.execute(
                """
                UPDATE scheduler_lease SET scheduler_instance_id = NULL,
                    acquired_at = NULL, heartbeat_at = NULL
                WHERE singleton = 1 AND scheduler_instance_id = ?
                """,
                (scheduler_instance_id,),
            )
            connection.commit()
        finally:
            connection.close()

    def active_jobs(self) -> list[JobRecord]:
        return self.list(states=("starting", "running", "cancelling"), limit=200)[0]

    def counts(self) -> JobCountRecord:
        connection = self.database.connect(readonly=True)
        try:
            row = connection.execute(
                """
                SELECT SUM(CASE WHEN state = 'queued' THEN 1 ELSE 0 END) AS queued,
                       SUM(CASE WHEN state IN ('starting', 'running', 'cancelling')
                                THEN 1 ELSE 0 END) AS active,
                       SUM(CASE WHEN state IN ('failed', 'interrupted')
                                THEN 1 ELSE 0 END) AS failed
                FROM jobs
                """
            ).fetchone()
        finally:
            connection.close()
        assert row is not None
        return JobCountRecord(
            queued=int(row["queued"] or 0),
            active=int(row["active"] or 0),
            failed=int(row["failed"] or 0),
        )

    def queue_state(self) -> QueueStateRecord:
        connection = self.database.connect(readonly=True)
        try:
            row = connection.execute(
                "SELECT * FROM scheduler_lease WHERE singleton = 1"
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise CatalogError("scheduler lease row is missing")
        return QueueStateRecord(
            paused=bool(row["queue_paused"]),
            scheduler_instance_id=(
                str(row["scheduler_instance_id"])
                if row["scheduler_instance_id"] is not None
                else None
            ),
            acquired_at=(
                str(row["acquired_at"]) if row["acquired_at"] is not None else None
            ),
            heartbeat_at=(
                str(row["heartbeat_at"]) if row["heartbeat_at"] is not None else None
            ),
        )

    def set_queue_paused(self, paused: bool) -> QueueStateRecord:
        connection = self.database.connect()
        try:
            connection.execute(
                "UPDATE scheduler_lease SET queue_paused = ? WHERE singleton = 1",
                (int(paused),),
            )
            connection.commit()
        except sqlite3.Error as error:
            connection.rollback()
            raise CatalogError(
                f"cannot update scheduler queue state: {error}"
            ) from error
        finally:
            connection.close()
        return self.queue_state()

    def interrupt(self, job_id: str, *, detail: str) -> JobRecord:
        now = isoformat_z()
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("job was not found")
            if str(row["state"]) not in {"starting", "running", "cancelling"}:
                connection.commit()
                return _record(row)
            attempt_id = row["active_attempt_id"]
            if attempt_id is not None:
                connection.execute(
                    """
                    UPDATE job_attempts SET state = 'interrupted',
                        failure_class = 'scheduler_recovery', error_summary = ?,
                        completed_at = ? WHERE attempt_id = ?
                    """,
                    (detail[:1_000], now, attempt_id),
                )
            connection.execute(
                """
                UPDATE jobs SET state = 'interrupted', outcome = 'interrupted',
                    active_attempt_id = NULL, failure_class = 'scheduler_recovery',
                    error_summary = ?, completed_at = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (detail[:1_000], now, now, job_id),
            )
            self._append_event(
                connection,
                job_id=job_id,
                event_type="recovered_interruption",
                stage="interrupted",
                detail={"message": detail[:1_000]},
                created_at=now,
            )
            final = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            connection.commit()
            assert final is not None
            return _record(final)
        except (sqlite3.Error, NotFoundError) as error:
            connection.rollback()
            if isinstance(error, NotFoundError):
                raise
            raise CatalogError(f"cannot reconcile interrupted job: {error}") from error
        finally:
            connection.close()

    def active_attempts(self) -> list[ActiveAttemptRecord]:
        connection = self.database.connect(readonly=True)
        try:
            rows = connection.execute(
                """
                SELECT job_id, attempt_id, worker_pid, process_group_id,
                       heartbeat_at, deadline_at
                FROM job_attempts
                WHERE state IN ('starting', 'running')
                ORDER BY started_at
                """
            ).fetchall()
        finally:
            connection.close()
        return [
            ActiveAttemptRecord(
                job_id=str(row["job_id"]),
                attempt_id=str(row["attempt_id"]),
                worker_pid=(
                    int(row["worker_pid"]) if row["worker_pid"] is not None else None
                ),
                process_group_id=(
                    int(row["process_group_id"])
                    if row["process_group_id"] is not None
                    else None
                ),
                heartbeat_at=(
                    str(row["heartbeat_at"])
                    if row["heartbeat_at"] is not None
                    else None
                ),
                deadline_at=str(row["deadline_at"]),
            )
            for row in rows
        ]

    def fail_claimed(
        self,
        *,
        job_id: str,
        attempt_id: str,
        failure_class: str,
        detail: str,
    ) -> JobRecord:
        now = isoformat_z()
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT state FROM jobs WHERE job_id = ? AND active_attempt_id = ?",
                (job_id, attempt_id),
            ).fetchone()
            if row is None or str(row["state"]) not in {
                "starting",
                "running",
                "cancelling",
            }:
                raise RequestError("job is not awaiting this attempt failure")
            connection.execute(
                """
                UPDATE job_attempts SET state = 'failed', failure_class = ?,
                    error_summary = ?, completed_at = ? WHERE attempt_id = ?
                """,
                (failure_class, detail[:1_000], now, attempt_id),
            )
            connection.execute(
                """
                UPDATE jobs SET state = 'failed', outcome = 'failed',
                    active_attempt_id = NULL, failure_class = ?,
                    error_summary = ?, completed_at = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (failure_class, detail[:1_000], now, now, job_id),
            )
            self._append_event(
                connection,
                job_id=job_id,
                event_type="failed",
                stage="completed",
                detail={"failure_class": failure_class, "message": detail[:1_000]},
                created_at=now,
            )
            final = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            connection.commit()
            assert final is not None
            return _record(final)
        except (sqlite3.Error, RequestError) as error:
            connection.rollback()
            if isinstance(error, RequestError):
                raise
            raise CatalogError(
                f"cannot persist claimed job failure: {error}"
            ) from error
        finally:
            connection.close()

    def reconcile_published(
        self,
        job_id: str,
        *,
        run_id: str,
        artifact_path: str,
        projection_failure: str | None = None,
    ) -> JobRecord:
        now = isoformat_z()
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("job was not found")
            if str(row["state"]) not in {"starting", "running", "cancelling"}:
                connection.commit()
                return _record(row)
            failed = projection_failure is not None
            state = "failed" if failed else "succeeded"
            outcome = "published_projection_failed" if failed else "recovered_published"
            attempt_id = row["active_attempt_id"]
            if attempt_id is not None:
                connection.execute(
                    """
                    UPDATE job_attempts SET state = ?, heartbeat_at = ?,
                        publication_outcome = ?, failure_class = ?,
                        error_summary = ?, completed_at = ? WHERE attempt_id = ?
                    """,
                    (
                        "failed" if failed else "succeeded",
                        now,
                        outcome,
                        "projection_failed" if failed else None,
                        projection_failure[:1_000] if projection_failure else None,
                        now,
                        attempt_id,
                    ),
                )
            connection.execute(
                """
                UPDATE jobs SET state = ?, outcome = ?, active_attempt_id = NULL,
                    result_run_id = ?, result_artifact_path = ?,
                    failure_class = ?, error_summary = ?, completed_at = ?,
                    updated_at = ? WHERE job_id = ?
                """,
                (
                    state,
                    outcome,
                    run_id,
                    artifact_path,
                    "projection_failed" if failed else None,
                    projection_failure[:1_000] if projection_failure else None,
                    now,
                    now,
                    job_id,
                ),
            )
            self._append_event(
                connection,
                job_id=job_id,
                event_type=outcome,
                stage="recovered",
                detail={"run_id": run_id, "message": projection_failure},
                created_at=now,
            )
            final = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            connection.commit()
            assert final is not None
            return _record(final)
        except (sqlite3.Error, NotFoundError) as error:
            connection.rollback()
            if isinstance(error, NotFoundError):
                raise
            raise CatalogError(f"cannot reconcile published job: {error}") from error
        finally:
            connection.close()

    def integrity_failure(self, job_id: str, *, detail: str) -> JobRecord:
        now = isoformat_z()
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("job was not found")
            if str(row["state"]) != "succeeded":
                connection.commit()
                return _record(row)
            connection.execute(
                """
                UPDATE jobs SET state = 'failed', outcome = 'integrity_failed',
                    failure_class = 'artifact_integrity', error_summary = ?,
                    updated_at = ? WHERE job_id = ?
                """,
                (detail[:1_000], now, job_id),
            )
            self._append_event(
                connection,
                job_id=job_id,
                event_type="integrity_failed",
                stage="recovered",
                detail={"message": detail[:1_000]},
                created_at=now,
            )
            final = connection.execute(
                "SELECT * FROM jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            connection.commit()
            assert final is not None
            return _record(final)
        except (sqlite3.Error, NotFoundError) as error:
            connection.rollback()
            if isinstance(error, NotFoundError):
                raise
            raise CatalogError(
                f"cannot record job integrity failure: {error}"
            ) from error
        finally:
            connection.close()
