"""OCRmyPDF/Tesseract adapter that creates derived searchable PDFs."""

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


class OcrMyPdfExtractor:
    extractor_id = "ocrmypdf-tesseract"

    def __init__(
        self,
        languages: tuple[str, ...] = ("eng",),
        timeout_seconds: int = 900,
        executable: str | None = None,
    ) -> None:
        self.ocrmypdf = resolve_executable("ocrmypdf", executable)
        self.tesseract = resolve_executable("tesseract")
        self.pdftotext = resolve_executable("pdftotext")
        self.pdfinfo = resolve_executable("pdfinfo")
        self.languages = tuple(languages) or ("eng",)
        self.timeout_seconds = timeout_seconds
        self.options = [
            "--language",
            "+".join(self.languages),
            "--rotate-pages",
            "--deskew",
            "--skip-text",
            "--output-type",
            "pdf",
            "--optimize",
            "0",
        ]
        self.descriptor = {
            "ocrmypdf_version": command_version([self.ocrmypdf, "--version"]),
            "tesseract_version": command_version([self.tesseract, "--version"]),
            "pdftotext_version": command_version([self.pdftotext, "-v"]),
            "languages": list(self.languages),
            "options": self.options,
            "normalization": "pdftotext-layout-utf8",
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
        run_dir.mkdir(parents=True, exist_ok=True)
        output_pdf = run_dir / "ocr.pdf"
        sidecar = run_dir / "sidecar.txt"
        command = [
            self.ocrmypdf,
            *self.options,
            "--sidecar",
            str(sidecar),
            str(source_path),
            str(output_pdf),
        ]
        ocr = run_command(command, self.timeout_seconds)
        atomic_write_text(run_dir / "ocr.stdout.txt", ocr.stdout)
        atomic_write_text(run_dir / "ocr.stderr.txt", ocr.stderr)
        warnings: list[str] = []
        pages = ()
        runtime_seconds = ocr.runtime_seconds
        raw_artifacts = {
            "ocr_stdout": "ocr.stdout.txt",
            "ocr_stderr": "ocr.stderr.txt",
        }

        if ocr.returncode == 0 and output_pdf.is_file():
            raw_artifacts["searchable_pdf"] = "ocr.pdf"
            if sidecar.is_file():
                raw_artifacts["ocr_sidecar"] = "sidecar.txt"
            info = run_command([self.pdfinfo, str(output_pdf)], 60)
            text = run_command(
                [
                    self.pdftotext,
                    "-layout",
                    "-enc",
                    "UTF-8",
                    str(output_pdf),
                    "-",
                ],
                180,
            )
            runtime_seconds += info.runtime_seconds + text.runtime_seconds
            atomic_write_text(run_dir / "pdfinfo.stdout.txt", info.stdout)
            atomic_write_text(run_dir / "pdfinfo.stderr.txt", info.stderr)
            atomic_write_text(run_dir / "pdftotext.stderr.txt", text.stderr)
            raw_artifacts.update(
                {
                    "pdfinfo_stdout": "pdfinfo.stdout.txt",
                    "pdfinfo_stderr": "pdfinfo.stderr.txt",
                    "pdftotext_stderr": "pdftotext.stderr.txt",
                }
            )
            page_count = None
            for line in info.stdout.splitlines():
                if line.startswith("Pages:"):
                    try:
                        page_count = int(line.split(":", 1)[1].strip())
                    except ValueError:
                        pass
            if info.returncode != 0:
                warnings.append(f"pdfinfo exited with status {info.returncode}")
            if text.returncode != 0:
                warnings.append(f"pdftotext exited with status {text.returncode}")
            pages = pages_from_text(text.stdout, page_count)
            status = "ok" if info.returncode == 0 and text.returncode == 0 else "error"
        else:
            status = "error"
            warnings.append(f"ocrmypdf exited with status {ocr.returncode}")

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
            runtime_seconds=runtime_seconds,
            raw_artifacts=raw_artifacts,
            started_at=started_at,
        )
