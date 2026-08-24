from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from doc_evidence.windows_desktop_packaging import (
    BUILD_INPUTS_SCHEMA,
    _load_inputs,
    audit_flat_pe_closure,
    build_inputs_path,
    extract_flat_zip_component,
    extract_poppler_component,
    extract_tesseract_component,
    repository_root,
    sha256_file,
    sha256_tree,
)
from doc_evidence.windows_pe import PE_X86_64_MACHINE, PortableExecutable


class WindowsDesktopPackagingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = repository_root()

    def test_inputs_pin_exact_runtime_tools_payloads_and_sources(self) -> None:
        inputs = _load_inputs(self.root)

        self.assertEqual(inputs["schema_version"], BUILD_INPUTS_SCHEMA)
        self.assertEqual(inputs["platform"], "windows")
        self.assertEqual(inputs["architecture"], "x86_64")
        self.assertEqual(inputs["python"]["version"], "3.12.12")
        self.assertEqual(inputs["python"]["build"], "20260114")
        self.assertEqual(
            inputs["python"]["sha256"],
            "65544affdc45a3755db3a08fd0b36c5b590bb49337b99a19b8840c33189fe75e",
        )
        baseline = inputs["baseline_pack"]
        self.assertEqual(baseline["pack_id"], "baseline-windows-x86_64")
        self.assertEqual(
            set(baseline["tools"]), {"pdfinfo", "pdftoppm", "pdftotext", "tesseract"}
        )
        self.assertEqual(
            {
                name: len(value["payload_sha256"])
                for name, value in baseline["native_components"].items()
            },
            {"msvc-runtime": 3, "poppler": 18, "tesseract": 34},
        )
        self.assertTrue(
            all(
                value["license_concluded"] == "NOASSERTION"
                and value["compliance_blocker"]
                for value in baseline["native_components"].values()
            )
        )
        self.assertEqual(
            set(baseline["language_data"]["files"]),
            {
                "tessdata-4.1.0/eng.traineddata",
                "tessdata-4.1.0/deu.traineddata",
                "tessdata-4.1.0/osd.traineddata",
            },
        )

    def test_manifest_rejects_unsafe_or_unresolved_payload_changes(self) -> None:
        document = json.loads(build_inputs_path(self.root).read_text(encoding="utf-8"))
        component = document["baseline_pack"]["native_components"]["poppler"]
        component["payload_sha256"]["../escape.dll"] = "a" * 64
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "inputs.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "unsafe"):
                _load_inputs(path=path)

        document = json.loads(build_inputs_path(self.root).read_text(encoding="utf-8"))
        component = document["baseline_pack"]["native_components"]["tesseract"]
        component.pop("compliance_blocker")
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "inputs.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "compliance blocker"):
                _load_inputs(path=path)

    def test_flat_pe_audit_requires_x64_and_complete_declared_closure(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "tool.exe").write_bytes(b"tool")
            (root / "owned.dll").write_bytes(b"owned")

            def inspect(path: Path) -> PortableExecutable:
                imports = (
                    ("owned.dll", "KERNEL32.dll", "api-ms-win-core-file-l1-1-0.dll")
                    if path.name == "tool.exe"
                    else ("KERNEL32.dll",)
                )
                return PortableExecutable(
                    machine=PE_X86_64_MACHINE,
                    format="PE32+",
                    imports=imports,
                    delay_imports=(),
                )

            with patch(
                "doc_evidence.windows_desktop_packaging.inspect_pe",
                side_effect=inspect,
            ):
                records = audit_flat_pe_closure(root, system_dlls=["KERNEL32.dll"])
            self.assertEqual(
                [record["path"] for record in records], ["owned.dll", "tool.exe"]
            )

            with (
                patch(
                    "doc_evidence.windows_desktop_packaging.inspect_pe",
                    return_value=PortableExecutable(
                        machine=PE_X86_64_MACHINE,
                        format="PE32+",
                        imports=("developer-only.dll",),
                        delay_imports=(),
                    ),
                ),
                self.assertRaisesRegex(RuntimeError, "developer-only.dll"),
            ):
                audit_flat_pe_closure(root, system_dlls=["KERNEL32.dll"])

    def test_poppler_extraction_selects_exact_payload_and_data_tree(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            data = root / "data"
            data.mkdir()
            (data / "COPYING").write_bytes(b"license")
            archive = root / "poppler.zip"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("poppler/Library/bin/pdfinfo.exe", b"binary")
                output.writestr("poppler/share/poppler/COPYING", b"license")
            component = {
                "archive": {
                    "sha256": sha256_file(archive),
                    "payload_root": "poppler/Library/bin",
                },
                "payload_sha256": {
                    "pdfinfo.exe": hashlib.sha256(b"binary").hexdigest()
                },
                "data_tree": {
                    "archive_root": "poppler/share/poppler",
                    "sha256": sha256_tree(data),
                    "file_count": 1,
                },
            }
            pack = root / "pack"

            binaries, data_files = extract_poppler_component(archive, component, pack)

            self.assertEqual([path.name for path in binaries], ["pdfinfo.exe"])
            self.assertEqual([path.name for path in data_files], ["COPYING"])
            self.assertEqual((pack / "bin" / "pdfinfo.exe").read_bytes(), b"binary")

    def test_flat_zip_extraction_rejects_collisions_and_selects_payload(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "component.vsix"
            with zipfile.ZipFile(archive, "w") as output:
                output.writestr("payload/msvcp140.dll", b"runtime")
                output.writestr("payload/unused.dll", b"unused")
            component = {
                "archive": {
                    "sha256": sha256_file(archive),
                    "payload_root": "payload",
                },
                "payload_sha256": {
                    "msvcp140.dll": hashlib.sha256(b"runtime").hexdigest()
                },
            }
            destination = root / "bin"

            files = extract_flat_zip_component(archive, component, destination)

            self.assertEqual([path.name for path in files], ["msvcp140.dll"])
            self.assertFalse((destination / "unused.dll").exists())
            with self.assertRaisesRegex(RuntimeError, "collision"):
                extract_flat_zip_component(archive, component, destination)

    def test_tesseract_extraction_uses_argument_safe_7zip_and_exact_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "installer.exe"
            archive.write_bytes(b"installer")
            component = {
                "archive": {"sha256": sha256_file(archive)},
                "payload_sha256": {
                    "tesseract.exe": hashlib.sha256(b"binary").hexdigest()
                },
                "support_data": {
                    "tessdata/configs/txt": hashlib.sha256(b"config").hexdigest()
                },
            }

            def extract(
                arguments: list[str | Path], **_: object
            ) -> subprocess.CompletedProcess[str]:
                output = Path(
                    next(
                        str(item)[2:]
                        for item in arguments
                        if str(item).startswith("-o")
                    )
                )
                (output / "tesseract.exe").write_bytes(b"binary")
                support = output / "tessdata" / "configs" / "txt"
                support.parent.mkdir(parents=True)
                support.write_bytes(b"config")
                return subprocess.CompletedProcess([str(item) for item in arguments], 0)

            with patch(
                "doc_evidence.windows_desktop_packaging._run", side_effect=extract
            ) as run:
                binaries, support = extract_tesseract_component(
                    archive,
                    component,
                    root / "pack",
                    seven_zip=root / "7z.exe",
                )

            arguments = run.call_args.args[0]
            self.assertEqual(arguments[:3], [root / "7z.exe", "x", "-y"])
            self.assertEqual([path.name for path in binaries], ["tesseract.exe"])
            self.assertEqual([path.name for path in support], ["txt"])
