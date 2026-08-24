"""Strict inputs and native-byte audits for the Windows x86_64 desktop lane."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import queue
import re
import secrets
import shutil
import subprocess
import tarfile
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import jsonschema

from doc_evidence import __version__
from doc_evidence.contracts.desktop import (
    DESKTOP_ARCHITECTURE_ENV,
    DESKTOP_PLATFORM_ENV,
    DESKTOP_PROTOCOL_VERSION,
    WINDOWS_DESKTOP_ORIGIN,
)
from doc_evidence.desktop_pack import load_baseline_pack
from doc_evidence.windows_pe import PE_X86_64_MACHINE, inspect_pe

BUILD_INPUTS_SCHEMA = "doc-evidence.desktop-build-inputs.v1"
RUNTIME_MANIFEST_SCHEMA = "doc-evidence.desktop-runtime-manifest.v1"
BUNDLE_MANIFEST_SCHEMA = "doc-evidence.desktop-bundle-manifest.v1"
WINDOWS_PLATFORM = "windows"
WINDOWS_ARCHITECTURE = "x86_64"
PRODUCT_NAME = "Doc Evidence"
PRODUCT_IDENTIFIER = "io.github.kzahel.doc-evidence"
EXPECTED_NATIVE_COMPONENTS = {"msvc-runtime", "poppler", "tesseract"}
EXPECTED_TOOLS = {"pdfinfo", "pdftoppm", "pdftotext", "tesseract"}
_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NATIVE_SUFFIXES = {".dll", ".exe", ".pyd"}


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_inputs_path(root: Path | None = None) -> Path:
    base = root or repository_root()
    return base / "desktop" / "packaging" / "windows-x86_64.json"


def cache_root(root: Path | None = None) -> Path:
    base = root or repository_root()
    return base / "results" / "desktop" / "cache" / "windows-x86_64"


def stage_root(root: Path | None = None) -> Path:
    base = root or repository_root()
    return base / "desktop" / "src-tauri" / "resources" / "desktop-runtime"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(root).as_posix().encode()
        digest.update(b"F\0" + relative + b"\0")
        digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def _run(
    arguments: Sequence[str | Path],
    *,
    cwd: Path | None = None,
    environment: Mapping[str, str] | None = None,
    capture_output: bool = False,
    timeout_seconds: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(argument) for argument in arguments],
        cwd=cwd,
        env=None if environment is None else dict(environment),
        check=True,
        text=True,
        capture_output=capture_output,
        timeout=timeout_seconds,
    )


def _require_sha256(value: object, purpose: str) -> str:
    if not isinstance(value, str) or _HEX_SHA256.fullmatch(value) is None:
        raise RuntimeError(f"{purpose} SHA-256 is malformed")
    return value


def _require_name(value: object, purpose: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or Path(value).name != value
        or "/" in value
        or "\\" in value
    ):
        raise RuntimeError(f"{purpose} name is unsafe")
    return value


def _validate_archive(record: object, purpose: str) -> Mapping[str, Any]:
    if not isinstance(record, Mapping):
        raise TypeError(f"{purpose} archive record is missing")
    required = {"cache_name", "url", "sha256"}
    if not required.issubset(record):
        raise RuntimeError(f"{purpose} archive record is incomplete")
    _require_name(record["cache_name"], f"{purpose} archive")
    url = record["url"]
    if not isinstance(url, str) or not url.startswith("https://"):
        raise RuntimeError(f"{purpose} archive URL is invalid")
    _require_sha256(record["sha256"], f"{purpose} archive")
    return record


def _validate_source_archives(value: object, purpose: str) -> None:
    if not isinstance(value, list) or not value:
        raise RuntimeError(f"{purpose} source archives are missing")
    component_ids: set[str] = set()
    for index, raw in enumerate(value):
        record = _validate_archive(raw, f"{purpose} source archive {index}")
        component_id = record.get("component_id")
        version = record.get("version")
        if not isinstance(component_id, str) or not component_id:
            raise RuntimeError(f"{purpose} source component is missing")
        if not isinstance(version, str) or not version:
            raise RuntimeError(f"{purpose} source version is missing")
        if component_id in component_ids:
            raise RuntimeError(f"{purpose} repeats source component {component_id}")
        component_ids.add(component_id)


def _validate_payload(value: object, purpose: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise RuntimeError(f"{purpose} payload is missing")
    result: dict[str, str] = {}
    casefolded: set[str] = set()
    for raw_name, raw_hash in value.items():
        name = _require_name(raw_name, f"{purpose} payload")
        folded = name.casefold()
        if folded in casefolded:
            raise RuntimeError(f"{purpose} payload repeats Windows name {name}")
        casefolded.add(folded)
        result[name] = _require_sha256(raw_hash, f"{purpose} payload {name}")
    return result


def _load_inputs(
    root: Path | None = None, *, path: Path | None = None
) -> dict[str, Any]:
    source = path or build_inputs_path(root)
    document = json.loads(source.read_text(encoding="utf-8"))
    if (
        document.get("schema_version") != BUILD_INPUTS_SCHEMA
        or document.get("platform") != WINDOWS_PLATFORM
        or document.get("architecture") != WINDOWS_ARCHITECTURE
    ):
        raise RuntimeError("Windows desktop build inputs are incompatible")

    python = _validate_archive(document.get("python"), "standalone Python")
    for field in ("implementation", "version", "build", "license_concluded"):
        if not isinstance(python.get(field), str) or not python[field]:
            raise RuntimeError(f"standalone Python {field} is missing")

    baseline = document.get("baseline_pack")
    if not isinstance(baseline, Mapping):
        raise TypeError("Windows baseline-pack input is missing")
    if baseline.get("pack_id") != "baseline-windows-x86_64":
        raise RuntimeError("Windows baseline-pack identifier is incompatible")
    _require_sha256(
        baseline.get("requirements_sha256"), "Windows baseline requirements"
    )
    python_components = baseline.get("python_components")
    if not isinstance(python_components, Mapping) or set(python_components) != {
        "ocrmypdf",
        "pypdfium2",
    }:
        raise RuntimeError("Windows baseline Python components are incompatible")

    components = baseline.get("native_components")
    if not isinstance(components, Mapping) or set(components) != (
        EXPECTED_NATIVE_COMPONENTS
    ):
        raise RuntimeError("Windows native-component set is incompatible")
    payloads: dict[str, dict[str, str]] = {}
    for component_id in sorted(EXPECTED_NATIVE_COMPONENTS):
        raw = components[component_id]
        if not isinstance(raw, Mapping):
            raise TypeError(f"Windows {component_id} input is invalid")
        _validate_archive(raw.get("archive"), f"Windows {component_id}")
        if not isinstance(raw.get("version"), str) or not raw["version"]:
            raise RuntimeError(f"Windows {component_id} version is missing")
        conclusion = raw.get("license_concluded")
        if not isinstance(conclusion, str) or not conclusion:
            raise RuntimeError(f"Windows {component_id} license conclusion is missing")
        if conclusion == "NOASSERTION" and not isinstance(
            raw.get("compliance_blocker"), str
        ):
            raise RuntimeError(
                f"Windows {component_id} lacks its unresolved compliance blocker"
            )
        payloads[component_id] = _validate_payload(
            raw.get("payload_sha256"), f"Windows {component_id}"
        )
        if component_id == "msvc-runtime":
            source_url = raw.get("source_url")
            if not isinstance(source_url, str) or not source_url.startswith("https://"):
                raise RuntimeError("Windows MSVC runtime source record is invalid")
        else:
            _validate_source_archives(
                raw.get("source_archives"), f"Windows {component_id}"
            )

    tools = baseline.get("tools")
    if not isinstance(tools, Mapping) or set(tools) != EXPECTED_TOOLS:
        raise RuntimeError("Windows baseline tool set is incompatible")
    for tool_id, raw_reference in tools.items():
        if not isinstance(raw_reference, str) or raw_reference.count(":") != 1:
            raise RuntimeError(f"Windows tool reference is invalid: {tool_id}")
        component_id, payload_name = raw_reference.split(":", 1)
        if payload_name not in payloads.get(component_id, {}):
            raise RuntimeError(f"Windows tool payload is undeclared: {tool_id}")

    language = baseline.get("language_data")
    if not isinstance(language, Mapping):
        raise TypeError("Windows Tesseract language data is missing")
    _validate_archive(language.get("archive"), "Tesseract language data")
    language_files = language.get("files")
    if not isinstance(language_files, Mapping) or len(language_files) != 3:
        raise RuntimeError("Windows Tesseract language files are incompatible")
    for name, digest in language_files.items():
        if not isinstance(name, str) or not name.endswith(".traineddata"):
            raise RuntimeError("Windows Tesseract language path is invalid")
        _require_sha256(digest, f"Windows Tesseract language {name}")

    _validate_source_archives(
        baseline.get("source_archives"), "Windows baseline Python"
    )
    system_dlls = baseline.get("system_dlls")
    if not isinstance(system_dlls, list) or not system_dlls:
        raise RuntimeError("Windows system-DLL allowlist is missing")
    folded_system: set[str] = set()
    for raw in system_dlls:
        name = _require_name(raw, "Windows system DLL")
        if Path(name).suffix.casefold() not in {".dll", ".drv"}:
            raise RuntimeError(f"Windows system DLL name is invalid: {name}")
        folded = name.casefold()
        if folded in folded_system:
            raise RuntimeError(f"Windows system DLL is repeated: {name}")
        folded_system.add(folded)
    return document


def archive_path(record: Mapping[str, Any], cache: Path) -> Path:
    name = _require_name(record.get("cache_name"), "desktop input archive")
    parsed = urllib.parse.urlparse(str(record.get("url", "")))
    if parsed.scheme != "https" or not parsed.netloc:
        raise RuntimeError("desktop input archive URL is invalid")
    return cache / name


def acquire_archive(record: Mapping[str, Any], cache: Path) -> Path:
    """Acquire one hash-pinned input without accepting a partial download."""

    destination = archive_path(record, cache)
    expected = _require_sha256(record.get("sha256"), "desktop input archive")
    cache.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and sha256_file(destination) == expected:
        return destination
    if destination.exists():
        destination.unlink()
    partial = destination.with_name(f"{destination.name}.partial")
    partial.unlink(missing_ok=True)
    try:
        with (
            urllib.request.urlopen(str(record["url"]), timeout=60) as response,
            partial.open("xb") as output,
        ):
            shutil.copyfileobj(response, output)
        actual = sha256_file(partial)
        if actual != expected:
            raise RuntimeError(
                f"desktop input archive hash mismatch: expected {expected}, "
                f"got {actual}"
            )
        os.replace(partial, destination)
    finally:
        partial.unlink(missing_ok=True)
    return destination


def _require_windows_host() -> None:
    system = platform.system()
    machine = platform.machine().casefold()
    if system != "Windows" or machine not in {"amd64", "x86_64", "arm64", "aarch64"}:
        raise RuntimeError(
            "Windows desktop packaging requires a Windows x64-capable host"
        )


def extract_python_runtime(archive: Path, destination: Path) -> Path:
    """Extract the standalone runtime without links or Windows path collisions."""

    if destination.exists():
        raise RuntimeError(f"standalone Python destination exists: {destination}")
    destination.mkdir(parents=True)
    folded: set[str] = set()
    with tarfile.open(archive, "r:gz") as source:
        members = source.getmembers()
        for member in members:
            relative = _safe_archive_relative(member.name, "standalone Python")
            identity = relative.as_posix().casefold()
            if identity in folded:
                raise RuntimeError(
                    f"standalone Python repeats a Windows path: {relative}"
                )
            folded.add(identity)
            if member.issym() or member.islnk() or member.isdev():
                raise RuntimeError(
                    f"standalone Python contains an unsupported member: {relative}"
                )
        source.extractall(destination, members=members, filter="data")
    python_root = destination / "python"
    python = python_root / "python.exe"
    if not python.is_file():
        raise RuntimeError("standalone Python archive has an unexpected layout")
    pe = inspect_pe(python)
    if pe.machine != PE_X86_64_MACHINE or pe.format != "PE32+":
        raise RuntimeError("standalone Python interpreter is not x86_64 PE32+")
    return python_root


def _baseline_requirements(repository: Path) -> Path:
    return repository / "desktop" / "packaging" / "baseline-requirements.txt"


def _locked_requirements(path: Path) -> list[str]:
    values: list[str] = []
    pattern = re.compile(r"^([A-Za-z0-9_.-]+)==([^ ;\\]+)")
    for line in path.read_text(encoding="utf-8").splitlines():
        matched = pattern.match(line)
        if matched:
            values.append(f"{matched.group(1)}=={matched.group(2)}")
    if not values:
        raise RuntimeError("baseline Python requirements are empty")
    return values


def stage_python_dependencies(
    repository: Path,
    python_root: Path,
    inputs: Mapping[str, Any],
) -> list[str]:
    """Install frozen production and baseline dependencies into target Python."""

    python = python_root / "python.exe"
    requirements = python_root.parent / ".desktop-requirements.txt"
    _run(
        [
            "uv",
            "export",
            "--frozen",
            "--no-dev",
            "--no-editable",
            "--no-emit-project",
            "--format",
            "requirements-txt",
            "--output-file",
            requirements,
        ],
        cwd=repository,
        capture_output=True,
    )
    baseline = _baseline_requirements(repository)
    if sha256_file(baseline) != inputs["baseline_pack"]["requirements_sha256"]:
        raise RuntimeError("baseline Python requirements identity changed")
    try:
        for locked in (requirements, baseline):
            _run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    python,
                    "--requirements",
                    locked,
                    "--require-hashes",
                    "--strict",
                    "--only-binary",
                    ":all:",
                    "--link-mode",
                    "copy",
                ],
                cwd=repository,
                timeout_seconds=600,
            )
        _run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                python,
                "--no-deps",
                "--reinstall",
                "--link-mode",
                "copy",
                repository,
            ],
            cwd=repository,
            timeout_seconds=300,
        )
    finally:
        requirements.unlink(missing_ok=True)
    return _locked_requirements(baseline)


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def prune_python_runtime(python_root: Path) -> None:
    """Remove development, installer, GUI, and relocatability-hostile bytes."""

    for relative in (
        "include",
        "Lib/idlelib",
        "Lib/test",
        "Lib/tkinter",
        "Lib/turtledemo",
        "Lib/venv",
        "Scripts",
        "tcl",
        "pythonw.exe",
    ):
        _remove_path(python_root / relative)
    for name in (
        "_msi.pyd",
        "_tkinter.pyd",
        "_wmi.pyd",
        "tcl86t.dll",
        "tk86t.dll",
        "winsound.pyd",
    ):
        _remove_path(python_root / "DLLs" / name)
    for test_binary in (python_root / "DLLs").glob("_test*.pyd"):
        _remove_path(test_binary)

    site_packages = python_root / "Lib" / "site-packages"
    for candidate in list(site_packages.glob("pip*")):
        _remove_path(candidate)
    for imaging_tk in (site_packages / "PIL").glob("_imagingtk*.pyd"):
        _remove_path(imaging_tk)
    for module in (
        "desktop_packaging.py",
        "windows_desktop_packaging.py",
        "windows_pe.py",
    ):
        _remove_path(site_packages / "doc_evidence" / module)
    for direct_url in site_packages.glob("*.dist-info/direct_url.json"):
        direct_url.unlink()
    for cache in sorted(
        python_root.rglob("__pycache__"),
        key=lambda value: len(value.parts),
        reverse=True,
    ):
        _remove_path(cache)
    for bytecode in python_root.rglob("*.py[co]"):
        bytecode.unlink()


def _safe_archive_relative(value: str, purpose: str) -> PurePosixPath:
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise RuntimeError(f"{purpose} archive path is unsafe: {value}")
    return relative


def _copy_declared_payloads(
    source_root: Path,
    destination: Path,
    payload_sha256: Mapping[str, str],
) -> list[Path]:
    """Copy an exact, flat payload set with Windows collision semantics."""

    destination.mkdir(parents=True, exist_ok=True)
    existing = {path.name.casefold() for path in destination.iterdir()}
    copied: list[Path] = []
    for raw_name, expected in sorted(
        payload_sha256.items(), key=lambda item: item[0].casefold()
    ):
        name = _require_name(raw_name, "native payload")
        source = source_root / name
        if not source.is_file() or source.is_symlink():
            raise RuntimeError(f"declared native payload is missing: {name}")
        actual = sha256_file(source)
        if actual != expected:
            raise RuntimeError(
                f"declared native payload hash changed: {name}: "
                f"expected {expected}, got {actual}"
            )
        if name.casefold() in existing:
            raise RuntimeError(f"native payload has a Windows name collision: {name}")
        target = destination / name
        shutil.copy2(source, target)
        existing.add(name.casefold())
        copied.append(target)
    return copied


def _copy_data_tree(source: Path, destination: Path) -> list[Path]:
    copied: list[Path] = []
    if destination.exists():
        raise RuntimeError(f"native data destination already exists: {destination}")
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_symlink():
            raise RuntimeError(f"native data contains a symbolic link: {relative}")
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
            copied.append(target)
    return copied


def extract_flat_zip_component(
    archive: Path,
    component: Mapping[str, Any],
    destination: Path,
) -> list[Path]:
    """Extract one exact flat payload from a hash-pinned ZIP/VSIX archive."""

    archive_record = component["archive"]
    if sha256_file(archive) != archive_record["sha256"]:
        raise RuntimeError("flat ZIP component archive identity changed")
    payload = component["payload_sha256"]
    payload_root = PurePosixPath(str(archive_record["payload_root"]))
    with tempfile.TemporaryDirectory(prefix="doc-evidence-zip-component-") as raw:
        extracted = Path(raw)
        with zipfile.ZipFile(archive) as source:
            by_name = {item.filename: item for item in source.infolist()}
            for name in payload:
                archive_name = (payload_root / name).as_posix()
                info = by_name.get(archive_name)
                if (
                    info is None
                    or info.is_dir()
                    or ((info.external_attr >> 16) & 0o170000) == 0o120000
                ):
                    raise RuntimeError(f"flat ZIP component payload is invalid: {name}")
                output = extracted / name
                with source.open(info) as input_stream, output.open("xb") as target:
                    shutil.copyfileobj(input_stream, target)
        return _copy_declared_payloads(extracted, destination, payload)


def extract_poppler_component(
    archive: Path,
    component: Mapping[str, Any],
    pack: Path,
) -> tuple[list[Path], list[Path]]:
    """Extract only the declared Poppler executable closure and data tree."""

    archive_record = component["archive"]
    if sha256_file(archive) != archive_record["sha256"]:
        raise RuntimeError("Poppler archive identity changed")
    payload = component["payload_sha256"]
    payload_root = PurePosixPath(str(archive_record["payload_root"]))
    data_record = component["data_tree"]
    data_root = PurePosixPath(str(data_record["archive_root"]))
    with tempfile.TemporaryDirectory(prefix="doc-evidence-poppler-") as raw:
        extracted = Path(raw)
        with zipfile.ZipFile(archive) as source:
            by_name = {item.filename: item for item in source.infolist()}
            for name in payload:
                archive_name = (payload_root / name).as_posix()
                info = by_name.get(archive_name)
                if (
                    info is None
                    or info.is_dir()
                    or ((info.external_attr >> 16) & 0o170000) == 0o120000
                ):
                    raise RuntimeError(f"Poppler archive payload is invalid: {name}")
                output = extracted / "bin" / name
                output.parent.mkdir(parents=True, exist_ok=True)
                with source.open(info) as input_stream, output.open("xb") as target:
                    shutil.copyfileobj(input_stream, target)
            data_destination = extracted / "share" / "poppler"
            for info in source.infolist():
                archive_relative = _safe_archive_relative(info.filename, "Poppler data")
                try:
                    relative = archive_relative.relative_to(data_root)
                except ValueError:
                    continue
                if not relative.parts:
                    continue
                output = data_destination.joinpath(*relative.parts)
                if info.is_dir():
                    output.mkdir(parents=True, exist_ok=True)
                    continue
                if ((info.external_attr >> 16) & 0o170000) == 0o120000:
                    raise RuntimeError(
                        f"Poppler data contains a symbolic link: {relative}"
                    )
                output.parent.mkdir(parents=True, exist_ok=True)
                with source.open(info) as input_stream, output.open("xb") as target:
                    shutil.copyfileobj(input_stream, target)
        if sha256_tree(data_destination) != data_record["sha256"]:
            raise RuntimeError("Poppler data tree identity changed")
        file_count = sum(1 for path in data_destination.rglob("*") if path.is_file())
        if file_count != data_record["file_count"]:
            raise RuntimeError("Poppler data tree file count changed")
        binaries = _copy_declared_payloads(extracted / "bin", pack / "bin", payload)
        data = _copy_data_tree(data_destination, pack / "share" / "poppler")
    return binaries, data


def extract_tesseract_component(
    archive: Path,
    component: Mapping[str, Any],
    pack: Path,
    *,
    seven_zip: str | Path | None = None,
) -> tuple[list[Path], list[Path]]:
    """Extract the declared Tesseract closure from its official NSIS asset."""

    archive_record = component["archive"]
    if sha256_file(archive) != archive_record["sha256"]:
        raise RuntimeError("Tesseract archive identity changed")
    executable = Path(seven_zip) if seven_zip is not None else None
    if executable is None:
        found = shutil.which("7z")
        if found is None:
            raise RuntimeError("7-Zip is required to extract the Tesseract installer")
        executable = Path(found)
    with tempfile.TemporaryDirectory(prefix="doc-evidence-tesseract-") as raw:
        extracted = Path(raw)
        _run(
            [executable, "x", "-y", f"-o{extracted}", archive],
            capture_output=True,
            timeout_seconds=180,
        )
        binaries = _copy_declared_payloads(
            extracted, pack / "bin", component["payload_sha256"]
        )
        support: list[Path] = []
        for raw_path, expected in sorted(component["support_data"].items()):
            relative = _safe_archive_relative(raw_path, "Tesseract support")
            source = extracted.joinpath(*relative.parts)
            if not source.is_file() or sha256_file(source) != expected:
                raise RuntimeError(
                    f"Tesseract support file identity changed: {raw_path}"
                )
            target = pack.joinpath(*relative.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            support.append(target)
    return binaries, support


def extract_language_data(
    archive: Path,
    language: Mapping[str, Any],
    pack: Path,
) -> list[dict[str, str]]:
    """Extract only the three declared Tesseract language files."""

    archive_record = language["archive"]
    if sha256_file(archive) != archive_record["sha256"]:
        raise RuntimeError("Tesseract language archive identity changed")
    destination = pack / "tessdata"
    destination.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, str]] = []
    with tarfile.open(archive, "r:gz") as source:
        members = {member.name: member for member in source.getmembers()}
        for raw_path, expected in sorted(language["files"].items()):
            relative = _safe_archive_relative(raw_path, "Tesseract language")
            member = members.get(relative.as_posix())
            if (
                member is None
                or not member.isfile()
                or member.issym()
                or member.islnk()
            ):
                raise RuntimeError(
                    f"Tesseract language archive member is invalid: {raw_path}"
                )
            stream = source.extractfile(member)
            if stream is None:
                raise RuntimeError(
                    f"Tesseract language archive member is unreadable: {raw_path}"
                )
            target = destination / relative.name
            with stream, target.open("xb") as output:
                shutil.copyfileobj(stream, output)
            actual = sha256_file(target)
            if actual != expected:
                raise RuntimeError(
                    f"Tesseract language identity changed: {raw_path}: "
                    f"expected {expected}, got {actual}"
                )
            records.append(
                {
                    "language": target.stem,
                    "path": target.relative_to(pack).as_posix(),
                    "sha256": actual,
                    "license_concluded": "Apache-2.0",
                }
            )
    return records


def compile_ocrmypdf_launcher(repository: Path, destination: Path) -> Path:
    """Compile the tracked relocatable launcher with the target-native Rust toolchain."""

    source = repository / "desktop" / "packaging" / "windows-ocrmypdf-launcher.rs"
    if not source.is_file():
        raise RuntimeError("Windows OCRmyPDF launcher source is missing")
    destination.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "rustc",
            "--edition",
            "2021",
            "--target",
            "x86_64-pc-windows-msvc",
            "-C",
            "opt-level=z",
            "-C",
            "strip=symbols",
            source,
            "-o",
            destination,
        ],
        cwd=repository,
        capture_output=True,
        timeout_seconds=180,
    )
    pe = inspect_pe(destination)
    if pe.machine != PE_X86_64_MACHINE or pe.format != "PE32+":
        raise RuntimeError("Windows OCRmyPDF launcher is not x86_64 PE32+")
    return destination


def _component_source_url(component: Mapping[str, Any]) -> str:
    source_url = component.get("source_url")
    if isinstance(source_url, str):
        return source_url
    sources = component.get("source_archives")
    if isinstance(sources, list) and sources and isinstance(sources[0], Mapping):
        value = sources[0].get("url")
        if isinstance(value, str):
            return value
    raise RuntimeError("Windows native component source URL is missing")


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def stage_pypdfium2_licenses(
    runtime_root: Path,
    baseline: Mapping[str, Any],
    *,
    cache: Path,
) -> list[str]:
    """Stage license material from the exact pypdfium2 source archive."""

    source_record = next(
        (
            item
            for item in baseline["source_archives"]
            if item["component_id"] == "python-pypdfium2"
        ),
        None,
    )
    if source_record is None:
        raise RuntimeError("pypdfium2 license source is not declared")
    archive = acquire_archive(source_record, cache)
    destination = runtime_root / "baseline-pack" / "licenses" / "python" / "pypdfium2"
    copied: list[str] = []
    with tarfile.open(archive, "r:gz") as source:
        for member in source.getmembers():
            relative = _safe_archive_relative(member.name, "pypdfium2 license")
            if (
                not member.isfile()
                or len(relative.parts) < 3
                or relative.parts[1] not in {"LICENSES", "BUILD_LICENSES"}
            ):
                continue
            output_relative = Path(*relative.parts[1:])
            output = destination / output_relative
            output.parent.mkdir(parents=True, exist_ok=True)
            stream = source.extractfile(member)
            if stream is None:
                raise RuntimeError("pypdfium2 license member is unreadable")
            with stream, output.open("xb") as target:
                shutil.copyfileobj(stream, target)
            copied.append(output.relative_to(runtime_root).as_posix())
    if not copied:
        raise RuntimeError("pypdfium2 source archive has no license material")
    return sorted(copied)


def stage_baseline_pack(
    repository: Path,
    runtime_root: Path,
    inputs: Mapping[str, Any],
    python_components: list[str],
    *,
    cache: Path,
    seven_zip: str | Path | None = None,
) -> dict[str, Any]:
    """Assemble the exact Windows baseline pack and validate its PE closure."""

    baseline = inputs["baseline_pack"]
    pack = runtime_root / "baseline-pack"
    if pack.exists():
        raise RuntimeError(f"Windows baseline-pack destination exists: {pack}")
    pack.mkdir(parents=True)
    components = baseline["native_components"]
    copied_by_component: dict[str, list[Path]] = {}

    poppler = components["poppler"]
    poppler_archive = acquire_archive(poppler["archive"], cache)
    poppler_files, poppler_data = extract_poppler_component(
        poppler_archive, poppler, pack
    )
    copied_by_component["poppler"] = [*poppler_files, *poppler_data]

    tesseract = components["tesseract"]
    tesseract_archive = acquire_archive(tesseract["archive"], cache)
    tesseract_files, tesseract_support = extract_tesseract_component(
        tesseract_archive,
        tesseract,
        pack,
        seven_zip=seven_zip,
    )
    copied_by_component["tesseract"] = [
        *tesseract_files,
        *tesseract_support,
    ]

    msvc = components["msvc-runtime"]
    msvc_archive = acquire_archive(msvc["archive"], cache)
    copied_by_component["msvc-runtime"] = extract_flat_zip_component(
        msvc_archive, msvc, pack / "bin"
    )

    language = baseline["language_data"]
    language_archive = acquire_archive(language["archive"], cache)
    language_data = extract_language_data(language_archive, language, pack)
    pypdfium2_licenses = stage_pypdfium2_licenses(runtime_root, baseline, cache=cache)

    launcher = compile_ocrmypdf_launcher(repository, pack / "bin" / "ocrmypdf.exe")
    closure = audit_flat_pe_closure(
        pack / "bin", system_dlls=list(baseline["system_dlls"])
    )
    closure_by_path = {record["path"].casefold(): record for record in closure}

    tools = []
    for tool_id, reference in sorted(baseline["tools"].items()):
        component_id, name = reference.split(":", 1)
        path = pack / "bin" / name
        tools.append(
            {
                "tool_id": tool_id,
                "version": str(components[component_id]["version"]),
                "executable": path.relative_to(pack).as_posix(),
                "sha256": sha256_file(path),
                "license_concluded": components[component_id]["license_concluded"],
                "component_id": component_id,
            }
        )
    tools.append(
        {
            "tool_id": "ocrmypdf",
            "version": str(baseline["python_components"]["ocrmypdf"]),
            "executable": launcher.relative_to(pack).as_posix(),
            "sha256": sha256_file(launcher),
            "license_concluded": "MPL-2.0",
            "component_id": "python-ocrmypdf",
        }
    )

    owner_by_name = {
        name.casefold(): component_id
        for component_id, component in components.items()
        for name in component["payload_sha256"]
    }
    native_libraries = []
    for record in closure:
        path = pack / "bin" / record["path"]
        if path.suffix.casefold() != ".dll":
            continue
        native_libraries.append(
            {
                "path": path.relative_to(pack).as_posix(),
                "sha256": record["sha256"],
                "component_id": owner_by_name[path.name.casefold()],
                "architectures": ["x86_64"],
            }
        )
    support_files = [
        {
            "path": path.relative_to(pack).as_posix(),
            "sha256": sha256_file(path),
            "component_id": "tesseract",
        }
        for path in sorted(tesseract_support)
    ]
    pack_manifest = {
        "schema_version": "doc-evidence.extractor-pack-manifest.v1",
        "pack_id": baseline["pack_id"],
        "version": baseline["version"],
        "platform": WINDOWS_PLATFORM,
        "architecture": WINDOWS_ARCHITECTURE,
        "tools": sorted(tools, key=lambda item: item["tool_id"]),
        "language_data": language_data,
        "support_files": support_files,
        "python_components": python_components,
        "native_libraries": native_libraries,
    }
    schema = json.loads(
        (
            repository
            / "src"
            / "doc_evidence"
            / "schema_files"
            / "extractor-pack-manifest.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(schema).validate(pack_manifest)
    manifest_path = pack / "pack-manifest.json"
    _write_json(manifest_path, pack_manifest)

    file_owners: dict[str, str] = {}
    for component_id, paths in copied_by_component.items():
        for path in paths:
            file_owners[path.relative_to(runtime_root).as_posix()] = component_id
    for item in language_data:
        file_owners[f"baseline-pack/{item['path']}"] = "tesseract-language-data"
    for path in pypdfium2_licenses:
        file_owners[path] = "python-pypdfium2"
    file_owners[launcher.relative_to(runtime_root).as_posix()] = "python-ocrmypdf"
    file_owners[manifest_path.relative_to(runtime_root).as_posix()] = (
        "baseline-pack-metadata"
    )
    component_records = [
        {
            "component_id": component_id,
            "name": component_id,
            "version": str(component["version"]),
            "license_concluded": component["license_concluded"],
            "source_url": _component_source_url(component),
            "bundled_paths": sorted(
                path.relative_to(runtime_root).as_posix()
                for path in copied_by_component[component_id]
            ),
        }
        for component_id, component in sorted(components.items())
    ]
    component_records.extend(
        [
            {
                "component_id": "tesseract-language-data",
                "name": "Tesseract language data",
                "version": str(language["archive"]["version"]),
                "license_concluded": "Apache-2.0",
                "source_url": language["archive"]["url"],
                "source_sha256": language["archive"]["sha256"],
                "bundled_paths": sorted(
                    f"baseline-pack/{item['path']}" for item in language_data
                ),
            },
            {
                "component_id": "baseline-pack-metadata",
                "name": "Doc Evidence baseline extractor pack metadata",
                "version": str(baseline["version"]),
                "license_concluded": "Apache-2.0",
                "source_url": "https://github.com/kzahel/doc-evidence",
                "bundled_paths": [manifest_path.relative_to(runtime_root).as_posix()],
            },
        ]
    )
    return {
        "identity": {
            "pack_id": baseline["pack_id"],
            "version": baseline["version"],
            "manifest_sha256": sha256_file(manifest_path),
        },
        "components": component_records,
        "file_owners": file_owners,
        "native_closure": closure_by_path,
        "package_license_files": {"pypdfium2": pypdfium2_licenses},
    }


_DISTRIBUTION_SCRIPT = r"""
import importlib.metadata as metadata
import json
import sys
from pathlib import Path

