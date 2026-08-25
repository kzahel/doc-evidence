"""Supervised extraction attempts and validated atomic artifact publication."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from doc_evidence.errors import RequestError
from doc_evidence.extractor_registry import ExtractorExecution
from doc_evidence.util import (
    atomic_write_json,
    hash_file,
    hash_json,
    isoformat_z,
)
from doc_evidence.windows_job import WindowsJob

ATTEMPT_SCHEMA_VERSION = 1
WORKER_PROTOCOL_VERSION = 2
DEFAULT_LOG_LIMIT_BYTES = 1_000_000
DEFAULT_MINIMUM_FREE_BYTES = 64 * 1024 * 1024
DEFAULT_WORKER_LAUNCH_TIMEOUT_SECONDS = 30.0
WINDOWS_WORKER_LAUNCH_FAILED_EXIT = 125

AttemptOutcome = Literal[
    "executed",
    "concurrent_cache_win",
    "verified_cache_match",
    "nondeterministic",
    "failed",
    "cancelled",
    "timeout",
]


class _HandledWorkerFailureError(Exception):
    pass


@dataclass(frozen=True)
class AttemptPlan:
    attempt_id: str
    execution: ExtractorExecution
    expected_run_id: str
    expected_run_key: str
    source_path: Path
    source_sha256: str
    expected_size_bytes: int
    expected_modified_ns: int
    store_root: Path
    blob_dir: Path
    extraction_config_hash: str
    fresh_verification: bool = False


@dataclass(frozen=True)
class AttemptUpdate:
    attempt_id: str
    stage: str
    worker_pid: int | None
    heartbeat_at: str


@dataclass(frozen=True)
class AttemptResult:
    attempt_id: str
    extractor_id: str
    outcome: AttemptOutcome
    run_id: str | None
    run_key: str | None
    canonical_artifact_path: str | None
    attempt_path: str
    worker_pid: int | None
    process_group_id: int | None
    exit_code: int | None
    started_at: str
    completed_at: str
    runtime_seconds: float
    stdout_truncated_bytes: int
    stderr_truncated_bytes: int
    artifact_manifest_sha256: str | None
    failure_class: str | None
    message: str | None

    def value(self) -> dict[str, object]:
        return {
            "schema_version": ATTEMPT_SCHEMA_VERSION,
            **self.__dict__,
        }


@dataclass
class _DrainState:
    retained_bytes: int = 0
    truncated_bytes: int = 0


def _drain(
    stream: Any,
    path: Path,
    limit_bytes: int,
    state: _DrainState,
) -> None:
    with path.open("wb") as output:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                break
            remaining = max(0, limit_bytes - state.retained_bytes)
            if remaining:
                retained = chunk[:remaining]
                output.write(retained)
                state.retained_bytes += len(retained)
            state.truncated_bytes += max(0, len(chunk) - remaining)
        output.flush()
        os.fsync(output.fileno())


def _safe_tree_manifest(run_dir: Path) -> dict[str, dict[str, object]]:
    manifest: dict[str, dict[str, object]] = {}
    for path in sorted(run_dir.rglob("*")):
        if path.is_symlink():
            raise ValueError("artifact output contains a symbolic link")
        if not path.is_file():
            continue
        relative = path.relative_to(run_dir).as_posix()
        hashed = hash_file(path)
        manifest[relative] = {
            "sha256": hashed.content_sha256,
            "size_bytes": hashed.size_bytes,
        }
    return manifest


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain an object")
    return value


def _validate_raw_artifacts(run_dir: Path, run: dict[str, Any]) -> None:
    raw = run.get("raw_artifacts", run.get("raw_outputs", {}))
    if not isinstance(raw, dict):
        raise TypeError("run raw artifact map is invalid")
    resolved_run = run_dir.resolve()
    for value in raw.values():
        if not isinstance(value, str) or not value:
            raise ValueError("run raw artifact path is invalid")
        target = (run_dir / value).resolve()
        if not target.is_relative_to(resolved_run) or not target.exists():
            raise ValueError("run raw artifact is missing or outside the run")


def validate_run(
    run_dir: Path,
    *,
    extractor_id: str,
    source_sha256: str,
    run_key: str,
) -> dict[str, dict[str, object]]:
    resolved = run_dir.resolve()
    if not resolved.is_dir():
        raise ValueError("staged run directory is missing")
    run = _read_json(resolved / "run.json")
    if (
        run.get("status") != "ok"
        or run.get("run_key") != run_key
        or run.get("source_sha256") != source_sha256
        or run.get("run_id") != f"{extractor_id}:{run_key}"
    ):
        raise ValueError("run completion identity or status is invalid")
    _validate_raw_artifacts(resolved, run)
    if extractor_id == "poppler":
        pages = json.loads((resolved / "pages.json").read_text(encoding="utf-8"))
        text = (resolved / "text.txt").read_text(encoding="utf-8")
        if not isinstance(pages, list):
            raise ValueError("Poppler page index is invalid")
        previous_end = 0
        for expected_page, row in enumerate(pages, start=1):
            if not isinstance(row, dict) or row.get("page_number") != expected_page:
                raise ValueError("Poppler page numbering is invalid")
            start = row.get("start_offset")
            end = row.get("end_offset")
            if (
                not isinstance(start, int)
                or not isinstance(end, int)
                or start < previous_end
                or end < start
                or end > len(text)
            ):
                raise ValueError("Poppler page offsets are invalid")
            previous_end = end
    else:
        normalized = _read_json(resolved / "normalized.json")
        if (
            normalized.get("source_sha256") != source_sha256
            or normalized.get("extractor_id") != extractor_id
        ):
            raise ValueError("normalized output identity is invalid")
        pages = normalized.get("pages")
        if not isinstance(pages, list):
            raise ValueError("normalized pages are invalid")
        for expected_page, page in enumerate(pages, start=1):
            if (
                not isinstance(page, dict)
                or page.get("page_number") != expected_page
                or not isinstance(page.get("text"), str)
                or not isinstance(page.get("character_count"), int)
                or not isinstance(page.get("non_whitespace_character_count"), int)
            ):
                raise ValueError("normalized page contract is invalid")
    manifest = _safe_tree_manifest(resolved)
    if "run.json" not in manifest or "text.txt" not in manifest:
        raise ValueError("run is missing required canonical files")
    return manifest


def _comparison_identity(
    run_dir: Path,
    manifest: dict[str, dict[str, object]],
) -> str:
    """Exclude attempt-time bookkeeping and logs from deterministic output."""

    run = _read_json(run_dir / "run.json")
    sanitized_run = {
        key: value
        for key, value in run.items()
        if key not in {"started_at", "completed_at", "runtime_seconds"}
    }
    raw = run.get("raw_artifacts", run.get("raw_outputs", {}))
    ignored: set[str] = set()
    if isinstance(raw, dict):
        for label, path in raw.items():
            if (
                isinstance(label, str)
                and isinstance(path, str)
                and any(
                    token in label.casefold() for token in ("stdout", "stderr", "log")
                )
            ):
                ignored.add(path.rstrip("/"))
    comparable = {
        path: identity
        for path, identity in manifest.items()
        if path != "run.json"
        and not any(
            path == ignored_path or path.startswith(ignored_path + "/")
            for ignored_path in ignored
        )
    }
    return hash_json({"run": sanitized_run, "files": comparable})


def _fsync_tree(root: Path) -> None:
    directories = [root]
    for path in sorted(root.rglob("*")):
        if path.is_file():
            with path.open("rb+") as source:
                os.fsync(source.fileno())
        elif path.is_dir():
            directories.append(path)
    if os.name == "posix":
        for directory in reversed(directories):
            descriptor = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)


def _signal_tree(
    process: subprocess.Popen[bytes],
    *,
    force: bool,
    windows_job: WindowsJob | None = None,
) -> None:
    if process.poll() is not None:
        return
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL if force else signal.SIGTERM)
        except ProcessLookupError:
            return
    elif windows_job is not None:
        windows_job.terminate(exit_code=1 if force else 2)
    elif force:
        process.kill()
    else:
        process.terminate()


def _cleanup_lingering_process_group(process_group_id: int | None) -> None:
    if os.name != "posix" or process_group_id is None:
        return
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except ProcessLookupError:
        return


def _read_worker_pid(path: Path) -> int | None:
    try:
        value = int(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, ValueError):
        return None
    return value if value > 0 else None


def _wait_for_launcher_ready(
    process: subprocess.Popen[bytes],
    ready_path: Path,
    timeout_seconds: float,
) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if ready_path.is_file():
            return True
        if process.poll() is not None:
            return False
        time.sleep(0.01)
    return False


class AttemptSupervisor:
    def __init__(
        self,
        *,
        worker_command: tuple[str, ...] | None = None,
        log_limit_bytes: int = DEFAULT_LOG_LIMIT_BYTES,
        minimum_free_bytes: int = DEFAULT_MINIMUM_FREE_BYTES,
        cancellation_grace_seconds: float = 5.0,
        heartbeat_seconds: float = 1.0,
        worker_launch_timeout_seconds: float = DEFAULT_WORKER_LAUNCH_TIMEOUT_SECONDS,
    ):
        self.worker_command = worker_command or (
            sys.executable,
            "-m",
            "doc_evidence.worker",
        )
        self.log_limit_bytes = log_limit_bytes
        self.minimum_free_bytes = minimum_free_bytes
        self.cancellation_grace_seconds = cancellation_grace_seconds
        self.heartbeat_seconds = heartbeat_seconds
        if worker_launch_timeout_seconds <= 0:
            raise ValueError("worker launch timeout must be positive")
        self.worker_launch_timeout_seconds = worker_launch_timeout_seconds

    def execute(
        self,
        plan: AttemptPlan,
        *,
        cancel: threading.Event | None = None,
        on_update: Callable[[AttemptUpdate], None] | None = None,
    ) -> AttemptResult:
        started_at = isoformat_z()
        started = time.monotonic()
        attempt_dir = plan.blob_dir / "attempts" / plan.attempt_id
        if attempt_dir.exists():
            raise RequestError("attempt identity already has a workspace")
        if not plan.blob_dir.resolve().is_relative_to(plan.store_root.resolve()):
            raise RequestError("attempt blob directory is outside the library store")
        if shutil.disk_usage(plan.store_root).free < self.minimum_free_bytes:
            raise RequestError("artifact store does not have enough free staging space")
        attempt_dir.mkdir(parents=True)
        request_path = attempt_dir / "request.json"
        response_path = attempt_dir / "response.json"
        atomic_write_json(
            request_path,
            {
                "protocol_version": WORKER_PROTOCOL_VERSION,
                "attempt_id": plan.attempt_id,
                "extractor_id": plan.execution.extractor_id,
                "expected_run_id": plan.expected_run_id,
                "expected_run_key": plan.expected_run_key,
                "settings": plan.execution.settings,
                "timeout_seconds": plan.execution.timeout_seconds,
                "source_path": str(plan.source_path.resolve()),
                "source_sha256": plan.source_sha256,
                "expected_size_bytes": plan.expected_size_bytes,
                "expected_modified_ns": plan.expected_modified_ns,
                "store_root": str(plan.store_root.resolve()),
                "blob_dir": str(plan.blob_dir.resolve()),
                "attempt_dir": str(attempt_dir.resolve()),
                "extraction_config_hash": plan.extraction_config_hash,
                "fresh_verification": plan.fresh_verification,
            },
        )
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        worker_command = [
            *self.worker_command,
            str(request_path),
            str(response_path),
        ]
        windows_job: WindowsJob | None = None
        gate_path = attempt_dir / "worker-launch.gate"
        launcher_ready_path = attempt_dir / "worker-launcher.ready"
        worker_pid_path = attempt_dir / "worker.pid"
        process: subprocess.Popen[bytes] | None = None
        windows_job_assigned = False
        try:
            if os.name == "nt":
                windows_job = WindowsJob.create()
                worker_command = [
                    sys.executable,
                    "-I",
                    "-B",
                    "-m",
                    "doc_evidence.windows_job_launcher",
                    str(gate_path.resolve()),
                    str(launcher_ready_path.resolve()),
                    str(worker_pid_path.resolve()),
                    *worker_command,
                ]
            process = subprocess.Popen(
                worker_command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=os.name == "posix",
                creationflags=flags,
            )
            if windows_job is not None:
                if not _wait_for_launcher_ready(
                    process,
                    launcher_ready_path,
                    self.worker_launch_timeout_seconds,
                ):
                    raise OSError(
                        "Windows worker launcher did not become ready within "
                        f"{self.worker_launch_timeout_seconds:g} seconds"
                    )
                windows_job.assign(process.pid)
                windows_job_assigned = True
                atomic_write_json(
                    gate_path,
                    {
                        "schema_version": 1,
                        "attempt_id": plan.attempt_id,
                    },
                )
            atomic_write_json(
                attempt_dir / "worker.json",
                {
                    "schema_version": 1,
                    "attempt_id": plan.attempt_id,
                    "worker_pid": process.pid if os.name == "posix" else None,
                    "launcher_pid": process.pid if os.name == "nt" else None,
                    "process_group_id": process.pid if os.name == "posix" else None,
                    "process_tree": (
                        "windows_job_kill_on_close"
                        if windows_job is not None
                        else "posix_process_group"
                    ),
                    "started_at": started_at,
                },
            )
        except OSError as error:
            if process is not None:
                _signal_tree(
                    process,
                    force=True,
                    windows_job=windows_job if windows_job_assigned else None,
                )
                process.wait(timeout=10)
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()
            if windows_job is not None:
                windows_job.close()
            completed_at = isoformat_z()
            result = AttemptResult(
                attempt_id=plan.attempt_id,
                extractor_id=plan.execution.extractor_id,
                outcome="failed",
                run_id=None,
                run_key=None,
                canonical_artifact_path=None,
                attempt_path=attempt_dir.relative_to(plan.store_root).as_posix(),
                worker_pid=(
                    process.pid
                    if process is not None and os.name == "posix"
                    else _read_worker_pid(worker_pid_path)
                ),
                process_group_id=(
                    process.pid if process is not None and os.name == "posix" else None
                ),
                exit_code=None,
                started_at=started_at,
                completed_at=completed_at,
                runtime_seconds=time.monotonic() - started,
                stdout_truncated_bytes=0,
                stderr_truncated_bytes=0,
                artifact_manifest_sha256=None,
                failure_class="worker_launch_failed",
                message=str(error)[:1_000],
            )
            atomic_write_json(attempt_dir / "attempt.json", result.value())
            if on_update is not None:
                on_update(
                    AttemptUpdate(
                        plan.attempt_id,
                        "failed",
                        None,
                        completed_at,
                    )
                )
            return result
        assert process is not None
        assert process.stdout is not None
        assert process.stderr is not None
        stdout_state = _DrainState()
        stderr_state = _DrainState()
        stdout_thread = threading.Thread(
            target=_drain,
            args=(
                process.stdout,
                attempt_dir / "worker.stdout.log",
                self.log_limit_bytes,
                stdout_state,
            ),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_drain,
            args=(
                process.stderr,
                attempt_dir / "worker.stderr.log",
                self.log_limit_bytes,
                stderr_state,
            ),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        process_group_id = process.pid if os.name == "posix" else None
        worker_pid = (
            process.pid if os.name == "posix" else _read_worker_pid(worker_pid_path)
        )
        outcome: AttemptOutcome = "failed"
        failure_class: str | None = None
        message: str | None = None
        run_id: str | None = None
        run_key: str | None = None
        canonical_path: str | None = None
        manifest_sha256: str | None = None
        last_heartbeat = 0.0
        if on_update is not None:
            on_update(
                AttemptUpdate(plan.attempt_id, "running", worker_pid, isoformat_z())
            )
        while process.poll() is None:
            now = time.monotonic()
            if worker_pid is None and os.name == "nt":
                worker_pid = _read_worker_pid(worker_pid_path)
                if now - started >= self.worker_launch_timeout_seconds:
                    outcome = "failed"
                    failure_class = "worker_launch_failed"
                    message = (
                        "Windows worker launcher did not report a worker process "
                        f"within {self.worker_launch_timeout_seconds:g} seconds"
                    )
                    _signal_tree(process, force=False, windows_job=windows_job)
                    break
            if cancel is not None and cancel.is_set():
                outcome = "cancelled"
                failure_class = "cancelled"
                message = "attempt cancellation was requested"
                _signal_tree(process, force=False, windows_job=windows_job)
                break
            if now - started >= plan.execution.timeout_seconds:
                outcome = "timeout"
                failure_class = "timeout"
                message = (
                    f"attempt exceeded {plan.execution.timeout_seconds} second deadline"
                )
                _signal_tree(process, force=False, windows_job=windows_job)
                break
            if on_update is not None and now - last_heartbeat >= self.heartbeat_seconds:
                on_update(
                    AttemptUpdate(
                        plan.attempt_id,
                        "running",
                        worker_pid,
                        isoformat_z(),
                    )
                )
                last_heartbeat = now
            time.sleep(0.05)
        if process.poll() is None:
            try:
                process.wait(timeout=self.cancellation_grace_seconds)
            except subprocess.TimeoutExpired:
                _signal_tree(process, force=True, windows_job=windows_job)
                process.wait(timeout=10)
        exit_code = process.returncode
        if worker_pid is None and os.name == "nt":
            worker_pid = _read_worker_pid(worker_pid_path)
        _cleanup_lingering_process_group(process_group_id)
        if windows_job is not None:
            windows_job.close()
        stdout_thread.join(timeout=10)
        stderr_thread.join(timeout=10)
        process.stdout.close()
        process.stderr.close()
        if outcome not in {"cancelled", "timeout"}:
            try:
                if (
                    os.name == "nt"
                    and (
                        exit_code == WINDOWS_WORKER_LAUNCH_FAILED_EXIT
                        or failure_class == "worker_launch_failed"
                    )
                    and not response_path.exists()
                ):
                    if failure_class is None:
                        failure_class = "worker_launch_failed"
                        message = "Windows worker launcher could not start the worker"
                    raise _HandledWorkerFailureError
                response = _read_json(response_path)
                if (
                    exit_code != 0
                    or response.get("protocol_version") != WORKER_PROTOCOL_VERSION
                    or response.get("status") != "ok"
                ):
                    failure_class = str(response.get("error_type", "worker_failed"))
                    message = str(response.get("message", "extraction worker failed"))[
                        :1_000
                    ]
                else:
                    response_run_id = str(response["run_id"])
                    response_run_key = str(response["run_key"])
                    if (
                        response_run_id != plan.expected_run_id
                        or response_run_key != plan.expected_run_key
                    ):
                        raise ValueError(
                            "worker result identity disagrees with the planned run"
                        )
                    run_id = response_run_id
                    run_key = response_run_key
                    staged = (
                        attempt_dir / "runs" / plan.execution.extractor_id / run_key
                    )
                    manifest = validate_run(
                        staged,
                        extractor_id=plan.execution.extractor_id,
                        source_sha256=plan.source_sha256,
                        run_key=run_key,
                    )
                    manifest_sha256 = hash_json(manifest)
                    staged_comparison = _comparison_identity(staged, manifest)
                    _fsync_tree(staged)
                    canonical = (
                        plan.blob_dir / "runs" / plan.execution.extractor_id / run_key
                    )
                    canonical.parent.mkdir(parents=True, exist_ok=True)
                    if canonical.exists():
                        existing = validate_run(
                            canonical,
                            extractor_id=plan.execution.extractor_id,
                            source_sha256=plan.source_sha256,
                            run_key=run_key,
                        )
                        existing_comparison = _comparison_identity(canonical, existing)
                        if existing_comparison == staged_comparison:
                            outcome = (
                                "verified_cache_match"
                                if plan.fresh_verification
                                else "concurrent_cache_win"
                            )
                        elif plan.fresh_verification:
                            outcome = "nondeterministic"
                            failure_class = "nondeterministic_output"
                            message = "fresh output disagrees with the canonical deterministic run"
                        else:
                            raise ValueError(
                                "canonical run conflicts with staged deterministic output"
                            )
                    else:
                        try:
                            staged.rename(canonical)
                        except OSError:
                            if not canonical.exists():
                                raise
                            existing = validate_run(
                                canonical,
                                extractor_id=plan.execution.extractor_id,
                                source_sha256=plan.source_sha256,
                                run_key=run_key,
                            )
                            if (
                                _comparison_identity(canonical, existing)
                                != staged_comparison
                            ):
                                raise ValueError(
                                    "concurrent canonical publication disagrees"
                                )
                            outcome = "concurrent_cache_win"
                        else:
                            _fsync_tree(canonical)
                            if os.name == "posix":
                                descriptor = os.open(canonical.parent, os.O_RDONLY)
                                try:
                                    os.fsync(descriptor)
                                finally:
                                    os.close(descriptor)
                            outcome = "executed"
                    canonical_path = canonical.relative_to(plan.store_root).as_posix()
            except _HandledWorkerFailureError:
                pass
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValueError,
            ) as error:
                outcome = "failed"
                failure_class = "validation_or_publication"
                message = str(error)[:1_000]
        completed_at = isoformat_z()
        if canonical_path is not None and outcome in {
            "executed",
            "concurrent_cache_win",
            "verified_cache_match",
        }:
            try:
                atomic_write_json(
                    attempt_dir / "publication.json",
                    {
                        "schema_version": 1,
                        "attempt_id": plan.attempt_id,
                        "outcome": outcome,
                        "run_id": run_id,
                        "run_key": run_key,
                        "canonical_artifact_path": canonical_path,
                        "completed_at": completed_at,
                    },
                )
            except OSError:
                pass
        result = AttemptResult(
            attempt_id=plan.attempt_id,
            extractor_id=plan.execution.extractor_id,
            outcome=outcome,
            run_id=run_id,
            run_key=run_key,
            canonical_artifact_path=canonical_path,
            attempt_path=attempt_dir.relative_to(plan.store_root).as_posix(),
            worker_pid=worker_pid,
            process_group_id=process_group_id,
            exit_code=exit_code,
            started_at=started_at,
            completed_at=completed_at,
            runtime_seconds=time.monotonic() - started,
            stdout_truncated_bytes=stdout_state.truncated_bytes,
            stderr_truncated_bytes=stderr_state.truncated_bytes,
            artifact_manifest_sha256=manifest_sha256,
            failure_class=failure_class,
            message=message,
        )
        atomic_write_json(attempt_dir / "attempt.json", result.value())
        if on_update is not None:
            on_update(
                AttemptUpdate(
                    plan.attempt_id,
                    outcome,
                    worker_pid,
                    completed_at,
                )
            )
        return result


@dataclass(frozen=True)
class AttemptCleanupResult:
    removed_attempt_ids: tuple[str, ...]
    removed_bytes: int
    retained_bytes: int


def _directory_size(path: Path) -> int:
    return sum(
        item.stat().st_size
        for item in path.rglob("*")
        if item.is_file() and not item.is_symlink()
    )


class AttemptRetention:
    """Separately bound completed attempt diagnostics by age and total bytes."""

    def cleanup(
        self,
        *,
        blob_dir: Path,
        active_attempt_ids: set[str],
        max_bytes: int,
        max_age_days: int,
        now: datetime | None = None,
    ) -> AttemptCleanupResult:
        if max_bytes < 0 or max_age_days < 0:
            raise RequestError("attempt retention bounds may not be negative")
        root = (blob_dir / "attempts").resolve()
        if not root.is_dir():
            return AttemptCleanupResult((), 0, 0)
        current = now or datetime.now(UTC)
        cutoff = current - timedelta(days=max_age_days)
        candidates: list[tuple[datetime, str, Path, int]] = []
        retained_bytes = 0
        for path in sorted(root.iterdir()):
            if (
                not path.is_dir()
                or path.is_symlink()
                or path.name in active_attempt_ids
                or not path.resolve().is_relative_to(root)
            ):
                continue
            record_path = path / "attempt.json"
            if not record_path.is_file():
                continue
            try:
                record = _read_json(record_path)
                completed = datetime.fromisoformat(str(record["completed_at"]))
                size = _directory_size(path)
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValueError,
            ):
                continue
            candidates.append((completed, path.name, path, size))
            retained_bytes += size
        removed: list[str] = []
        removed_bytes = 0
        for completed, attempt_id, path, size in sorted(candidates):
            if completed >= cutoff and retained_bytes <= max_bytes:
                continue
            shutil.rmtree(path)
            removed.append(attempt_id)
            removed_bytes += size
            retained_bytes -= size
        return AttemptCleanupResult(
            removed_attempt_ids=tuple(removed),
            removed_bytes=removed_bytes,
            retained_bytes=retained_bytes,
        )
