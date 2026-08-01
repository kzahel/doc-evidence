"""Run headless browser validation under an isolated application home."""

from __future__ import annotations

import hashlib
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from doc_evidence.app_home import LibraryRegistry, resolve_application_home
from doc_evidence.config import load_config
from doc_evidence.inventory import run_inventory

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from tests.helpers import write_minimal_pdf


def _bytes_or_none(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_library(root: Path, slug: str, text: str) -> tuple[Path, Path]:
    library = root / slug
    documents = library / "documents"
    documents.mkdir(parents=True)
    source = documents / f"{slug}.pdf"
    write_minimal_pdf(source, text)
    config = library / "case.yaml"
    config.write_text(
        """
schema_version: 1
collections:
  - id: documents
    source: documents
store:
  path: derived
""".lstrip(),
        encoding="utf-8",
    )
    return config, source


def _available_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_server(url: str, token: str, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("isolated E2E server exited before becoming ready")
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
    raise RuntimeError("isolated E2E server did not become ready")


def main() -> int:
    default_state = resolve_application_home(environ={}).root / "app-state.json"
    production_before = _bytes_or_none(default_state)
    with tempfile.TemporaryDirectory(prefix="doc-evidence-playwright-") as temporary:
        root = Path(temporary)
        app_home = root / "app-home"
        first_config, first_source = _write_library(
            root, "first", "first library durable evidence"
        )
        second_config, second_source = _write_library(
            root, "second", "second library isolated evidence"
        )
        first_inventory = run_inventory(load_config(first_config))
        second_inventory = run_inventory(load_config(second_config))
        registry = LibraryRegistry(
            resolve_application_home(environ={"DOC_EVIDENCE_HOME": str(app_home)})
        )
        first = registry.register_config(first_config, name="First Library")
        second = registry.register_config(
            second_config,
            name="Second Library",
            make_default=False,
        )
        registry.activate(first.library_id, make_default=True)
        source_hashes = {
            first_source: _sha256(first_source),
            second_source: _sha256(second_source),
        }
        port = _available_port()
        token = "isolated-playwright-launch-token"
        base_url = f"http://127.0.0.1:{port}"
        environment = {
            **os.environ,
            "DOC_EVIDENCE_HOME": str(app_home),
            "DOC_EVIDENCE_E2E_PORT": str(port),
            "DOC_EVIDENCE_E2E_TOKEN": token,
            "DOC_EVIDENCE_E2E_URL": base_url,
            "DOC_EVIDENCE_E2E_FIRST_LIBRARY": first.library_id,
            "DOC_EVIDENCE_E2E_SECOND_LIBRARY": second.library_id,
            "DOC_EVIDENCE_E2E_FIRST_DOCUMENT": first_inventory.documents[0].document_id,
            "DOC_EVIDENCE_E2E_SECOND_DOCUMENT": second_inventory.documents[
                0
            ].document_id,
        }
        server = subprocess.Popen(
            [sys.executable, str(ROOT / "tests" / "e2e_server.py")],
            cwd=ROOT,
            env=environment,
        )
        try:
            _wait_for_server(base_url, token, server)
            completed = subprocess.run(
                [
                    str(ROOT / "web" / "node_modules" / ".bin" / "playwright"),
                    "test",
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
                server.wait(timeout=20)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=10)
        if completed.returncode != 0:
            return completed.returncode
        for source, expected in source_hashes.items():
            if _sha256(source) != expected:
                raise RuntimeError("Playwright validation changed a source fixture")
    if _bytes_or_none(default_state) != production_before:
        raise RuntimeError(
            "isolated Playwright validation changed production app state"
        )
    print(
        "Playwright passed with two isolated libraries; source hashes and "
        "production app state are unchanged."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
