from __future__ import annotations

import hashlib
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from doc_evidence.app_home import legacy_library_id
from doc_evidence.catalog import build_catalog
from doc_evidence.config import load_config
from doc_evidence.errors import CatalogError
from doc_evidence.inventory import run_inventory
from doc_evidence.persistence import ensure_library_database
from tests.helpers import write_minimal_pdf


def _write_config(root: Path, source: str = "documents/child") -> Path:
    config = root / "case.yaml"
    config.write_text(
        f"""
schema_version: 1
collections:
  - id: sample
    source: {source}
store:
  path: derived
""".lstrip(),
        encoding="utf-8",
    )
    return config


@unittest.skipUnless(
    shutil.which("pdfinfo") and shutil.which("pdftotext"),
    "Poppler tools are required for persistence integration",
)
class LibraryPersistenceTest(unittest.TestCase):
    def test_interrupted_generation_keeps_prior_active(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "documents" / "child"
            source.mkdir(parents=True)
            write_minimal_pdf(source / "one.pdf", "first")
            config = load_config(_write_config(root))
            first = run_inventory(config)
            database = ensure_library_database(config)

            building = database.begin_generation(
                run_id="interrupted-generation",
                config_hash=config.config_hash,
                selected_collections=["sample"],
                started_at="2026-08-01T00:00:00Z",
                full_hash_verification=False,
            )

            self.assertEqual(database.active_generation_id(), first.generation_id)
            connection = database.connect(readonly=True)
            try:
                state = connection.execute(
                    "SELECT status FROM inventory_generations WHERE generation_id = ?",
                    (building,),
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(state, "building")

    def test_parent_scope_expansion_reuses_artifacts_and_stable_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            child = root / "documents" / "child"
            child.mkdir(parents=True)
            first_pdf = child / "one.pdf"
            write_minimal_pdf(first_pdf, "first evidence")
            config_path = _write_config(root)
            child_config = load_config(config_path)
            first = run_inventory(child_config)
            digest = hashlib.sha256(first_pdf.read_bytes()).hexdigest()
            run_path = next(
                child_config.store.glob(
                    f"blobs/{digest[:2]}/{digest}/runs/poppler/*/run.json"
                )
            )
            before = run_path.read_bytes()
            write_minimal_pdf(root / "documents" / "two.pdf", "second evidence")
            _write_config(root, source="documents")
            parent_config = load_config(config_path)

            expanded = run_inventory(parent_config)

            self.assertEqual(run_path.read_bytes(), before)
            self.assertEqual(expanded.summary["unique_documents"], 2)
            self.assertEqual(expanded.summary["poppler_cache_hits"], 1)
            connection = sqlite3.connect(expanded.catalog_path)
            try:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM content_objects"
                    ).fetchone()[0],
                    2,
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM run_pages").fetchone()[0],
                    2,
                )
            finally:
                connection.close()
            self.assertNotEqual(first.generation_id, expanded.generation_id)

    def test_legacy_catalog_import_is_read_only_and_projects_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "documents" / "child"
            source.mkdir(parents=True)
            write_minimal_pdf(source / "one.pdf", "legacy evidence")
            config = load_config(_write_config(root))
            result = run_inventory(config)
            legacy = config.store / "catalog.sqlite"
            build_catalog(result, legacy, enable_fts=True)
            legacy_before = legacy.read_bytes()
            database_path = config.store / "doc-evidence.sqlite"
            for suffix in ("", "-wal", "-shm"):
                (config.store / f"doc-evidence.sqlite{suffix}").unlink(missing_ok=True)

            database = ensure_library_database(config)

            self.assertEqual(legacy.read_bytes(), legacy_before)
            self.assertEqual(database.path, database_path)
            connection = database.connect(readonly=True)
            try:
                self.assertEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM content_objects"
                    ).fetchone()[0],
                    1,
                )
                self.assertGreaterEqual(
                    connection.execute(
                        "SELECT COUNT(*) FROM extraction_runs"
                    ).fetchone()[0],
                    1,
                )
            finally:
                connection.close()

    def test_database_identity_mismatch_blocks_opening(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "documents" / "child"
            source.mkdir(parents=True)
            write_minimal_pdf(source / "one.pdf", "identity")
            config = load_config(_write_config(root))
            run_inventory(config)

            with self.assertRaisesRegex(CatalogError, "identity disagree"):
                ensure_library_database(config, library_id="wrong-library-id")

            connection = sqlite3.connect(config.store / "doc-evidence.sqlite")
            try:
                stored = connection.execute(
                    "SELECT library_id FROM library_metadata"
                ).fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(stored, legacy_library_id(config.path))

    def test_schema_metadata_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "documents" / "child"
            source.mkdir(parents=True)
            config = load_config(_write_config(root))
            database = ensure_library_database(config)
            connection = database.connect(readonly=True)
            try:
                self.assertEqual(
                    connection.execute("PRAGMA user_version").fetchone()[0], 3
                )
                migrations = connection.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            finally:
                connection.close()
            self.assertEqual([row[0] for row in migrations], [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
