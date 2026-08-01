from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from doc_evidence.app_home import LibraryRegistry, resolve_application_home
from doc_evidence.errors import ApplicationStateError


def _write_config(root: Path, name: str = "case") -> Path:
    source = root / "documents"
    source.mkdir(exist_ok=True)
    config = root / f"{name}.yaml"
    config.write_text(
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
    return config


class ApplicationHomeTest(unittest.TestCase):
    def test_resolution_precedence_and_platform_defaults(self) -> None:
        explicit = resolve_application_home(
            environ={"DOC_EVIDENCE_HOME": "/tmp/doc-evidence-explicit"},
            desktop_host_root=Path("/tmp/doc-evidence-desktop"),
            platform_name="darwin",
            home_directory=Path("/Users/example"),
        )
        self.assertEqual(explicit.root, Path("/tmp/doc-evidence-explicit").resolve())
        self.assertEqual(explicit.source, "environment")

        desktop = resolve_application_home(
            environ={},
            desktop_host_root=Path("/tmp/doc-evidence-desktop"),
            platform_name="darwin",
            home_directory=Path("/Users/example"),
        )
        self.assertEqual(desktop.root, Path("/tmp/doc-evidence-desktop").resolve())
        self.assertEqual(desktop.source, "desktop_host")

        macos = resolve_application_home(
            environ={},
            platform_name="darwin",
            home_directory=Path("/Users/example"),
        )
        self.assertEqual(
            macos.root,
            Path("/Users/example/Library/Application Support/doc-evidence").resolve(),
        )
        self.assertEqual(macos.source, "platform_default")

    def test_relative_override_is_rejected(self) -> None:
        with self.assertRaisesRegex(ApplicationStateError, "must be an absolute"):
            resolve_application_home(environ={"DOC_EVIDENCE_HOME": "relative/app-home"})

    def test_registry_adopts_without_rewriting_external_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            external = root / "external"
            external.mkdir()
            config_path = _write_config(external)
            before = config_path.read_bytes()
            app_root = root / "app-home"
            registry = LibraryRegistry(
                resolve_application_home(environ={"DOC_EVIDENCE_HOME": str(app_root)})
            )

            descriptor = registry.register_config(config_path, name="Example Library")
            repeated = registry.register_config(config_path, name="Ignored Name")
            state = registry.load()

            self.assertEqual(config_path.read_bytes(), before)
            self.assertEqual(descriptor.library_id, repeated.library_id)
            self.assertEqual(len(state.libraries), 1)
            self.assertEqual(state.default_library_id, descriptor.library_id)
            self.assertEqual(state.last_library_id, descriptor.library_id)
            self.assertTrue(descriptor.descriptor_path.is_file())
            _known, selected, config = registry.selected()
            self.assertEqual(selected.library_id, descriptor.library_id)
            self.assertEqual(config.path, config_path.resolve())

    def test_isolated_homes_do_not_share_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            external = root / "external"
            external.mkdir()
            config = _write_config(external)
            first = LibraryRegistry(
                resolve_application_home(
                    environ={"DOC_EVIDENCE_HOME": str(root / "first")}
                )
            )
            second = LibraryRegistry(
                resolve_application_home(
                    environ={"DOC_EVIDENCE_HOME": str(root / "second")}
                )
            )

            first.register_config(config)

            self.assertEqual(len(first.load().libraries), 1)
            self.assertEqual(second.load().libraries, ())
            self.assertFalse(second.state_path.exists())

    def test_malformed_registry_blocks_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            registry = LibraryRegistry(
                resolve_application_home(
                    environ={"DOC_EVIDENCE_HOME": str(root / "app")}
                )
            )
            registry.state_path.parent.mkdir(parents=True)
            malformed = b'{"schema_version":1,"libraries":"lost"}\n'
            registry.state_path.write_bytes(malformed)

            with self.assertRaisesRegex(ApplicationStateError, "must be a list"):
                registry.load()

            self.assertEqual(registry.state_path.read_bytes(), malformed)

    def test_registry_identity_disagreement_blocks_opening(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            external = root / "external"
            external.mkdir()
            config = _write_config(external)
            registry = LibraryRegistry(
                resolve_application_home(
                    environ={"DOC_EVIDENCE_HOME": str(root / "app")}
                )
            )
            descriptor = registry.register_config(config)
            raw = descriptor.descriptor_path.read_text(encoding="utf-8")
            descriptor.descriptor_path.write_text(
                raw.replace(descriptor.library_id, "wrong-library-id"),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ApplicationStateError, "identity disagree"):
                registry.selected()

    def test_unknown_registry_fields_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            registry = LibraryRegistry(
                resolve_application_home(
                    environ={"DOC_EVIDENCE_HOME": str(root / "app")}
                )
            )
            registry.state_path.parent.mkdir(parents=True)
            registry.state_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "default_library_id": None,
                        "last_library_id": None,
                        "libraries": [],
                        "unexpected": True,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ApplicationStateError, "unknown fields"):
                registry.load()


if __name__ == "__main__":
    unittest.main()