items = []
for distribution in metadata.distributions():
    value = distribution.metadata
    files = []
    licenses = []
    for relative in distribution.files or []:
        path = distribution.locate_file(relative)
        try:
            if not path.is_file():
                continue
        except OSError:
            continue
        item = Path(path).resolve().relative_to(Path(sys.prefix).resolve()).as_posix()
        files.append(item)
        lowered = Path(item).name.lower()
        if any(name in lowered for name in ("license", "copying", "notice")):
            licenses.append(item)
    classifiers = value.get_all("Classifier") or []
    items.append({
        "name": value.get("Name", distribution.name),
        "version": distribution.version,
        "license": value.get("License"),
        "license_expression": value.get("License-Expression"),
        "license_classifiers": [
            item for item in classifiers if item.startswith("License ::")
        ],
        "files": sorted(files),
        "license_files": sorted(licenses),
    })
print(json.dumps(sorted(items, key=lambda item: item["name"].lower())))
"""


def distribution_inventory(python_root: Path) -> list[dict[str, Any]]:
    result = _run(
        [python_root / "python.exe", "-I", "-B", "-c", _DISTRIBUTION_SCRIPT],
        capture_output=True,
        timeout_seconds=60,
    )
    value = json.loads(result.stdout)
    if not isinstance(value, list):
        raise TypeError("Windows Python distribution inventory is invalid")
    return value


def _license_conclusion(distribution: Mapping[str, Any]) -> str:
    expression = distribution.get("license_expression")
    if isinstance(expression, str) and expression.strip() not in {"", "UNKNOWN"}:
        return expression.strip()
    raw = distribution.get("license")
    if isinstance(raw, str) and 0 < len(raw.strip()) <= 100 and "\n" not in raw:
        return raw.strip()
    classifiers = distribution.get("license_classifiers")
    if isinstance(classifiers, list) and classifiers:
        return str(classifiers[0]).removeprefix("License :: ")
    raise RuntimeError(
        f"Python distribution lacks reviewed license metadata: {distribution['name']}"
    )


def _python_license_conclusion(
    distribution: Mapping[str, Any], baseline: Mapping[str, Any]
) -> str:
    normalized = str(distribution["name"]).lower().replace("_", "-")
    override = baseline["python_license_conclusions"].get(normalized)
    if override is None:
        return _license_conclusion(distribution)
    if (
        not isinstance(override, Mapping)
        or override.get("version") != distribution.get("version")
        or not isinstance(override.get("license_concluded"), str)
    ):
        raise RuntimeError(f"Python license conclusion drifted: {normalized}")
    return str(override["license_concluded"])


def _component_id(name: str) -> str:
    normalized = "".join(
        character if character.isalnum() else "-" for character in name.lower()
    )
    return "python-" + "-".join(filter(None, normalized.split("-")))


def write_runtime_manifests(
    repository: Path,
    runtime_root: Path,
    python_archive: Path,
    inputs: Mapping[str, Any],
    baseline_metadata: Mapping[str, Any],
) -> None:
    """Bind all staged Windows bytes to package, component, and bundle manifests."""

    python_root = runtime_root / "python"
    packages = distribution_inventory(python_root)
    if not packages:
        raise RuntimeError("staged Windows Python package inventory is empty")
    forbidden = {
        str(name).lower().replace("_", "-")
        for name in inputs["forbidden_python_distributions"]
    }
    package_license_files = baseline_metadata["package_license_files"]
    baseline = inputs["baseline_pack"]
    for package in packages:
        normalized = str(package["name"]).lower().replace("_", "-")
        if normalized in forbidden:
            raise RuntimeError(
                f"development distribution entered Windows runtime: {package['name']}"
            )
        external = package_license_files.get(normalized, [])
        if not package["files"] or not (package["license_files"] or external):
            raise RuntimeError(
                f"Windows Python distribution is not fully licensed: {package['name']}"
            )

    notices = [
        "Doc Evidence third-party notices (generated from staged bytes)",
        "",
        "Complete available license texts remain beside their components.",
        "",
        (
            f"CPython {inputs['python']['version']} — "
            f"{inputs['python']['license_concluded']}"
        ),
    ]
    components: list[dict[str, Any]] = [
        {
            "component_id": "cpython",
            "name": "CPython",
            "version": inputs["python"]["version"],
            "license_concluded": inputs["python"]["license_concluded"],
            "source_url": inputs["python"]["url"],
            "source_sha256": inputs["python"]["sha256"],
            "license_files": ["python/LICENSE.txt"],
            "bundled_paths": ["python"],
        }
    ]
    baseline_components = baseline_metadata["components"]
    components.extend(baseline_components)
    notices.extend(
        f"{component['name']} {component['version']} — {component['license_concluded']}"
        for component in baseline_components
    )
    file_owners = {
        str(path): str(owner)
        for path, owner in baseline_metadata["file_owners"].items()
    }
    for package in packages:
        name = str(package["name"])
        normalized = name.lower().replace("_", "-")
        component_id = _component_id(name)
        external_licenses = [
            str(path) for path in package_license_files.get(normalized, [])
        ]
        conclusion = _python_license_conclusion(package, baseline)
        notices.append(f"{name} {package['version']} — {conclusion}")
        bundled_paths = [f"python/{path}" for path in package["files"]]
        if component_id == "python-ocrmypdf":
            bundled_paths.append("baseline-pack/bin/ocrmypdf.exe")
        for path in package["files"]:
            file_owners[f"python/{path}"] = component_id
        components.append(
            {
                "component_id": component_id,
                "name": name,
                "version": package["version"],
                "license_concluded": conclusion,
                "source_url": f"https://pypi.org/project/{name}/{package['version']}/",
                "license_files": [f"python/{path}" for path in package["license_files"]]
                + external_licenses,
                "bundled_paths": sorted([*bundled_paths, *external_licenses]),
            }
        )

    notice_path = runtime_root / "THIRD_PARTY_NOTICES.txt"
    notice_path.write_text("\n".join(notices) + "\n", encoding="utf-8")
    runtime_manifest = {
        "schema_version": RUNTIME_MANIFEST_SCHEMA,
        "platform": WINDOWS_PLATFORM,
        "architecture": WINDOWS_ARCHITECTURE,
        "python": {
            **inputs["python"],
            "archive_bytes": python_archive.stat().st_size,
        },
        "application_version": __version__,
        "packages": [
            {
                "name": package["name"],
                "version": package["version"],
                "license_concluded": _python_license_conclusion(package, baseline),
            }
            for package in packages
        ],
        "build": {
            "dependency_locks": [
                "uv.lock",
                "desktop/packaging/baseline-requirements.txt",
            ],
            "production_only": True,
            "isolated_python": True,
        },
    }
    runtime_manifest_path = runtime_root / "runtime-manifest.json"
    _write_json(runtime_manifest_path, runtime_manifest)
    project_license = next(
        f"python/{path}"
        for package in packages
        if str(package["name"]).lower().replace("_", "-") == "doc-evidence"
        for path in package["license_files"]
    )
    components.append(
        {
            "component_id": "desktop-runtime-metadata",
            "name": "Doc Evidence desktop runtime metadata",
            "version": __version__,
            "license_concluded": "Apache-2.0",
            "source_url": "https://github.com/kzahel/doc-evidence",
            "license_files": [project_license],
            "bundled_paths": ["runtime-manifest.json", "THIRD_PARTY_NOTICES.txt"],
        }
    )
    file_owners["runtime-manifest.json"] = "desktop-runtime-metadata"
    file_owners["THIRD_PARTY_NOTICES.txt"] = "desktop-runtime-metadata"

    component_ids = [str(component["component_id"]) for component in components]
    if len(component_ids) != len(set(component_ids)):
        raise RuntimeError("Windows runtime repeats a component identifier")
    frontend = repository / "web" / "dist"
    if not frontend.is_dir():
        raise RuntimeError("web/dist must be built before Windows runtime staging")
    pe_records = {
        record["path"]: record
        for record in audit_runtime_pe_closure(
            runtime_root, system_dlls=list(baseline["system_dlls"])
        )
    }
    files = []
    for path in sorted(runtime_root.rglob("*")):
        if (
            not path.is_file()
            or path.is_symlink()
            or path.name == "bundle-manifest.json"
        ):
            continue
        relative = path.relative_to(runtime_root).as_posix()
        record = {
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "component_id": file_owners.get(relative, "cpython"),
        }
        if relative in pe_records:
            record["pe_architecture"] = "x86_64"
        files.append(record)
    if not set(file_owners).issubset({item["path"] for item in files}):
        raise RuntimeError("Windows runtime ownership names a missing file")
    bundle_manifest = {
        "schema_version": BUNDLE_MANIFEST_SCHEMA,
        "product": PRODUCT_NAME,
        "version": __version__,
        "identifier": PRODUCT_IDENTIFIER,
        "platform": WINDOWS_PLATFORM,
        "architecture": WINDOWS_ARCHITECTURE,
        "python_version": inputs["python"]["version"],
        "frontend_sha256": sha256_tree(frontend),
        "runtime_manifest_sha256": sha256_file(runtime_manifest_path),
        "extractor_packs": [baseline_metadata["identity"]],
        "components": components,
        "files": files,
    }
    schema = json.loads(
        (
            repository
            / "src"
            / "doc_evidence"
            / "schema_files"
            / "desktop-bundle-manifest.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    ).validate(bundle_manifest)
    _write_json(runtime_root / "bundle-manifest.json", bundle_manifest)


def validate_bundle_manifest(runtime_root: Path, repository: Path) -> dict[str, Any]:
    """Validate target identity plus the exact current runtime file inventory."""

    manifest_path = runtime_root / "bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = json.loads(
        (
            repository
            / "src"
            / "doc_evidence"
            / "schema_files"
            / "desktop-bundle-manifest.schema.json"
        ).read_text(encoding="utf-8")
    )
    jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    ).validate(manifest)
    if (manifest["platform"], manifest["architecture"]) != (
        WINDOWS_PLATFORM,
        WINDOWS_ARCHITECTURE,
    ):
        raise RuntimeError("Windows bundle manifest target is incompatible")
    if manifest["frontend_sha256"] != sha256_tree(repository / "web" / "dist"):
        raise RuntimeError("staged Windows frontend identity changed")
    runtime_manifest = runtime_root / "runtime-manifest.json"
    if manifest["runtime_manifest_sha256"] != sha256_file(runtime_manifest):
        raise RuntimeError("staged Windows runtime manifest identity changed")
    pack_identity = load_baseline_pack(
        runtime_root / "baseline-pack",
        expected_platform=WINDOWS_PLATFORM,
        expected_architecture=WINDOWS_ARCHITECTURE,
    )
    if manifest["extractor_packs"] != [pack_identity.model_dump(mode="json")]:
        raise RuntimeError("staged Windows baseline-pack identity changed")
    expected = {
        item["path"]: (item["bytes"], item["sha256"]) for item in manifest["files"]
    }
    actual = {
        path.relative_to(runtime_root).as_posix(): (
            path.stat().st_size,
            sha256_file(path),
        )
        for path in runtime_root.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and path.name != "bundle-manifest.json"
    }
    if expected != actual:
        raise RuntimeError("staged Windows runtime file inventory changed")
    return manifest


def _audit_no_symlinks(root: Path) -> list[str]:
    links = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_symlink()
    ]
    if links:
        raise RuntimeError(f"Windows desktop runtime contains links: {links[:10]}")
    return links


def baseline_environment(runtime_root: Path, writable_root: Path) -> dict[str, str]:
    pack = runtime_root / "baseline-pack"
    cache = writable_root / "cache"
    temporary = writable_root / "tmp"
    cache.mkdir(parents=True, exist_ok=True)
    temporary.mkdir(parents=True, exist_ok=True)
    system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    if not system_root:
        raise RuntimeError("Windows system root is unavailable")
    environment = {
        "DOC_EVIDENCE_BASELINE_PACK": str(pack),
        "PATH": os.pathsep.join(
            [
                str(pack / "bin"),
                str(runtime_root / "python"),
                str(Path(system_root) / "System32"),
                system_root,
            ]
        ),
        "TESSDATA_PREFIX": str(pack / "tessdata"),
        "XDG_CACHE_HOME": str(cache),
        "TEMP": str(temporary),
        "TMP": str(temporary),
        "SystemRoot": system_root,
        "WINDIR": system_root,
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
    }
    return environment


def smoke_baseline_pack(
    runtime_root: Path, inputs: Mapping[str, Any]
) -> dict[str, Any]:
    pack = runtime_root / "baseline-pack"
    identity = load_baseline_pack(
        pack,
        expected_platform=WINDOWS_PLATFORM,
        expected_architecture=WINDOWS_ARCHITECTURE,
    )
    baseline = inputs["baseline_pack"]
    with tempfile.TemporaryDirectory(prefix="doc-evidence-windows-ocr-") as raw:
        working = Path(raw)
        environment = baseline_environment(runtime_root, working)
        commands = {
            "pdfinfo": [pack / "bin" / "pdfinfo.exe", "-v"],
            "pdftotext": [pack / "bin" / "pdftotext.exe", "-v"],
            "pdftoppm": [pack / "bin" / "pdftoppm.exe", "-v"],
            "tesseract": [pack / "bin" / "tesseract.exe", "--version"],
            "ocrmypdf": [pack / "bin" / "ocrmypdf.exe", "--version"],
        }
        versions = {}
        for name, command in commands.items():
            result = _run(
                command,
                cwd=working,
                environment=environment,
                capture_output=True,
                timeout_seconds=60,
            )
            lines = (result.stdout + result.stderr).splitlines()
            if not lines:
                raise RuntimeError(f"Windows baseline tool returned no version: {name}")
            versions[name] = lines[0]
        expected_versions = {
            "pdfinfo": str(baseline["native_components"]["poppler"]["version"]),
            "pdftotext": str(baseline["native_components"]["poppler"]["version"]),
            "pdftoppm": str(baseline["native_components"]["poppler"]["version"]),
            "tesseract": str(baseline["native_components"]["tesseract"]["version"]),
            "ocrmypdf": str(baseline["python_components"]["ocrmypdf"]),
        }
        for name, expected in expected_versions.items():
            if expected not in versions[name]:
                raise RuntimeError(f"Windows baseline tool version drifted: {name}")
        language_result = _run(
            [pack / "bin" / "tesseract.exe", "--list-langs"],
            cwd=working,
            environment=environment,
            capture_output=True,
            timeout_seconds=60,
        )
        languages = {
            line.strip()
            for line in (language_result.stdout + language_result.stderr).splitlines()
            if line.strip() in {"eng", "deu", "osd"}
        }
        if languages != {"eng", "deu", "osd"}:
            raise RuntimeError("Windows baseline Tesseract languages are unavailable")
        for name in ("gs.exe", "gswin32c.exe", "gswin64c.exe"):
            if shutil.which(name, path=environment["PATH"]) is not None:
                raise RuntimeError("Ghostscript entered the Windows baseline runtime")

        source = working / "synthetic scan.pdf"
        fixture_script = r"""
