from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout

from doc_evidence.cli import main


class DoctorCommandTest(unittest.TestCase):
    def test_doctor_json_has_expected_contract(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            status = main(["doctor", "--json"])

        self.assertEqual(status, 0)
        report = json.loads(output.getvalue())
        self.assertIn("doc_evidence_version", report)
        self.assertIn("python", report)
        self.assertIn("platform", report)
        self.assertIn("tools", report)
        self.assertIn("pdftotext", report["tools"])


if __name__ == "__main__":
    unittest.main()
