from __future__ import annotations

import ast
import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from doc_evidence.adapters.local_libraries import LocalLibraryManager
from doc_evidence.adapters.local_workspace import LocalWorkspace
from doc_evidence.api.app import create_app, create_contract_app
from doc_evidence.application.library import LibraryApplication
from doc_evidence.config import load_config
from doc_evidence.contracts.api import (
    ComparisonRequest,
    ComparisonResult,
    WorkspaceSummary,
)
from doc_evidence.errors import NotFoundError
from doc_evidence.inventory import run_inventory
from tests.helpers import write_hybrid_pdf


def _write_config(root: Path) -> Path:
    path = root / "case.yaml"
    path.write_text(
        """
schema_version: 1
collections:
  - id: sample
    source: documents
    include: ["**/*"]
store:
  path: derived
extraction:
  baseline: poppler
  ocr_when: image_only
  layout_when: complex
  normalized_text_duplicates: true
search:
  sqlite_fts: true
  vector_index: false
""".lstrip(),
        encoding="utf-8",
    )
    return path


def _add_extractor_run(
    store: Path,
    digest: str,
    extractor: str,
    run_key: str,
    text: str,
    *,
    version: str,
) -> None:
    run_dir = store / "blobs" / digest[:2] / digest / "runs" / extractor / run_key
    run_dir.mkdir(parents=True)
    (run_dir / "stdout.txt").write_text("synthetic expert output\n", encoding="utf-8")
    (run_dir / "run.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": f"{extractor}:{run_key}",
                "run_key": run_key,
                "status": "ok",
                "descriptor": {"version": version, "options": ["fixture"]},
                "warnings": [],
                "runtime_seconds": 0.01,
                "raw_artifacts": {"stdout": "stdout.txt"},
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "normalized.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "pages": [
                    {
                        "page_number": 1,
                        "text": text,
                        "character_count": len(text),
                        "non_whitespace_character_count": len("".join(text.split())),
                    }
                ],
                "table_count": 0,
            }
        ),
        encoding="utf-8",
    )