import os
import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
image = Image.new("RGB", (1800, 1100), "white")
draw = ImageDraw.Draw(image)
font = ImageFont.truetype(str(Path(os.environ["WINDIR"]) / "Fonts" / "arial.ttf"), 72)
lines = [
    "DOC EVIDENCE 12345",
    "LOCAL DOCUMENT REVIEW",
    "SOURCE PROVENANCE RECORD",
    "EXTRACTED TEXT VALIDATION",
    "HUMAN CONFIRMATION REQUIRED",
]
for index, line in enumerate(lines):
    draw.text((80, 100 + index * 180), line, fill="black", font=font)
image.save(sys.argv[1], "PDF", resolution=200.0)
"""
        _run(
            [
                runtime_root / "python" / "python.exe",
                "-I",
                "-B",
                "-c",
                fixture_script,
                source,
            ],
            cwd=working,
            environment=environment,
            capture_output=True,
            timeout_seconds=60,
        )
        output = working / "ocr output.pdf"
        sidecar = working / "ocr sidecar.txt"
        try:
            ocr = _run(
                [
                    pack / "bin" / "ocrmypdf.exe",
                    "--language",
                    "eng+deu",
                    "--rotate-pages",
                    "--deskew",
                    "--skip-text",
                    "--output-type",
                    "pdf",
                    "--optimize",
                    "0",
                    "--sidecar",
                    sidecar,
                    source,
                    output,
                ],
                cwd=working,
                environment=environment,
                capture_output=True,
                timeout_seconds=300,
            )
        except subprocess.CalledProcessError as error:
            detail = ((error.stdout or "") + (error.stderr or ""))[-4000:]
            raise RuntimeError(
                f"Ghostscript-free Windows baseline OCR failed: {detail}"
            ) from error
        if not output.is_file() or not sidecar.is_file():
            raise RuntimeError("Windows baseline OCR produced no output")
        extracted = _run(
            [pack / "bin" / "pdftotext.exe", output, "-"],
            cwd=working,
            environment=environment,
            capture_output=True,
            timeout_seconds=60,
        ).stdout
        if "12345" not in extracted:
            raise RuntimeError(
                "Windows baseline OCR synthetic text was not recoverable"
            )
        combined_log = ocr.stdout + ocr.stderr
        if str(repository_root()) in combined_log:
            raise RuntimeError("Windows baseline OCR leaked a build-host path")
        return {
            "status": "passed",
            "identity": identity.model_dump(mode="json"),
            "versions": versions,
            "languages": sorted(languages),
            "ghostscript_available": False,
            "synthetic_ocr_text": "DOC EVIDENCE 12345",
        }


def _read_ready_line(process: subprocess.Popen[str], *, timeout_seconds: float) -> str:
    stdout = process.stdout
    if stdout is None:
        raise RuntimeError("Windows sidecar startup output is unavailable")
    result: queue.Queue[tuple[bool, str]] = queue.Queue(maxsize=1)

    def read() -> None:
        try:
            result.put((True, stdout.readline(64 * 1024 + 1)))
        except (OSError, ValueError) as error:
            result.put((False, str(error)))

    threading.Thread(target=read, daemon=True).start()
    try:
        ok, value = result.get(timeout=timeout_seconds)
    except queue.Empty as error:
        raise RuntimeError("Windows desktop sidecar did not become ready") from error
    if not ok:
        raise RuntimeError(f"Windows desktop ready record is unreadable: {value}")
    if len(value.encode()) > 64 * 1024 or not value.endswith("\n"):
        raise RuntimeError("Windows desktop ready record exceeded its bound")
    return value


def smoke_sidecar(runtime_root: Path) -> dict[str, Any]:
    runtime_token = secrets.token_hex(32)
    control_token = secrets.token_hex(32)
    with tempfile.TemporaryDirectory(prefix="doc-evidence-windows-sidecar-") as raw:
        working = Path(raw)
        environment = {
            **baseline_environment(runtime_root, working),
            "DOC_EVIDENCE_DESKTOP_RUNTIME_TOKEN": runtime_token,
            "DOC_EVIDENCE_DESKTOP_HOST_CONTROL_TOKEN": control_token,
            "DOC_EVIDENCE_DESKTOP_APP_HOME": str(working / "application data"),
            DESKTOP_PLATFORM_ENV: WINDOWS_PLATFORM,
            DESKTOP_ARCHITECTURE_ENV: WINDOWS_ARCHITECTURE,
        }
        process = subprocess.Popen(
            [
                str(runtime_root / "python" / "python.exe"),
                "-I",
                "-B",
                "-m",
                "doc_evidence.desktop_sidecar",
                "--expected-protocol",
                DESKTOP_PROTOCOL_VERSION,
                "--desktop-origin",
                WINDOWS_DESKTOP_ORIGIN,
            ],
            cwd=working,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if process.stdin is None or process.stderr is None:
            process.kill()
            raise RuntimeError("Windows desktop smoke pipes are unavailable")
        try:
            ready_line = _read_ready_line(process, timeout_seconds=30)
            ready = json.loads(ready_line)
            expected_pack = load_baseline_pack(
                runtime_root / "baseline-pack",
                expected_platform=WINDOWS_PLATFORM,
                expected_architecture=WINDOWS_ARCHITECTURE,
            ).model_dump(mode="json")
            if (
                ready.get("protocol_version") != DESKTOP_PROTOCOL_VERSION
                or ready.get("application_version") != __version__
                or ready.get("host") != "127.0.0.1"
                or ready.get("platform") != WINDOWS_PLATFORM
                or ready.get("architecture") != WINDOWS_ARCHITECTURE
                or ready.get("baseline_pack") != expected_pack
            ):
                raise RuntimeError("Windows desktop ready record is incompatible")
            url = f"http://127.0.0.1:{ready['port']}/api/v1/desktop/handshake"
            unauthenticated = urllib.request.Request(
                url, headers={"Origin": WINDOWS_DESKTOP_ORIGIN}
            )
            try:
                urllib.request.urlopen(unauthenticated, timeout=3)
            except urllib.error.HTTPError as error:
                if error.code != 401:
                    raise RuntimeError(
                        "Windows desktop smoke returned unexpected auth status"
                    ) from error
            else:
                raise RuntimeError(
                    "Windows desktop smoke accepted an unauthenticated request"
                )
            authenticated = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {runtime_token}",
                    "Origin": WINDOWS_DESKTOP_ORIGIN,
                },
            )
            with urllib.request.urlopen(authenticated, timeout=3) as response:
                handshake = json.load(response)
            if handshake.get("protocol_version") != DESKTOP_PROTOCOL_VERSION:
                raise RuntimeError("Windows desktop smoke handshake is incompatible")
            process.stdin.close()
            if process.wait(timeout=20) != 0:
                raise RuntimeError("Windows desktop sidecar did not stop cleanly")
            stderr = process.stderr.read()
            if (
                runtime_token in ready_line
                or runtime_token in stderr
                or control_token in stderr
            ):
                raise RuntimeError("Windows desktop smoke leaked a launch credential")
            return {
                "status": "passed",
                "protocol_version": DESKTOP_PROTOCOL_VERSION,
                "unauthenticated_status": 401,
                "parent_eof_shutdown": True,
            }
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


def smoke_long_path_io(runtime_root: Path) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="doc-evidence-windows-long-path-") as raw:
        working = Path(raw)
        environment = baseline_environment(runtime_root, working)
        script = r"""
