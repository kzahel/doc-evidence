"""Tesseract adapter for explicit standalone raster-image OCR."""

from __future__ import annotations

from pathlib import Path

from doc_evidence.extraction import (
    ExtractionResult,
    command_version,
    descriptor_identity,
    load_cached_result,
    pages_from_text,
    resolve_executable,
    run_command,
    save_result,
)
from doc_evidence.util import atomic_write_text, isoformat_z


class TesseractRasterExtractor:
    extractor_id = "tesseract-raster"

    def __init__(
        self,
        languages: tuple[str, ...] = ("eng",),
        timeout_seconds: int = 600,
    ) -> None:
        self.tesseract = resolve_executable("tesseract")
        self.languages = tuple(languages) or ("eng",)
        self.timeout_seconds = timeout_seconds
        self.options = ["-l", "+".join(self.languages), "txt", "tsv"]
        self.descriptor = {
            "version": command_version([self.tesseract, "--version"]),
            "languages": list(self.languages),
            "options": self.options,
            "normalization": "tesseract-standalone-raster-text-v1",
        }
        self.run_key, self.run_id = descriptor_identity(
            self.extractor_id,
            self.descriptor,
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
            run_dir,
            store_root,
            self.extractor_id,
            self.run_key,
        )
        if cached is not None:
            return cached
        started_at = isoformat_z()
        run_dir.mkdir(parents=True, exist_ok=True)
        output_base = run_dir / "tesseract"
        result = run_command(
            [
                self.tesseract,
                str(source_path),
                str(output_base),
                *self.options,
            ],
            timeout_seconds=self.timeout_seconds,
        )
        atomic_write_text(run_dir / "stdout.txt", result.stdout)
        atomic_write_text(run_dir / "stderr.txt", result.stderr)
        text_path = output_base.with_suffix(".txt")
        tsv_path = output_base.with_suffix(".tsv")
        warnings: list[str] = []
        raw_artifacts = {"stdout": "stdout.txt", "stderr": "stderr.txt"}
        if text_path.is_file():
            raw_artifacts["tesseract_text"] = text_path.name
        if tsv_path.is_file():
            raw_artifacts["tesseract_tsv"] = tsv_path.name
        if result.returncode == 0 and text_path.is_file():
            text = text_path.read_text(encoding="utf-8", errors="replace")
            pages = pages_from_text(text, 1)
            status = "ok"
        else:
            pages = ()
            status = "error"
            warnings.append(f"tesseract exited with status {result.returncode}")
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
            raw_artifacts=raw_artifacts,
            started_at=started_at,
        )