@unittest.skipUnless(
    shutil.which("pdfinfo") and shutil.which("pdftotext") and shutil.which("pdftoppm"),
    "Poppler tools are required for the application integration test",
)
class ApplicationIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        source = self.root / "documents"
        source.mkdir()
        self.pdf = source / "hybrid.pdf"
        write_hybrid_pdf(self.pdf, "Account balance 1,234.50")
        self.source_hash = hashlib.sha256(self.pdf.read_bytes()).hexdigest()
        self.source_stat = self.pdf.stat()
        self.config = load_config(_write_config(self.root))
        result = run_inventory(self.config)
        self.document_id = result.documents[0].document_id
        poppler_text = result.documents[0].pages[0].text
        _add_extractor_run(
            self.config.store,
            self.source_hash,
            "ocrmypdf-tesseract",
            "same",
            poppler_text,
            version="OCR fixture 1",
        )
        _add_extractor_run(
            self.config.store,
            self.source_hash,
            "docling-standard",
            "changed",
            poppler_text.replace("1,234.50", "1,284.50") + "\nRaster label",
            version="Layout fixture 1",
        )
        self.workspace = LocalWorkspace(self.config)
        self.application = LibraryApplication(self.workspace)
        self.manager = LocalLibraryManager(explicit_config=self.config)
        self.library_id = self.manager.app_summary().active_library_id
        assert self.library_id is not None
        self.token = "test-token-that-must-never-appear"
        self.origin = "http://127.0.0.1:43111"
        self.client = TestClient(
            create_app(
                self.application,
                library_manager=self.manager,
                launch_token=self.token,
                allowed_origins={self.origin},
            )
        )
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Origin": self.origin,
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_library_search_groups_diff_artifacts_and_render_cache(self) -> None:
        app_summary = self.client.get("/api/v1/app", headers=self.headers)
        libraries = self.client.get("/api/v1/libraries", headers=self.headers)
        detail = self.client.get(
            f"/api/v1/libraries/{self.library_id}", headers=self.headers
        )
        scoped_workspace = self.client.get(
            f"/api/v1/libraries/{self.library_id}/workspace",
            headers=self.headers,
        )
        self.assertEqual(app_summary.json()["active_library_id"], self.library_id)
        self.assertEqual(libraries.json()["items"][0]["status"], "ready")
        self.assertEqual(detail.json()["collections"][0]["collection_id"], "sample")
        self.assertEqual(scoped_workspace.json()["library_id"], self.library_id)

        workspace = self.client.get("/api/v1/workspace", headers=self.headers)
        self.assertEqual(workspace.status_code, 200)
        self.assertEqual(workspace.json()["document_count"], 1)

        documents = self.client.get("/api/v1/documents", headers=self.headers)
        self.assertEqual(documents.status_code, 200)
        self.assertEqual(
            documents.json()["items"][0]["source_path_hint"], "sample:hybrid.pdf"
        )

        search = self.client.get(
            "/api/v1/search",
            params={"query": "balance", "mode": "literal"},
            headers=self.headers,
        )
        self.assertEqual(search.status_code, 200)
        self.assertEqual(search.json()["items"][0]["page"], 1)

        groups_response = self.client.get(
            f"/api/v1/documents/{self.document_id}/pages/1/groups",
            headers=self.headers,
        )
        self.assertEqual(groups_response.status_code, 200)
        groups = groups_response.json()["groups"]
        equivalent = next(group for group in groups if len(group["runs"]) == 2)
        changed = next(group for group in groups if len(group["runs"]) == 1)
        self.assertEqual(
            {run["extractor_id"] for run in equivalent["runs"]},
            {"poppler", "ocrmypdf-tesseract"},
        )
        raw = equivalent["runs"][1]["raw_artifacts"][0]
        artifact = self.client.get(
            f"/api/v1/artifacts/{raw['artifact_id']}", headers=self.headers
        )
        self.assertEqual(artifact.status_code, 200)
        self.assertIn(b"synthetic expert output", artifact.content)

        comparison = self.client.post(
            "/api/v1/comparisons",
            headers=self.headers,
            json={
                "document_id": self.document_id,
                "page": 1,
                "left_run_ref": equivalent["representative_run_ref"],
                "right_run_ref": changed["representative_run_ref"],
            },
        )
        self.assertEqual(comparison.status_code, 200)
        payload = comparison.json()
        self.assertFalse(payload["equivalent"])
        self.assertEqual(
            payload["comparison_algorithm_version"], "word_numeric_diff_v1"
        )
        self.assertEqual(len(payload["numeric_discrepancies"]), 1)
        self.assertEqual(
            payload["numeric_discrepancies"][0]["left_values"], ["1,234.50"]
        )
        self.assertEqual(
            payload["numeric_discrepancies"][0]["right_values"], ["1,284.50"]
        )

        first_render = self.client.get(
            f"/api/v1/documents/{self.document_id}/pages/1/render",
            headers=self.headers,
        )
        second_render = self.client.get(
            f"/api/v1/documents/{self.document_id}/pages/1/render",
            headers=self.headers,
        )
        self.assertEqual(first_render.status_code, 200)
        self.assertEqual(first_render.headers["content-type"], "image/png")
        self.assertEqual(first_render.content, second_render.content)
        render_runs = list(
            self.config.store.glob(
                f"blobs/{self.source_hash[:2]}/{self.source_hash}/runs/page-render/*/run.json"
            )
        )
        self.assertEqual(len(render_runs), 1)
        render_record = json.loads(render_runs[0].read_text(encoding="utf-8"))
        self.assertEqual(render_record["source_sha256"], self.source_hash)
        after = self.pdf.stat()
        self.assertEqual(
            (after.st_size, after.st_mtime_ns),
            (self.source_stat.st_size, self.source_stat.st_mtime_ns),
        )
        self.assertEqual(
            hashlib.sha256(self.pdf.read_bytes()).hexdigest(), self.source_hash
        )

    def test_auth_origin_bounds_and_missing_identities(self) -> None:
        missing = self.client.get("/api/v1/workspace")
        wrong = self.client.get(
            "/api/v1/workspace", headers={"Authorization": "Bearer wrong"}
        )
        foreign = self.client.get(
            "/api/v1/workspace",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Origin": "https://attacker.invalid",
            },
        )
        self.assertEqual(missing.status_code, 401)
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(foreign.status_code, 403)
        self.assertNotIn(self.token, missing.text + wrong.text + foreign.text)

        bad_limit = self.client.get(
            "/api/v1/documents", params={"limit": 101}, headers=self.headers
        )
        self.assertEqual(bad_limit.status_code, 400)
        missing_page = self.client.get(
            f"/api/v1/documents/{self.document_id}/pages/2",
            headers=self.headers,
        )
        self.assertEqual(missing_page.status_code, 404)
        with self.assertRaises(NotFoundError):
            self.application.artifact("artifact:" + "0" * 64)

    def test_contract_schema_has_bearer_security(self) -> None:
        schema = create_contract_app().openapi()
        self.assertIn("HTTPBearer", schema["components"]["securitySchemes"])
        self.assertIn("/api/v1/comparisons", schema["paths"])
        self.assertIn("/api/v1/libraries/{library_id}", schema["paths"])


class DependencyDirectionTest(unittest.TestCase):
    def test_application_modules_do_not_import_framework_or_adapter_code(self) -> None:
        root = Path(__file__).parents[1] / "src" / "doc_evidence" / "application"
        forbidden = ("fastapi", "uvicorn", "doc_evidence.adapters", "doc_evidence.api")
        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            imported = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.append(node.module)
            self.assertFalse(
                [name for name in imported if name.startswith(forbidden)],
                path.name,
            )

    def test_shared_representative_payloads_validate_in_python(self) -> None:
        path = Path(__file__).parents[1] / "contracts" / "representative-payloads.json"
        payloads = json.loads(path.read_text(encoding="utf-8"))
        WorkspaceSummary.model_validate(payloads["workspace"])
        ComparisonResult.model_validate(payloads["comparison"])


class ComparisonUnitTest(unittest.TestCase):
    def test_exact_and_numeric_replacement_contract(self) -> None:
        request = ComparisonRequest(
            document_id="sha256:" + "a" * 64,
            page=1,
            left_run_ref="run:left",
            right_run_ref="run:right",
        )
        self.assertEqual(request.page, 1)


if __name__ == "__main__":
    unittest.main()
