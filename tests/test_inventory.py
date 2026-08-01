from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from doc_evidence.catalog import list_duplicate_groups, search_catalog
from doc_evidence.config import load_config
from doc_evidence.inventory import run_inventory
from tests.helpers import write_minimal_pdf


@unittest.skipUnless(
    shutil.which("pdfinfo") and shutil.which("pdftotext"),
    "Poppler tools are required for the integration test",
)
class InventoryIntegrationTest(unittest.TestCase):
    def test_inventory_cache_duplicates_catalog_and_search(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "documents"
            source.mkdir()
            first = source / "first.pdf"
            exact_copy = source / "exact-copy.pdf"
            text_variant = source / "text-variant.pdf"
            blank = source / "blank.pdf"
            notes = source / "notes.txt"

            write_minimal_pdf(first, "Hello Evidence 123", producer="first")
            shutil.copyfile(first, exact_copy)
            write_minimal_pdf(
                text_variant,
                "Hello Evidence 123",
                producer="different bytes",
            )
            write_minimal_pdf(blank, None, producer="blank")
            notes.write_text("not a PDF\n", encoding="utf-8")
            original_hash = hashlib.sha256(first.read_bytes()).hexdigest()

            config_path = root / "case.yaml"
            config_path.write_text(
                """
schema_version: 1
collections:
  - id: sample
    source: documents
    include:
      - "**/*"
store:
  path: derived
extraction:
  baseline: poppler
  ocr_when: image_only
  layout_when: complex
  normalized_text_duplicates: true
search:
  sqlite_fts: true
  vector_index: false
""".lstrip(),
                encoding="utf-8",
            )
            config = load_config(config_path)

            first_result = run_inventory(config)
            summary = first_result.summary
            self.assertEqual(summary["discovered_files"], 5)
            self.assertEqual(summary["indexed_source_files"], 5)
            self.assertEqual(summary["unique_documents"], 4)
            self.assertEqual(summary["pdf_source_files"], 4)
            self.assertEqual(summary["unique_pdf_documents"], 3)
            self.assertEqual(summary["pdf_source_pages"], 4)
            self.assertEqual(summary["unique_pdf_pages"], 3)
            self.assertEqual(summary["embedded_text_pdf_documents"], 2)
            self.assertEqual(summary["image_only_pdf_documents"], 1)
            self.assertEqual(summary["byte_duplicate_groups"], 1)
            self.assertEqual(summary["normalized_text_duplicate_groups"], 1)
            self.assertEqual(summary["poppler_cache_hits"], 0)
            self.assertEqual(summary["path_errors"], 0)
            self.assertEqual(
                hashlib.sha256(first.read_bytes()).hexdigest(), original_hash
            )

            root_schema = (
                Path(__file__).parents[1] / "schemas" / "manifest-record.schema.json"
            )
            validator = Draft202012Validator(
                json.loads(root_schema.read_text(encoding="utf-8"))
            )
            for line in first_result.manifest_path.read_text(
                encoding="utf-8"
            ).splitlines():
                validator.validate(json.loads(line))

            literal_results = search_catalog(
                config.store, "Evidence 123", mode="literal"
            )
            self.assertEqual(len(literal_results), 2)
            fts_results = search_catalog(config.store, "Evidence", mode="fts")
            self.assertEqual(len(fts_results), 2)

            duplicate_groups = list_duplicate_groups(config.store)
            self.assertEqual(len(duplicate_groups), 2)
            self.assertEqual(
                {group["kind"] for group in duplicate_groups},
                {"byte", "normalized_text"},
            )

            second_result = run_inventory(config)
            self.assertEqual(second_result.summary["poppler_cache_hits"], 3)
            self.assertEqual(second_result.summary["poppler_cache_misses"], 0)
            self.assertEqual(
                hashlib.sha256(first.read_bytes()).hexdigest(), original_hash
            )


if __name__ == "__main__":
    unittest.main()
