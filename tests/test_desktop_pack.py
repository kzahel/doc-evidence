from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from doc_evidence.desktop_pack import load_baseline_pack
from doc_evidence.errors import RequestError


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class DesktopPackTest(unittest.TestCase):
    def _pack(self, root: Path) -> dict[str, Any]:
        tools = []
        for name in ("ocrmypdf", "pdfinfo", "pdftoppm", "pdftotext", "tesseract"):
            content = f"tool:{name}".encode()
            path = root / "bin" / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(content)
            tools.append(
                {
                    "tool_id": name,
                    "version": "1",
                    "executable": f"bin/{name}",
                    "sha256": _sha256(content),
                    "license_concluded": "Apache-2.0",
                    "component_id": f"tool-{name}",
                }
            )
        languages = []
        for language in ("eng", "deu", "osd"):
            content = f"language:{language}".encode()
            path = root / "tessdata" / f"{language}.traineddata"
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(content)
            languages.append(
                {
                    "language": language,
                    "path": f"tessdata/{language}.traineddata",
                    "sha256": _sha256(content),
                    "license_concluded": "Apache-2.0",
                }
            )
        support_content = b"tessedit_create_hocr 1"
        support_path = root / "tessdata" / "configs" / "hocr"
        support_path.parent.mkdir(exist_ok=True)
        support_path.write_bytes(support_content)
        return {
            "schema_version": "doc-evidence.extractor-pack-manifest.v1",
            "pack_id": "baseline-macos-arm64",
            "version": "2026.08.1",
            "platform": "macos",
            "architecture": "arm64",
            "tools": tools,
            "language_data": languages,
            "support_files": [
                {
                    "path": "tessdata/configs/hocr",
                    "sha256": _sha256(support_content),
                    "component_id": "homebrew-tesseract",
                }
            ],
            "python_components": ["ocrmypdf==17.8.1", "pypdfium2==5.5.0"],
            "native_libraries": [],
        }

    def test_valid_pack_returns_manifest_bound_identity(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = self._pack(root)
            encoded = json.dumps(manifest).encode()
            (root / "pack-manifest.json").write_bytes(encoded)

            identity = load_baseline_pack(root)

            self.assertEqual(identity.pack_id, "baseline-macos-arm64")
            self.assertEqual(identity.version, "2026.08.1")
            self.assertEqual(identity.manifest_sha256, _sha256(encoded))

    def test_pack_rejects_tampered_and_repeated_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = self._pack(root)
            manifest_path = root / "pack-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            (root / "bin" / "pdfinfo").write_bytes(b"tampered")
            with self.assertRaisesRegex(RequestError, "identity changed"):
                load_baseline_pack(root)

            manifest = self._pack(root)
            manifest["support_files"][0]["path"] = "bin/pdfinfo"
            manifest["support_files"][0]["sha256"] = manifest["tools"][1]["sha256"]
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(RequestError, "path is repeated"):
                load_baseline_pack(root)

    def test_pack_rejects_paths_outside_its_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            manifest = self._pack(root)
            manifest["support_files"][0]["path"] = "../outside"
            (root / "pack-manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8"
            )

            with self.assertRaisesRegex(RequestError, "manifest is invalid"):
                load_baseline_pack(root)


if __name__ == "__main__":
    unittest.main()
