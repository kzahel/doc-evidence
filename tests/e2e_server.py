"""Isolated production-like server composition for Playwright validation."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import uvicorn

from doc_evidence.adapters.local_jobs import LocalExtractionJobs
from doc_evidence.adapters.local_libraries import LocalLibraryManager
from doc_evidence.api.app import create_app
from doc_evidence.app_home import LibraryRegistry, resolve_application_home
from doc_evidence.attempts import AttemptSupervisor
from doc_evidence.extractor_registry import (
    ExtractorExecution,
    ExtractorRegistry,
    ExtractorSpec,
    PreparedExtraction,
)
from doc_evidence.persistence import ensure_library_database
from doc_evidence.util import hash_json

ROOT = Path(__file__).parents[1]
FAKE_WORKER = ROOT / "tests" / "fixtures" / "fake_extraction_worker.py"


def _empty_schema() -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
    }


E2E_EXTRACTORS = (
    ExtractorSpec(
        extractor_id="fixture-success",
        display_name="Fixture success",
        category="layout_parser",
        supported_media_types=("application/pdf",),
        dependencies=(),
        resource_class="light",
        settings_schema=_empty_schema(),
        default_timeout_seconds=10,
        deterministic=True,
        output_kinds=("normalized_page_text", "raw_logs"),
    ),
    ExtractorSpec(
        extractor_id="fixture-cancellable",
        display_name="Fixture cancellable",
        category="other",
        supported_media_types=("application/pdf",),
        dependencies=(),
        resource_class="light",
        settings_schema=_empty_schema(),
        default_timeout_seconds=20,
        deterministic=True,
        output_kinds=("normalized_page_text", "raw_logs"),
    ),
    ExtractorSpec(
        extractor_id="fixture-timeout",
        display_name="Fixture timeout",
        category="other",
        supported_media_types=("application/pdf",),
        dependencies=(),
        resource_class="light",
        settings_schema=_empty_schema(),
        default_timeout_seconds=1,
        deterministic=True,
        output_kinds=("normalized_page_text", "raw_logs"),
    ),
)


class E2EExtractorRegistry(ExtractorRegistry):
    """Keep fake execution wiring outside the shipped extractor registry."""

    def __init__(self) -> None:
        super().__init__(E2E_EXTRACTORS)

    def prepare(
        self,
        *,
        extractor_id: str,
        media_type: str,
        settings: dict[str, Any],
        extraction_config_hash: str,
        default_languages: tuple[str, ...] = (),
    ) -> PreparedExtraction:
        del default_languages
        if settings:
            raise ValueError("E2E fixture extractors do not accept settings")
        spec = self.spec(extractor_id)
        if media_type not in spec.supported_media_types:
            raise ValueError("E2E fixture extractor received unsupported media")
        behavior = {
            "fixture-success": "success",
            "fixture-cancellable": "ignore-cancel",
            "fixture-timeout": "hang",
        }[extractor_id]
        run_key = hash_json(
            {
                "extractor_id": extractor_id,
                "fixture_version": 1,
                "extraction_config_hash": extraction_config_hash,
            }
        )
        return PreparedExtraction(
            execution=ExtractorExecution(
                extractor_id=extractor_id,
                settings={"behavior": behavior, "run_key": run_key},
                timeout_seconds=spec.default_timeout_seconds,
                resource_class=spec.resource_class,
                deterministic=True,
            ),
            descriptor={
                "extractor": extractor_id,
                "version": "e2e-fixture-1",
                "output_schema_version": "normalized_extraction_v1",
            },
            run_key=run_key,
            run_id=f"{extractor_id}:{run_key}",
        )


def main() -> int:
    port = int(os.environ["DOC_EVIDENCE_E2E_PORT"])
    token = os.environ["DOC_EVIDENCE_E2E_TOKEN"]
    app_home = resolve_application_home()
    registry = LibraryRegistry(app_home)
    manager = LocalLibraryManager(registry=registry)
    for known in registry.load().libraries:
        _, _, config = registry.open(known.library_id)
        database = ensure_library_database(
            config,
            library_id=known.library_id,
            name=known.name,
        )
        manager._jobs[known.library_id] = LocalExtractionJobs(
            library_id=known.library_id,
            config=config,
            database=database,
            registry=E2EExtractorRegistry(),
            supervisor=AttemptSupervisor(
                worker_command=(sys.executable, str(FAKE_WORKER)),
                minimum_free_bytes=0,
                cancellation_grace_seconds=0.2,
                heartbeat_seconds=0.1,
            ),
        )
    active_library_id = manager.app_summary().active_library_id
    application = (
        manager.application(active_library_id)
        if active_library_id is not None
        else None
    )
    base_url = f"http://127.0.0.1:{port}"
    app = create_app(
        application,
        library_manager=manager,
        launch_token=token,
        allowed_origins={base_url},
        static_dir=ROOT / "web" / "dist",
    )
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        access_log=False,
        log_level="warning",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
