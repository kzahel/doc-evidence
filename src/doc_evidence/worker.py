"""Private extraction-worker entry point used by the attempt supervisor."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

from doc_evidence.docling_adapter import DoclingExtractor
from doc_evidence.errors import DocEvidenceError
from doc_evidence.marker_adapter import MarkerExtractor
from doc_evidence.ocrmypdf_adapter import OcrMyPdfExtractor
from doc_evidence.poppler import PopplerExtractor
from doc_evidence.tesseract_raster_adapter import TesseractRasterExtractor
from doc_evidence.util import atomic_write_json, hash_file

WORKER_PROTOCOL_VERSION = 1


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"worker field {field} must be an object")
    return value


def _required_string(request: dict[str, Any], field: str) -> str:
    value = request.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"worker field {field} must be a non-empty string")
    return value


def _integer(request: dict[str, Any], field: str) -> int:
    value = request.get(field)
    if not isinstance(value, int):
        raise TypeError(f"worker field {field} must be an integer")
    return value


def _execute(request: dict[str, Any]) -> dict[str, object]:
    if request.get("protocol_version") != WORKER_PROTOCOL_VERSION:
        raise ValueError("unsupported extraction-worker protocol")
    extractor_id = _required_string(request, "extractor_id")
    source_path = Path(_required_string(request, "source_path")).resolve()
    store_root = Path(_required_string(request, "store_root")).resolve()
    blob_dir = Path(_required_string(request, "blob_dir")).resolve()
    attempt_dir = Path(_required_string(request, "attempt_dir")).resolve()
    source_sha256 = _required_string(request, "source_sha256")
    expected_size_bytes = _integer(request, "expected_size_bytes")
    expected_modified_ns = _integer(request, "expected_modified_ns")
    timeout_seconds = _integer(request, "timeout_seconds")
    settings = _mapping(request.get("settings", {}), "settings")
    if not attempt_dir.is_relative_to(blob_dir) or not blob_dir.is_relative_to(
        store_root
    ):
        raise ValueError("worker attempt paths are outside the artifact store")
    atomic_write_json(
        attempt_dir / "worker.json",
        {
            "schema_version": 1,
            "attempt_id": _required_string(request, "attempt_id"),
            "worker_pid": os.getpid(),
            "process_group_id": os.getpid() if os.name == "posix" else None,
        },
    )
    before = source_path.stat()
    if (before.st_size, before.st_mtime_ns) != (
        expected_size_bytes,
        expected_modified_ns,
    ):
        raise ValueError("source metadata changed before worker execution")
    observed = hash_file(source_path)
    if observed.content_sha256 != source_sha256:
        raise ValueError("source content changed before worker execution")
    attempt_dir.mkdir(parents=True, exist_ok=True)
    languages = tuple(str(item) for item in settings.get("languages", ["eng"]))
    os.environ["DOC_EVIDENCE_SUPERVISED_WORKER"] = "1"

    if extractor_id == "poppler":
        extractor = PopplerExtractor(
            _required_string(request, "extraction_config_hash"),
            timeout_seconds=timeout_seconds,
        )
        result = extractor.extract(
            source_path,
            attempt_dir,
            source_sha256,
            store_root,
            expected_size_bytes,
            expected_modified_ns,
        )
    elif extractor_id == "ocrmypdf-tesseract":
        result = OcrMyPdfExtractor(
            languages=languages,
            timeout_seconds=timeout_seconds,
        ).extract(source_path, attempt_dir, source_sha256, store_root)
    elif extractor_id == "tesseract-raster":
        result = TesseractRasterExtractor(
            languages=languages,
            timeout_seconds=timeout_seconds,
        ).extract(source_path, attempt_dir, source_sha256, store_root)
    elif extractor_id == "docling-standard":
        result = DoclingExtractor(timeout_seconds=timeout_seconds).extract(
            source_path,
            attempt_dir,
            source_sha256,
            store_root,
        )
    elif extractor_id == "marker-fast":
        result = MarkerExtractor(timeout_seconds=timeout_seconds).extract(
            source_path,
            attempt_dir,
            source_sha256,
            store_root,
        )
    else:
        raise ValueError("worker extractor is not registered")
    return {
        "protocol_version": WORKER_PROTOCOL_VERSION,
        "status": result.status,
        "extractor_id": extractor_id,
        "run_id": result.run_id,
        "run_key": result.run_key,
        "artifact_path": result.artifact_path,
        "warnings": list(result.warnings),
    }


def main(arguments: list[str] | None = None) -> int:
    values = arguments if arguments is not None else sys.argv[1:]
    if len(values) != 2:
        return 2
    request_path = Path(values[0])
    response_path = Path(values[1])
    try:
        request = json.loads(request_path.read_text(encoding="utf-8"))
        if not isinstance(request, dict):
            raise TypeError("worker request must be an object")
        response = _execute(request)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
        DocEvidenceError,
    ) as error:
        atomic_write_json(
            response_path,
            {
                "protocol_version": WORKER_PROTOCOL_VERSION,
                "status": "error",
                "error_type": type(error).__name__,
                "message": str(error)[:1_000],
            },
        )
        return 1
    atomic_write_json(response_path, response)
    return 0 if response["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
