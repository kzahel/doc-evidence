"""Common Phase 2 extraction result, cache, and subprocess helpers."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from doc_evidence.errors import DependencyError
from doc_evidence.util import (
    atomic_write_json,
    atomic_write_text,
    hash_json,
    isoformat_z,
    non_whitespace_character_count,
)

NORMALIZED_EXTRACTION_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class NormalizedPage:
    page_number: int
    text: str
    character_count: int
    non_whitespace_character_count: int

    def value(self) -> dict[str, object]:
        return {
            "page_number": self.page_number,
            "text": self.text,
            "character_count": self.character_count,
            "non_whitespace_character_count": self.non_whitespace_character_count,
        }


@dataclass(frozen=True)
class ExtractionResult:
    extractor_id: str
    run_id: str
    run_key: str
    artifact_path: str
    status: str
    pages: tuple[NormalizedPage, ...]
    warnings: tuple[str, ...]
    cache_hit: bool
    runtime_seconds: float
    descriptor: dict[str, Any]
    raw_artifacts: dict[str, str]
    table_count: int | None = None

    @property
    def text(self) -> str:
        return "\f".join(page.text for page in self.pages)

    @property
    def page_count(self) -> int:
        return len(self.pages)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str
    runtime_seconds: float


def resolve_executable(
    name: str,
    explicit: str | None = None,
    repo_relative: str | None = None,
) -> str:
    candidates = [explicit]
    if repo_relative:
        candidates.append(str(Path(__file__).parents[2] / repo_relative))
    candidates.append(shutil.which(name))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).resolve())
    raise DependencyError(
        f"requested extractor requires {name!r}; install it or configure its path"
    )


def command_version(command: list[str], timeout_seconds: int = 60) -> str:
    result = run_command(command, timeout_seconds=timeout_seconds)
    combined = (result.stdout + "\n" + result.stderr).strip()
    return combined.splitlines()[0] if combined else "unknown"


def run_command(
    command: list[str],
    timeout_seconds: int,
    cleanup_process_group: bool = False,
) -> CommandResult:
    started = time.monotonic()
    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=cleanup_process_group,
        )
        raw_stdout, raw_stderr = process.communicate(timeout=timeout_seconds)
        stdout = raw_stdout.decode("utf-8", errors="replace")
        stderr = raw_stderr.decode("utf-8", errors="replace")
        returncode = process.returncode
    except OSError as error:
        stdout = ""
        stderr = str(error)
        returncode = 127
    except subprocess.TimeoutExpired as error:
        stdout = (error.stdout or b"").decode("utf-8", errors="replace")
        stderr = (error.stderr or b"").decode("utf-8", errors="replace")
        stderr += f"\ncommand timed out after {timeout_seconds} seconds"
        if process is not None:
            if cleanup_process_group:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            else:
                process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if cleanup_process_group:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    process.kill()
        returncode = 124
    finally:
        if cleanup_process_group and process is not None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    return CommandResult(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        runtime_seconds=time.monotonic() - started,
    )


def pages_from_text(
    text: str, expected_page_count: int | None = None
) -> tuple[NormalizedPage, ...]:
    parts = text.replace("\x00", "").split("\f")
    if parts and parts[-1] == "":
        parts.pop()
    if expected_page_count is not None and len(parts) < expected_page_count:
        parts.extend([""] * (expected_page_count - len(parts)))
    return tuple(
        NormalizedPage(
            page_number=index,
            text=part,
            character_count=len(part),
            non_whitespace_character_count=non_whitespace_character_count(part),
        )
        for index, part in enumerate(parts, start=1)
    )


def descriptor_identity(
    extractor_id: str, descriptor: dict[str, Any]
) -> tuple[str, str]:
    run_key = hash_json(
        {
            "schema_version": NORMALIZED_EXTRACTION_SCHEMA_VERSION,
            "extractor_id": extractor_id,
            **descriptor,
        }
    )
    return run_key, f"{extractor_id}:{run_key}"


def load_cached_result(
    run_dir: Path,
    store_root: Path,
    extractor_id: str,
    run_key: str,
) -> ExtractionResult | None:
    run_path = run_dir / "run.json"
    normalized_path = run_dir / "normalized.json"
    if not (run_path.is_file() and normalized_path.is_file()):
        return None
    try:
        run = json.loads(run_path.read_text(encoding="utf-8"))
        normalized = json.loads(normalized_path.read_text(encoding="utf-8"))
        if run.get("status") != "ok" or run.get("run_key") != run_key:
            return None
        pages = tuple(
            NormalizedPage(
                page_number=int(row["page_number"]),
                text=str(row["text"]),
                character_count=int(row["character_count"]),
                non_whitespace_character_count=int(
                    row["non_whitespace_character_count"]
                ),
            )
            for row in normalized["pages"]
        )
        return ExtractionResult(
            extractor_id=extractor_id,
            run_id=run["run_id"],
            run_key=run_key,
            artifact_path=run_dir.relative_to(store_root).as_posix(),
            status="ok",
            pages=pages,
            warnings=tuple(run.get("warnings", [])),
            cache_hit=True,
            runtime_seconds=float(run.get("runtime_seconds", 0.0)),
            descriptor=run["descriptor"],
            raw_artifacts=run.get("raw_artifacts", {}),
            table_count=normalized.get("table_count"),
        )
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ):
        return None


def save_result(
    *,
    run_dir: Path,
    store_root: Path,
    extractor_id: str,
    run_id: str,
    run_key: str,
    source_sha256: str,
    descriptor: dict[str, Any],
    status: str,
    pages: tuple[NormalizedPage, ...],
    warnings: list[str],
    runtime_seconds: float,
    raw_artifacts: dict[str, str],
    table_count: int | None = None,
    started_at: str | None = None,
) -> ExtractionResult:
    started = started_at or isoformat_z()
    completed = isoformat_z()
    atomic_write_json(
        run_dir / "normalized.json",
        {
            "schema_version": NORMALIZED_EXTRACTION_SCHEMA_VERSION,
            "extractor_id": extractor_id,
            "source_sha256": source_sha256,
            "page_count": len(pages),
            "table_count": table_count,
            "pages": [page.value() for page in pages],
        },
    )
    atomic_write_text(run_dir / "text.txt", "\f".join(page.text for page in pages))
    atomic_write_json(
        run_dir / "run.json",
        {
            "schema_version": NORMALIZED_EXTRACTION_SCHEMA_VERSION,
            "extractor_id": extractor_id,
            "run_id": run_id,
            "run_key": run_key,
            "source_sha256": source_sha256,
            "started_at": started,
            "completed_at": completed,
            "status": status,
            "runtime_seconds": runtime_seconds,
            "descriptor": descriptor,
            "warnings": warnings,
            "raw_artifacts": raw_artifacts,
        },
    )
    return ExtractionResult(
        extractor_id=extractor_id,
        run_id=run_id,
        run_key=run_key,
        artifact_path=run_dir.relative_to(store_root).as_posix(),
        status=status,
        pages=pages,
        warnings=tuple(warnings),
        cache_hit=False,
        runtime_seconds=runtime_seconds,
        descriptor=descriptor,
        raw_artifacts=raw_artifacts,
        table_count=table_count,
    )
