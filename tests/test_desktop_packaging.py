from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from doc_evidence.desktop_packaging import (
    BUILD_INPUTS_SCHEMA,
    _archive_path,
    _audit_symlinks,
    _dependency_license_files,
    _files_containing,
    _installed_homebrew_bottle,
    _load_inputs,
    _python_license_conclusion,
    _python_native_inventory,
    _requires_corresponding_source,
    _rust_license_expression,
    _spdx_license,
    compliance_root,
    create_unsigned_dmg,
    generate_compliance_preflight,
    repository_root,
    sha256_tree,
    stage_runtime,
    unsigned_dmg_path,
)


class DesktopPackagingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = repository_root()

    def test_build_inputs_pin_exact_standalone_python_archive(self) -> None:
        inputs = _load_inputs(self.root)

        self.assertEqual(inputs["schema_version"], BUILD_INPUTS_SCHEMA)
        self.assertEqual(inputs["python"]["version"], "3.12.12")
        self.assertEqual(inputs["python"]["build"], "20260114")
        self.assertEqual(
            inputs["python"]["sha256"],
            "ed1f300bd3b45aa481d887b2dd8e12f989b583f67755c219a6092756a09b609f",
        )
        self.assertEqual(
            _archive_path(inputs, Path("/cache")).name,
            "cpython-3.12.12+20260114-aarch64-apple-darwin-install_only_stripped.tar.gz",
        )
        baseline = inputs["baseline_pack"]
        self.assertEqual(baseline["pack_id"], "baseline-macos-arm64")
        self.assertEqual(baseline["version"], "2026.08.1")
        self.assertEqual(
            baseline["requirements_sha256"],
            "8aae7fe4803b8023ccbfffd35bc4be092e5dc38ad13f1c4fe7cd14637a44baff",
        )
        self.assertEqual(
            baseline["python_components"],
            {"ocrmypdf": "17.8.1", "pypdfium2": "5.5.0"},
        )
        self.assertEqual(
            set(baseline["tools"]),
            {"pdfinfo", "pdftoppm", "pdftotext", "tesseract"},
        )
        self.assertEqual(set(baseline["language_data"]), {"eng", "deu", "osd"})
        self.assertEqual(set(baseline["support_data"]), {"configs/hocr", "configs/txt"})

    def test_tree_identity_includes_paths_bytes_and_symlink_targets(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "one").write_text("value", encoding="utf-8")
            (root / "link").symlink_to("one")
            original = sha256_tree(root)
            (root / "link").unlink()
            (root / "link").symlink_to("missing")
            changed_link = sha256_tree(root)
            (root / "link").unlink()
            (root / "one").write_text("different", encoding="utf-8")

            self.assertNotEqual(original, changed_link)
            self.assertNotEqual(original, sha256_tree(root))

    def test_symlink_audit_rejects_escape(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "runtime"
            root.mkdir()
            (root / "escape").symlink_to(root.parent)

            with self.assertRaisesRegex(RuntimeError, "symlink escapes"):
                _audit_symlinks(root)

    def test_build_host_path_scan_reports_bounded_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "payload").write_bytes(b"prefix /opt/homebrew suffix")

            self.assertEqual(
                _files_containing(root, ["/opt/homebrew", "/unseen"]),
                {"/opt/homebrew": ["payload"]},
            )

    def test_stage_refuses_to_overwrite_without_explicit_replace(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            existing = Path(raw) / "desktop-runtime"
            existing.mkdir()

            with self.assertRaisesRegex(RuntimeError, "already exists"):
                stage_runtime(root=self.root, destination=existing)

    def test_build_entrypoint_is_tracked_executable(self) -> None:
        script = self.root / "scripts" / "build-macos-desktop"

        self.assertTrue(script.is_file())
        self.assertTrue(os.access(script, os.X_OK))
        inputs = json.loads(
            (self.root / "desktop" / "packaging" / "macos-arm64.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(inputs["platform"], "macos")
        self.assertEqual(inputs["architecture"], "arm64")

    def test_unsigned_dmg_path_and_replacement_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = unsigned_dmg_path(root)
            self.assertEqual(
                output,
                root
                / "results"
                / "desktop"
                / "distribution"
                / "Doc-Evidence_0.4.0_aarch64-unsigned.dmg",
            )
            output.parent.mkdir(parents=True)
            output.write_bytes(b"existing")
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                create_unsigned_dmg(root / "missing.app", output, repository=root)

    def test_compliance_preflight_is_explicit_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = compliance_root(root)
            self.assertEqual(
                output.name,
                "Doc-Evidence_0.4.0_compliance-preflight",
            )
            output.mkdir(parents=True)
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                generate_compliance_preflight(
                    root / "missing.app",
                    output,
                    repository=root,
                )
        self.assertEqual(_spdx_license("Apache License 2.0"), ("Apache-2.0", False))
        self.assertEqual(
            _spdx_license("BSD-3-Clause, dependency licenses"),
            ("NOASSERTION", True),
        )

    def test_homebrew_bottle_requires_exact_version_and_platform(self) -> None:
        info = {
            "formulae": [
                {
                    "versions": {"stable": "2.0.0"},
                    "revision": 1,
                    "bottle": {
                        "stable": {
                            "files": {
                                "arm64_tahoe": {
                                    "url": "https://ghcr.io/v2/example",
                                    "sha256": "a" * 64,
                                },
                                "sonoma": {
                                    "url": "https://ghcr.io/v2/wrong-arch",
                                    "sha256": "b" * 64,
                                },
                            }
                        }
                    },
                }
            ]
        }
        receipt = {
            "arch": "arm64",
            "source": {"path": "/cache/internal/packages.arm64_tahoe.jws.json"},
        }

        self.assertEqual(
            _installed_homebrew_bottle(
                info,
                name="example",
                version="2.0.0_1",
                receipt=receipt,
            ),
            {
                "bottle_tag": "arm64_tahoe",
                "bottle_url": "https://ghcr.io/v2/example",
                "bottle_sha256": "a" * 64,
            },
        )
        self.assertIsNone(
            _installed_homebrew_bottle(
                info,
                name="example",
                version="2.0.0",
                receipt=receipt,
            )
        )

    def test_dependency_license_discovery_and_rust_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "LICENCE").write_text("British spelling", encoding="utf-8")
            (root / "LICENSE-MIT").write_text("MIT", encoding="utf-8")
            (root / "README.md").write_text("Not a license", encoding="utf-8")

            self.assertEqual(
                [path.name for path in _dependency_license_files(root)],
                ["LICENCE", "LICENSE-MIT"],
            )

        self.assertEqual(
            _rust_license_expression("MIT/Apache-2.0"),
            "MIT OR Apache-2.0",
        )
        self.assertEqual(_rust_license_expression("MPL-2.0"), "MPL-2.0")
        self.assertTrue(_requires_corresponding_source("LGPL-2.1-or-later"))
        self.assertTrue(_requires_corresponding_source("MPL-2.0"))
        self.assertFalse(_requires_corresponding_source("Apache-2.0 OR MIT"))
        self.assertEqual(
            _python_license_conclusion(
                {"name": "pi_heif", "version": "1.4.0"},
                {
                    "python_license_conclusions": {
                        "pi-heif": {
                            "version": "1.4.0",
                            "license_concluded": "BSD-3-Clause AND LGPL-3.0-only",
                        }
                    }
                },
            ),
            "BSD-3-Clause AND LGPL-3.0-only",
        )

    def test_python_native_inventory_distinguishes_nested_libraries(self) -> None:
        native = [
            {"path": "python/bin/python3", "dependencies": []},
            {
                "path": "python/lib/python3.12/site-packages/demo/_core.so",
                "dependencies": [],
            },
            {
                "path": "python/lib/python3.12/site-packages/demo/.dylibs/libx.dylib",
                "dependencies": ["/usr/lib/libSystem.B.dylib"],
            },
        ]
        manifest = [
            {
                "path": item["path"],
                "component_id": "cpython" if index == 0 else "python-demo",
                "sha256": str(index) * 64,
                "bytes": index + 1,
            }
            for index, item in enumerate(native)
        ]

        records = _python_native_inventory(native, manifest)

        self.assertFalse(records[0]["wheel_owned"])
        self.assertFalse(records[1]["nested_dependency"])
        self.assertTrue(records[2]["nested_dependency"])


if __name__ == "__main__":
    unittest.main()
