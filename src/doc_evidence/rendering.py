"""Versioned on-demand page rendering into the derived artifact store."""

from __future__ import annotations

import json
import shutil
import struct
import tempfile
from dataclasses import dataclass
from pathlib import Path

from doc_evidence.errors import DependencyError, DocEvidenceError
from doc_evidence.extraction import command_version, run_command
from doc_evidence.util import atomic_write_json, hash_file, hash_json, isoformat_z

PAGE_RENDER_SCHEMA_VERSION = 1
PAGE_RENDER_DPI = 144
MAX_RENDER_DIMENSION = 8192
MAX_RENDER_PIXELS = 40_000_000


@dataclass(frozen=True)
class PageRender:
    path: Path
    media_type: str
    cache_hit: bool
    width: int
    height: int


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise DocEvidenceError("pdftoppm output was not a valid PNG")
    return struct.unpack(">II", header[16:24])


class PageRenderer:
    def __init__(self, store: Path, timeout_seconds: int = 180):
        executable = shutil.which("pdftoppm")
        if executable is None:
            raise DependencyError("page rendering requires pdftoppm")
        self.store = store.resolve()
        self.executable = executable
        self.timeout_seconds = timeout_seconds
        self.descriptor = {
            "schema_version": PAGE_RENDER_SCHEMA_VERSION,
            "renderer": "pdftoppm",
            "version": command_version([executable, "-v"]),
            "dpi": PAGE_RENDER_DPI,
            "format": "png",
            "maximum_dimension": MAX_RENDER_DIMENSION,
            "maximum_pixels": MAX_RENDER_PIXELS,
        }

    def render(
        self,
        *,
        source: Path,
        source_sha256: str,
        page: int,
    ) -> PageRender:
        run_key = hash_json(
            {"source_sha256": source_sha256, "descriptor": self.descriptor}
        )
        blob_dir = self.store / "blobs" / source_sha256[:2] / source_sha256
        run_dir = blob_dir / "runs" / "page-render" / run_key
        page_dir = run_dir / "pages"
        output = page_dir / f"page-{page:04d}.png"
        page_record = page_dir / f"page-{page:04d}.json"
        if output.is_file() and page_record.is_file():
            try:
                record = json.loads(page_record.read_text(encoding="utf-8"))
                width, height = _png_dimensions(output)
                if (
                    record.get("status") == "ok"
                    and record.get("source_sha256") == source_sha256
                    and record.get("page") == page
                    and record.get("run_key") == run_key
                    and record.get("width") == width
                    and record.get("height") == height
                ):
                    return PageRender(output, "image/png", True, width, height)
            except (OSError, UnicodeError, json.JSONDecodeError, DocEvidenceError):
                pass

        page_dir.mkdir(parents=True, exist_ok=True)
        before = source.stat()
        width = 0
        height = 0
        error: str | None = None
        with tempfile.TemporaryDirectory(prefix="doc-evidence-render-") as raw:
            render_source = Path(raw) / "source.pdf"
            temporary_output = Path(raw) / "page.png"
            temporary_stem = temporary_output.with_suffix("")
            with (
                source.open("rb") as source_stream,
                render_source.open("xb") as target_stream,
            ):
                shutil.copyfileobj(source_stream, target_stream)
            if hash_file(render_source).content_sha256 != source_sha256:
                raise DocEvidenceError("source bytes changed while staging page render")
            result = run_command(
                [
                    self.executable,
                    "-f",
                    str(page),
                    "-l",
                    str(page),
                    "-singlefile",
                    "-r",
                    str(PAGE_RENDER_DPI),
                    "-png",
                    str(render_source),
                    str(temporary_stem),
                ],
                timeout_seconds=self.timeout_seconds,
            )
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (
                after.st_size,
                after.st_mtime_ns,
            ):
                error = "source metadata changed while rendering"
            elif result.returncode != 0 or not temporary_output.is_file():
                error = result.stderr.strip() or (
                    f"pdftoppm exited with status {result.returncode}"
                )
            else:
                try:
                    width, height = _png_dimensions(temporary_output)
                except (OSError, DocEvidenceError) as exception:
                    error = str(exception)
                if width > MAX_RENDER_DIMENSION or height > MAX_RENDER_DIMENSION:
                    error = (
                        f"render dimensions {width}x{height} exceed "
                        f"{MAX_RENDER_DIMENSION}px"
                    )
                elif width * height > MAX_RENDER_PIXELS:
                    error = (
                        f"render dimensions {width}x{height} exceed "
                        f"{MAX_RENDER_PIXELS:,} pixels"
                    )
                if error is None:
                    shutil.copyfile(temporary_output, output)
        record = {
            "schema_version": PAGE_RENDER_SCHEMA_VERSION,
            "source_sha256": source_sha256,
            "page": page,
            "run_key": run_key,
            "descriptor": self.descriptor,
            "created_at": isoformat_z(),
            "status": "error" if error else "ok",
            "width": width,
            "height": height,
            "runtime_seconds": result.runtime_seconds,
            "error": error,
        }
        atomic_write_json(page_record, record)
        atomic_write_json(
            run_dir / "run.json",
            {
                "schema_version": PAGE_RENDER_SCHEMA_VERSION,
                "run_id": f"page-render:{run_key}",
                "run_key": run_key,
                "source_sha256": source_sha256,
                "descriptor": self.descriptor,
                "status": "ok",
            },
        )
        if error:
            output.unlink(missing_ok=True)
            raise DocEvidenceError(f"cannot render page {page}: {error}")
        return PageRender(output, "image/png", False, width, height)
