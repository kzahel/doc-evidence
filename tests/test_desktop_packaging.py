from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path

from doc_evidence.desktop_packaging import (
    BUILD_INPUTS_SCHEMA,
    WHEEL_NATIVE_COMPONENTS_SCHEMA,
    _archive_path,
    _audit_symlinks,
    _dependency_license_files,
    _excluded_baseline_distributions,
    _files_containing,
    _included_locked_requirements,
    _installed_homebrew_bottle,
    _load_inputs,
    _python_binary_compliance_record,
    _python_native_inventory,
    _recover_rust_license_files,
    _requires_corresponding_source,
    _rust_license_expression,
    _spdx_license,
    _unreconciled_nested_native,
    compliance_root,
    create_unsigned_dmg,
    generate_compliance_preflight,
    repository_root,
    sha256_tree,
    stage_runtime,
    unsigned_dmg_path,
    wheel_native_components_path,
)


class DesktopPackagingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = repository_root()

    def test_build_inputs_pin_exact_standalone_python_archive(self) -> None:
        inputs = _load_inputs(self.root)

        self.assertEqual(inputs["schema_version"], BUILD_INPUTS_SCHEMA)
        self.assertEqual(inputs["python"]["version"], "3.12.12")
        self.assertEqual(inputs["python"]["build"], "20260114")
        self.assertEqual(
            inputs["python"]["sha256"],
            "ed1f300bd3b45aa481d887b2dd8e12f989b583f67755c219a6092756a09b609f",
        )
        self.assertEqual(
            _archive_path(inputs, Path("/cache")).name,
            "cpython-3.12.12+20260114-aarch64-apple-darwin-install_only_stripped.tar.gz",
        )
        baseline = inputs["baseline_pack"]
        self.assertEqual(baseline["pack_id"], "baseline-macos-arm64")
        self.assertEqual(baseline["version"], "2026.08.1")
        self.assertEqual(
            baseline["requirements_sha256"],
            "8aae7fe4803b8023ccbfffd35bc4be092e5dc38ad13f1c4fe7cd14637a44baff",
        )
        self.assertEqual(
            baseline["python_components"],
            {"ocrmypdf": "17.8.1", "pypdfium2": "5.5.0"},
        )
        self.assertEqual(
            _excluded_baseline_distributions(inputs),
            {"pi-heif"},
        )
        self.assertEqual(
            set(baseline["tools"]),
            {"pdfinfo", "pdftoppm", "pdftotext", "tesseract"},
        )
        self.assertEqual(set(baseline["language_data"]), {"eng", "deu", "osd"})
        self.assertEqual(set(baseline["support_data"]), {"configs/hocr", "configs/txt"})

    def test_wheel_native_inventory_is_exact_and_source_bound(self) -> None:
        document = json.loads(
            wheel_native_components_path(self.root).read_text(encoding="utf-8")
        )

        self.assertEqual(document["schema_version"], WHEEL_NATIVE_COMPONENTS_SCHEMA)
        self.assertEqual(
            [(item["component_id"], item["version"]) for item in document["wheels"]],
            [("python-pillow", "12.3.0"), ("python-pikepdf", "10.11.0")],
        )
        components = document["components"]
        self.assertEqual(len(components), 24)
        self.assertEqual(sum(len(item["paths"]) for item in components), 29)
        self.assertEqual(
            {item["parent_component_id"] for item in components},
            {"python-pillow", "python-pikepdf"},
        )
        self.assertTrue(
            all(
                len(item["source"]["sha256"]) == 64
                and item["source"]["url"].startswith("https://")
                and item["evidence"]
                for item in components
            )
        )

    def test_tree_identity_includes_paths_bytes_and_symlink_targets(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "one").write_text("value", encoding="utf-8")
            (root / "link").symlink_to("one")
            original = sha256_tree(root)
            (root / "link").unlink()
            (root / "link").symlink_to("missing")
            changed_link = sha256_tree(root)
            (root / "link").unlink()
            (root / "one").write_text("different", encoding="utf-8")

            self.assertNotEqual(original, changed_link)
            self.assertNotEqual(original, sha256_tree(root))

    def test_symlink_audit_rejects_escape(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw) / "runtime"
            root.mkdir()
            (root / "escape").symlink_to(root.parent)

            with self.assertRaisesRegex(RuntimeError, "symlink escapes"):
                _audit_symlinks(root)

    def test_build_host_path_scan_reports_bounded_relative_paths(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "payload").write_bytes(b"prefix /opt/homebrew suffix")

            self.assertEqual(
                _files_containing(root, ["/opt/homebrew", "/unseen"]),
                {"/opt/homebrew": ["payload"]},
            )

    def test_stage_refuses_to_overwrite_without_explicit_replace(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            existing = Path(raw) / "desktop-runtime"
            existing.mkdir()

            with self.assertRaisesRegex(RuntimeError, "already exists"):
                stage_runtime(root=self.root, destination=existing)

    def test_build_entrypoint_is_tracked_executable(self) -> None:
        script = self.root / "scripts" / "build-macos-desktop"

        self.assertTrue(script.is_file())
        self.assertTrue(os.access(script, os.X_OK))
        inputs = json.loads(
            (self.root / "desktop" / "packaging" / "macos-arm64.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(inputs["platform"], "macos")
        self.assertEqual(inputs["architecture"], "arm64")

    def test_unsigned_dmg_path_and_replacement_are_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = unsigned_dmg_path(root)
            self.assertEqual(
                output,
                root
                / "results"
                / "desktop"
                / "distribution"
                / "Doc-Evidence_0.4.0_aarch64-unsigned.dmg",
            )
            output.parent.mkdir(parents=True)
            output.write_bytes(b"existing")
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                create_unsigned_dmg(root / "missing.app", output, repository=root)

    def test_compliance_preflight_is_explicit_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            output = compliance_root(root)
            self.assertEqual(
                output.name,
                "Doc-Evidence_0.4.0_compliance-preflight",
            )
            output.mkdir(parents=True)
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                generate_compliance_preflight(
                    root / "missing.app",
                    output,
                    repository=root,
                )
        self.assertEqual(_spdx_license("Apache License 2.0"), ("Apache-2.0", False))
        self.assertEqual(
            _spdx_license("LicenseRef-Pypdfium2-Binary"),
            ("LicenseRef-Pypdfium2-Binary", False),
        )
        self.assertEqual(
            _spdx_license("BSD-3-Clause, dependency licenses"),
            ("NOASSERTION", True),
        )

    def test_homebrew_bottle_requires_exact_version_and_platform(self) -> None:
        info = {
            "formulae": [
                {
                    "versions": {"stable": "2.0.0"},
                    "revision": 1,
                    "bottle": {
                        "stable": {
                            "files": {
                                "arm64_tahoe": {
                                    "url": "https://ghcr.io/v2/example",
                                    "sha256": "a" * 64,
                                },
                                "sonoma": {
                                    "url": "https://ghcr.io/v2/wrong-arch",
                                    "sha256": "b" * 64,
                                },
                            }
                        }
                    },
                }
            ]
        }
        receipt = {
            "arch": "arm64",
            "source": {"path": "/cache/internal/packages.arm64_tahoe.jws.json"},
        }

        self.assertEqual(
            _installed_homebrew_bottle(
                info,
                name="example",
                version="2.0.0_1",
                receipt=receipt,
            ),
            {
                "bottle_tag": "arm64_tahoe",
                "bottle_url": "https://ghcr.io/v2/example",
                "bottle_sha256": "a" * 64,
            },
        )
        self.assertIsNone(
            _installed_homebrew_bottle(
                info,
                name="example",
                version="2.0.0",
                receipt=receipt,
            )
        )

    def test_dependency_license_discovery_and_rust_normalization(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "LICENCE").write_text("British spelling", encoding="utf-8")
            (root / "LICENSE-MIT").write_text("MIT", encoding="utf-8")
            (root / "README.md").write_text("Not a license", encoding="utf-8")

            self.assertEqual(
                [path.name for path in _dependency_license_files(root)],
                ["LICENCE", "LICENSE-MIT"],
            )

        self.assertEqual(
            _rust_license_expression("MIT/Apache-2.0"),
            "MIT OR Apache-2.0",
        )
        self.assertEqual(_rust_license_expression("MPL-2.0"), "MPL-2.0")
        self.assertTrue(_requires_corresponding_source("LGPL-2.1-or-later"))
        self.assertTrue(_requires_corresponding_source("MPL-2.0"))
        self.assertFalse(_requires_corresponding_source("Apache-2.0 OR MIT"))

    def test_rust_license_recovery_binds_package_vcs_and_document_hash(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            packaging = root / "desktop" / "packaging"
            packaging.mkdir(parents=True)
            package_root = root / "cargo" / "example-1.0.0"
            package_root.mkdir(parents=True)
            (package_root / ".cargo_vcs_info.json").write_text(
                json.dumps(
                    {
                        "git": {"sha1": "a" * 40},
                        "path_in_vcs": "crates/example",
                    }
                ),
                encoding="utf-8",
            )
            content = b"Exact license text\n"
            digest = hashlib.sha256(content).hexdigest()
            (packaging / "macos-rust-license-sources.json").write_text(
                json.dumps(
                    {
                        "schema_version": (
                            "doc-evidence.macos-rust-license-sources.v1"
                        ),
                        "documents": {
                            "example-license": {
                                "url": "https://example.invalid/LICENSE",
                                "sha256": digest,
                                "filename": "LICENSE",
                            }
                        },
                        "packages": {
                            "example@1.0.0": {
                                "vcs_revision": "a" * 40,
                                "path_in_vcs": "crates/example",
                                "license_declared": "MIT",
                                "documents": ["example-license"],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            cached = (
                root
                / "results"
                / "desktop"
                / "cache"
                / "compliance-licenses"
                / "example-license-LICENSE"
            )
            cached.parent.mkdir(parents=True)
            cached.write_bytes(content)
            output = root / "compliance"

            paths, provenance = _recover_rust_license_files(
                package_root=package_root,
                name="example",
                version="1.0.0",
                license_expression="MIT",
                repository=root,
                output=output,
            )

            self.assertEqual([path.read_bytes() for path in paths], [content])
            self.assertEqual(provenance[0]["vcs_revision"], "a" * 40)
            with self.assertRaisesRegex(RuntimeError, "expression drifted"):
                _recover_rust_license_files(
                    package_root=package_root,
                    name="example",
                    version="1.0.0",
                    license_expression="Apache-2.0",
                    repository=root,
                    output=output,
                )

    def test_excluded_optional_requirement_is_absent_from_pack_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            requirements = Path(raw) / "requirements.txt"
            requirements.write_text(
                "ocrmypdf==17.8.1\npi-heif==1.4.0\npillow==12.3.0\n",
                encoding="utf-8",
            )

            self.assertEqual(
                _included_locked_requirements(requirements, {"pi-heif"}),
                ["ocrmypdf==17.8.1", "pillow==12.3.0"],
            )

    def test_python_native_inventory_distinguishes_nested_libraries(self) -> None:
        native = [
            {"path": "python/bin/python3", "dependencies": []},
            {
                "path": "python/lib/python3.12/site-packages/demo/_core.so",
                "dependencies": [],
            },
            {
                "path": "python/lib/python3.12/site-packages/demo/.dylibs/libx.dylib",
                "dependencies": ["/usr/lib/libSystem.B.dylib"],
            },
        ]
        manifest = [
            {
                "path": item["path"],
                "component_id": "cpython" if index == 0 else "python-demo",
                "sha256": str(index) * 64,
                "bytes": index + 1,
            }
            for index, item in enumerate(native)
        ]

        records = _python_native_inventory(native, manifest)

        self.assertFalse(records[0]["wheel_owned"])
        self.assertFalse(records[1]["nested_dependency"])
        self.assertTrue(records[2]["nested_dependency"])
        self.assertEqual(
            _unreconciled_nested_native(records, []),
            [records[2]],
        )
        self.assertEqual(
            _unreconciled_nested_native(
                records,
                [{"binary_path": records[2]["path"]}],
            ),
            [],
        )
        with self.assertRaisesRegex(RuntimeError, "absent from native inventory"):
            _unreconciled_nested_native(
                records,
                [{"binary_path": "python/missing.dylib"}],
            )

    def test_python_binary_compliance_binds_exact_wheel_and_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            runtime = root / "runtime"
            site = runtime / "python" / "lib" / "python3.12" / "site-packages"
            binary_member = "demo_raw/libdemo.dylib"
            license_member = "demo-1.0.0.dist-info/licenses/LICENSE.txt"
            binary = b"exact native binary"
            license_text = b"exact license text"
            (site / binary_member).parent.mkdir(parents=True)
            (site / binary_member).write_bytes(binary)
            (site / license_member).parent.mkdir(parents=True)
            (site / license_member).write_bytes(license_text)
            cache = root / "cache"
            cache.mkdir()
            wheel = cache / "demo-1.0.0-py3-none-macosx_11_0_arm64.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr(binary_member, binary)
                archive.writestr(license_member, license_text)
            wheel_hash = hashlib.sha256(wheel.read_bytes()).hexdigest()
            binary_hash = hashlib.sha256(binary).hexdigest()
            inputs = {
                "baseline_pack": {
                    "python_license_conclusions": {
                        "demo": {
                            "version": "1.0.0",
                            "license_declared": "MIT",
                            "license_concluded": "LicenseRef-Demo-Binary",
                            "wheel_url": (
                                "https://files.pythonhosted.org/packages/demo/"
                                f"{wheel.name}"
                            ),
                            "wheel_sha256": wheel_hash,
                            "binary_member": binary_member,
                            "binary_sha256": binary_hash,
                        }
                    }
                }
            }
            component = {
                "component_id": "python-demo",
                "name": "demo",
                "version": "1.0.0",
                "license_concluded": "LicenseRef-Demo-Binary",
            }

            record = _python_binary_compliance_record(
                component,
                inputs=inputs,
                runtime=runtime,
                cache=cache,
            )

            self.assertIsNotNone(record)
            assert record is not None
            self.assertEqual(record["license_declared"], "MIT")
            self.assertEqual(record["binary_sha256"], binary_hash)
            self.assertEqual(
                record["license_files"],
                [f"python/lib/python3.12/site-packages/{license_member}"],
            )
            (site / license_member).write_bytes(b"tampered")
            with self.assertRaisesRegex(RuntimeError, "wheel bytes drifted"):
                _python_binary_compliance_record(
                    component,
                    inputs=inputs,
                    runtime=runtime,
                    cache=cache,
                )


if __name__ == "__main__":
    unittest.main()
