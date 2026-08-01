from __future__ import annotations

import json
import tomllib
import unittest
from importlib import resources
from pathlib import Path

from jsonschema import Draft202012Validator


class DesktopPackagingContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).parents[1]

    def test_project_packages_declare_apache_2(self) -> None:
        project = tomllib.loads(
            (self.root / "pyproject.toml").read_text(encoding="utf-8")
        )
        frontend = json.loads(
            (self.root / "web" / "package.json").read_text(encoding="utf-8")
        )
        lock_root = json.loads(
            (self.root / "web" / "package-lock.json").read_text(encoding="utf-8")
        )["packages"][""]
        desktop = json.loads(
            (self.root / "desktop" / "package.json").read_text(encoding="utf-8")
        )
        desktop_lock_root = json.loads(
            (self.root / "desktop" / "package-lock.json").read_text(encoding="utf-8")
        )["packages"][""]
        rust = tomllib.loads(
            (self.root / "desktop" / "src-tauri" / "Cargo.toml").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(project["project"]["license"], "Apache-2.0")
        self.assertEqual(frontend["license"], "Apache-2.0")
        self.assertEqual(lock_root["license"], "Apache-2.0")
        self.assertEqual(desktop["license"], "Apache-2.0")
        self.assertEqual(desktop_lock_root["license"], "Apache-2.0")
        self.assertEqual(rust["package"]["license"], "Apache-2.0")
        license_text = (self.root / "LICENSE").read_text(encoding="utf-8")
        self.assertIn("Apache License", license_text)
        self.assertIn("Version 2.0, January 2004", license_text)

    def test_desktop_versions_and_identity_cannot_drift(self) -> None:
        project = tomllib.loads(
            (self.root / "pyproject.toml").read_text(encoding="utf-8")
        )
        rust = tomllib.loads(
            (self.root / "desktop" / "src-tauri" / "Cargo.toml").read_text(
                encoding="utf-8"
            )
        )
        tauri = json.loads(
            (self.root / "desktop" / "src-tauri" / "tauri.conf.json").read_text(
                encoding="utf-8"
            )
        )
        expected = project["project"]["version"]
        self.assertEqual(rust["package"]["version"], expected)
        self.assertEqual(tauri["version"], expected)
        self.assertEqual(tauri["productName"], "Doc Evidence")
        self.assertEqual(tauri["identifier"], "io.github.kzahel.doc-evidence")
        self.assertEqual(tauri["bundle"]["macOS"]["minimumSystemVersion"], "13.0")

    def test_packaged_desktop_schemas_match_and_are_valid(self) -> None:
        for name in (
            "desktop-bundle-manifest.schema.json",
            "extractor-pack-manifest.schema.json",
        ):
            documented = json.loads(
                (self.root / "schemas" / name).read_text(encoding="utf-8")
            )
            packaged = json.loads(
                resources.files("doc_evidence")
                .joinpath(f"schema_files/{name}")
                .read_text(encoding="utf-8")
            )
            self.assertEqual(packaged, documented)
            Draft202012Validator.check_schema(documented)

    def test_manifest_schemas_reject_unreviewed_or_escaping_values(self) -> None:
        digest = "a" * 64
        bundle_schema = json.loads(
            (self.root / "schemas" / "desktop-bundle-manifest.schema.json").read_text(
                encoding="utf-8"
            )
        )
        bundle = {
            "schema_version": "doc-evidence.desktop-bundle-manifest.v1",
            "product": "Doc Evidence",
            "version": "0.4.0",
            "identifier": "io.github.kzahel.doc-evidence",
            "platform": "macos",
            "architecture": "arm64",
            "python_version": "3.12.11",
            "frontend_sha256": digest,
            "runtime_manifest_sha256": digest,
            "extractor_packs": [],
            "components": [
                {
                    "component_id": "pkg:generic/doc-evidence@0.4.0",
                    "name": "doc-evidence",
                    "version": "0.4.0",
                    "license_concluded": "Apache-2.0",
                    "source_url": "https://example.invalid/doc-evidence",
                    "license_files": ["licenses/doc-evidence/LICENSE"],
                    "bundled_paths": ["runtime/site-packages/doc_evidence"],
                }
            ],
            "files": [
                {
                    "path": "runtime/site-packages/doc_evidence/__init__.py",
                    "bytes": 10,
                    "sha256": digest,
                    "component_id": "pkg:generic/doc-evidence@0.4.0",
                }
            ],
        }
        validator = Draft202012Validator(bundle_schema)
        validator.validate(bundle)
        bundle["components"][0]["license_concluded"] = ""
        self.assertTrue(list(validator.iter_errors(bundle)))
        bundle["components"][0]["license_concluded"] = "Apache-2.0"
        bundle["files"][0]["path"] = "../outside"
        self.assertTrue(list(validator.iter_errors(bundle)))


if __name__ == "__main__":
    unittest.main()
