"""Run the authorized private-library UI integration without recording names."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from doc_evidence.adapters.local_jobs import LocalExtractionJobs
from doc_evidence.adapters.local_libraries import LocalLibraryManager
from doc_evidence.app_home import LibraryRegistry, resolve_application_home
from doc_evidence.config import AppConfig
from doc_evidence.discovery import discover_files
from doc_evidence.util import hash_file

ROOT = Path(__file__).parents[1]


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_server(url: str, token: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("private integration server exited before readiness")
        request = urllib.request.Request(
            url + "/api/v1/app",
            headers={"Authorization": f"Bearer {token}"},
        )
        try:
            with urllib.request.urlopen(request, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("private integration server did not become ready")


def _source_identity(config: AppConfig) -> tuple[int, str, int]:
    aggregate = hashlib.sha256()
    count = 0
    warnings: list[dict[str, str]] = []
    for collection in config.collections:
        for item in discover_files(collection, warnings):
            digest = hash_file(item.path).content_sha256
            aggregate.update(collection.id.encode())
            aggregate.update(b"\0")
            aggregate.update(item.relative_path.encode())
            aggregate.update(b"\0")
            aggregate.update(digest.encode())
            aggregate.update(b"\n")
            count += 1
    return count, aggregate.hexdigest(), len(warnings)


def _exact_layout(service: LocalExtractionJobs) -> tuple[str, str, str]:
    connection = service.database.connect(readonly=True)
    try:
        rows = connection.execute(
            """
            SELECT DISTINCT content.document_id
            FROM content_objects content
            JOIN generation_documents member
              ON member.content_sha256 = content.content_sha256
             AND member.generation_id = (
                SELECT active_generation_id FROM library_metadata WHERE singleton = 1
             )
            JOIN extraction_runs run
              ON run.content_sha256 = content.content_sha256
            WHERE run.extractor_id IN ('docling-standard', 'marker-fast')
              AND run.status = 'ok'
            ORDER BY content.document_id
            """
        ).fetchall()
    finally:
        connection.close()
    for row in rows:
        document_id = str(row[0])
        for item in service.capabilities(document_id=document_id):
            if item.category == "layout_parser" and item.cached:
                return document_id, item.extractor_id, item.display_name
    raise RuntimeError("private library has no exact current layout run to reuse")


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-config", required=True, type=Path)
    args = parser.parse_args(arguments)
    environment = {
        key: value for key, value in os.environ.items() if key != "DOC_EVIDENCE_HOME"
    }
    app_home = resolve_application_home(environ=environment)
    registry = LibraryRegistry(app_home)
    registry_before = registry.state_path.read_bytes()
    known, descriptor, config = registry.selected()
    if descriptor.config_path.resolve() != args.expected_config.expanduser().resolve():
        raise RuntimeError(
            "default registered library is not the expected configuration"
        )
    manager = LocalLibraryManager(registry=registry)
    service = manager.jobs(known.library_id)
    source_before = _source_identity(config)
    preflight_before = service.preflight_image_only_ocr()
    if not preflight_before.document_ids or preflight_before.execution_count < 1:
        raise RuntimeError("private library has no bounded missing OCR execution")
    ocr_document_id = preflight_before.document_ids[0]
    layout_document_id, layout_extractor_id, layout_display_name = _exact_layout(
        service
    )
    manager.shutdown()

    port = _available_port()
    token = "authorized-private-integration-token"
    base_url = f"http://127.0.0.1:{port}"
    environment.update(
        {
            "DOC_EVIDENCE_PRIVATE_PORT": str(port),
            "DOC_EVIDENCE_PRIVATE_TOKEN": token,
            "DOC_EVIDENCE_E2E_URL": base_url,
            "DOC_EVIDENCE_E2E_TOKEN": token,
            "DOC_EVIDENCE_PRIVATE_LIBRARY": known.library_id,
            "DOC_EVIDENCE_PRIVATE_OCR_DOCUMENT": ocr_document_id,
            "DOC_EVIDENCE_PRIVATE_LAYOUT_DOCUMENT": layout_document_id,
            "DOC_EVIDENCE_PRIVATE_LAYOUT_EXTRACTOR": layout_extractor_id,
            "DOC_EVIDENCE_PRIVATE_LAYOUT_DISPLAY": layout_display_name,
            "DOC_EVIDENCE_PRIVATE_PREFLIGHT_CANDIDATES": str(
                preflight_before.candidate_count
            ),
            "DOC_EVIDENCE_PRIVATE_PREFLIGHT_EXECUTIONS": str(
                preflight_before.execution_count - 1
            ),
        }
    )
    server = subprocess.Popen(
        [sys.executable, str(ROOT / "tests" / "registered_library_server.py")],
        cwd=ROOT,
        env=environment,
    )
    started = time.monotonic()
    try:
        _wait_for_server(base_url, token, server)
        completed = subprocess.run(
            [
                str(ROOT / "web" / "node_modules" / ".bin" / "playwright"),
                "test",
                "e2e/private-library.spec.ts",
                "--config",
                str(ROOT / "web" / "playwright.config.ts"),
            ],
            cwd=ROOT / "web",
            env=environment,
            check=False,
        )
    finally:
        server.terminate()
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)
    if completed.returncode != 0:
        return completed.returncode

    manager = LocalLibraryManager(registry=registry)
    service = manager.jobs(known.library_id)
    source_after = _source_identity(config)
    preflight_after = service.preflight_image_only_ocr()
    jobs, _ = service.list(limit=200)
    manager.shutdown()
    ocr_outcomes = [
        job.outcome
        for job in jobs
        if job.document_id == ocr_document_id
        and job.extractor_id == "ocrmypdf-tesseract"
    ]
    layout_outcomes = [
        job.outcome
        for job in jobs
        if job.document_id == layout_document_id
        and job.extractor_id == layout_extractor_id
    ]
    if source_after != source_before:
        raise RuntimeError("private source hash aggregate changed")
    if registry.state_path.read_bytes() != registry_before:
        raise RuntimeError("ordinary private integration changed the default registry")
    if "cache_hit" not in ocr_outcomes or not any(
        outcome in {"executed", "concurrent_cache_win"} for outcome in ocr_outcomes
    ):
        raise RuntimeError("private OCR execution/cache history is incomplete")
    if "cache_hit" not in layout_outcomes:
        raise RuntimeError("private exact layout reuse was not recorded")
    if (
        preflight_after.candidate_count != preflight_before.candidate_count
        or preflight_after.cache_hit_count != preflight_before.cache_hit_count + 1
        or preflight_after.execution_count != preflight_before.execution_count - 1
    ):
        raise RuntimeError("private OCR preflight did not gain exactly one cache hit")
    print(
        json.dumps(
            {
                "library_id": known.library_id,
                "source_count": source_after[0],
                "source_aggregate_sha256": source_after[1],
                "discovery_warning_count": source_after[2],
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "ocr_execution_outcomes": sorted(
                    outcome for outcome in ocr_outcomes if outcome is not None
                ),
                "layout_extractor_id": layout_extractor_id,
                "layout_outcomes": sorted(
                    outcome for outcome in layout_outcomes if outcome is not None
                ),
                "preflight_before": {
                    "candidates": preflight_before.candidate_count,
                    "cache_hits": preflight_before.cache_hit_count,
                    "executions": preflight_before.execution_count,
                },
                "preflight_after": {
                    "candidates": preflight_after.candidate_count,
                    "cache_hits": preflight_after.cache_hit_count,
                    "executions": preflight_after.execution_count,
                },
                "source_unchanged": True,
                "registry_unchanged": True,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
