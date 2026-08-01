from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from doc_evidence.adapters.local_libraries import LocalLibraryManager
from doc_evidence.app_home import LibraryRegistry, resolve_application_home
from doc_evidence.persistence import ensure_library_database


def _write_config(root: Path, name: str) -> Path:
    library = root / name
    source = library / "documents"
    source.mkdir(parents=True)
    path = library / "case.yaml"
    path.write_text(
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
    return path


class LocalLibraryManagerTest(unittest.TestCase):
    def test_empty_home_and_distinct_registered_libraries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            registry = LibraryRegistry(
                resolve_application_home(
                    environ={"DOC_EVIDENCE_HOME": str(root / "app-home")}
                )
            )
            empty = LocalLibraryManager(registry=registry)
            self.assertIsNone(empty.app_summary().active_library_id)
            self.assertEqual(empty.libraries().items, [])

            first_descriptor = registry.register_config(
                _write_config(root, "first"),
                name="First Library",
            )
            second_descriptor = registry.register_config(
                _write_config(root, "second"),
                name="Second Library",
            )
            for descriptor in (first_descriptor, second_descriptor):
                _known, _managed, config = registry.open(descriptor.library_id)
                ensure_library_database(
                    config,
                    library_id=descriptor.library_id,
                    name=descriptor.name,
                )

            manager = LocalLibraryManager(registry=registry)
            libraries = manager.libraries()

            self.assertEqual(len(libraries.items), 2)
            self.assertEqual(
                {item.library_id for item in libraries.items},
                {first_descriptor.library_id, second_descriptor.library_id},
            )
            self.assertTrue(all(item.status == "ready" for item in libraries.items))
            manager.activate(first_descriptor.library_id)
            self.assertEqual(
                manager.app_summary().active_library_id,
                first_descriptor.library_id,
            )
            first_workspace = manager.application(
                first_descriptor.library_id
            ).workspace()
            self.assertEqual(first_workspace.library_id, first_descriptor.library_id)
            self.assertEqual(first_workspace.library_name, "First Library")


if __name__ == "__main__":
    unittest.main()
