from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from doc_evidence.adapters.local_desktop import LocalDesktopLibraryControl
from doc_evidence.adapters.local_libraries import LocalLibraryManager
from doc_evidence.api.app import create_app
from doc_evidence.app_home import LibraryRegistry, resolve_application_home
from doc_evidence.contracts.desktop import (
    DESKTOP_ORIGIN,
    DesktopAddCollectionRequest,
    DesktopControlHandshake,
    DesktopCreateLibraryRequest,
    DesktopRegisterLibraryRequest,
)
from doc_evidence.errors import ApplicationStateError

RUNTIME_TOKEN = "3" * 64
CONTROL_TOKEN = "4" * 64


def _write_adopted_config(root: Path) -> Path:
    source = root / "documents"
    source.mkdir()
    path = root / ".doc-evidence.yaml"
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


class DesktopLibraryControlTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.registry = LibraryRegistry(
            resolve_application_home(
                environ={"DOC_EVIDENCE_HOME": str(self.root / "app-home")}
            )
        )
        self.manager = LocalLibraryManager(registry=self.registry)
        self.control = LocalDesktopLibraryControl(
            registry=self.registry,
            manager=self.manager,
        )

    def tearDown(self) -> None:
        self.manager.shutdown()
        self.temporary.cleanup()

    def test_create_managed_library_keeps_sources_read_only_and_paths_private(
        self,
    ) -> None:
        source = self.root / "external" / "documents"
        source.mkdir(parents=True)
        document = source / "record.txt"
        document.write_text("immutable evidence\n", encoding="utf-8")
        before = hashlib.sha256(document.read_bytes()).hexdigest()

        result = self.control.create_managed(
            DesktopCreateLibraryRequest(
                source_path=str(source),
                name="Evidence Library",
            )
        )

        self.assertEqual(result.outcome, "created")
        self.assertEqual(result.store_mode, "managed")
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.collection_count, 1)
        self.assertNotIn(str(source), result.model_dump_json())
        self.assertEqual(hashlib.sha256(document.read_bytes()).hexdigest(), before)
        known, descriptor, config = self.registry.selected()
        self.assertEqual(known.library_id, result.library_id)
        self.assertTrue(descriptor.descriptor_path.is_file())
        self.assertTrue((config.store / "doc-evidence.sqlite").is_file())
        self.assertTrue(config.store.is_relative_to(self.registry.home.root))
        self.assertEqual(config.collections[0].source, source.resolve())

    def test_register_existing_is_idempotent_and_does_not_rewrite_config(self) -> None:
        external = self.root / "external-adopted"
        external.mkdir()
        config = _write_adopted_config(external)
        before = config.read_bytes()

        first = self.control.register_existing(
            DesktopRegisterLibraryRequest(
                config_path=str(config),
                name="Adopted Library",
            )
        )
        second = self.control.register_existing(
            DesktopRegisterLibraryRequest(config_path=str(config))
        )

        self.assertEqual(first.outcome, "registered")
        self.assertEqual(second.outcome, "already_registered")
        self.assertEqual(first.library_id, second.library_id)
        self.assertEqual(config.read_bytes(), before)
        with self.assertRaisesRegex(ApplicationStateError, "managed library"):
            self.control.add_collection(
                DesktopAddCollectionRequest(
                    library_id=first.library_id,
                    source_path=str(self.root),
                )
            )

    def test_parent_replacement_requires_confirmation_and_preserves_identity(
        self,
    ) -> None:
        parent = self.root / "external-parent"
        child = parent / "year-2025"
        child.mkdir(parents=True)
        created = self.control.create_managed(
            DesktopCreateLibraryRequest(
                source_path=str(child),
                name="Tax Library",
            )
        )
        _known, _descriptor, before_config = self.registry.selected()
        before_hash = before_config.config_hash

        preflight = self.control.add_collection(
            DesktopAddCollectionRequest(
                library_id=created.library_id,
                source_path=str(parent),
            )
        )
        self.assertEqual(preflight.preflight_kind, "replace_children")
        self.assertTrue(preflight.confirmation_required)
        self.assertFalse(preflight.changed)
        self.assertEqual(self.registry.selected()[2].config_hash, before_hash)

        changed = self.control.add_collection(
            DesktopAddCollectionRequest(
                library_id=created.library_id,
                source_path=str(parent),
                confirm_parent_replacement=True,
            )
        )
        self.assertTrue(changed.changed)
        self.assertFalse(changed.confirmation_required)
        _known, descriptor, config = self.registry.selected()
        self.assertEqual(descriptor.library_id, created.library_id)
        self.assertEqual(len(config.collections), 1)
        self.assertEqual(config.collections[0].source, parent.resolve())
        self.assertNotEqual(config.config_hash, before_hash)

    def test_control_routes_require_host_credential_and_reject_origins(self) -> None:
        source = self.root / "api-source"
        source.mkdir()
        app = create_app(
            None,
            library_manager=self.manager,
            launch_token=RUNTIME_TOKEN,
            allowed_origins={DESKTOP_ORIGIN},
            host_control_token=CONTROL_TOKEN,
            desktop_control_handshake=DesktopControlHandshake(
                capabilities=["create_managed_library"]
            ),
            desktop_library_control=self.control,
        )
        client = TestClient(app)
        endpoint = "/desktop-control/v1/libraries/create-managed"
        body = {"source_path": str(source), "name": "API Library"}
        runtime = client.post(
            endpoint,
            headers={"Authorization": f"Bearer {RUNTIME_TOKEN}"},
            json=body,
        )
        foreign_origin = client.post(
            endpoint,
            headers={
                "Authorization": f"Bearer {CONTROL_TOKEN}",
                "Origin": DESKTOP_ORIGIN,
            },
            json=body,
        )
        created = client.post(
            endpoint,
            headers={"Authorization": f"Bearer {CONTROL_TOKEN}"},
            json=body,
        )

        self.assertEqual(runtime.status_code, 401)
        self.assertEqual(foreign_origin.status_code, 403)
        self.assertEqual(created.status_code, 200)
        self.assertNotIn(str(source), created.text)
        self.assertNotIn(RUNTIME_TOKEN, runtime.text + foreign_origin.text)
        self.assertNotIn(CONTROL_TOKEN, created.text)


if __name__ == "__main__":
    unittest.main()
