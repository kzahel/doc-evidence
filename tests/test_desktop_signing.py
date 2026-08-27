import json
import tempfile
import unittest
from pathlib import Path

from doc_evidence.desktop_signing import (
    refresh_signed_runtime_manifests,
    sha256_file,
)


class DesktopSigningManifestTests(unittest.TestCase):
    def test_refresh_rebinds_pack_and_bundle_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            runtime = Path(raw)
            pack = runtime / "baseline-pack"
            (pack / "bin").mkdir(parents=True)
            tool = pack / "bin" / "tool"
            tool.write_bytes(b"unsigned")
            runtime_manifest = runtime / "runtime-manifest.json"
            runtime_manifest.write_text("{}\n", encoding="utf-8")
            pack_manifest = pack / "pack-manifest.json"
            pack_manifest.write_text(
                json.dumps(
                    {
                        "pack_id": "baseline-test",
                        "version": "1",
                        "tools": [{"executable": "bin/tool", "sha256": "0" * 64}],
                        "language_data": [],
                        "support_files": [],
                        "native_libraries": [],
                    }
                ),
                encoding="utf-8",
            )
            bundle_manifest = runtime / "bundle-manifest.json"
            paths = [
                pack_manifest.relative_to(runtime).as_posix(),
                tool.relative_to(runtime).as_posix(),
                runtime_manifest.relative_to(runtime).as_posix(),
            ]
            bundle_manifest.write_text(
                json.dumps(
                    {
                        "runtime_manifest_sha256": "0" * 64,
                        "extractor_packs": [],
                        "files": [
                            {
                                "path": path,
                                "bytes": 0,
                                "sha256": "0" * 64,
                                "component_id": "test",
                            }
                            for path in paths
                        ],
                    }
                ),
                encoding="utf-8",
            )

            tool.write_bytes(b"signed")
            result = refresh_signed_runtime_manifests(runtime)

            refreshed_pack = json.loads(pack_manifest.read_text(encoding="utf-8"))
            refreshed_bundle = json.loads(bundle_manifest.read_text(encoding="utf-8"))
            self.assertEqual(refreshed_pack["tools"][0]["sha256"], sha256_file(tool))
            self.assertEqual(
                refreshed_bundle["extractor_packs"][0]["manifest_sha256"],
                result["pack_manifest_sha256"],
            )
            self.assertEqual(
                {item["path"] for item in refreshed_bundle["files"]}, set(paths)
            )

    def test_refresh_rejects_file_set_changes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            runtime = Path(raw)
            pack = runtime / "baseline-pack"
            pack.mkdir()
            (runtime / "runtime-manifest.json").write_text("{}", encoding="utf-8")
            (pack / "pack-manifest.json").write_text(
                json.dumps(
                    {
                        "pack_id": "baseline-test",
                        "version": "1",
                        "tools": [],
                        "language_data": [],
                        "support_files": [],
                        "native_libraries": [],
                    }
                ),
                encoding="utf-8",
            )
            (runtime / "bundle-manifest.json").write_text(
                json.dumps(
                    {
                        "runtime_manifest_sha256": "0" * 64,
                        "extractor_packs": [],
                        "files": [],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "file set changed"):
                refresh_signed_runtime_manifests(runtime)