import json
import sys
from pathlib import Path
root = Path(sys.argv[1])
path = root.joinpath(*[("segment-" + str(i).zfill(2) + "-" + "x" * 36) for i in range(7)])
target = path / "evidence.txt"
target.parent.mkdir(parents=True)
target.write_text("long-path-ok", encoding="utf-8")
if target.read_text(encoding="utf-8") != "long-path-ok":
    raise RuntimeError("long path round trip changed bytes")
print(json.dumps({"path_length": len(str(target)), "round_trip": True}))
"""
        result = _run(
            [
                runtime_root / "python" / "python.exe",
                "-I",
                "-B",
                "-c",
                script,
                working / "library with spaces",
            ],
            cwd=working,
            environment=environment,
            capture_output=True,
            timeout_seconds=60,
        )
        record = json.loads(result.stdout)
        if record.get("path_length", 0) <= 260 or record.get("round_trip") is not True:
            raise RuntimeError("standalone Python did not exercise long-path I/O")
        return {"status": "passed", **record}


def audit_runtime(
    runtime_root: Path,
    *,
    repository: Path | None = None,
    smoke: bool = False,
) -> dict[str, Any]:
    root = runtime_root.resolve()
    repo = (repository or repository_root()).resolve()
    if not root.is_dir():
        raise RuntimeError(f"Windows desktop runtime does not exist: {root}")
    inputs = _load_inputs(repo)
    manifest = validate_bundle_manifest(root, repo)
    packages = distribution_inventory(root / "python")
    forbidden = {
        str(name).lower().replace("_", "-")
        for name in inputs["forbidden_python_distributions"]
    }
    included = {str(item["name"]).lower().replace("_", "-") for item in packages}
    unexpected = sorted(forbidden & included)
    if unexpected:
        raise RuntimeError(
            f"development packages entered Windows desktop runtime: {unexpected}"
        )
    result = {
        "schema_version": "doc-evidence.desktop-runtime-audit.v1",
        "status": "passed",
        "root": str(root),
        "tree_sha256": sha256_tree(root),
        "installed_bytes": sum(
            path.stat().st_size for path in root.rglob("*") if path.is_file()
        ),
        "file_count": sum(1 for path in root.rglob("*") if path.is_file()),
        "package_count": len(packages),
        "native_files": audit_runtime_pe_closure(
            root, system_dlls=list(inputs["baseline_pack"]["system_dlls"])
        ),
        "symlinks": _audit_no_symlinks(root),
        "manifest": {
            "version": manifest["version"],
            "python_version": manifest["python_version"],
            "component_count": len(manifest["components"]),
        },
    }
    if smoke:
        result["baseline_smoke"] = smoke_baseline_pack(root, inputs)
        result["sidecar_smoke"] = smoke_sidecar(root)
        result["long_path_smoke"] = smoke_long_path_io(root)
    return result


def stage_runtime(
    *,
    root: Path | None = None,
    cache: Path | None = None,
    destination: Path | None = None,
    replace: bool = False,
    seven_zip: str | Path | None = None,
) -> Path:
    """Transactionally stage and copied-out-smoke the Windows desktop runtime."""

    _require_windows_host()
    repository = (root or repository_root()).resolve()
    target = (destination or stage_root(repository)).resolve()
    cache_directory = (cache or cache_root(repository)).resolve()
    previous = target.with_name(f"{target.name}.previous")
    if previous.exists():
        raise RuntimeError(f"stale Windows runtime rollback exists: {previous}")
    if target.exists():
        if not replace:
            raise RuntimeError(f"Windows runtime staging target exists: {target}")
        audit_runtime(target, repository=repository, smoke=False)
        os.replace(target, previous)
    inputs = _load_inputs(repository)
    python_archive = acquire_archive(inputs["python"], cache_directory)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(
            prefix="doc-evidence-windows-runtime-", dir=target.parent
        ) as raw:
            temporary = Path(raw)
            python_root = extract_python_runtime(
                python_archive, temporary / "standalone"
            )
            python_components = stage_python_dependencies(
                repository, python_root, inputs
            )
            prune_python_runtime(python_root)
            staged = temporary / "desktop-runtime"
            staged.mkdir()
            os.replace(python_root, staged / "python")
            baseline_metadata = stage_baseline_pack(
                repository,
                staged,
                inputs,
                python_components,
                cache=cache_directory,
                seven_zip=seven_zip,
            )
            write_runtime_manifests(
                repository,
                staged,
                python_archive,
                inputs,
                baseline_metadata,
            )
            audit_runtime(staged, repository=repository, smoke=False)
            with tempfile.TemporaryDirectory(
                prefix="doc-evidence-windows-copy-", dir=target.parent
            ) as copied_raw:
                copied = Path(copied_raw) / "copied desktop runtime"
                shutil.copytree(staged, copied)
                audit_runtime(copied, repository=repository, smoke=True)
            os.replace(staged, target)
    except BaseException:
        if previous.exists() and not target.exists():
            os.replace(previous, target)
        raise
    if previous.exists():
        shutil.rmtree(previous)
    return target


def _cli(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    stage = subcommands.add_parser("stage")
    stage.add_argument("--replace", action="store_true")
    stage.add_argument("--cache", type=Path)
    stage.add_argument("--destination", type=Path)
    stage.add_argument("--seven-zip", type=Path)
    audit = subcommands.add_parser("audit")
    audit.add_argument("path", nargs="?", type=Path)
    audit.add_argument("--smoke", action="store_true")
    values = parser.parse_args(arguments)
    if values.command == "stage":
        path = stage_runtime(
            cache=values.cache,
            destination=values.destination,
            replace=values.replace,
            seven_zip=values.seven_zip,
        )
        print(path)
        return 0
    path = values.path or stage_root()
    print(json.dumps(audit_runtime(path, smoke=values.smoke), indent=2))
    return 0


def main() -> None:
    raise SystemExit(_cli())


def _is_windows_api_set(name: str) -> bool:
    folded = name.casefold()
    return folded.startswith(("api-ms-win-", "ext-ms-win-")) and folded.endswith(".dll")


def audit_flat_pe_closure(
    root: Path, *, system_dlls: list[str]
) -> list[dict[str, Any]]:
    """Audit one flat executable/DLL directory and its direct closure."""

    native = sorted(
        (
            path
            for path in root.iterdir()
            if path.is_file() and path.suffix.casefold() in _NATIVE_SUFFIXES
        ),
        key=lambda path: path.name.casefold(),
    )
    if not native:
        raise RuntimeError("Windows native directory has no PE files")
    by_name: dict[str, Path] = {}
    for path in native:
        folded = path.name.casefold()
        if folded in by_name:
            raise RuntimeError(f"Windows native directory repeats {path.name}")
        by_name[folded] = path
    allowed_system = {name.casefold() for name in system_dlls}
    records: list[dict[str, Any]] = []
    missing: dict[str, set[str]] = {}
    for path in native:
        pe = inspect_pe(path)
        if pe.machine != PE_X86_64_MACHINE or pe.format != "PE32+":
            raise RuntimeError(f"Windows native file is not x86_64 PE32+: {path.name}")
        dependencies: list[dict[str, str]] = []
        for name in (*pe.imports, *pe.delay_imports):
            folded = name.casefold()
            if folded in by_name:
                kind = "bundled"
            elif folded in allowed_system or _is_windows_api_set(name):
                kind = "windows-system"
            else:
                missing.setdefault(path.name, set()).add(name)
                continue
            dependencies.append({"name": name, "kind": kind})
        records.append(
            {
                "path": path.name,
                "sha256": sha256_file(path),
                "machine": "x86_64",
                "format": pe.format,
                "dependencies": dependencies,
            }
        )
    if missing:
        detail = "; ".join(
            f"{source}: {', '.join(sorted(names, key=str.casefold))}"
            for source, names in sorted(missing.items())
        )
        raise RuntimeError(f"Windows native dependency closure is incomplete: {detail}")
    return records


def audit_runtime_pe_closure(
    root: Path, *, system_dlls: list[str]
) -> list[dict[str, Any]]:
    """Audit architecture and bounded loader/package closure for every runtime PE."""

    native = sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file()
            and not path.is_symlink()
            and path.suffix.casefold() in _NATIVE_SUFFIXES
        ),
        key=lambda path: path.relative_to(root).as_posix().casefold(),
    )
    if not native:
        raise RuntimeError("Windows desktop runtime has no PE files")
    by_name: dict[str, list[Path]] = {}
    by_relative: dict[str, Path] = {}
    for path in native:
        relative = path.relative_to(root).as_posix()
        folded_relative = relative.casefold()
        if folded_relative in by_relative:
            raise RuntimeError(f"Windows runtime repeats a path: {relative}")
        by_relative[folded_relative] = path
        by_name.setdefault(path.name.casefold(), []).append(path)
    search_roots = [
        root / "python",
        root / "python" / "DLLs",
        root / "baseline-pack" / "bin",
    ]
    allowed_system = {name.casefold() for name in system_dlls}
    missing: dict[str, set[str]] = {}
    ambiguous: dict[str, set[str]] = {}
    records: list[dict[str, Any]] = []
    for path in native:
        pe = inspect_pe(path)
        relative = path.relative_to(root).as_posix()
        if pe.machine != PE_X86_64_MACHINE or pe.format != "PE32+":
            raise RuntimeError(f"Windows runtime PE is not x86_64 PE32+: {relative}")
        dependencies: list[dict[str, str]] = []
        seen: set[str] = set()
        for name in (*pe.imports, *pe.delay_imports):
            folded = name.casefold()
            if folded in seen:
                continue
            seen.add(folded)
            if folded in allowed_system or _is_windows_api_set(name):
                dependencies.append({"name": name, "kind": "windows-system"})
                continue
            candidates = by_name.get(folded, [])
            loader_candidates = []
            for directory in (path.parent, *search_roots):
                match = next(
                    (
                        candidate
                        for candidate in candidates
                        if candidate.parent == directory
                    ),
                    None,
                )
                if match is not None and match not in loader_candidates:
                    loader_candidates.append(match)
            if loader_candidates:
                resolved = loader_candidates[0]
                kind = "bundled-loader-path"
            elif len(candidates) == 1:
                resolved = candidates[0]
                kind = "bundled-package-private"
            elif not candidates:
                missing.setdefault(relative, set()).add(name)
                continue
            else:
                ambiguous.setdefault(relative, set()).add(name)
                continue
            dependencies.append(
                {
                    "name": name,
                    "kind": kind,
                    "path": resolved.relative_to(root).as_posix(),
                }
            )
        records.append(
            {
                "path": relative,
                "sha256": sha256_file(path),
                "machine": "x86_64",
                "format": pe.format,
                "dependencies": dependencies,
            }
        )
    problems = []
    for label, values in (("missing", missing), ("ambiguous", ambiguous)):
        problems.extend(
            f"{source}: {label} {', '.join(sorted(names, key=str.casefold))}"
            for source, names in sorted(values.items())
        )
    if problems:
        raise RuntimeError(
            "Windows runtime PE dependency closure is incomplete: "
            + "; ".join(problems)
        )
    return records


if __name__ == "__main__":
    main()
