from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from doc_evidence.desktop_acceptance import (
    _collection_hashes,
    _long_fixture_path,
    _runtime_environment,
    _write_text_pdf,
    run_acceptance,
    run_cli,
)


class DesktopAcceptanceFixtureTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_text_pdf_and_collection_hashes_are_deterministic_and_bounded(self) -> None:
        primary = self.root / "primary"
        secondary = self.root / "secondary"
        _write_text_pdf(primary / "one.pdf", "Evidence (one) \\ source")
        _write_text_pdf(secondary / "two.pdf", "Evidence two")

        before = _collection_hashes({"primary": primary, "secondary": secondary})
        (self.root / "app-home").mkdir()
        (self.root / "app-home" / "state.json").write_text("changed")

        self.assertEqual(
            _collection_hashes({"primary": primary, "secondary": secondary}),
            before,
        )
        self.assertEqual(set(before), {"primary/one.pdf", "secondary/two.pdf"})
        self.assertTrue((primary / "one.pdf").read_bytes().startswith(b"%PDF-1.4"))

    def test_windows_fixture_path_exceeds_legacy_path_limit(self) -> None:
        path = _long_fixture_path(self.root / "collection", enabled=True)

        self.assertGreater(len(str(path)), 280)
        self.assertEqual(path.name, "image scan 12345.pdf")

    def test_macos_runtime_environment_is_explicit_and_isolated(self) -> None:
        runtime_root = self.root / "runtime"
        writable_root = self.root / "writable"

        environment = _runtime_environment(
            runtime_root,
            writable_root,
            platform_name="macos",
            runtime_token="runtime-secret",
            control_token="control-secret",
        )

        self.assertEqual(environment["DOC_EVIDENCE_DESKTOP_PLATFORM"], "macos")
        self.assertEqual(environment["DOC_EVIDENCE_DESKTOP_ARCHITECTURE"], "arm64")
        self.assertEqual(environment["PYTHONNOUSERSITE"], "1")
        self.assertIn(str(runtime_root / "baseline-pack" / "bin"), environment["PATH"])
        self.assertNotIn("PYTHONPATH", environment)

    def test_acceptance_rejects_an_unpacked_interpreter(self) -> None:
        runtime_root = self.root / "runtime"
        (runtime_root / "baseline-pack").mkdir(parents=True)
        (runtime_root / "bundle-manifest.json").write_text(
            '{"platform":"macos","architecture":"arm64"}'
        )
        (runtime_root / "baseline-pack" / "pack-manifest.json").write_text("{}")

        with self.assertRaisesRegex(
            RuntimeError,
            "packaged Python interpreter",
        ):
            run_acceptance(
                runtime_root,
                platform_name="macos",
                timeout_seconds=60,
            )

    def test_cli_rejects_unbounded_timeout_before_runtime_access(self) -> None:
        with self.assertRaisesRegex(SystemExit, "between 60 and 3600"):
            run_cli(
                [
                    "--runtime-root",
                    str(self.root / "missing"),
                    "--platform",
                    "macos",
                    "--timeout-seconds",
                    "59",
                ]
            )


if __name__ == "__main__":
    unittest.main()
