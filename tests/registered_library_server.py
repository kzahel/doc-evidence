"""Known-token production composition for authorized private integration."""

from __future__ import annotations

import os
from pathlib import Path

import uvicorn

from doc_evidence.adapters.local_libraries import LocalLibraryManager
from doc_evidence.api.app import create_app
from doc_evidence.app_home import LibraryRegistry, resolve_application_home

ROOT = Path(__file__).parents[1]


def main() -> int:
    port = int(os.environ["DOC_EVIDENCE_PRIVATE_PORT"])
    token = os.environ["DOC_EVIDENCE_PRIVATE_TOKEN"]
    registry = LibraryRegistry(resolve_application_home())
    known, _, _ = registry.selected()
    manager = LocalLibraryManager(registry=registry)
    base_url = f"http://127.0.0.1:{port}"
    app = create_app(
        manager.application(known.library_id),
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
