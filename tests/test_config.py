from __future__ import annotations

import tempfile
import unittest
from importlib import resources
from pathlib import Path

from doc_evidence.config import load_config
from doc_evidence.errors import ConfigError


class ConfigTest(unittest.TestCase):
    def test_packaged_config_schema_matches_documented_schema(self) -> None:
        repository_schema = (
            Path(__file__).parents[1] / "schemas" / "config.schema.json"
        ).read_text(encoding="utf-8")
        packaged_schema = (
            resources.files("doc_evidence")
            .joinpath("schema_files/config.schema.json")
            .read_text(encoding="utf-8")
        )
        self.assertEqual(packaged_schema, repository_schema)

    def test_loads_relative_paths_and_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "documents").mkdir()
            config_path = root / "case.yaml"
            config_path.write_text(
                """
schema_version: 1
collections:
  - id: sample
    source: documents
store:
  path: derived
""".lstrip(),
                encoding="utf-8",
            )

            config = load_config(config_path)

            self.assertEqual(
                config.collections[0].source, (root / "documents").resolve()
            )
            self.assertEqual(config.store, (root / "derived").resolve())
            self.assertEqual(config.extraction.baseline, "poppler")
            self.assertTrue(config.search.sqlite_fts)
            self.assertEqual(len(config.config_hash), 64)

    def test_rejects_store_inside_source_collection(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "documents").mkdir()
            config_path = root / "case.yaml"
            config_path.write_text(
                """
schema_version: 1
collections:
  - id: sample
    source: documents
store:
  path: documents/derived
""".lstrip(),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "may not overlap"):
                load_config(config_path)

    def test_rejects_unknown_configuration_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "documents").mkdir()
            config_path = root / "case.yaml"
            config_path.write_text(
                """
schema_version: 1
collections:
  - id: sample
    source: documents
store:
  path: derived
surprise: true
""".lstrip(),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "Additional properties"):
                load_config(config_path)

    def test_rejects_overlapping_source_collections(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            (root / "documents" / "child").mkdir(parents=True)
            config_path = root / "case.yaml"
            config_path.write_text(
                """
schema_version: 1
collections:
  - id: parent
    source: documents
  - id: child
    source: documents/child
store:
  path: derived
""".lstrip(),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ConfigError, "collections may not overlap"):
                load_config(config_path)


if __name__ == "__main__":
    unittest.main()
