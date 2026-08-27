from __future__ import annotations

import hashlib
import io
import json
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from doc_evidence.windows_desktop_packaging import (
    BUILD_INPUTS_SCHEMA,
    _excluded_baseline_distributions,
    _included_locked_requirements,
    _load_inputs,
    _locked_requirements,
    _read_ready_line,
    application_executable_path,
    audit_flat_pe_closure,
    audit_runtime_pe_closure,
    authenticode_status,
    baseline_environment,
    build_application,
    build_inputs_path,
    extract_flat_zip_component,
    extract_language_data,
    extract_poppler_component,
    extract_python_runtime,
    extract_tesseract_component,
    nsis_installer_path,
    prune_python_runtime,
    repository_root,
    sha256_file,
    sha256_tree,
    stage_pypdfium2_licenses,
)
from doc_evidence.windows_pe import PE_X86_64_MACHINE, PortableExecutable


class WindowsDesktopPackagingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = repository_root()

    def test_tree_hash_uses_platform_independent_path_order(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "Z.txt").write_bytes(b"upper")
            (root / "a.txt").write_bytes(b"lower")
            expected = hashlib.sha256()
            for relative, content in (("Z.txt", b"upper"), ("a.txt", b"lower")):
                expected.update(b"F\0" + relative.encode() + b"\0")
                expected.update(hashlib.sha256(content).digest())

            self.assertEqual(sha256_tree(root), expected.hexdigest())

    def test_empty_sidecar_output_is_reported_as_early_exit(self) -> None:
        process = subprocess.Popen(
            [sys.executable, "-c", "pass"],
            stdout=subprocess.PIPE,
            text=True,
        )
        try:
            with self.assertRaisesRegex(RuntimeError, "exited before"):
                _read_ready_line(process, timeout_seconds=5)
        finally:
            process.wait(timeout=5)

    def test_baseline_environment_supplies_isolated_windows_home(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            with patch.dict("os.environ", {"SystemRoot": r"C:\Windows"}, clear=True):
                environment = baseline_environment(root / "runtime", root / "writable")

            self.assertEqual(
                environment["USERPROFILE"], str(root / "writable" / "user-home")
            )
            self.assertTrue((root / "writable" / "user-home").is_dir())

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
            _excluded_baseline_distributions(inputs),
            {"pi-heif"},
        )
        self.assertEqual(
            baseline["requirements_sha256"],
            sha256_file(self.root / "desktop/packaging/baseline-requirements.txt"),
        )
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

    def test_excluded_optional_requirement_is_absent_from_pack_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            requirements = Path(raw) / "requirements.txt"
            requirements.write_text(
                "ocrmypdf==17.8.1\npi_heif==1.4.0\npillow==12.3.0\n",
                encoding="utf-8",
            )

            self.assertEqual(
                _included_locked_requirements(requirements, {"pi-heif"}),
                ["ocrmypdf==17.8.1", "pillow==12.3.0"],
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

    def test_runtime_pe_audit_distinguishes_loader_and_package_private_files(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            python = root / "python"
            package = python / "Lib" / "site-packages" / "example"
            pack = root / "baseline-pack" / "bin"
            for directory in (python, package, pack):
                directory.mkdir(parents=True, exist_ok=True)
            files = {
                python / "python.exe": ("python312.dll", "private.dll"),
                python / "python312.dll": ("KERNEL32.dll",),
                package / "private.dll": (),
                pack / "tool.exe": ("python312.dll",),
            }
            for path in files:
                path.write_bytes(b"pe")

            def inspect(path: Path) -> PortableExecutable:
                return PortableExecutable(
                    machine=PE_X86_64_MACHINE,
                    format="PE32+",
                    imports=files[path],
                    delay_imports=(),
                )

            with patch(
                "doc_evidence.windows_desktop_packaging.inspect_pe",
                side_effect=inspect,
            ):
                records = audit_runtime_pe_closure(root, system_dlls=["KERNEL32.dll"])

            python_record = next(
                item for item in records if item["path"] == "python/python.exe"
            )
            self.assertEqual(
                [item["kind"] for item in python_record["dependencies"]],
                ["bundled-loader-path", "bundled-package-private"],
            )
            tool_record = next(
                item for item in records if item["path"] == "baseline-pack/bin/tool.exe"
            )
            self.assertEqual(
                tool_record["dependencies"][0]["path"], "python/python312.dll"
            )

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

    def test_language_extraction_selects_only_declared_regular_files(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "tessdata.tar.gz"
            language_bytes = b"trained"
            with tempfile.TemporaryDirectory() as source_raw:
                source = Path(source_raw) / "tessdata-1"
                source.mkdir()
                (source / "eng.traineddata").write_bytes(language_bytes)
                (source / "unused.traineddata").write_bytes(b"unused")
                with tarfile.open(archive, "w:gz") as output:
                    output.add(source, arcname="tessdata-1")
            language = {
                "archive": {"sha256": sha256_file(archive)},
                "files": {
                    "tessdata-1/eng.traineddata": hashlib.sha256(
                        language_bytes
                    ).hexdigest()
                },
            }

            records = extract_language_data(archive, language, root / "pack")

            self.assertEqual([item["language"] for item in records], ["eng"])
            self.assertEqual(
                (root / "pack" / "tessdata" / "eng.traineddata").read_bytes(),
                language_bytes,
            )
            self.assertFalse(
                (root / "pack" / "tessdata" / "unused.traineddata").exists()
            )

    def test_windows_ocrmypdf_launcher_is_relocatable_and_argument_safe(self) -> None:
        source = (
            self.root / "desktop" / "packaging" / "windows-ocrmypdf-launcher.rs"
        ).read_text(encoding="utf-8")

        self.assertIn('join("python").join("python.exe")', source)
        self.assertIn('.arg("-m")', source)
        self.assertIn('.arg("ocrmypdf")', source)
        self.assertIn(".args(env::args_os().skip(1))", source)
        self.assertNotIn("cmd.exe", source.casefold())

    def test_windows_build_entrypoint_is_tracked_and_executable(self) -> None:
        entrypoint = self.root / "scripts" / "build-windows-desktop"

        self.assertTrue(entrypoint.stat().st_mode & stat.S_IXUSR)
        self.assertIn(
            "doc_evidence.windows_desktop_packaging",
            entrypoint.read_text(encoding="utf-8"),
        )
        module = (
            self.root / "src/doc_evidence/windows_desktop_packaging.py"
        ).read_text(encoding="utf-8")
        self.assertGreater(
            module.rfind('if __name__ == "__main__"'),
            module.rfind("def audit_runtime_pe_closure"),
        )

    def test_windows_build_resolves_the_npm_command_shim(self) -> None:
        with (
            patch("doc_evidence.windows_desktop_packaging._require_windows_host"),
            patch(
                "doc_evidence.windows_desktop_packaging.shutil.which",
                return_value=r"C:\Program Files\nodejs\npm.cmd",
            ) as which,
            patch(
                "doc_evidence.windows_desktop_packaging._run",
                side_effect=RuntimeError("stop after npm"),
            ) as run,
            patch("doc_evidence.windows_desktop_packaging.os.name", "nt"),
            self.assertRaisesRegex(RuntimeError, "stop after npm"),
        ):
            build_application(root=self.root)

        which.assert_called_once_with("npm.cmd")
        self.assertEqual(run.call_args.args[0][0], r"C:\Program Files\nodejs\npm.cmd")

    def test_authenticode_path_uses_environment_not_command_interpolation(self) -> None:
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                '{"Status":"NotSigned","StatusMessage":"not signed","Subject":null}'
            ),
            stderr="",
        )
        with (
            patch(
                "doc_evidence.windows_desktop_packaging.shutil.which",
                return_value=r"C:\Program Files\PowerShell\7\pwsh.exe",
            ),
            patch(
                "doc_evidence.windows_desktop_packaging._run",
                return_value=completed,
            ) as run,
        ):
            result = authenticode_status(Path(r"C:\candidate with spaces.exe"))

        arguments = run.call_args.args[0]
        environment = run.call_args.kwargs["environment"]
        self.assertEqual(result["status"], "NotSigned")
        self.assertNotIn("candidate with spaces", " ".join(arguments))
        self.assertEqual(
            environment["DOC_EVIDENCE_AUTHENTICODE_PATH"],
            str(Path(r"C:\candidate with spaces.exe").resolve()),
        )
        self.assertIn("$env:DOC_EVIDENCE_AUTHENTICODE_PATH", arguments[-1])

    def test_windows_tauri_package_is_current_user_nsis(self) -> None:
        config = json.loads(
            (self.root / "desktop/src-tauri/tauri.windows.conf.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual(config["bundle"]["targets"], ["nsis"])
        self.assertEqual(
            config["bundle"]["windows"],
            {
                "allowDowngrades": False,
                "webviewInstallMode": {
                    "type": "embedBootstrapper",
                    "silent": False,
                },
                "nsis": {
                    "installMode": "currentUser",
                    "languages": ["English"],
                    "displayLanguageSelector": False,
                    "compression": "lzma",
                },
            },
        )
        self.assertEqual(
            application_executable_path(self.root).name,
            "doc-evidence-desktop.exe",
        )
        self.assertEqual(
            nsis_installer_path(self.root).name,
            "Doc Evidence_0.5.0_x64-setup.exe",
        )

    def test_python_extraction_rejects_links_and_windows_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "python.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                first = tarfile.TarInfo("python/File.txt")
                first.size = 1
                output.addfile(first, fileobj=io.BytesIO(b"a"))
                second = tarfile.TarInfo("python/file.TXT")
                second.size = 1
                output.addfile(second, fileobj=io.BytesIO(b"b"))
            with self.assertRaisesRegex(RuntimeError, "Windows path"):
                extract_python_runtime(archive, root / "output")

            archive = root / "linked.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                link = tarfile.TarInfo("python/link")
                link.type = tarfile.SYMTYPE
                link.linkname = "../escape"
                output.addfile(link)
            with self.assertRaisesRegex(RuntimeError, "unsupported member"):
                extract_python_runtime(archive, root / "linked-output")

    def test_python_pruning_removes_packagers_scripts_and_gui_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            python = Path(raw) / "python"
            removable = (
                "Lib/test/example.py",
                "Lib/site-packages/pip/__init__.py",
                "Lib/site-packages/PIL/_imagingtk.cp312-win_amd64.pyd",
                "Lib/site-packages/doc_evidence/windows_desktop_packaging.py",
                "Lib/site-packages/example/__pycache__/value.pyc",
                "DLLs/_tkinter.pyd",
                "Scripts/ocrmypdf.exe",
            )
            for relative in removable:
                path = python / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"unused")
            keep = python / "Lib/site-packages/doc_evidence/desktop_sidecar.py"
            keep.parent.mkdir(parents=True, exist_ok=True)
            keep.write_bytes(b"keep")

            prune_python_runtime(python)

            self.assertTrue(keep.is_file())
            self.assertFalse(
                any((python / relative).exists() for relative in removable)
            )

    def test_locked_requirement_inventory_is_version_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            requirements = Path(raw) / "requirements.txt"
            requirements.write_text(
                "example==1.2.3 \\\n+    --hash=sha256:" + "a" * 64 + "\n",
                encoding="utf-8",
            )

            self.assertEqual(_locked_requirements(requirements), ["example==1.2.3"])

    def test_pypdfium_license_staging_selects_declared_license_trees(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            archive = root / "pypdfium2.tar.gz"
            with tarfile.open(archive, "w:gz") as output:
                for name, content in (
                    ("source/LICENSES/Apache-2.0.txt", b"license"),
                    ("source/BUILD_LICENSES/BSD.txt", b"build license"),
                    ("source/src/private.py", b"not selected"),
                ):
                    member = tarfile.TarInfo(name)
                    member.size = len(content)
                    output.addfile(member, io.BytesIO(content))
            baseline = {
                "source_archives": [
                    {
                        "component_id": "python-pypdfium2",
                        "cache_name": archive.name,
                        "url": "https://example.invalid/pypdfium2.tar.gz",
                        "sha256": sha256_file(archive),
                    }
                ]
            }
            runtime = root / "runtime"
            runtime.mkdir()

            copied = stage_pypdfium2_licenses(runtime, baseline, cache=root)

            self.assertEqual(len(copied), 2)
            self.assertFalse(
                (runtime / "baseline-pack/licenses/python/pypdfium2/src").exists()
            )
