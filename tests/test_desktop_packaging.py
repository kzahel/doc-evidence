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
    _files_containing,
    _load_inputs,
    create_unsigned_dmg,
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
            "f5fefe5c38b22be54318b12ccd742d75b4e4192f4530457f8dee0873d59db5e8",
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


if __name__ == "__main__":
    unittest.main()
