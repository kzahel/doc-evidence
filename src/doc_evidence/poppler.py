"""Versioned, cacheable Poppler metadata and embedded-text extraction."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from doc_evidence.errors import DependencyError
from doc_evidence.util import (
    atomic_write_json,
    atomic_write_text,
    compact_timestamp,
    hash_json,
    isoformat_z,
    non_whitespace_character_count,
)

POPPLER_OUTPUT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PageText:
    page_number: int
    text: str
    start_offset: int
    end_offset: int
    character_count: int
    non_whitespace_character_count: int


@dataclass(frozen=True)
class PdfExtraction:
    run_id: str
    run_key: str
    artifact_path: str
    status: str
    page_count: int | None
    pdf_metadata: dict[str, str]
    text: str
    pages: tuple[PageText, ...]
    character_count: int
    non_whitespace_character_count: int
    warnings: tuple[str, ...]
    cache_hit: bool


@dataclass(frozen=True)
class _CommandResult:
    returncode: int
    stdout: bytes
    stderr: bytes


def _decode(value: bytes) -> str:
    return value.decode("utf-8", errors="replace")


def _tool_version(executable: str) -> str:
    result = subprocess.run(
        [executable, "-v"],
        capture_output=True,
        check=False,
        timeout=15,
    )
    combined = (_decode(result.stdout) + "\n" + _decode(result.stderr)).strip()
    return combined.splitlines()[0] if combined else "unknown"


def _parse_pdfinfo(output: str) -> dict[str, str]:
    metadata: dict[str, str] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip()
    return metadata


def _page_count(metadata: dict[str, str]) -> int | None:
    raw = metadata.get("Pages")
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _split_pages(text: str, expected_page_count: int | None) -> tuple[PageText, ...]:
    raw_parts = text.split("\f")
    if raw_parts and raw_parts[-1] == "":
        raw_parts.pop()
    if expected_page_count is not None and len(raw_parts) < expected_page_count:
        raw_parts.extend([""] * (expected_page_count - len(raw_parts)))

    pages: list[PageText] = []
    offset = 0
    for index, part in enumerate(raw_parts, start=1):
        pages.append(
            PageText(
                page_number=index,
                text=part,
                start_offset=offset,
                end_offset=offset + len(part),
                character_count=len(part),
                non_whitespace_character_count=non_whitespace_character_count(part),
            )
        )
        offset += len(part) + 1
    return tuple(pages)


class PopplerExtractor:
    """Extract PDF metadata and embedded text without mutating the source."""

    def __init__(self, extraction_config_hash: str, timeout_seconds: int = 180):
        pdfinfo = shutil.which("pdfinfo")
        pdftotext = shutil.which("pdftotext")
        missing = [
            name
            for name, value in (("pdfinfo", pdfinfo), ("pdftotext", pdftotext))
            if value is None
        ]
        if missing:
            raise DependencyError(
                "Poppler baseline requires missing command(s): " + ", ".join(missing)
            )
        assert pdfinfo is not None
        assert pdftotext is not None
        self.pdfinfo = pdfinfo
        self.pdftotext = pdftotext
        self.timeout_seconds = timeout_seconds
        self.pdfinfo_version = _tool_version(pdfinfo)
        self.pdftotext_version = _tool_version(pdftotext)
        self.descriptor = {
            "name": "poppler",
            "schema_version": POPPLER_OUTPUT_SCHEMA_VERSION,
            "pdfinfo_version": self.pdfinfo_version,
            "pdftotext_version": self.pdftotext_version,
            "pdftotext_options": ["-layout", "-enc", "UTF-8"],
            "extraction_config_hash": extraction_config_hash,
        }
        self.run_key = hash_json(self.descriptor)
        self.run_id = f"poppler:{self.run_key}"

    def _run(self, arguments: list[str]) -> _CommandResult:
        try:
            completed = subprocess.run(
                arguments,
                capture_output=True,
                check=False,
                timeout=self.timeout_seconds,
            )
        except OSError as error:
            return _CommandResult(
                returncode=127,
                stdout=b"",
                stderr=str(error).encode("utf-8", errors="replace"),
            )
        except subprocess.TimeoutExpired as error:
            return _CommandResult(
                returncode=124,
                stdout=error.stdout or b"",
                stderr=(error.stderr or b"")
                + f"\ncommand timed out after {self.timeout_seconds} seconds".encode(),
            )
        return _CommandResult(
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )

    def _load_cached(self, run_dir: Path) -> PdfExtraction | None:
        run_path = run_dir / "run.json"
        text_path = run_dir / "text.txt"
        pages_path = run_dir / "pages.json"
        if not (run_path.is_file() and text_path.is_file() and pages_path.is_file()):
            return None
        try:
            record = json.loads(run_path.read_text(encoding="utf-8"))
            if record.get("status") != "ok" or record.get("run_key") != self.run_key:
                return None
            text = text_path.read_text(encoding="utf-8")
            page_rows = json.loads(pages_path.read_text(encoding="utf-8"))
            pages = tuple(
                PageText(
                    page_number=row["page_number"],
                    text=text[row["start_offset"] : row["end_offset"]],
                    start_offset=row["start_offset"],
                    end_offset=row["end_offset"],
                    character_count=row["character_count"],
                    non_whitespace_character_count=row[
                        "non_whitespace_character_count"
                    ],
                )
                for row in page_rows
            )
            return PdfExtraction(
                run_id=self.run_id,
                run_key=self.run_key,
                artifact_path=run_dir.as_posix(),
                status="ok",
                page_count=record["page_count"],
                pdf_metadata=record["pdf_metadata"],
                text=text,
                pages=pages,
                character_count=record["character_count"],
                non_whitespace_character_count=record["non_whitespace_character_count"],
                warnings=tuple(record.get("warnings", [])),
                cache_hit=True,
            )
        except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError):
            return None

    def extract(
        self,
        source_path: Path,
        blob_dir: Path,
        content_sha256: str,
        store_root: Path,
        expected_size_bytes: int,
        expected_modified_ns: int,
    ) -> PdfExtraction:
        run_dir = blob_dir / "runs" / "poppler" / self.run_key
        cached = self._load_cached(run_dir)
        if cached is not None:
            return PdfExtraction(
                **{
                    **cached.__dict__,
                    "artifact_path": run_dir.relative_to(store_root).as_posix(),
                }
            )

        started_at = isoformat_z()
        before = source_path.stat()
        if (before.st_size, before.st_mtime_ns) != (
            expected_size_bytes,
            expected_modified_ns,
        ):
            raise OSError(f"source changed after hashing: {source_path}")
        info_result = self._run([self.pdfinfo, str(source_path)])
        text_result = self._run(
            [
                self.pdftotext,
                "-layout",
                "-enc",
                "UTF-8",
                str(source_path),
                "-",
            ]
        )
        try:
            after = source_path.stat()
        except OSError:
            after = before
            warnings = ["source became unavailable while Poppler was reading it"]
        else:
            warnings = []

        if (before.st_size, before.st_mtime_ns) != (
            after.st_size,
            after.st_mtime_ns,
        ):
            warnings.append("source changed while Poppler was reading it")

        pdfinfo_text = _decode(info_result.stdout)
        pdftotext_raw = _decode(text_result.stdout)
        pdftotext_text = pdftotext_raw.replace("\x00", "")
        metadata = _parse_pdfinfo(pdfinfo_text)
        page_count = _page_count(metadata)

        if info_result.returncode != 0:
            warnings.append(f"pdfinfo exited with status {info_result.returncode}")
        if text_result.returncode != 0:
            warnings.append(f"pdftotext exited with status {text_result.returncode}")
        if page_count is None:
            warnings.append("pdfinfo did not report a valid page count")

        status = (
            "ok"
            if info_result.returncode == 0
            and text_result.returncode == 0
            and page_count is not None
            and "source changed while Poppler was reading it" not in warnings
            else "error"
        )

        if status != "ok":
            failure_dir = run_dir / "failures" / compact_timestamp()
            atomic_write_text(failure_dir / "pdfinfo.stdout.txt", pdfinfo_text)
            atomic_write_text(
                failure_dir / "pdfinfo.stderr.txt", _decode(info_result.stderr)
            )
            atomic_write_text(failure_dir / "pdftotext.stdout.txt", pdftotext_raw)
            atomic_write_text(
                failure_dir / "pdftotext.stderr.txt", _decode(text_result.stderr)
            )
            atomic_write_json(
                failure_dir / "failure.json",
                {
                    "schema_version": POPPLER_OUTPUT_SCHEMA_VERSION,
                    "run_id": self.run_id,
                    "run_key": self.run_key,
                    "source_sha256": content_sha256,
                    "started_at": started_at,
                    "completed_at": isoformat_z(),
                    "descriptor": self.descriptor,
                    "warnings": warnings,
                    "pdfinfo_returncode": info_result.returncode,
                    "pdftotext_returncode": text_result.returncode,
                },
            )
            return PdfExtraction(
                run_id=self.run_id,
                run_key=self.run_key,
                artifact_path=failure_dir.relative_to(store_root).as_posix(),
                status="error",
                page_count=page_count,
                pdf_metadata=metadata,
                text="",
                pages=(),
                character_count=0,
                non_whitespace_character_count=0,
                warnings=tuple(warnings),
                cache_hit=False,
            )

        pages = _split_pages(pdftotext_text, page_count)
        if page_count != len(pages):
            warnings.append(
                f"pdftotext produced {len(pages)} page segment(s) for "
                f"pdfinfo page count {page_count}"
            )

        page_rows = [
            {
                "page_number": page.page_number,
                "start_offset": page.start_offset,
                "end_offset": page.end_offset,
                "character_count": page.character_count,
                "non_whitespace_character_count": page.non_whitespace_character_count,
            }
            for page in pages
        ]
        run_record = {
            "schema_version": POPPLER_OUTPUT_SCHEMA_VERSION,
            "run_id": self.run_id,
            "run_key": self.run_key,
            "source_sha256": content_sha256,
            "started_at": started_at,
            "completed_at": isoformat_z(),
            "descriptor": self.descriptor,
            "status": "ok",
            "page_count": page_count,
            "pdf_metadata": metadata,
            "character_count": len(pdftotext_text),
            "non_whitespace_character_count": non_whitespace_character_count(
                pdftotext_text
            ),
            "warnings": warnings,
            "raw_outputs": {
                "pdfinfo_stdout": "pdfinfo.stdout.txt",
                "pdfinfo_stderr": "pdfinfo.stderr.txt",
                "pdftotext_stdout": "pdftotext.stdout.txt",
                "pdftotext_stderr": "pdftotext.stderr.txt",
            },
        }

        atomic_write_text(run_dir / "pdfinfo.stdout.txt", pdfinfo_text)
        atomic_write_text(run_dir / "pdfinfo.stderr.txt", _decode(info_result.stderr))
        atomic_write_text(run_dir / "pdftotext.stdout.txt", pdftotext_raw)
        atomic_write_text(run_dir / "pdftotext.stderr.txt", _decode(text_result.stderr))
        atomic_write_text(run_dir / "text.txt", pdftotext_text)
        atomic_write_json(run_dir / "pages.json", page_rows)
        atomic_write_json(run_dir / "run.json", run_record)

        return PdfExtraction(
            run_id=self.run_id,
            run_key=self.run_key,
            artifact_path=run_dir.relative_to(store_root).as_posix(),
            status="ok",
            page_count=page_count,
            pdf_metadata=metadata,
            text=pdftotext_text,
            pages=pages,
            character_count=len(pdftotext_text),
            non_whitespace_character_count=non_whitespace_character_count(
                pdftotext_text
            ),
            warnings=tuple(warnings),
            cache_hit=False,
        )
