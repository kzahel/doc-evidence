from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from doc_evidence.config import CollectionConfig, load_config
from doc_evidence.discovery import discover_files
from doc_evidence.errors import ConfigError
from doc_evidence.platform_paths import (
    WINDOWS_DRIVE_FIXED,
    WINDOWS_FILE_ATTRIBUTE_OFFLINE,
    path_contains,
    paths_overlap,
    resolve_collection_root,
    same_path,
)


class PlatformPathIdentityTest(unittest.TestCase):
    def test_windows_identity_normalizes_case_and_separators(self) -> None:
        left = r"C:\Evidence\Résumé\2024"
        right = r"c:/evidence/RÉSUMÉ/2024/."

        self.assertTrue(same_path(left, right, kind="windows"))
        self.assertTrue(
            path_contains(r"c:\evidence", r"C:/Evidence/Résumé", kind="windows")
        )

    def test_windows_identity_does_not_confuse_prefixes_or_drives(self) -> None:
        self.assertFalse(
            paths_overlap(
                r"C:\Evidence",
                r"C:\Evidence-Archive",
                kind="windows",
            )
        )
        self.assertFalse(paths_overlap(r"C:\Evidence", r"D:\Evidence", kind="windows"))

    def test_windows_identity_handles_long_aliases_without_rewriting_them(self) -> None:
        left = "C:\\" + "\\".join(
            f"segment-{index}-" + ("x" * 32) for index in range(7)
        )
        right = left.swapcase().replace("\\", "/")

        self.assertGreater(len(left), 260)
        self.assertTrue(same_path(left, right, kind="windows"))

    def test_posix_identity_remains_case_sensitive(self) -> None:
        self.assertFalse(same_path("/Evidence", "/evidence", kind="posix"))


@unittest.skipUnless(os.name == "nt", "Windows collection policy")
class WindowsCollectionPolicyTest(unittest.TestCase):
    def test_fixed_drive_accepts_unicode_spaces_and_case_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "Résumé 資料"
            source.mkdir()

            resolved, issue = resolve_collection_root(source)

            self.assertIsNone(issue)
            self.assertTrue(resolved.is_dir())
            self.assertTrue(same_path(resolved, Path(str(source).swapcase())))

    def test_non_fixed_and_offline_roots_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            source = Path(temporary_directory)
            with patch(
                "doc_evidence.platform_paths._windows_drive_type",
                return_value=WINDOWS_DRIVE_FIXED + 1,
            ):
                _resolved, issue = resolve_collection_root(source)
            self.assertIn("local fixed drive", issue or "")

            with patch(
                "doc_evidence.platform_paths.file_attributes",
                return_value=WINDOWS_FILE_ATTRIBUTE_OFFLINE,
            ):
                _resolved, issue = resolve_collection_root(source)
            self.assertIn("cloud or offline", issue or "")

    def test_case_aliases_overlap_when_loading_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "Résumé"
            source.mkdir()
            config_path = root / "case.yaml"
            config_path.write_text(
                yaml.safe_dump(
                    {
                        "schema_version": 1,
                        "collections": [
                            {"id": "one", "source": str(source)},
                            {"id": "two", "source": str(source).swapcase()},
                        ],
                        "store": {"path": str(root / "derived")},
                    },
                    sort_keys=False,
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "collections may not overlap"):
                load_config(config_path)

    def test_selected_junction_is_rejected_and_nested_junction_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "source"
            outside = root / "outside"
            source.mkdir()
            outside.mkdir()
            (source / "visible.pdf").write_bytes(b"visible")
            (outside / "hidden.pdf").write_bytes(b"hidden")
            junction = source / "linked"
            subprocess.run(
                [
                    "cmd.exe",
                    "/d",
                    "/c",
                    "mklink",
                    "/J",
                    str(junction),
                    str(outside),
                ],
                check=True,
                capture_output=True,
                text=True,
            )

            _resolved, issue = resolve_collection_root(junction)
            self.assertIsNotNone(issue)
            self.assertIn("reparse point", issue or "")

            warnings: list[dict[str, str]] = []
            discovered = discover_files(
                CollectionConfig(
                    id="documents",
                    source=source,
                    include=("**/*",),
                    exclude=(),
                ),
                warnings,
            )

            self.assertEqual(
                [item.relative_path for item in discovered], ["visible.pdf"]
            )
            self.assertEqual(
                warnings,
                [
                    {
                        "collection_id": "documents",
                        "path": "linked",
                        "warning": "reparse-point directory skipped",
                    }
                ],
            )


if __name__ == "__main__":
    unittest.main()
