"""Marker fast-mode adapter, isolated from the core environment."""

from __future__ import annotations

import atexit
import json
import os
import signal
import subprocess
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
from doc_evidence.structured import marker_pages
from doc_evidence.util import atomic_write_text, isoformat_z


class MarkerExtractor:
    extractor_id = "marker-fast"

    def __init__(
        self, executable: str | None = None, timeout_seconds: int = 1200
    ) -> None:
        self.executable = resolve_executable(
            "marker_single", executable, ".extractors/marker/bin/marker_single"
        )
        self.timeout_seconds = timeout_seconds
        self.python = str(Path(self.executable).parent / "python")
        atexit.register(self.stop_services)
        self.options = [
            "--mode",
            "fast",
            "--output_format",
            "json",
            "--disable_image_extraction",
            "--disable_multiprocessing",
            "--disable_tqdm",
        ]
        self.descriptor = {
            "version": command_version(
                [
                    self.python,
                    "-c",
                    "import importlib.metadata as m; print(m.version('marker-pdf'))",
                ],
                120,
            ),
            "options": self.options,
            "normalization": "marker-block-tree-html-v2",
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
            str(source_path),
            *self.options,
            "--output_dir",
            str(raw_dir),
        ]
        # Isolate the direct command for timeout cleanup. Marker also starts
        # persistent Surya services in new sessions; stop_services handles only
        # services belonging to this adapter's isolated Python environment.
        result = run_command(
            command,
            self.timeout_seconds,
            cleanup_process_group=True,
        )
        atomic_write_text(run_dir / "stdout.txt", result.stdout)
        atomic_write_text(run_dir / "stderr.txt", result.stderr)
        json_files = sorted(
            path
            for path in raw_dir.rglob("*.json")
            if not path.name.endswith("_meta.json")
        )
        warnings: list[str] = []
        pages = ()
        table_count = None
        if result.returncode == 0 and len(json_files) == 1:
            try:
                document = json.loads(json_files[0].read_text(encoding="utf-8"))
                pages, table_count = marker_pages(document)
                status = "ok"
            except (
                OSError,
                UnicodeError,
                json.JSONDecodeError,
                TypeError,
                KeyError,
            ) as error:
                status = "error"
                warnings.append(f"cannot normalize Marker JSON: {error}")
        else:
            status = "error"
            warnings.append(f"Marker exited with status {result.returncode}")
            if len(json_files) != 1:
                warnings.append(
                    f"expected one Marker JSON output; found {len(json_files)}"
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

    def stop_services(self) -> list[int]:
        """Stop persistent Surya services owned by this isolated Marker env."""

        try:
            completed = subprocess.run(
                ["ps", "-axo", "pid=,command="],
                capture_output=True,
                check=False,
                timeout=15,
                text=True,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        modules = (
            "surya.fast_layout.server",
            "surya.ocr_error.server",
        )
        prefixes = tuple(f"{self.python} -m {module} " for module in modules)
        stopped = []
        for line in completed.stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                raw_pid, command = stripped.split(None, 1)
                pid = int(raw_pid)
            except (ValueError, IndexError):
                continue
            if command.startswith(prefixes):
                try:
                    os.kill(pid, signal.SIGTERM)
                except (ProcessLookupError, PermissionError):
                    continue
                stopped.append(pid)
        return stopped
