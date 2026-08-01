from __future__ import annotations

import json
import tempfile
import unittest
from importlib import resources
from pathlib import Path

from doc_evidence.benchmark import _comparison, load_suite, score_review
from doc_evidence.extraction import ExtractionResult, NormalizedPage
from doc_evidence.structured import docling_pages, marker_pages


def _result(identifier: str, text: str) -> ExtractionResult:
    page = NormalizedPage(1, text, len(text), len(text.replace(" ", "")))
    return ExtractionResult(
        extractor_id=identifier,
        run_id=f"{identifier}:test",
        run_key="test",
        artifact_path="",
        status="ok",
        pages=(page,),
        warnings=(),
        cache_hit=False,
        runtime_seconds=0.1,
        descriptor={},
        raw_artifacts={},
    )


class Phase2Test(unittest.TestCase):
    def test_packaged_phase2_schemas_match_documented_schemas(self) -> None:
        root = Path(__file__).parents[1]
        for name in ("benchmark-suite.schema.json", "review.schema.json"):
            documented = json.loads(
                (root / "schemas" / name).read_text(encoding="utf-8")
            )
            packaged = json.loads(
                resources.files("doc_evidence")
                .joinpath(f"schema_files/{name}")
                .read_text(encoding="utf-8")
            )
            self.assertEqual(packaged, documented)

    def test_disagreement_does_not_claim_ground_truth(self) -> None:
        comparison = _comparison(
            _result("left", "Balance 1,234.50"),
            _result("right", "Balance 1,284.50"),
            1,
        )
        kinds = {flag["kind"] for flag in comparison["flags"]}
        self.assertIn("numeric_token_disagreement", kinds)
        self.assertNotIn("winner", comparison)

    def test_normalizes_docling_and_marker_page_trees(self) -> None:
        docling = {
            "pages": {"1": {}},
            "body": {"children": [{"$ref": "#/texts/0"}]},
            "texts": [
                {
                    "self_ref": "#/texts/0",
                    "text": "Invoice 42",
                    "prov": [{"page_no": 1}],
                }
            ],
            "tables": [],
        }
        pages, tables = docling_pages(docling)
        self.assertEqual(pages[0].text, "Invoice 42")
        self.assertEqual(tables, 0)

        marker = {
            "block_type": "Document",
            "children": [
                {
                    "block_type": "Page",
                    "id": "/page/0/Page/1",
                    "children": [
                        {
                            "id": "/page/0/Text/1",
                            "block_type": "Text",
                            "html": "Amount <b>42</b>",
                        }
                    ],
                },
                {
                    "block_type": "Page",
                    "id": "/page/1/Page/2",
                    "children": [
                        {
                            "id": "/page/1/Text/2",
                            "block_type": "Text",
                            "html": "Second page",
                        }
                    ],
                },
            ],
        }
        pages, _ = marker_pages(marker)
        self.assertEqual(pages[0].text, "Amount 42")
        self.assertEqual(pages[1].text, "Second page")

    def test_suite_validation_and_human_scorecard(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            suite_path = root / "suite.yaml"
            suite_path.write_text(
                """
schema_version: 1
suite_id: sample
extractors: [poppler, marker-fast]
documents:
  - document_id: sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    document_class: statement
    pages: [1]
""".lstrip(),
                encoding="utf-8",
            )
            suite, suite_hash = load_suite(suite_path)
            self.assertEqual(suite["suite_id"], "sample")
            self.assertEqual(len(suite_hash), 64)

            report_path = root / "report.json"
            report_path.write_text(
                json.dumps({"suite_id": "sample", "benchmark_run_id": "run-1"}),
                encoding="utf-8",
            )
            ratings = [
                {
                    "document_id": "sha256:" + "a" * 64,
                    "document_class": "statement",
                    "page": page,
                    "extractor_id": "marker-fast",
                    "reviewed": True,
                    "text_accuracy": 1,
                    "numeric_fidelity": 1,
                    "reading_order": 2,
                    "table_structure": None,
                    "contains_invented_values": page == 1,
                    "notes": "calibration",
                }
                for page in range(1, 6)
            ]
            review_path = root / "review.json"
            review_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "suite_id": "sample",
                        "benchmark_run_id": "run-1",
                        "reviewer": "tester",
                        "created_at": None,
                        "ratings": ratings,
                    }
                ),
                encoding="utf-8",
            )
            _, scorecard = score_review(report_path, review_path)
            self.assertEqual(
                scorecard["scorecards"][0]["recommendation"],
                "corroborating-only-review-retirement",
            )
            self.assertFalse(scorecard["scorecards"][0]["automatic_policy_change"])


if __name__ == "__main__":
    unittest.main()
