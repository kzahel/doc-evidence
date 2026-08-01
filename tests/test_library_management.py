from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from doc_evidence.application.library_management import preflight_collection_root
from doc_evidence.config import load_config


class CollectionPreflightTest(unittest.TestCase):
    def test_parent_child_sibling_and_store_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            child = root / "records" / "2023"
            sibling = root / "records-2024"
            nested = child / "forms"
            store = root / "derived"
            child.mkdir(parents=True)
            sibling.mkdir()
            nested.mkdir()
            store.mkdir()
            config_path = root / "case.yaml"
            config_path.write_text(
                """
schema_version: 1
collections:
  - id: records-2023
    source: records/2023
store:
  path: derived
""".lstrip(),
                encoding="utf-8",
            )
            config = load_config(config_path)

            parent = preflight_collection_root(config, root / "records")
            covered = preflight_collection_root(config, nested)
            same = preflight_collection_root(config, child)
            separate = preflight_collection_root(config, sibling)
            overlapping_store = preflight_collection_root(config, store)

            self.assertEqual(parent.kind, "replace_children")
            self.assertEqual(parent.affected_collection_ids, ("records-2023",))
            self.assertEqual(covered.kind, "already_covered")
            self.assertEqual(same.kind, "same_root")
            self.assertEqual(separate.kind, "add_sibling")
            self.assertEqual(overlapping_store.kind, "store_overlap")


if __name__ == "__main__":
    unittest.main()
