"""Per-library durable scheduler with process locking and bounded resources."""

from __future__ import annotations

import os
import signal
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from doc_evidence.adapters.local_jobs import LocalExtractionJobs
from doc_evidence.application.jobs import ClaimedJob
from doc_evidence.errors import DocEvidenceError
from doc_evidence.extractor_registry import ResourceClass

TRANSIENT_FAILURES = frozenset(
    {"worker_launch_failed", "timeout", "OSError", "unexpected_scheduler_error"}
)


@dataclass(frozen=True)
class ResourceLimits:
    light: int = 2
    ocr: int = 1
    model_heavy: int = 1

    def value(self, resource_class: ResourceClass) -> int:
        return {
            "light": self.light,
            "ocr": self.ocr,
            "model_heavy": self.model_heavy,
        }[resource_class]


class LibraryProcessLock:
    """Advisory one-scheduler lock retained for the scheduler lifetime."""

    def __init__(self, path: Path):
        self.path = path
        self._handle: BinaryIO | None = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        try:
            if os.name == "posix":
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                import msvcrt

                handle.seek(0)
                handle.write(b"\0")
                handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except (OSError, BlockingIOError):
            handle.close()
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        try:
            if os.name == "posix":
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            else:
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            handle.close()
            self._handle = None


@dataclass
class _Running:
    thread: threading.Thread
    cancel: threading.Event
    resource_class: ResourceClass


class LibraryScheduler:
    """Claim bounded work from SQLite; in-memory state is only active handles."""

    def __init__(
        self,
        application: LocalExtractionJobs,
        *,
        resource_limits: ResourceLimits | None = None,
        poll_seconds: float = 0.1,
        heartbeat_seconds: float = 1.0,
        lease_stale_seconds: float = 10.0,
    ):
        self.application = application
        self.repository = application.repository
        self.resource_limits = resource_limits or ResourceLimits()
        self.poll_seconds = poll_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.lease_stale_seconds = lease_stale_seconds
        self.instance_id = str(uuid.uuid4())
        self.process_lock = LibraryProcessLock(
            application.config.filesystem_store / ".doc-evidence-scheduler.lock"
        )
        self._stop = threading.Event()
        self._state_lock = threading.Lock()
        self._running: dict[str, _Running] = {}
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> bool:
        if self.running:
            return True
        if not self.process_lock.acquire():
            return False
        if not self.repository.acquire_lease(
            self.instance_id,
            stale_after_seconds=self.lease_stale_seconds,
        ):
            self.process_lock.release()
            return False
        self._stop.clear()
        self._terminate_recovered_processes()
        self.application.reconcile()
        self._thread = threading.Thread(
            target=self._loop,
            name=f"doc-evidence-scheduler-{self.application.library_id}",
            daemon=True,
        )
        self._thread.start()
        return True

    @staticmethod
    def _group_alive(process_group_id: int) -> bool:
        if os.name != "posix":
            return False
        try:
            os.killpg(process_group_id, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    def _terminate_recovered_processes(self) -> None:
        if os.name != "posix":
            return
        groups = {
            item.process_group_id
            for item in self.repository.active_attempts()
            if item.process_group_id is not None
        }
        groups.update(self.application.recovered_process_groups())
        for group in groups:
            try:
                os.killpg(group, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                continue
        deadline = time.monotonic() + 1.0
        while groups and time.monotonic() < deadline:
            groups = {group for group in groups if self._group_alive(group)}
            if groups:
                time.sleep(0.02)
        for group in groups:
            try:
                os.killpg(group, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                continue

    def _free_classes(self) -> set[ResourceClass]:
        counts: dict[ResourceClass, int] = {"light": 0, "ocr": 0, "model_heavy": 0}
        with self._state_lock:
            for running in self._running.values():
                counts[running.resource_class] += 1
        return {
            resource_class
            for resource_class, count in counts.items()
            if count < self.resource_limits.value(resource_class)
        }

    def _dispatch(self) -> None:
        while not self._stop.is_set():
            free = self._free_classes()
            if not free:
                return
            claimed = self.repository.claim_next(
                scheduler_instance_id=self.instance_id,
                resource_classes=free,
            )
            if claimed is None:
                return
            cancel = threading.Event()
            thread = threading.Thread(
                target=self._run_claimed,
                args=(claimed, cancel),
                name=f"doc-evidence-job-{claimed.job.job_id}",
                daemon=True,
            )
            with self._state_lock:
                self._running[claimed.job.job_id] = _Running(
                    thread=thread,
                    cancel=cancel,
                    resource_class=claimed.job.resource_class,
                )
            thread.start()

    def _run_claimed(self, claimed: ClaimedJob, cancel: threading.Event) -> None:
        try:
            completed = self.application.execute_claimed(claimed, cancel=cancel)
            if (
                completed.state == "failed"
                and completed.failure_class in TRANSIENT_FAILURES
                and completed.automatic_retry_count == 0
            ):
                self.repository.schedule_automatic_retry(completed.job_id)
        except Exception as error:  # noqa: BLE001 - scheduler must close durable state
            try:
                self.repository.fail_claimed(
                    job_id=claimed.job.job_id,
                    attempt_id=claimed.attempt_id,
                    failure_class=(
                        "application_error"
                        if isinstance(error, DocEvidenceError)
                        else "unexpected_scheduler_error"
                    ),
                    detail=str(error),
                )
            except DocEvidenceError:
                pass
        finally:
            with self._state_lock:
                self._running.pop(claimed.job.job_id, None)

    def _propagate_cancellation(self) -> None:
        with self._state_lock:
            running = list(self._running.items())
        for job_id, active in running:
            try:
                job = self.repository.get(job_id)
            except DocEvidenceError:
                continue
            if job.cancellation_requested or job.state == "cancelling":
                active.cancel.set()

    def _loop(self) -> None:
        last_heartbeat = 0.0
        try:
            while not self._stop.is_set():
                now = time.monotonic()
                if now - last_heartbeat >= self.heartbeat_seconds:
                    if not self.repository.heartbeat_lease(self.instance_id):
                        self._stop.set()
                        break
                    last_heartbeat = now
                self._propagate_cancellation()
                self._dispatch()
                self._stop.wait(self.poll_seconds)
        finally:
            self._propagate_cancellation()

    def cancel(self, job_id: str) -> None:
        self.application.cancel(job_id)
        with self._state_lock:
            active = self._running.get(job_id)
        if active is not None:
            active.cancel.set()

    def stop(self, *, timeout_seconds: float = 15.0) -> None:
        self._stop.set()
        with self._state_lock:
            running = list(self._running.items())
        for job_id, active in running:
            try:
                self.application.cancel(job_id)
            except DocEvidenceError:
                pass
            active.cancel.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=min(timeout_seconds, 5.0))
        deadline = time.monotonic() + timeout_seconds
        for _job_id, active in running:
            remaining = max(0.0, deadline - time.monotonic())
            active.thread.join(timeout=remaining)
        self.repository.release_lease(self.instance_id)
        self.process_lock.release()
        self._thread = None
