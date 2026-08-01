"""Docling standard-pipeline adapter."""

from __future__ import annotations

import json
from pathlib import Path

from doc_evidence.extraction import (
    ExtractionResult,
    command_version,
    descriptor_identity,
    load_cached_result,
    resolve_executable,
    run_command,
    save_result,
)
from doc_evidence.structured import docling_pages
from doc_evidence.util import atomic_write_text, isoformat_z


class DoclingExtractor:
    extractor_id = "docling-standard"

    def __init__(
        self, executable: str | None = None, timeout_seconds: int = 1200
    ) -> None:
        self.executable = resolve_executable(
            "docling", executable, ".extractors/docling/bin/docling"
        )
        self.timeout_seconds = timeout_seconds
        self.options = [
            "--to",
            "json",
            "--to",
            "md",
            "--image-export-mode",
            "placeholder",
            "--pipeline",
            "standard",
            "--tables",
            "--table-mode",
            "accurate",
            "--device",
            "auto",
            "--quiet",
        ]
        self.descriptor = {
            "version": command_version([self.executable, "--version"], 120),
            "options": self.options,
            "normalization": "docling-body-reference-page-provenance-v1",
        }
        self.run_key, self.run_id = descriptor_identity(
            self.extractor_id, self.descriptor
        )

    def extract(
        self,
        source_path: Path,
        blob_dir: Path,
        source_sha256: str,
        store_root: Path,
    ) -> ExtractionResult:
        run_dir = blob_dir / "runs" / self.extractor_id / self.run_key
        cached = load_cached_result(
            run_dir, store_root, self.extractor_id, self.run_key
        )
        if cached is not None:
            return cached
        started_at = isoformat_z()
        raw_dir = run_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        command = [
            self.executable,
            "convert",
            str(source_path),
            *self.options,
            "--output",
            str(raw_dir),
        ]
        result = run_command(command, self.timeout_seconds)
        atomic_write_text(run_dir / "stdout.txt", result.stdout)
        atomic_write_text(run_dir / "stderr.txt", result.stderr)
        json_files = sorted(raw_dir.glob("*.json"))
        warnings: list[str] = []
        pages = ()
        table_count = None
        if result.returncode == 0 and len(json_files) == 1:
            try:
                document = json.loads(json_files[0].read_text(encoding="utf-8"))
                pages, table_count = docling_pages(document)
                status = "ok"
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                TypeError,
                KeyError,
            ) as error:
                status = "error"
                warnings.append(f"cannot normalize Docling JSON: {error}")
        else:
            status = "error"
            warnings.append(f"Docling exited with status {result.returncode}")
            if len(json_files) != 1:
                warnings.append(
                    f"expected one Docling JSON output; found {len(json_files)}"
                )
        return save_result(
            run_dir=run_dir,
            store_root=store_root,
            extractor_id=self.extractor_id,
            run_id=self.run_id,
            run_key=self.run_key,
            source_sha256=source_sha256,
            descriptor=self.descriptor,
            status=status,
            pages=pages,
            warnings=warnings,
            runtime_seconds=result.runtime_seconds,
            raw_artifacts={
                "stdout": "stdout.txt",
                "stderr": "stderr.txt",
                "output": "raw/",
            },
            table_count=table_count,
            started_at=started_at,
        )
