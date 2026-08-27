"""Reproducible staging and audit for the local macOS desktop application."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import platform
import plistlib
import re
import secrets
import select
import shutil
import stat
import struct
import subprocess
import tarfile
import tempfile
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import deque
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jsonschema

from doc_evidence import __version__
from doc_evidence.contracts.desktop import (
    DESKTOP_ARCHITECTURE_ENV,
    DESKTOP_PLATFORM_ENV,
    DESKTOP_PROTOCOL_VERSION,
    MACOS_DESKTOP_ORIGIN,
)
from doc_evidence.desktop_pack import BASELINE_PACK_ENV, load_baseline_pack
from doc_evidence.desktop_signing import refresh_signed_runtime_manifests

BUNDLE_MANIFEST_SCHEMA = "doc-evidence.desktop-bundle-manifest.v1"
RUNTIME_MANIFEST_SCHEMA = "doc-evidence.desktop-runtime-manifest.v1"
BUILD_INPUTS_SCHEMA = "doc-evidence.desktop-build-inputs.v1"
RUST_LICENSE_SOURCES_SCHEMA = "doc-evidence.macos-rust-license-sources.v1"
WHEEL_NATIVE_COMPONENTS_SCHEMA = "doc-evidence.macos-wheel-native-components.v1"
PRODUCT_NAME = "Doc Evidence"
PRODUCT_IDENTIFIER = "io.github.kzahel.doc-evidence"
SYSTEM_LOAD_PREFIXES = ("/System/Library/", "/usr/lib/")
HOMEBREW_BUILD_PREFIX = b"/opt/homebrew"
NEUTRAL_BUILD_PREFIX = b"/__doc_evid__"
MAX_READY_BYTES = 64 * 1024
_LICENSE_NAMES = ("license", "licence", "copying", "notice")
_SPDX_LICENSE_NORMALIZATION = {
    "Apache License 2.0": "Apache-2.0",
    "OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)": ("LGPL-3.0-only"),
    "OSI Approved :: MIT License": "MIT",
    "PSFL": "PSF-2.0",
}


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_inputs_path(root: Path | None = None) -> Path:
    base = root or repository_root()
    return base / "desktop" / "packaging" / "macos-arm64.json"


def rust_license_sources_path(root: Path | None = None) -> Path:
    base = root or repository_root()
    return base / "desktop" / "packaging" / "macos-rust-license-sources.json"


def wheel_native_components_path(root: Path | None = None) -> Path:
    base = root or repository_root()
    return base / "desktop" / "packaging" / "macos-wheel-native-components.json"


def stage_root(root: Path | None = None) -> Path:
    base = root or repository_root()
    return base / "desktop" / "src-tauri" / "resources" / "desktop-runtime"


def cache_root(root: Path | None = None) -> Path:
    base = root or repository_root()
    return base / "results" / "desktop" / "cache"


def distribution_root(root: Path | None = None) -> Path:
    base = root or repository_root()
    return base / "results" / "desktop" / "distribution"


def application_bundle_path(root: Path | None = None) -> Path:
    base = root or repository_root()
    return (
        base
        / "desktop"
        / "src-tauri"
        / "target"
        / "release"
        / "bundle"
        / "macos"
        / f"{PRODUCT_NAME}.app"
    )


def unsigned_dmg_path(root: Path | None = None) -> Path:
    return distribution_root(root) / f"Doc-Evidence_{__version__}_aarch64-unsigned.dmg"


def compliance_root(root: Path | None = None) -> Path:
    return distribution_root(root) / f"Doc-Evidence_{__version__}_compliance-preflight"


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    paths = sorted(root.rglob("*"), key=lambda path: path.relative_to(root).as_posix())
    for path in paths:
        relative = path.relative_to(root).as_posix().encode()
        if path.is_symlink():
            digest.update(
                b"L\0" + relative + b"\0" + os.readlink(path).encode() + b"\0"
            )
        elif path.is_file():
            digest.update(b"F\0" + relative + b"\0")
            digest.update(bytes.fromhex(sha256_file(path)))
    return digest.hexdigest()


def _load_inputs(root: Path) -> dict[str, Any]:
    document = json.loads(build_inputs_path(root).read_text(encoding="utf-8"))
    if (
        document.get("schema_version") != BUILD_INPUTS_SCHEMA
        or document.get("platform") != "macos"
        or document.get("architecture") != "arm64"
    ):
        raise RuntimeError("desktop build inputs are incompatible")
    python = document.get("python")
    if not isinstance(python, dict):
        raise TypeError("desktop Python input is missing")
    required = {"version", "build", "url", "sha256", "license_concluded"}
    if not required.issubset(python):
        raise RuntimeError("desktop Python input is incomplete")
    if len(str(python["sha256"])) != 64:
        raise RuntimeError("desktop Python input hash is malformed")
    return document


def _require_host() -> None:
    if platform.system() != "Darwin" or platform.machine() not in {"arm64", "aarch64"}:
        raise RuntimeError("desktop packaging requires macOS arm64")


def _archive_path(inputs: Mapping[str, Any], cache: Path) -> Path:
    python = inputs["python"]
    url_path = urllib.parse.unquote(urllib.parse.urlparse(str(python["url"])).path)
    name = Path(url_path).name
    if not name.endswith(".tar.gz"):
        raise RuntimeError("desktop Python input is not a tar.gz archive")
    return cache / name


def acquire_python_archive(inputs: Mapping[str, Any], cache: Path) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    archive = _archive_path(inputs, cache)
    expected = str(inputs["python"]["sha256"])
    if archive.is_file() and sha256_file(archive) == expected:
        return archive
    if archive.exists():
        archive.unlink()
    temporary = archive.with_suffix(f"{archive.suffix}.partial")
    temporary.unlink(missing_ok=True)
    try:
        with (
            urllib.request.urlopen(
                str(inputs["python"]["url"]), timeout=60
            ) as response,
            temporary.open("wb") as output,
        ):
            shutil.copyfileobj(response, output)
        actual = sha256_file(temporary)
        if actual != expected:
            raise RuntimeError(
                f"desktop Python archive hash mismatch: expected {expected}, got {actual}"
            )
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)
    return archive


def acquire_declared_archive(record: Mapping[str, Any], cache: Path) -> Path:
    cache.mkdir(parents=True, exist_ok=True)
    name = record.get("cache_name")
    if not isinstance(name, str) or not name or Path(name).name != name:
        raise RuntimeError("declared source archive cache name is invalid")
    archive = cache / name
    expected = str(record.get("sha256", ""))
    if archive.is_file() and sha256_file(archive) == expected:
        return archive
    if archive.exists():
        archive.unlink()
    temporary = archive.with_suffix(f"{archive.suffix}.partial")
    temporary.unlink(missing_ok=True)
    try:
        with (
            urllib.request.urlopen(str(record["url"]), timeout=60) as response,
            temporary.open("wb") as output,
        ):
            shutil.copyfileobj(response, output)
        actual = sha256_file(temporary)
        if actual != expected:
            raise RuntimeError(
                f"declared source archive hash mismatch: expected {expected}, got {actual}"
            )
        os.replace(temporary, archive)
    finally:
        temporary.unlink(missing_ok=True)
    return archive


def _extract_python(archive: Path, destination: Path) -> Path:
    with tarfile.open(archive, "r:gz") as source:
        source.extractall(destination, filter="data")
    python_root = destination / "python"
    if not (python_root / "bin" / "python3").is_file():
        raise RuntimeError("standalone Python archive has an unexpected layout")
    return python_root


def copy_clean_project_source(root: Path, destination: Path) -> Path:
    """Copy only declared project build inputs into a fresh source tree."""

    if destination.exists():
        raise RuntimeError(f"project build context already exists: {destination}")
    destination.mkdir(parents=True)
    for relative in ("LICENSE", "README.md", "pyproject.toml"):
        source = root / relative
        if not source.is_file() or source.is_symlink():
            raise RuntimeError(f"project build input is invalid: {relative}")
        shutil.copy2(source, destination / relative)
    package = root / "src" / "doc_evidence"
    if not package.is_dir() or package.is_symlink():
        raise RuntimeError("project package source is invalid")
    for source in package.rglob("*"):
        if source.is_symlink():
            raise RuntimeError(
                f"project package source contains a symbolic link: "
                f"{source.relative_to(package)}"
            )
    shutil.copytree(package, destination / "src" / "doc_evidence")
    return destination


def _stage_dependencies(root: Path, python_root: Path) -> None:
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
        cwd=root,
        capture_output=True,
    )
    externally_managed = python_root / "lib" / "python3.12" / "EXTERNALLY-MANAGED"
    externally_managed.unlink(missing_ok=True)
    python = python_root / "bin" / "python3"
    _run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            python,
            "--requirements",
            requirements,
            "--require-hashes",
            "--strict",
            "--link-mode",
            "copy",
        ],
        cwd=root,
    )
    with tempfile.TemporaryDirectory(prefix="doc-evidence-project-source-") as raw:
        project = copy_clean_project_source(root, Path(raw) / "project")
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
                project,
            ],
            cwd=project,
        )
    requirements.unlink()


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _prune_runtime(python_root: Path) -> None:
    for relative in (
        "include",
        "share/man",
        "lib/pkgconfig",
        "lib/python3.12/idlelib",
        "lib/python3.12/test",
        "lib/python3.12/tkinter",
        "lib/python3.12/turtledemo",
    ):
        _remove_path(python_root / relative)
    site_packages = python_root / "lib" / "python3.12" / "site-packages"
    for build_only_module in (
        "desktop_packaging.py",
        "windows_desktop_packaging.py",
        "windows_pe.py",
    ):
        (site_packages / "doc_evidence" / build_only_module).unlink(missing_ok=True)
    for candidate in list(site_packages.glob("pip*")):
        _remove_path(candidate)
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
    binaries = python_root / "bin"
    interpreter = binaries / ".python3.staged"
    shutil.copy2((binaries / "python3").resolve(), interpreter)
    interpreter.chmod(interpreter.stat().st_mode | stat.S_IXUSR)
    for executable in list(binaries.iterdir()):
        if executable != interpreter:
            _remove_path(executable)
    os.replace(interpreter, binaries / "python3")


def _baseline_requirements(root: Path) -> Path:
    return root / "desktop" / "packaging" / "baseline-requirements.txt"


def _locked_requirements(path: Path) -> list[str]:
    values = []
    pattern = re.compile(r"^([A-Za-z0-9_.-]+)==([^ ;\\]+)")
    for line in path.read_text(encoding="utf-8").splitlines():
        matched = pattern.match(line)
        if matched:
            values.append(f"{matched.group(1)}=={matched.group(2)}")
    if not values:
        raise RuntimeError("baseline Python requirements are empty")
    return values


def _excluded_baseline_distributions(inputs: Mapping[str, Any]) -> set[str]:
    baseline = inputs.get("baseline_pack")
    values = (
        baseline.get("excluded_python_distributions")
        if isinstance(baseline, Mapping)
        else None
    )
    if not isinstance(values, list) or not values:
        raise TypeError("excluded baseline Python distributions are invalid")
    normalized = {
        str(value).lower().replace("_", "-")
        for value in values
        if isinstance(value, str) and value
    }
    if len(normalized) != len(values):
        raise RuntimeError(
            "excluded baseline Python distributions repeat or are invalid"
        )
    return normalized


def _included_locked_requirements(requirements: Path, excluded: set[str]) -> list[str]:
    included = []
    for value in _locked_requirements(requirements):
        name = value.split("==", 1)[0].lower().replace("_", "-")
        if name not in excluded:
            included.append(value)
    return included


def _stage_baseline_python(
    repository: Path,
    python_root: Path,
    inputs: Mapping[str, Any],
) -> list[str]:
    requirements = _baseline_requirements(repository)
    baseline = inputs.get("baseline_pack")
    if not isinstance(baseline, dict):
        raise TypeError("baseline extractor-pack inputs are missing")
    if sha256_file(requirements) != baseline.get("requirements_sha256"):
        raise RuntimeError("baseline Python requirements identity changed")
    _run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            python_root / "bin" / "python3",
            "--requirements",
            requirements,
            "--require-hashes",
            "--strict",
            "--link-mode",
            "copy",
        ],
        cwd=repository,
    )
    excluded = _excluded_baseline_distributions(inputs)
    _run(
        [
            "uv",
            "pip",
            "uninstall",
            "--python",
            python_root / "bin" / "python3",
            *sorted(excluded),
        ],
        cwd=repository,
    )
    return _included_locked_requirements(requirements, excluded)


def _thin_python_native(python_root: Path) -> list[str]:
    modified = []
    for path in python_root.rglob("*"):
        if not _is_macho(path):
            continue
        description = _run(["file", "-b", path], capture_output=True).stdout
        if "arm64" not in description:
            raise RuntimeError(f"Python native file has no arm64 slice: {path}")
        changed = False
        if "x86_64" in description:
            mode = path.stat().st_mode
            thinned = path.with_name(f"{path.name}.arm64")
            _run(
                ["lipo", path, "-thin", "arm64", "-output", thinned],
                capture_output=True,
            )
            os.replace(thinned, path)
            path.chmod(mode)
            changed = True
        changed = _neutralize_native_build_prefix(path) or changed
        if not changed:
            continue
        _run(
            ["codesign", "--force", "--sign", "-", path],
            capture_output=True,
        )
        modified.append(path.relative_to(python_root).as_posix())
    return modified


def _neutralize_native_build_prefix(path: Path) -> bool:
    content = path.read_bytes()
    if HOMEBREW_BUILD_PREFIX not in content:
        return False
    if len(HOMEBREW_BUILD_PREFIX) != len(NEUTRAL_BUILD_PREFIX):
        raise RuntimeError("native build-prefix replacement changed length")
    path.write_bytes(content.replace(HOMEBREW_BUILD_PREFIX, NEUTRAL_BUILD_PREFIX))
    return True


def _staged_wheel_native_bytes(member: str, content: bytes) -> bytes:
    if HOMEBREW_BUILD_PREFIX not in content:
        return content
    with tempfile.TemporaryDirectory(prefix="doc-evidence-wheel-native-") as raw:
        candidate = Path(raw) / Path(member).name
        candidate.write_bytes(content)
        candidate.chmod(0o755)
        _neutralize_native_build_prefix(candidate)
        _run(
            ["codesign", "--force", "--sign", "-", candidate],
            capture_output=True,
        )
        return candidate.read_bytes()


def _homebrew_formula(path: Path) -> str | None:
    parts = path.resolve().parts
    if "Cellar" not in parts:
        return None
    index = parts.index("Cellar")
    return parts[index + 1] if index + 1 < len(parts) else None


def _homebrew_formula_record(formula: str) -> dict[str, Any]:
    prefix = Path(
        _run(["brew", "--prefix", formula], capture_output=True).stdout.strip()
    ).resolve()
    if not prefix.is_dir() or prefix.parent.name != formula:
        raise RuntimeError(f"Homebrew formula prefix is incompatible: {formula}")
    document = json.loads(
        _run(["brew", "info", "--json=v2", formula], capture_output=True).stdout
    )
    value = document["formulae"][0]
    license_concluded = value.get("license")
    if not isinstance(license_concluded, str) or not license_concluded:
        raise RuntimeError(f"Homebrew formula lacks license metadata: {formula}")
    return {
        "formula": formula,
        "version": prefix.name,
        "prefix": prefix,
        "license_concluded": license_concluded,
        "formula_url": f"https://formulae.brew.sh/formula/{formula}",
        "upstream_url": value.get("homepage")
        or value.get("urls", {}).get("stable", {}).get("url"),
    }


def _macho_rpaths(path: Path) -> list[str]:
    result = _run(["otool", "-l", path], capture_output=True)
    values = []
    waiting = False
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if stripped == "cmd LC_RPATH":
            waiting = True
        elif waiting and stripped.startswith("path "):
            values.append(stripped.removeprefix("path ").split(" (offset", 1)[0])
            waiting = False
    return values


def _expand_loader_path(value: str, source: Path) -> Path:
    if value == "@loader_path":
        return source.parent
    if value.startswith("@loader_path/"):
        return source.parent / value.removeprefix("@loader_path/")
    if value == "@executable_path":
        return source.parent
    if value.startswith("@executable_path/"):
        return source.parent / value.removeprefix("@executable_path/")
    return Path(value)


def _resolve_load_dependency(load_path: str, source: Path) -> Path:
    if load_path.startswith("@rpath/"):
        relative = load_path.removeprefix("@rpath/")
        for rpath in _macho_rpaths(source):
            candidate = _expand_loader_path(rpath, source) / relative
            if candidate.is_file():
                return candidate.resolve()
        raise RuntimeError(
            f"native @rpath dependency is unresolved: {load_path} from {source}"
        )
    candidate = _expand_loader_path(load_path, source)
    if not candidate.is_file():
        raise RuntimeError(
            f"native dependency is unresolved: {load_path} from {source}"
        )
    return candidate.resolve()


def _copy_native_dependency(
    source: Path,
    libraries: Path,
    copied: dict[str, Path],
) -> Path:
    resolved = source.resolve()
    destination = libraries / resolved.name
    if resolved.name in copied:
        if sha256_file(copied[resolved.name]) != sha256_file(resolved):
            raise RuntimeError(f"native dependency basename collision: {resolved.name}")
        return copied[resolved.name]
    shutil.copy2(resolved, destination)
    destination.chmod(destination.stat().st_mode | stat.S_IWUSR | stat.S_IXUSR)
    copied[resolved.name] = destination
    return destination


def _copy_formula_license(
    pack: Path,
    record: Mapping[str, Any],
) -> list[str]:
    formula = str(record["formula"])
    destination = pack / "licenses" / "homebrew" / formula
    destination.mkdir(parents=True, exist_ok=True)
    notice = destination / "FORMULA.txt"
    notice.write_text(
        "\n".join(
            [
                f"Formula: {formula}",
                f"Installed version: {record['version']}",
                f"License conclusion: {record['license_concluded']}",
                f"Formula record: {record['formula_url']}",
                f"Upstream: {record['upstream_url'] or 'not recorded'}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    copied = [notice]
    prefix = Path(record["prefix"])
    candidates = sorted(
        path
        for path in prefix.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and any(name in path.name.casefold() for name in _LICENSE_NAMES)
        and path.stat().st_size <= 1024 * 1024
    )
    used: set[str] = set()
    for source in candidates:
        name = source.name
        if name in used:
            continue
        used.add(name)
        target = destination / name
        shutil.copy2(source, target)
        copied.append(target)
    return [path.relative_to(pack.parent).as_posix() for path in copied]


def _stage_native_tools(
    pack: Path,
    baseline: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, str], list[dict[str, Any]]]:
    binaries = pack / "bin"
    libraries = pack / "lib"
    binaries.mkdir(parents=True)
    libraries.mkdir()
    tool_inputs = baseline.get("tools")
    if not isinstance(tool_inputs, dict):
        raise TypeError("baseline native-tool inputs are missing")
    staged: dict[str, Path] = {}
    source_by_destination: dict[Path, Path] = {}
    owner_by_destination: dict[Path, str] = {}
    for name, raw in tool_inputs.items():
        if not isinstance(raw, dict):
            raise TypeError(f"baseline tool input is invalid: {name}")
        formula = str(raw["formula"])
        record = _homebrew_formula_record(formula)
        if record["version"] != raw["version"]:
            raise RuntimeError(
                f"baseline tool version changed: {name}; "
                f"expected {raw['version']}, got {record['version']}"
            )
        source = Path(record["prefix"]) / "bin" / name
        actual_hash = sha256_file(source) if source.is_file() else "missing"
        if actual_hash != raw["input_sha256"]:
            raise RuntimeError(
                f"baseline tool input identity changed: {name}; "
                f"expected {raw['input_sha256']}, got {actual_hash}"
            )
        destination = binaries / name
        shutil.copy2(source.resolve(), destination)
        destination.chmod(destination.stat().st_mode | stat.S_IWUSR | stat.S_IXUSR)
        staged[name] = destination
        source_by_destination[destination] = source.resolve()
        owner_by_destination[destination] = formula

    copied: dict[str, Path] = {}
    replacements: dict[Path, list[tuple[str, Path]]] = {}
    queue = deque(staged.values())
    visited: set[Path] = set()
    while queue:
        destination = queue.popleft()
        if destination in visited:
            continue
        visited.add(destination)
        source = source_by_destination[destination]
        install_id = _otool_id(source)
        changes: list[tuple[str, Path]] = []
        for load_path in _otool_dependencies(source):
            if load_path == install_id or load_path.startswith(SYSTEM_LOAD_PREFIXES):
                continue
            dependency_source = _resolve_load_dependency(load_path, source)
            dependency = _copy_native_dependency(
                dependency_source,
                libraries,
                copied,
            )
            changes.append((load_path, dependency))
            if dependency not in source_by_destination:
                source_by_destination[dependency] = dependency_source
                owner = _homebrew_formula(dependency_source)
                if owner is None:
                    raise RuntimeError(
                        f"native dependency is not owned by Homebrew: {dependency_source}"
                    )
                owner_by_destination[dependency] = owner
                queue.append(dependency)
        replacements[destination] = changes

    for destination, changes in replacements.items():
        in_library = destination.parent == libraries
        for original, dependency in changes:
            relocated = (
                f"@loader_path/{dependency.name}"
                if in_library
                else f"@loader_path/../lib/{dependency.name}"
            )
            _run(
                ["install_name_tool", "-change", original, relocated, destination],
                capture_output=True,
            )
        if in_library:
            _run(
                [
                    "install_name_tool",
                    "-id",
                    f"@loader_path/{destination.name}",
                    destination,
                ],
                capture_output=True,
            )
    for destination in replacements:
        _neutralize_native_build_prefix(destination)
        _run(
            ["codesign", "--force", "--sign", "-", destination],
            capture_output=True,
        )

    formula_records = {
        formula: _homebrew_formula_record(formula)
        for formula in sorted(set(owner_by_destination.values()))
    }
    components = []
    file_owners: dict[str, str] = {}
    for formula, record in formula_records.items():
        component_id = f"homebrew-{formula}"
        paths = sorted(
            destination.relative_to(pack.parent).as_posix()
            for destination, owner in owner_by_destination.items()
            if owner == formula
        )
        license_files = _copy_formula_license(pack, record)
        paths.extend(license_files)
        for path in paths:
            file_owners[path] = component_id
        components.append(
            {
                "component_id": component_id,
                "name": formula,
                "version": record["version"],
                "license_concluded": record["license_concluded"],
                "source_url": record["formula_url"],
                "license_files": license_files,
                "bundled_paths": paths,
            }
        )
    tools = [
        {
            "tool_id": name,
            "version": str(raw["version"]),
            "executable": f"bin/{name}",
            "sha256": sha256_file(staged[name]),
            "license_concluded": str(raw["license_concluded"]),
            "component_id": f"homebrew-{raw['formula']}",
        }
        for name, raw in sorted(tool_inputs.items())
    ]
    native = [
        {
            "path": destination.relative_to(pack).as_posix(),
            "sha256": sha256_file(destination),
            "component_id": f"homebrew-{owner_by_destination[destination]}",
            "architectures": ["arm64"],
        }
        for destination in sorted(replacements)
        if destination.parent == libraries
    ]
    return components, file_owners, [*tools, *native]


def _stage_pypdfium2_licenses(
    repository: Path,
    runtime_root: Path,
    baseline: Mapping[str, Any],
) -> list[str]:
    records = baseline.get("source_archives")
    if not isinstance(records, list):
        raise TypeError("baseline source-archive records are missing")
    record = next(
        (
            item
            for item in records
            if isinstance(item, dict) and item.get("component_id") == "python-pypdfium2"
        ),
        None,
    )
    if record is None:
        raise RuntimeError("pypdfium2 license source is not declared")
    archive = acquire_declared_archive(record, cache_root(repository))
    destination = runtime_root / "baseline-pack" / "licenses" / "python" / "pypdfium2"
    destination.mkdir(parents=True)
    copied = []
    with tarfile.open(archive, "r:gz") as source:
        for member in source.getmembers():
            parts = Path(member.name).parts
            if (
                not member.isfile()
                or len(parts) < 3
                or parts[1] not in {"LICENSES", "BUILD_LICENSES"}
            ):
                continue
            relative = Path(*parts[1:])
            output = destination / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            stream = source.extractfile(member)
            if stream is None:
                raise RuntimeError("pypdfium2 license archive member is unreadable")
            with stream, output.open("wb") as target:
                shutil.copyfileobj(stream, target)
            copied.append(output.relative_to(runtime_root).as_posix())
    if not copied:
        raise RuntimeError("pypdfium2 license archive contained no license material")
    return sorted(copied)


def _stage_baseline_pack(
    repository: Path,
    runtime_root: Path,
    inputs: Mapping[str, Any],
    python_components: list[str],
) -> dict[str, Any]:
    baseline = inputs["baseline_pack"]
    pack = runtime_root / "baseline-pack"
    pack.mkdir()
    components, file_owners, native_items = _stage_native_tools(pack, baseline)
    pypdfium2_licenses = _stage_pypdfium2_licenses(
        repository,
        runtime_root,
        baseline,
    )
    for path in pypdfium2_licenses:
        file_owners[path] = "python-pypdfium2"
    tool_count = len(baseline["tools"])
    tools = native_items[:tool_count]
    native = native_items[tool_count:]

    wrapper = pack / "bin" / "ocrmypdf"
    wrapper.write_text(
        "#!/bin/sh\n"
        'pack_bin=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
        'exec "$pack_bin/../../python/bin/python3" -I -B -m ocrmypdf "$@"\n',
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    tools.append(
        {
            "tool_id": "ocrmypdf",
            "version": str(baseline["python_components"]["ocrmypdf"]),
            "executable": "bin/ocrmypdf",
            "sha256": sha256_file(wrapper),
            "license_concluded": "MPL-2.0",
            "component_id": "python-ocrmypdf",
        }
    )
    wrapper_relative = wrapper.relative_to(runtime_root).as_posix()
    file_owners[wrapper_relative] = "python-ocrmypdf"

    tessdata = pack / "tessdata"
    tessdata.mkdir()
    language_data = []
    language_prefixes = {
        "eng": Path(
            _run(["brew", "--prefix", "tesseract"], capture_output=True).stdout.strip()
        ),
        "osd": Path(
            _run(["brew", "--prefix", "tesseract"], capture_output=True).stdout.strip()
        ),
        "deu": Path(
            _run(
                ["brew", "--prefix", "tesseract-lang"], capture_output=True
            ).stdout.strip()
        ),
    }
    for language, expected in sorted(baseline["language_data"].items()):
        source = (
            language_prefixes[language]
            / "share"
            / "tessdata"
            / f"{language}.traineddata"
        )
        if not source.is_file() or sha256_file(source) != expected:
            raise RuntimeError(f"Tesseract language input changed: {language}")
        destination = tessdata / source.name
        shutil.copy2(source.resolve(), destination)
        relative = destination.relative_to(runtime_root).as_posix()
        file_owners[relative] = "tesseract-language-data"
        language_data.append(
            {
                "language": language,
                "path": f"tessdata/{source.name}",
                "sha256": sha256_file(destination),
                "license_concluded": "Apache-2.0",
            }
        )
    language_paths = [f"baseline-pack/{item['path']}" for item in language_data]
    tesseract_component = next(
        item for item in components if item["component_id"] == "homebrew-tesseract"
    )
    components.append(
        {
            "component_id": "tesseract-language-data",
            "name": "Tesseract language data",
            "version": "4.1.0/5.5.3",
            "license_concluded": "Apache-2.0",
            "source_url": ("https://github.com/tesseract-ocr/tessdata/tree/4.1.0"),
            "license_files": list(tesseract_component["license_files"]),
            "bundled_paths": language_paths,
        }
    )

    tesseract_prefix = language_prefixes["eng"]
    support_files = []
    support_paths = []
    for relative, expected in sorted(baseline["support_data"].items()):
        source = tesseract_prefix / "share" / "tessdata" / relative
        if not source.is_file() or sha256_file(source) != expected:
            raise RuntimeError(f"Tesseract support input changed: {relative}")
        destination = tessdata / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source.resolve(), destination)
        runtime_relative = destination.relative_to(runtime_root).as_posix()
        file_owners[runtime_relative] = "homebrew-tesseract"
        support_paths.append(runtime_relative)
        support_files.append(
            {
                "path": destination.relative_to(pack).as_posix(),
                "sha256": sha256_file(destination),
                "component_id": "homebrew-tesseract",
            }
        )
    tesseract_component["bundled_paths"] = sorted(
        [*tesseract_component["bundled_paths"], *support_paths]
    )

    fonts = pack / "etc" / "fonts"
    fonts.mkdir(parents=True)
    font_config = fonts / "fonts.conf"
    font_config.write_text(
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n'
        "<fontconfig>\n"
        "  <dir>/System/Library/Fonts</dir>\n"
        "  <dir>/Library/Fonts</dir>\n"
        '  <cachedir prefix="xdg">fontconfig</cachedir>\n'
        "</fontconfig>\n",
        encoding="utf-8",
    )
    metadata_paths = [font_config.relative_to(runtime_root).as_posix()]
    file_owners[metadata_paths[0]] = "baseline-pack-metadata"

    pack_manifest = {
        "schema_version": "doc-evidence.extractor-pack-manifest.v1",
        "pack_id": baseline["pack_id"],
        "version": baseline["version"],
        "platform": "macos",
        "architecture": "arm64",
        "tools": tools,
        "language_data": language_data,
        "support_files": support_files,
        "python_components": python_components,
        "native_libraries": native,
    }
    pack_manifest_path = pack / "pack-manifest.json"
    _write_json(pack_manifest_path, pack_manifest)
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
    manifest_relative = pack_manifest_path.relative_to(runtime_root).as_posix()
    metadata_paths.append(manifest_relative)
    file_owners[manifest_relative] = "baseline-pack-metadata"
    components.append(
        {
            "component_id": "baseline-pack-metadata",
            "name": "Doc Evidence baseline extractor pack metadata",
            "version": str(baseline["version"]),
            "license_concluded": "Apache-2.0",
            "source_url": "https://github.com/kzahel/doc-evidence",
            "license_files": [
                (
                    "python/lib/python3.12/site-packages/"
                    f"doc_evidence-{__version__}.dist-info/licenses/LICENSE"
                )
            ],
            "bundled_paths": metadata_paths,
        }
    )
    return {
        "identity": {
            "pack_id": baseline["pack_id"],
            "version": baseline["version"],
            "manifest_sha256": sha256_file(pack_manifest_path),
        },
        "components": components,
        "file_owners": file_owners,
        "package_license_files": {
            "pypdfium2": pypdfium2_licenses,
        },
    }


_DISTRIBUTION_SCRIPT = r"""
import importlib.metadata as metadata
import json
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
        lowered_parts = [part.lower() for part in Path(item).parts]
        if any(
            name in part
            for part in lowered_parts
            for name in ("license", "copying", "notice")
        ):
            licenses.append(item)
    classifiers = value.get_all("Classifier") or []
    project_urls = value.get_all("Project-URL") or []
    items.append({
        "name": value.get("Name", distribution.name),
        "version": distribution.version,
        "license": value.get("License"),
        "license_expression": value.get("License-Expression"),
        "license_classifiers": [
            item for item in classifiers if item.startswith("License ::")
        ],
        "project_urls": project_urls,
        "files": sorted(files),
        "license_files": sorted(licenses),
    })
print(json.dumps(sorted(items, key=lambda item: item["name"].lower())))
"""


def _distribution_inventory(python_root: Path) -> list[dict[str, Any]]:
    script = "import sys\n" + _DISTRIBUTION_SCRIPT
    result = _run(
        [python_root / "bin" / "python3", "-I", "-B", "-c", script],
        capture_output=True,
    )
    return json.loads(result.stdout)


def _license_conclusion(distribution: Mapping[str, Any]) -> str:
    expression = distribution.get("license_expression")
    if isinstance(expression, str) and expression.strip() and expression != "UNKNOWN":
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
    overrides = baseline.get("python_license_conclusions")
    if not isinstance(overrides, Mapping):
        raise TypeError("baseline Python license conclusions are invalid")
    normalized = str(distribution["name"]).lower().replace("_", "-")
    override = overrides.get(normalized)
    if override is None:
        return _license_conclusion(distribution)
    if not isinstance(override, Mapping):
        raise TypeError(f"Python license conclusion is invalid: {normalized}")
    version = override.get("version")
    conclusion = override.get("license_concluded")
    if version != distribution.get("version") or not isinstance(conclusion, str):
        raise RuntimeError(f"Python license conclusion drifted: {normalized}")
    return conclusion


def _component_id(name: str) -> str:
    normalized = "".join(
        character if character.isalnum() else "-" for character in name.lower()
    )
    return "python-" + "-".join(filter(None, normalized.split("-")))


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _write_manifests(
    root: Path,
    runtime_root: Path,
    archive: Path,
    inputs: Mapping[str, Any],
    baseline_metadata: Mapping[str, Any],
) -> None:
    python_root = runtime_root / "python"
    packages = _distribution_inventory(python_root)
    if not packages:
        raise RuntimeError("staged Python package inventory is empty")
    forbidden = {
        str(name).lower().replace("_", "-")
        for name in inputs["forbidden_python_distributions"]
    } | _excluded_baseline_distributions(inputs)
    package_license_files = baseline_metadata.get("package_license_files")
    if not isinstance(package_license_files, dict):
        raise TypeError("baseline Python license inventory is invalid")
    baseline = inputs.get("baseline_pack")
    if not isinstance(baseline, Mapping):
        raise TypeError("baseline extractor-pack inputs are missing")
    for package in packages:
        normalized = str(package["name"]).lower().replace("_", "-")
        if normalized in forbidden:
            raise RuntimeError(
                f"development distribution entered desktop runtime: {package['name']}"
            )
        external_licenses = package_license_files.get(normalized, [])
        if not isinstance(external_licenses, list):
            raise TypeError(f"Python license inventory is invalid: {package['name']}")
        if not package["files"] or not (package["license_files"] or external_licenses):
            raise RuntimeError(
                f"Python distribution is not fully licensed: {package['name']}"
            )

    notices = [
        "Doc Evidence third-party notices (generated from staged bytes)",
        "",
        "The complete license texts remain beside their installed components.",
        "",
        f"CPython {inputs['python']['version']} — {inputs['python']['license_concluded']}",
    ]
    components: list[dict[str, Any]] = [
        {
            "component_id": "cpython",
            "name": "CPython",
            "version": inputs["python"]["version"],
            "license_concluded": inputs["python"]["license_concluded"],
            "source_url": inputs["python"]["url"],
            "source_sha256": inputs["python"]["sha256"],
            "license_files": ["python/lib/python3.12/LICENSE.txt"],
            "bundled_paths": ["python"],
        }
    ]
    baseline_components = baseline_metadata.get("components")
    baseline_file_owners = baseline_metadata.get("file_owners")
    if not isinstance(baseline_components, list) or not isinstance(
        baseline_file_owners, dict
    ):
        raise TypeError("baseline component inventory is invalid")
    components.extend(baseline_components)
    file_owners: dict[str, str] = {
        str(path): str(owner) for path, owner in baseline_file_owners.items()
    }
    notices.extend(
        f"{component['name']} {component['version']} — {component['license_concluded']}"
        for component in baseline_components
    )
    for package in packages:
        component_id = _component_id(str(package["name"]))
        normalized = str(package["name"]).lower().replace("_", "-")
        external_licenses = [
            str(path) for path in package_license_files.get(normalized, [])
        ]
        conclusion = _python_license_conclusion(package, baseline)
        notices.append(f"{package['name']} {package['version']} — {conclusion}")
        for path in package["files"]:
            file_owners[f"python/{path}"] = component_id
        components.append(
            {
                "component_id": component_id,
                "name": package["name"],
                "version": package["version"],
                "license_concluded": conclusion,
                "source_url": (
                    f"https://pypi.org/project/{package['name']}/{package['version']}/"
                ),
                "license_files": [f"python/{path}" for path in package["license_files"]]
                + external_licenses,
                "bundled_paths": [f"python/{path}" for path in package["files"]]
                + external_licenses,
            }
        )
    notice_path = runtime_root / "THIRD_PARTY_NOTICES.txt"
    notice_path.write_text("\n".join(notices) + "\n", encoding="utf-8")
    runtime_manifest = {
        "schema_version": RUNTIME_MANIFEST_SCHEMA,
        "platform": "macos",
        "architecture": "arm64",
        "python": {
            **inputs["python"],
            "archive_bytes": archive.stat().st_size,
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
    components.append(
        {
            "component_id": "desktop-runtime-metadata",
            "name": "Doc Evidence desktop runtime metadata",
            "version": __version__,
            "license_concluded": "Apache-2.0",
            "source_url": "https://github.com/kzahel/doc-evidence",
            "license_files": [
                next(
                    path
                    for path in file_owners
                    if path.endswith(
                        f"doc_evidence-{__version__}.dist-info/licenses/LICENSE"
                    )
                )
            ],
            "bundled_paths": ["runtime-manifest.json", "THIRD_PARTY_NOTICES.txt"],
        }
    )
    file_owners["runtime-manifest.json"] = "desktop-runtime-metadata"
    file_owners["THIRD_PARTY_NOTICES.txt"] = "desktop-runtime-metadata"

    frontend = root / "web" / "dist"
    if not frontend.is_dir():
        raise RuntimeError("web/dist must be built before staging the desktop runtime")
    files = []
    for path in sorted(runtime_root.rglob("*")):
        if (
            not path.is_file()
            or path.is_symlink()
            or path.name == "bundle-manifest.json"
        ):
            continue
        relative = path.relative_to(runtime_root).as_posix()
        files.append(
            {
                "path": relative,
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "component_id": file_owners.get(relative, "cpython"),
            }
        )
    bundle_manifest = {
        "schema_version": BUNDLE_MANIFEST_SCHEMA,
        "product": PRODUCT_NAME,
        "version": __version__,
        "identifier": PRODUCT_IDENTIFIER,
        "platform": "macos",
        "architecture": "arm64",
        "python_version": inputs["python"]["version"],
        "frontend_sha256": sha256_tree(frontend),
        "runtime_manifest_sha256": sha256_file(runtime_manifest_path),
        "extractor_packs": [baseline_metadata["identity"]],
        "components": components,
        "files": files,
    }
    _write_json(runtime_root / "bundle-manifest.json", bundle_manifest)


def stage_runtime(
    *,
    root: Path | None = None,
    cache: Path | None = None,
    destination: Path | None = None,
    replace: bool = False,
) -> Path:
    _require_host()
    repository = (root or repository_root()).resolve()
    target = (destination or stage_root(repository)).resolve()
    previous = target.with_name(f"{target.name}.previous")
    if previous.exists():
        raise RuntimeError(
            f"stale desktop runtime rollback directory exists: {previous}"
        )
    if target.exists():
        if not replace:
            raise RuntimeError(
                f"desktop runtime staging target already exists: {target}"
            )
        audit_runtime(
            target,
            repository=repository,
            smoke=False,
            require_baseline=False,
            allow_excluded_for_replacement=True,
            require_current_frontend=False,
        )
        os.replace(target, previous)
    inputs = _load_inputs(repository)
    archive = acquire_python_archive(
        inputs, (cache or cache_root(repository)).resolve()
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(
            prefix="doc-evidence-runtime-", dir=target.parent
        ) as raw:
            temporary = Path(raw)
            python_root = _extract_python(archive, temporary)
            _stage_dependencies(repository, python_root)
            python_components = _stage_baseline_python(repository, python_root, inputs)
            _thin_python_native(python_root)
            _prune_runtime(python_root)
            staged = temporary / "desktop-runtime"
            staged.mkdir()
            os.replace(python_root, staged / "python")
            baseline_metadata = _stage_baseline_pack(
                repository,
                staged,
                inputs,
                python_components,
            )
            _write_manifests(
                repository,
                staged,
                archive,
                inputs,
                baseline_metadata,
            )
            audit_runtime(staged, repository=repository, smoke=True)
            os.replace(staged, target)
    except BaseException:
        if previous.exists() and not target.exists():
            os.replace(previous, target)
        raise
    if previous.exists():
        shutil.rmtree(previous)
    return target


def _is_macho(path: Path) -> bool:
    if not path.is_file() or path.is_symlink():
        return False
    result = subprocess.run(
        ["file", "-b", path],
        check=False,
        text=True,
        capture_output=True,
    )
    return "Mach-O" in result.stdout


def _otool_dependencies(path: Path) -> list[str]:
    result = _run(["otool", "-L", path], capture_output=True)
    return [
        line.strip().split(" (", 1)[0]
        for line in result.stdout.splitlines()[1:]
        if line.strip()
    ]


def _otool_id(path: Path) -> str | None:
    result = _run(["otool", "-D", path], capture_output=True)
    values = [line.strip() for line in result.stdout.splitlines()[1:] if line.strip()]
    return values[0] if values else None


def _audit_native(root: Path) -> list[dict[str, Any]]:
    native = []
    for path in root.rglob("*"):
        if not _is_macho(path):
            continue
        description = _run(["file", "-b", path], capture_output=True).stdout.strip()
        if "arm64" not in description or "x86_64" in description:
            raise RuntimeError(f"native runtime file is not arm64-only: {path}")
        dependencies = _otool_dependencies(path)
        install_id = _otool_id(path)
        for dependency in dependencies:
            if dependency == install_id:
                continue
            if dependency.startswith(("@loader_path/", "@rpath/", "@executable_path/")):
                continue
            if dependency.startswith(SYSTEM_LOAD_PREFIXES):
                continue
            candidate = Path(dependency)
            if candidate == root or root in candidate.parents:
                continue
            raise RuntimeError(
                f"native dependency escapes desktop runtime: {dependency}"
            )
        native.append(
            {
                "path": path.relative_to(root).as_posix(),
                "description": description,
                "dependencies": dependencies,
            }
        )
    return native


def _audit_symlinks(root: Path) -> list[str]:
    resolved = root.resolve()
    links = []
    for path in root.rglob("*"):
        if not path.is_symlink():
            continue
        target = path.resolve()
        if target != resolved and resolved not in target.parents:
            raise RuntimeError(f"desktop runtime symlink escapes its root: {path}")
        links.append(path.relative_to(root).as_posix())
    return links


def _validate_bundle_manifest(
    runtime_root: Path,
    repository: Path,
    *,
    require_baseline: bool = True,
    require_current_frontend: bool = True,
) -> dict[str, Any]:
    manifest = json.loads(
        (runtime_root / "bundle-manifest.json").read_text(encoding="utf-8")
    )
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
    if require_current_frontend and manifest["frontend_sha256"] != sha256_tree(
        repository / "web" / "dist"
    ):
        raise RuntimeError("staged frontend identity changed")
    runtime_manifest = runtime_root / "runtime-manifest.json"
    if manifest["runtime_manifest_sha256"] != sha256_file(runtime_manifest):
        raise RuntimeError("staged runtime manifest identity changed")
    if len(manifest["extractor_packs"]) > 1 or (
        require_baseline and len(manifest["extractor_packs"]) != 1
    ):
        raise RuntimeError("staged baseline extractor-pack identity is missing")
    if manifest["extractor_packs"]:
        pack_identity = load_baseline_pack(runtime_root / "baseline-pack")
        if manifest["extractor_packs"][0] != pack_identity.model_dump(mode="json"):
            raise RuntimeError("staged baseline extractor-pack identity changed")
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
        raise RuntimeError("staged desktop runtime file inventory changed")
    return manifest


def _baseline_environment(runtime_root: Path, writable_root: Path) -> dict[str, str]:
    pack = runtime_root / "baseline-pack"
    cache = writable_root / "cache"
    temporary = writable_root / "tmp"
    cache.mkdir(parents=True, exist_ok=True)
    temporary.mkdir(parents=True, exist_ok=True)
    return {
        BASELINE_PACK_ENV: str(pack),
        "PATH": ":".join(
            [
                str(pack / "bin"),
                str(runtime_root / "python" / "bin"),
                "/usr/bin",
                "/bin",
            ]
        ),
        "TESSDATA_PREFIX": str(pack / "tessdata"),
        "FONTCONFIG_FILE": str(pack / "etc" / "fonts" / "fonts.conf"),
        "FONTCONFIG_PATH": str(pack / "etc" / "fonts"),
        "XDG_CACHE_HOME": str(cache),
        "TMPDIR": str(temporary),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
        "LANG": "en_US.UTF-8",
    }


def smoke_baseline_pack(runtime_root: Path) -> dict[str, Any]:
    pack = runtime_root / "baseline-pack"
    identity = load_baseline_pack(pack)
    with tempfile.TemporaryDirectory(prefix="doc-evidence-baseline-smoke-") as raw:
        working = Path(raw)
        environment = _baseline_environment(runtime_root, working)
        versions = {}
        commands = {
            "pdfinfo": [pack / "bin" / "pdfinfo", "-v"],
            "pdftotext": [pack / "bin" / "pdftotext", "-v"],
            "pdftoppm": [pack / "bin" / "pdftoppm", "-v"],
            "tesseract": [pack / "bin" / "tesseract", "--version"],
            "ocrmypdf": [pack / "bin" / "ocrmypdf", "--version"],
        }
        for name, command in commands.items():
            result = _run(
                command,
                cwd=working,
                environment=environment,
                capture_output=True,
            )
            versions[name] = (result.stdout + result.stderr).splitlines()[0]
        expected_versions = {
            "pdfinfo": "26.08.0",
            "pdftotext": "26.08.0",
            "pdftoppm": "26.08.0",
            "tesseract": "5.5.3",
            "ocrmypdf": "17.8.1",
        }
        for name, version in expected_versions.items():
            if version not in versions[name]:
                raise RuntimeError(f"baseline tool version is incompatible: {name}")
        language_result = _run(
            [pack / "bin" / "tesseract", "--list-langs"],
            cwd=working,
            environment=environment,
            capture_output=True,
        )
        languages = {
            line.strip()
            for line in (language_result.stdout + language_result.stderr).splitlines()
            if line.strip() in {"eng", "deu", "osd"}
        }
        if languages != {"eng", "deu", "osd"}:
            raise RuntimeError("baseline Tesseract languages are unavailable")
        if shutil.which("gs", path=environment["PATH"]) is not None:
            raise RuntimeError("Ghostscript entered the baseline runtime")

        source = working / "synthetic-scan.pdf"
        create_fixture = f"""
from PIL import Image, ImageDraw, ImageFont
image = Image.new("RGB", (1800, 1100), "white")
draw = ImageDraw.Draw(image)
font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 72)
lines = [
    "DOC EVIDENCE 12345",
    "LOCAL DOCUMENT REVIEW",
    "SOURCE PROVENANCE RECORD",
    "EXTRACTED TEXT VALIDATION",
    "HUMAN CONFIRMATION REQUIRED",
]
for index, line in enumerate(lines):
    draw.text((80, 100 + index * 180), line, fill="black", font=font)
image.save({str(source)!r}, "PDF", resolution=200.0)
"""
        _run(
            [
                runtime_root / "python" / "bin" / "python3",
                "-I",
                "-B",
                "-c",
                create_fixture,
            ],
            cwd=working,
            environment=environment,
            capture_output=True,
        )
        output = working / "ocr.pdf"
        sidecar = working / "ocr.txt"
        try:
            ocr = _run(
                [
                    pack / "bin" / "ocrmypdf",
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
            )
        except subprocess.CalledProcessError as error:
            detail = ((error.stdout or "") + (error.stderr or ""))[-4000:]
            raise RuntimeError(
                f"Ghostscript-free baseline OCR failed: {detail}"
            ) from error
        if not output.is_file() or not sidecar.is_file():
            raise RuntimeError("Ghostscript-free baseline OCR produced no output")
        extracted = _run(
            [pack / "bin" / "pdftotext", output, "-"],
            cwd=working,
            environment=environment,
            capture_output=True,
        ).stdout
        if "12345" not in extracted:
            raise RuntimeError("baseline OCR synthetic text was not recoverable")
        combined_log = ocr.stdout + ocr.stderr
        if "/opt/homebrew" in combined_log or str(repository_root()) in combined_log:
            raise RuntimeError("baseline OCR leaked a build-host path")
        return {
            "status": "passed",
            "identity": identity.model_dump(mode="json"),
            "versions": versions,
            "languages": sorted(languages),
            "ghostscript_available": False,
            "synthetic_ocr_text": "DOC EVIDENCE 12345",
        }


def smoke_sidecar(runtime_root: Path) -> dict[str, Any]:
    runtime_token = secrets.token_hex(32)
    control_token = secrets.token_hex(32)
    with tempfile.TemporaryDirectory(prefix="doc-evidence-desktop-smoke-") as raw:
        working = Path(raw)
        environment = {
            **_baseline_environment(runtime_root, working),
            "DOC_EVIDENCE_DESKTOP_RUNTIME_TOKEN": runtime_token,
            "DOC_EVIDENCE_DESKTOP_HOST_CONTROL_TOKEN": control_token,
            "DOC_EVIDENCE_DESKTOP_APP_HOME": str(working / "app-home"),
            DESKTOP_PLATFORM_ENV: "macos",
            DESKTOP_ARCHITECTURE_ENV: "arm64",
        }
        process = subprocess.Popen(
            [
                str(runtime_root / "python" / "bin" / "python3"),
                "-I",
                "-B",
                "-m",
                "doc_evidence.desktop_sidecar",
                "--expected-protocol",
                DESKTOP_PROTOCOL_VERSION,
                "--desktop-origin",
                MACOS_DESKTOP_ORIGIN,
            ],
            cwd=working,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if process.stdin is None or process.stdout is None or process.stderr is None:
            process.kill()
            raise RuntimeError("desktop smoke pipes are unavailable")
        try:
            readable, _, _ = select.select([process.stdout], [], [], 30)
            if not readable:
                raise RuntimeError("staged desktop sidecar did not become ready")
            ready_line = process.stdout.readline(MAX_READY_BYTES + 1)
            if len(ready_line.encode()) > MAX_READY_BYTES:
                raise RuntimeError("staged desktop ready record exceeded its bound")
            ready = json.loads(ready_line)
            if (
                ready.get("protocol_version") != DESKTOP_PROTOCOL_VERSION
                or ready.get("application_version") != __version__
                or ready.get("host") != "127.0.0.1"
                or ready.get("baseline_pack")
                != load_baseline_pack(runtime_root / "baseline-pack").model_dump(
                    mode="json"
                )
            ):
                raise RuntimeError("staged desktop ready record is incompatible")
            url = f"http://127.0.0.1:{ready['port']}/api/v1/desktop/handshake"
            unauthenticated = urllib.request.Request(
                url, headers={"Origin": MACOS_DESKTOP_ORIGIN}
            )
            try:
                urllib.request.urlopen(unauthenticated, timeout=3)
            except urllib.error.HTTPError as error:
                if error.code != 401:
                    raise RuntimeError(
                        "desktop smoke returned unexpected auth status"
                    ) from error
            else:
                raise RuntimeError("desktop smoke accepted an unauthenticated request")
            authenticated = urllib.request.Request(
                url,
                headers={
                    "Authorization": f"Bearer {runtime_token}",
                    "Origin": MACOS_DESKTOP_ORIGIN,
                },
            )
            with urllib.request.urlopen(authenticated, timeout=3) as response:
                handshake = json.load(response)
            if handshake.get("protocol_version") != DESKTOP_PROTOCOL_VERSION:
                raise RuntimeError("desktop smoke handshake is incompatible")
            process.stdin.close()
            if process.wait(timeout=20) != 0:
                raise RuntimeError("staged desktop sidecar did not stop cleanly")
            stderr = process.stderr.read()
            if (
                runtime_token in ready_line
                or runtime_token in stderr
                or control_token in stderr
            ):
                raise RuntimeError("desktop smoke leaked a launch credential")
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


def audit_runtime(
    runtime_root: Path,
    *,
    repository: Path | None = None,
    smoke: bool = False,
    require_baseline: bool = True,
    allow_excluded_for_replacement: bool = False,
    require_current_frontend: bool = True,
) -> dict[str, Any]:
    root = runtime_root.resolve()
    repo = (repository or repository_root()).resolve()
    if not root.is_dir():
        raise RuntimeError(f"desktop runtime does not exist: {root}")
    manifest = _validate_bundle_manifest(
        root,
        repo,
        require_baseline=require_baseline,
        require_current_frontend=require_current_frontend,
    )
    packages = _distribution_inventory(root / "python")
    inputs = _load_inputs(repo)
    forbidden = {
        str(name).lower().replace("_", "-")
        for name in inputs["forbidden_python_distributions"]
    }
    excluded = _excluded_baseline_distributions(inputs)
    included = {str(package["name"]).lower().replace("_", "-") for package in packages}
    unexpected = sorted(forbidden & included)
    if unexpected:
        raise RuntimeError(
            f"development packages entered desktop runtime: {unexpected}"
        )
    unexpected_excluded = sorted(excluded & included)
    if unexpected_excluded and not allow_excluded_for_replacement:
        raise RuntimeError(
            f"excluded packages entered desktop runtime: {unexpected_excluded}"
        )
    result = {
        "schema_version": "doc-evidence.desktop-runtime-audit.v1",
        "status": "passed",
        "root": str(root),
        "tree_sha256": sha256_tree(root),
        "installed_bytes": sum(
            path.lstat().st_size
            for path in root.rglob("*")
            if path.is_file() or path.is_symlink()
        ),
        "file_count": sum(1 for path in root.rglob("*") if path.is_file()),
        "package_count": len(packages),
        "native_files": _audit_native(root),
        "symlinks": _audit_symlinks(root),
        "manifest": {
            "version": manifest["version"],
            "python_version": manifest["python_version"],
            "component_count": len(manifest["components"]),
        },
    }
    if smoke:
        result["baseline_smoke"] = smoke_baseline_pack(root)
        result["sidecar_smoke"] = smoke_sidecar(root)
    return result


def sign_runtime_for_distribution(
    runtime_root: Path,
    *,
    identity: str,
    repository: Path | None = None,
) -> dict[str, Any]:
    """Developer-ID sign every nested Mach-O and refresh exact manifests."""

    root = runtime_root.resolve()
    repo = (repository or repository_root()).resolve()
    if not identity.startswith("Developer ID Application: "):
        raise RuntimeError("macOS distribution signing identity is incompatible")
    audit_runtime(root, repository=repo, smoke=False)
    native_files = sorted(path for path in root.rglob("*") if _is_macho(path))
    if not native_files:
        raise RuntimeError("macOS desktop runtime has no native files to sign")
    for path in native_files:
        mode = path.stat().st_mode
        path.chmod(mode | stat.S_IWUSR)
        try:
            _run(
                [
                    "codesign",
                    "--force",
                    "--options",
                    "runtime",
                    "--timestamp",
                    "--sign",
                    identity,
                    path,
                ],
                capture_output=True,
                timeout_seconds=120,
            )
        finally:
            path.chmod(mode)
    manifests = refresh_signed_runtime_manifests(root)
    audit = audit_runtime(root, repository=repo, smoke=True)
    for path in native_files:
        _run(
            ["codesign", "--verify", "--strict", "--verbose=2", path],
            capture_output=True,
        )
        details = _run(
            ["codesign", "--display", "--verbose=4", path],
            capture_output=True,
        )
        output = f"{details.stdout}\n{details.stderr}"
        if "TeamIdentifier=VD7BYQ6ABM" not in output or "Signature=adhoc" in output:
            raise RuntimeError(f"nested native signature is incompatible: {path}")
    return {
        "schema_version": "doc-evidence.macos-runtime-signing.v1",
        "status": "passed",
        "identity": identity,
        "native_file_count": len(native_files),
        "manifests": manifests,
        "runtime": audit,
    }


def _files_containing(root: Path, values: Sequence[str]) -> dict[str, list[str]]:
    encoded = {value: value.encode() for value in values}
    hits = {value: [] for value in values}
    for path in root.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        try:
            content = path.read_bytes()
        except OSError:
            continue
        for value, needle in encoded.items():
            if needle in content:
                hits[value].append(path.relative_to(root).as_posix())
    return {value: paths for value, paths in hits.items() if paths}


def _application_build_host_hits(
    bundle: Path, repository: Path
) -> dict[str, list[str]]:
    hits = _files_containing(bundle, [str(repository), "/opt/homebrew"])
    home = str(Path.home())
    runtime_prefix = "Contents/Resources/desktop-runtime/"
    home_hits = [
        path
        for path in _files_containing(bundle, [home]).get(home, [])
        if not path.startswith(runtime_prefix)
    ]
    if home_hits:
        hits[home] = home_hits
    return hits


def audit_application(
    app: Path,
    *,
    repository: Path | None = None,
    smoke: bool = True,
    signed: bool = False,
) -> dict[str, Any]:
    bundle = app.resolve()
    repo = (repository or repository_root()).resolve()
    if bundle.suffix != ".app" or not bundle.is_dir():
        raise RuntimeError(f"desktop application does not exist: {bundle}")
    info_path = bundle / "Contents" / "Info.plist"
    with info_path.open("rb") as stream:
        info = plistlib.load(stream)
    expected_info = {
        "CFBundleDisplayName": PRODUCT_NAME,
        "CFBundleIdentifier": PRODUCT_IDENTIFIER,
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__,
        "CFBundleExecutable": "doc-evidence-desktop",
        "LSMinimumSystemVersion": "13.0",
    }
    if any(info.get(name) != value for name, value in expected_info.items()):
        raise RuntimeError("desktop application metadata is incompatible")
    executable = bundle / "Contents" / "MacOS" / str(info["CFBundleExecutable"])
    if not executable.is_file():
        raise RuntimeError("desktop application executable is missing")
    runtime = bundle / "Contents" / "Resources" / "desktop-runtime"
    runtime_audit = audit_runtime(runtime, repository=repo, smoke=smoke)
    forbidden_hits = _application_build_host_hits(bundle, repo)
    if forbidden_hits:
        raise RuntimeError(
            f"desktop application embeds build-host paths: {forbidden_hits}"
        )
    signature = subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", bundle],
        check=False,
        text=True,
        capture_output=True,
    )
    if signature.returncode != 0:
        raise RuntimeError(
            "local desktop proof has an invalid ad-hoc signature: "
            f"{signature.stderr.strip()}"
        )
    displayed = _run(
        ["codesign", "--display", "--verbose=4", bundle],
        capture_output=True,
    )
    signature_details = f"{displayed.stdout}\n{displayed.stderr}"
    required_signature_details = (
        (
            f"Identifier={PRODUCT_IDENTIFIER}",
            "Authority=Developer ID Application: Kyle Graehl (VD7BYQ6ABM)",
            "TeamIdentifier=VD7BYQ6ABM",
            "Sealed Resources version=2",
        )
        if signed
        else (
            f"Identifier={PRODUCT_IDENTIFIER}",
            "Signature=adhoc",
            "TeamIdentifier=not set",
            "Sealed Resources version=2",
        )
    )
    if any(value not in signature_details for value in required_signature_details):
        kind = "Developer ID" if signed else "ad-hoc"
        raise RuntimeError(f"desktop application is not an exact {kind} bundle seal")
    if signed:
        _run(
            ["spctl", "--assess", "--type", "execute", "--verbose=2", bundle],
            capture_output=True,
        )
        _run(["xcrun", "stapler", "validate", bundle], capture_output=True)
    return {
        "schema_version": "doc-evidence.desktop-app-audit.v1",
        "status": "passed",
        "app": str(bundle),
        "product": PRODUCT_NAME,
        "identifier": PRODUCT_IDENTIFIER,
        "version": __version__,
        "installed_bytes": sum(
            path.lstat().st_size
            for path in bundle.rglob("*")
            if path.is_file() or path.is_symlink()
        ),
        "file_count": sum(1 for path in bundle.rglob("*") if path.is_file()),
        "tree_sha256": sha256_tree(bundle),
        "native_files": _audit_native(bundle),
        "symlinks": _audit_symlinks(bundle),
        "build_host_path_hits": {},
        "signature": {
            "status": "developer-id-notarized" if signed else "ad-hoc-local-proof",
            "strict_verification_exit_code": signature.returncode,
        },
        "runtime": runtime_audit,
    }


def build_application(*, root: Path | None = None) -> Path:
    repository = (root or repository_root()).resolve()
    _run(["npm", "run", "build", "--prefix", "web"], cwd=repository)
    audit_runtime(stage_root(repository), repository=repository, smoke=True)
    environment = os.environ.copy()
    environment["RUSTFLAGS"] = " ".join(
        [
            f"--remap-path-prefix={repository}=/doc-evidence-source",
            f"--remap-path-prefix={Path.home()}=/build-host",
        ]
    )
    _run(
        [
            "npm",
            "run",
            "tauri",
            "--prefix",
            "desktop",
            "--",
            "build",
            "--bundles",
            "app",
            "--no-sign",
            "--ci",
        ],
        cwd=repository,
        environment=environment,
    )
    app = application_bundle_path(repository)
    if not app.is_dir():
        raise RuntimeError("Tauri did not produce the expected application bundle")
    _run(
        [
            "codesign",
            "--force",
            "--sign",
            "-",
            "--identifier",
            PRODUCT_IDENTIFIER,
            app,
        ],
        capture_output=True,
    )
    return app


def audit_dmg(
    dmg: Path,
    *,
    repository: Path | None = None,
    signed: bool = False,
) -> dict[str, Any]:
    _require_host()
    image = dmg.resolve()
    repo = (repository or repository_root()).resolve()
    if image.suffix != ".dmg" or not image.is_file():
        raise RuntimeError(f"desktop disk image does not exist: {image}")
    _run(
        ["hdiutil", "verify", image],
        capture_output=True,
        timeout_seconds=120,
    )
    with tempfile.TemporaryDirectory(prefix="doc-evidence-dmg-review-") as raw:
        mount = Path(raw) / "volume"
        mount.mkdir()
        attached = False
        detach_error: str | None = None
        try:
            _run(
                [
                    "hdiutil",
                    "attach",
                    image,
                    "-readonly",
                    "-nobrowse",
                    "-mountpoint",
                    mount,
                ],
                capture_output=True,
                timeout_seconds=120,
            )
            attached = True
            app = mount / f"{PRODUCT_NAME}.app"
            applications = mount / "Applications"
            if (
                not applications.is_symlink()
                or os.readlink(applications) != "/Applications"
            ):
                raise RuntimeError("desktop disk image lacks its Applications link")
            app_audit = audit_application(
                app,
                repository=repo,
                smoke=True,
                signed=signed,
            )
            app_audit["app"] = f"{PRODUCT_NAME}.app (mounted read-only)"
        finally:
            if attached:
                detached = subprocess.run(
                    ["hdiutil", "detach", str(mount)],
                    check=False,
                    text=True,
                    capture_output=True,
                    timeout=60,
                )
                if detached.returncode != 0:
                    forced = subprocess.run(
                        ["hdiutil", "detach", "-force", str(mount)],
                        check=False,
                        text=True,
                        capture_output=True,
                        timeout=60,
                    )
                    if forced.returncode != 0:
                        detach_error = (forced.stdout + forced.stderr)[-2000:]
        if detach_error is not None:
            raise RuntimeError(f"desktop disk image did not detach: {detach_error}")
    if signed:
        _run(["codesign", "--verify", "--verbose=2", image], capture_output=True)
        _run(["xcrun", "stapler", "validate", image], capture_output=True)
    return {
        "schema_version": "doc-evidence.desktop-dmg-audit.v1",
        "status": "passed",
        "dmg": str(image),
        "bytes": image.stat().st_size,
        "sha256": sha256_file(image),
        "volume_name": PRODUCT_NAME,
        "applications_link": "/Applications",
        "application": app_audit,
    }


def create_unsigned_dmg(
    app: Path,
    destination: Path,
    *,
    repository: Path | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    _require_host()
    bundle = app.resolve()
    repo = (repository or repository_root()).resolve()
    output = destination.resolve()
    if output.exists() and not replace:
        raise RuntimeError(f"desktop disk image already exists: {output}")
    audit_application(bundle, repository=repo, smoke=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(f".{output.stem}.partial.dmg")
    partial.unlink(missing_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix="doc-evidence-dmg-stage-") as raw:
            volume = Path(raw) / PRODUCT_NAME
            volume.mkdir()
            _run(
                ["ditto", bundle, volume / bundle.name],
                timeout_seconds=120,
            )
            (volume / "Applications").symlink_to("/Applications")
            _run(
                [
                    "hdiutil",
                    "create",
                    "-volname",
                    PRODUCT_NAME,
                    "-fs",
                    "HFS+",
                    "-format",
                    "UDZO",
                    "-imagekey",
                    "zlib-level=9",
                    "-srcfolder",
                    volume,
                    partial,
                ],
                capture_output=True,
                timeout_seconds=300,
            )
        os.replace(partial, output)
        return audit_dmg(output, repository=repo)
    finally:
        partial.unlink(missing_ok=True)


def _spdx_id(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9.-]+", "-", value).strip("-.")
    if not normalized:
        raise RuntimeError("SPDX component identifier is empty")
    return f"SPDXRef-{normalized}"


def _spdx_license(value: str) -> tuple[str, bool]:
    normalized = _SPDX_LICENSE_NORMALIZATION.get(value, value)
    unresolved = "," in normalized or "dependency licenses" in normalized.casefold()
    return ("NOASSERTION" if unresolved else normalized, unresolved)


def _copy_compliance_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _download_bounded(url: str, *, maximum_bytes: int = 4 * 1024 * 1024) -> bytes:
    headers = {"User-Agent": f"doc-evidence/{__version__} compliance-preflight"}
    if urllib.parse.urlparse(url).hostname == "api.github.com":
        token = os.environ.get("GH_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
            headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = urllib.request.Request(
        url,
        headers=headers,
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        content = response.read(maximum_bytes + 1)
    if len(content) > maximum_bytes:
        raise RuntimeError(f"compliance metadata exceeded its size bound: {url}")
    return content


def _resolve_homebrew_formula(
    *,
    name: str,
    version: str,
    prefix: Path,
    source_sha256: str,
    bottle_sha256: str,
    destination: Path,
    cache: Path,
) -> dict[str, str]:
    cache_key = f"{name}-{version}-{source_sha256[:12]}-{bottle_sha256[:12]}"
    cached_formula = cache / f"{cache_key}.rb"
    cached_record = cache / f"{cache_key}.json"
    if cached_formula.is_file() and cached_record.is_file():
        record = json.loads(cached_record.read_text(encoding="utf-8"))
        if (
            record.get("name") == name
            and record.get("version") == version
            and record.get("source_sha256") == source_sha256
            and record.get("bottle_sha256") == bottle_sha256
            and record.get("formula_sha256") == sha256_file(cached_formula)
        ):
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cached_formula, destination)
            return {
                "formula_revision": str(record["formula_revision"]),
                "formula_url": str(record["formula_url"]),
                "formula_path": destination.as_posix(),
                "formula_sha256": sha256_file(destination),
            }
    sbom = json.loads((prefix / "sbom.spdx.json").read_text(encoding="utf-8"))
    created_value = (sbom.get("creationInfo") or {}).get("created")
    if not isinstance(created_value, str):
        raise TypeError(f"Homebrew SBOM creation time is invalid: {name} {version}")
    try:
        created = datetime.fromisoformat(created_value)
    except ValueError as error:
        raise RuntimeError(
            f"Homebrew SBOM creation time is invalid: {name} {version}"
        ) from error
    if created.tzinfo is None:
        raise RuntimeError(f"Homebrew SBOM creation time is invalid: {name} {version}")
    info = json.loads(
        _run(
            ["brew", "info", "--json=v2", name],
            capture_output=True,
        ).stdout
    )
    formulae = info.get("formulae")
    if not isinstance(formulae, list) or len(formulae) != 1:
        raise RuntimeError(f"Homebrew formula metadata is invalid: {name}")
    formula_path = formulae[0].get("ruby_source_path")
    if not isinstance(formula_path, str) or not formula_path.endswith(".rb"):
        raise RuntimeError(f"Homebrew formula path is invalid: {name}")
    until = created.astimezone(UTC) + timedelta(days=1)
    query = urllib.parse.urlencode(
        {
            "path": formula_path,
            "until": until.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "per_page": 100,
        }
    )
    commits = json.loads(
        _download_bounded(
            f"https://api.github.com/repos/Homebrew/homebrew-core/commits?{query}"
        )
    )
    if not isinstance(commits, list):
        raise TypeError(f"Homebrew formula history is invalid: {name}")
    for commit in commits:
        revision = commit.get("sha") if isinstance(commit, dict) else None
        if not isinstance(revision, str) or not _is_lower_hex(revision, 40):
            continue
        raw_url = (
            "https://raw.githubusercontent.com/Homebrew/homebrew-core/"
            f"{revision}/{formula_path}"
        )
        formula = _download_bounded(raw_url)
        if (
            source_sha256.encode() not in formula
            or bottle_sha256.encode() not in formula
        ):
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(formula)
        result = {
            "formula_revision": revision,
            "formula_url": (
                "https://github.com/Homebrew/homebrew-core/blob/"
                f"{revision}/{formula_path}"
            ),
            "formula_path": destination.as_posix(),
            "formula_sha256": sha256_file(destination),
        }
        cache.mkdir(parents=True, exist_ok=True)
        shutil.copy2(destination, cached_formula)
        _write_json(
            cached_record,
            {
                "name": name,
                "version": version,
                "source_sha256": source_sha256,
                "bottle_sha256": bottle_sha256,
                **result,
            },
        )
        return result
    raise RuntimeError(
        f"exact Homebrew formula revision was not found: {name} {version}"
    )


def _is_lower_hex(value: str, length: int) -> bool:
    return len(value) == length and all(
        character in "0123456789abcdef" for character in value
    )


def _installed_homebrew_bottle(
    info: Mapping[str, Any],
    *,
    name: str,
    version: str,
    receipt: Mapping[str, Any],
) -> dict[str, str] | None:
    formulae = info.get("formulae")
    if not isinstance(formulae, list) or len(formulae) != 1:
        return None
    formula = formulae[0]
    if not isinstance(formula, Mapping):
        return None
    versions = formula.get("versions")
    if not isinstance(versions, Mapping):
        return None
    stable = versions.get("stable")
    revision = formula.get("revision", 0)
    if not isinstance(stable, str) or not isinstance(revision, int) or revision < 0:
        return None
    package_version = stable if revision == 0 else f"{stable}_{revision}"
    if package_version != version:
        return None
    files = ((formula.get("bottle") or {}).get("stable") or {}).get("files")
    if not isinstance(files, Mapping):
        return None
    source = receipt.get("source")
    source_path = source.get("path") if isinstance(source, Mapping) else None
    tag = None
    if isinstance(source_path, str):
        match = re.search(r"packages\.([a-z0-9_]+)\.jws\.json$", source_path)
        if match is not None:
            tag = match.group(1)
    arch = receipt.get("arch")
    candidates = [
        (str(key), value)
        for key, value in files.items()
        if isinstance(value, Mapping)
        and (not isinstance(arch, str) or str(key).startswith(f"{arch}_"))
    ]
    if tag is not None:
        candidates = [item for item in candidates if item[0] == tag]
    if len(candidates) != 1:
        return None
    bottle_tag, bottle = candidates[0]
    bottle_url = bottle.get("url")
    bottle_sha256 = bottle.get("sha256")
    if (
        not isinstance(bottle_url, str)
        or not bottle_url.startswith("https://ghcr.io/")
        or not isinstance(bottle_sha256, str)
        or not _is_lower_hex(bottle_sha256, 64)
    ):
        return None
    return {
        "bottle_tag": bottle_tag,
        "bottle_url": bottle_url,
        "bottle_sha256": bottle_sha256,
    }


def _homebrew_component_provenance(
    components: Sequence[Mapping[str, Any]],
    destination: Path,
    *,
    resolve_formulas: bool,
    formula_cache: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    records = []
    blockers = []
    cellar = Path(
        _run(["brew", "--cellar"], capture_output=True).stdout.strip()
    ).resolve()
    for component in components:
        component_id = str(component["component_id"])
        if not component_id.startswith("homebrew-"):
            continue
        name = str(component["name"])
        version = str(component["version"])
        source = cellar / name / version / "sbom.spdx.json"
        if not source.is_file():
            blockers.append(
                {
                    "code": "missing-homebrew-sbom",
                    "detail": f"Homebrew provenance is missing for {name} {version}",
                }
            )
            continue
        document = json.loads(source.read_text(encoding="utf-8"))
        if document.get("spdxVersion") != "SPDX-2.3":
            blockers.append(
                {
                    "code": "incompatible-homebrew-sbom",
                    "detail": f"Homebrew provenance is incompatible for {name} {version}",
                }
            )
            continue
        packages = document.get("packages")
        if not isinstance(packages, list):
            raise TypeError(f"Homebrew SBOM has no package list: {name}")
        source_package = next(
            (
                item
                for item in packages
                if item.get("name") == name
                and str(item.get("SPDXID", "")).startswith("SPDXRef-Archive-")
            ),
            None,
        )
        bottle_package = next(
            (
                item
                for item in reversed(packages)
                if item.get("name") == name
                and (
                    item.get("versionInfo") == version
                    or version.startswith(f"{item.get('versionInfo')}_")
                )
                and str(item.get("downloadLocation", "")).startswith("https://ghcr.io/")
            ),
            None,
        )
        source_version = (
            str(source_package.get("versionInfo")) if source_package is not None else ""
        )
        if source_package is None or not (
            version == source_version or version.startswith(f"{source_version}_")
        ):
            blockers.append(
                {
                    "code": "missing-homebrew-source-record",
                    "detail": f"Exact upstream source is missing for {name} {version}",
                }
            )
            continue
        copied = destination / f"{name}-{version}.spdx.json"
        _copy_compliance_file(source, copied)
        source_checksums = source_package.get("checksums") or []
        bottle_checksums = (bottle_package or {}).get("checksums") or []
        source_sha256 = next(
            (
                str(item.get("checksumValue"))
                for item in source_checksums
                if item.get("algorithm") == "SHA256"
            ),
            "",
        )
        bottle_sha256 = next(
            (
                str(item.get("checksumValue"))
                for item in bottle_checksums
                if item.get("algorithm") == "SHA256"
            ),
            "",
        )
        receipt_path = cellar / name / version / "INSTALL_RECEIPT.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        metadata_path: Path | None = None
        if resolve_formulas:
            brew_info = json.loads(
                _run(
                    ["brew", "info", "--json=v2", name],
                    capture_output=True,
                ).stdout
            )
            metadata_path = destination / f"{name}-{version}.brew-info.json"
            _write_json(metadata_path, brew_info)
            if not bottle_sha256:
                bottle = _installed_homebrew_bottle(
                    brew_info,
                    name=name,
                    version=version,
                    receipt=receipt,
                )
                if bottle is not None:
                    bottle_sha256 = bottle["bottle_sha256"]
                    bottle_package = {
                        "downloadLocation": bottle["bottle_url"],
                    }
        record = {
            "component_id": component_id,
            "name": name,
            "version": version,
            "license_concluded": source_package.get("licenseConcluded"),
            "source_url": source_package.get("downloadLocation"),
            "source_sha256": source_sha256 or None,
            "bottle_url": (bottle_package or {}).get("downloadLocation"),
            "bottle_sha256": bottle_sha256 or None,
            "homebrew_sbom": copied.relative_to(destination.parent).as_posix(),
            "homebrew_sbom_sha256": sha256_file(copied),
        }
        if resolve_formulas:
            if metadata_path is None:
                raise AssertionError("Homebrew metadata path was not initialized")
            record["homebrew_metadata"] = metadata_path.relative_to(
                destination.parent.parent
            ).as_posix()
            record["homebrew_metadata_sha256"] = sha256_file(metadata_path)
        if resolve_formulas:
            if not _is_lower_hex(source_sha256, 64) or not _is_lower_hex(
                bottle_sha256, 64
            ):
                blockers.append(
                    {
                        "code": "missing-homebrew-formula-input",
                        "detail": f"Formula source/bottle hashes are missing: {name}",
                    }
                )
            else:
                try:
                    formula = _resolve_homebrew_formula(
                        name=name,
                        version=version,
                        prefix=cellar / name / version,
                        source_sha256=source_sha256,
                        bottle_sha256=bottle_sha256,
                        destination=(
                            destination.parent.parent
                            / "formulae"
                            / f"{name}-{version}.rb"
                        ),
                        cache=formula_cache,
                    )
                except (OSError, RuntimeError, urllib.error.URLError) as error:
                    blockers.append(
                        {
                            "code": "missing-exact-homebrew-formula-recipe",
                            "detail": str(error),
                        }
                    )
                else:
                    formula["formula_path"] = (
                        Path(formula["formula_path"])
                        .relative_to(destination.parent.parent)
                        .as_posix()
                    )
                    record.update(formula)
        records.append(record)
    return records, blockers


def _dependency_license_files(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.iterdir()
        if path.is_file()
        and any(
            path.name.casefold() == name
            or path.name.casefold().startswith(f"{name}.")
            or path.name.casefold().startswith(f"{name}-")
            or path.name.casefold().startswith(f"{name}_")
            for name in _LICENSE_NAMES
        )
    )


def _rust_license_expression(value: str) -> str:
    return {
        "Apache-2.0 / MIT": "Apache-2.0 OR MIT",
        "BSD-3-Clause/MIT": "BSD-3-Clause OR MIT",
        "MIT/Apache-2.0": "MIT OR Apache-2.0",
    }.get(value, value)


def _load_rust_license_sources(repository: Path) -> dict[str, Any]:
    path = rust_license_sources_path(repository)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema_version") != (
        RUST_LICENSE_SOURCES_SCHEMA
    ):
        raise RuntimeError("macOS Rust license-source inventory is incompatible")
    documents = value.get("documents")
    packages = value.get("packages")
    if not isinstance(documents, dict) or not isinstance(packages, dict):
        raise TypeError("macOS Rust license-source inventory is invalid")
    return value


def _acquire_compliance_document(
    document_id: str,
    record: Mapping[str, Any],
    *,
    cache: Path,
) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*", document_id):
        raise RuntimeError(f"compliance document identifier is invalid: {document_id}")
    filename = record.get("filename")
    url = record.get("url")
    expected_sha256 = record.get("sha256")
    if (
        not isinstance(filename, str)
        or Path(filename).name != filename
        or not isinstance(url, str)
        or not url.startswith("https://")
        or not isinstance(expected_sha256, str)
        or not _is_lower_hex(expected_sha256, 64)
    ):
        raise RuntimeError(f"compliance document is invalid: {document_id}")
    cached = cache / f"{document_id}-{filename}"
    if cached.is_file() and sha256_file(cached) == expected_sha256:
        return cached
    content = _download_bounded(url)
    if hashlib.sha256(content).hexdigest() != expected_sha256:
        raise RuntimeError(f"compliance document hash mismatched: {document_id}")
    cache.mkdir(parents=True, exist_ok=True)
    temporary = cached.with_name(f".{cached.name}.{secrets.token_hex(6)}.partial")
    try:
        temporary.write_bytes(content)
        os.replace(temporary, cached)
    finally:
        temporary.unlink(missing_ok=True)
    return cached


def _recover_rust_license_files(
    *,
    package_root: Path,
    name: str,
    version: str,
    license_expression: str,
    repository: Path,
    output: Path,
) -> tuple[list[Path], list[dict[str, str]]]:
    inventory = _load_rust_license_sources(repository)
    packages = inventory["packages"]
    documents = inventory["documents"]
    package_key = f"{name}@{version}"
    record = packages.get(package_key)
    if not isinstance(record, Mapping):
        return [], []
    if record.get("license_declared") != license_expression:
        raise RuntimeError(f"Rust license-source expression drifted: {package_key}")
    vcs_path = package_root / ".cargo_vcs_info.json"
    if not vcs_path.is_file():
        raise RuntimeError(f"Rust package lacks VCS identity: {package_key}")
    vcs = json.loads(vcs_path.read_text(encoding="utf-8"))
    git = vcs.get("git")
    revision = git.get("sha1") if isinstance(git, Mapping) else None
    if revision != record.get("vcs_revision") or vcs.get("path_in_vcs") != record.get(
        "path_in_vcs"
    ):
        raise RuntimeError(f"Rust license-source revision drifted: {package_key}")
    document_ids = record.get("documents")
    if not isinstance(document_ids, list) or not document_ids:
        raise RuntimeError(f"Rust license-source documents are empty: {package_key}")
    destination = output / "dependency-licenses" / "rust" / f"{name}-{version}"
    license_paths = []
    provenance = []
    for document_id_value in document_ids:
        document_id = str(document_id_value)
        document = documents.get(document_id)
        if not isinstance(document, Mapping):
            raise TypeError(
                f"Rust license-source document is missing: {package_key} {document_id}"
            )
        source = _acquire_compliance_document(
            document_id,
            document,
            cache=cache_root(repository) / "compliance-licenses",
        )
        copied = destination / str(document["filename"])
        _copy_compliance_file(source, copied)
        license_paths.append(copied)
        provenance.append(
            {
                "document_id": document_id,
                "url": str(document["url"]),
                "sha256": str(document["sha256"]),
                "vcs_revision": str(record["vcs_revision"]),
            }
        )
    return license_paths, provenance


def _cargo_dependency_inventory(
    repository: Path,
    output: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]], list[str]]:
    manifest = repository / "desktop" / "src-tauri" / "Cargo.toml"
    metadata = json.loads(
        _run(
            [
                "cargo",
                "metadata",
                "--manifest-path",
                str(manifest),
                "--locked",
                "--format-version",
                "1",
                "--filter-platform",
                "aarch64-apple-darwin",
            ],
            capture_output=True,
        ).stdout
    )
    packages = metadata.get("packages")
    if not isinstance(packages, list):
        raise TypeError("Cargo metadata package list is invalid")
    lock = tomllib.loads(
        (repository / "desktop" / "src-tauri" / "Cargo.lock").read_text(
            encoding="utf-8"
        )
    )
    lock_packages = lock.get("package")
    if not isinstance(lock_packages, list):
        raise TypeError("Cargo lock package list is invalid")
    checksums = {
        (item.get("name"), str(item.get("version")), item.get("source")): item.get(
            "checksum"
        )
        for item in lock_packages
        if isinstance(item, Mapping)
    }
    records = []
    spdx_packages = []
    relationships = []
    missing_license_texts = []
    for package in sorted(
        (
            item
            for item in packages
            if isinstance(item, Mapping) and item.get("source") is not None
        ),
        key=lambda item: (str(item.get("name")), str(item.get("version"))),
    ):
        name = str(package.get("name"))
        version = str(package.get("version"))
        source = package.get("source")
        license_value = package.get("license")
        manifest_path = package.get("manifest_path")
        if not isinstance(source, str) or not source.startswith("registry+"):
            raise RuntimeError(f"unsupported Cargo dependency source: {name} {version}")
        if not isinstance(license_value, str) or not license_value:
            raise RuntimeError(f"Cargo dependency lacks a license: {name} {version}")
        if not isinstance(manifest_path, str):
            raise TypeError(f"Cargo dependency manifest is invalid: {name} {version}")
        checksum = checksums.get((name, version, source))
        if not isinstance(checksum, str) or not _is_lower_hex(checksum, 64):
            raise RuntimeError(f"Cargo dependency lacks a checksum: {name} {version}")
        package_root = Path(manifest_path).parent
        if not package_root.is_dir():
            raise RuntimeError(f"Cargo dependency source is absent: {name} {version}")
        license_sources = _dependency_license_files(package_root)
        declared_license_file = package.get("license_file")
        if isinstance(declared_license_file, str):
            declared = Path(declared_license_file)
            if declared.is_file() and declared not in license_sources:
                license_sources.append(declared)
        license_paths = []
        package_destination = (
            output / "dependency-licenses" / "rust" / f"{name}-{version}"
        )
        for source_path in sorted(license_sources):
            copied = package_destination / source_path.name
            _copy_compliance_file(source_path, copied)
            license_paths.append(copied.relative_to(output).as_posix())
        license_provenance: list[dict[str, str]] = []
        if not license_paths:
            try:
                recovered, license_provenance = _recover_rust_license_files(
                    package_root=package_root,
                    name=name,
                    version=version,
                    license_expression=_rust_license_expression(license_value),
                    repository=repository,
                    output=output,
                )
            except (OSError, RuntimeError, urllib.error.URLError):
                recovered = []
            license_paths.extend(
                path.relative_to(output).as_posix() for path in recovered
            )
        if not license_paths:
            missing_license_texts.append(f"{name} {version}")
        license_expression = _rust_license_expression(license_value)
        source_url = f"https://crates.io/api/v1/crates/{name}/{version}/download"
        spdx_id = _spdx_id(f"Package-rust-{name}-{version}")
        record = {
            "name": name,
            "version": version,
            "license_declared": license_expression,
            "license_declared_raw": license_value,
            "source_url": source_url,
            "source_sha256": checksum,
            "license_files": license_paths,
            "license_provenance": license_provenance,
        }
        records.append(record)
        spdx_packages.append(
            {
                "SPDXID": spdx_id,
                "name": name,
                "versionInfo": version,
                "downloadLocation": source_url,
                "checksums": [{"algorithm": "SHA256", "checksumValue": checksum}],
                "filesAnalyzed": False,
                "licenseConcluded": license_expression,
                "licenseDeclared": license_expression,
                "copyrightText": "NOASSERTION",
            }
        )
        relationships.append(
            {
                "spdxElementId": "SPDXRef-Package-Doc-Evidence",
                "relationshipType": "CONTAINS",
                "relatedSpdxElement": spdx_id,
            }
        )
    return records, spdx_packages, relationships, missing_license_texts


def _npm_dependency_inventory(
    repository: Path,
    output: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, str]]]:
    lock = json.loads(
        (repository / "web" / "package-lock.json").read_text(encoding="utf-8")
    )
    packages = lock.get("packages")
    if not isinstance(packages, Mapping):
        raise TypeError("Node lock package inventory is invalid")
    records = []
    spdx_packages = []
    relationships = []
    for package_path, package in sorted(packages.items()):
        if not package_path or not isinstance(package, Mapping) or package.get("dev"):
            continue
        name = str(package_path).rsplit("node_modules/", 1)[-1]
        version = package.get("version")
        license_value = package.get("license")
        resolved = package.get("resolved")
        integrity = package.get("integrity")
        if (
            not isinstance(version, str)
            or not isinstance(license_value, str)
            or not isinstance(resolved, str)
            or not resolved.startswith("https://registry.npmjs.org/")
            or not isinstance(integrity, str)
            or not integrity.startswith("sha512-")
        ):
            raise RuntimeError(f"Node dependency metadata is invalid: {name}")
        try:
            checksum = base64.b64decode(
                integrity.removeprefix("sha512-"), validate=True
            )
        except ValueError as error:
            raise RuntimeError(
                f"Node dependency checksum is invalid: {name}"
            ) from error
        if len(checksum) != 64:
            raise RuntimeError(f"Node dependency checksum is invalid: {name}")
        source_root = repository / "web" / str(package_path)
        if not source_root.is_dir():
            raise RuntimeError(f"Node dependency source is absent: {name} {version}")
        license_sources = _dependency_license_files(source_root)
        if not license_sources:
            raise RuntimeError(f"Node dependency lacks license text: {name} {version}")
        safe_name = name.replace("/", "-").removeprefix("@")
        license_paths = []
        for source_path in license_sources:
            copied = (
                output
                / "dependency-licenses"
                / "node"
                / f"{safe_name}-{version}"
                / source_path.name
            )
            _copy_compliance_file(source_path, copied)
            license_paths.append(copied.relative_to(output).as_posix())
        checksum_hex = checksum.hex()
        spdx_id = _spdx_id(f"Package-node-{safe_name}-{version}")
        record = {
            "name": name,
            "version": version,
            "license_declared": license_value,
            "source_url": resolved,
            "source_sha512": checksum_hex,
            "license_files": license_paths,
        }
        records.append(record)
        spdx_packages.append(
            {
                "SPDXID": spdx_id,
                "name": name,
                "versionInfo": version,
                "downloadLocation": resolved,
                "checksums": [{"algorithm": "SHA512", "checksumValue": checksum_hex}],
                "filesAnalyzed": False,
                "licenseConcluded": license_value,
                "licenseDeclared": license_value,
                "copyrightText": "NOASSERTION",
            }
        )
        relationships.append(
            {
                "spdxElementId": "SPDXRef-Package-Doc-Evidence",
                "relationshipType": "CONTAINS",
                "relatedSpdxElement": spdx_id,
            }
        )
    return records, spdx_packages, relationships


def _write_dependency_notices(
    destination: Path,
    rust: Sequence[Mapping[str, Any]],
    node: Sequence[Mapping[str, Any]],
) -> None:
    lines = [
        "Doc Evidence compiled and frontend dependency inventory",
        "",
        "Exact license texts are retained under dependency-licenses/.",
        "Source archive checksums are recorded in the aggregate SPDX document.",
    ]
    for heading, records in (("Rust", rust), ("Node", node)):
        lines.extend(("", heading, "-" * len(heading)))
        for record in records:
            lines.append(
                f"{record['name']} {record['version']} — "
                f"{record['license_declared']} — {record['source_url']}"
            )
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _requires_corresponding_source(license_value: str) -> bool:
    normalized = license_value.upper()
    return "GPL" in normalized or "MPL" in normalized


def _pypi_source_record(
    *,
    component_id: str,
    name: str,
    version: str,
    license_value: str,
    metadata_destination: Path,
) -> dict[str, Any]:
    url = f"https://pypi.org/pypi/{urllib.parse.quote(name)}/{version}/json"
    metadata = json.loads(_download_bounded(url))
    urls = metadata.get("urls")
    if not isinstance(urls, list):
        raise TypeError(f"PyPI source metadata is invalid: {name} {version}")
    sources = [
        item
        for item in urls
        if isinstance(item, Mapping) and item.get("packagetype") == "sdist"
    ]
    if len(sources) != 1:
        raise RuntimeError(f"PyPI source archive is ambiguous: {name} {version}")
    source = sources[0]
    filename = source.get("filename")
    source_url = source.get("url")
    digests = source.get("digests")
    sha256 = digests.get("sha256") if isinstance(digests, Mapping) else None
    if (
        not isinstance(filename, str)
        or Path(filename).name != filename
        or not isinstance(source_url, str)
        or not source_url.startswith("https://files.pythonhosted.org/")
        or not isinstance(sha256, str)
        or not _is_lower_hex(sha256, 64)
    ):
        raise RuntimeError(f"PyPI source archive is invalid: {name} {version}")
    metadata_destination.parent.mkdir(parents=True, exist_ok=True)
    _write_json(metadata_destination, metadata)
    return {
        "component_id": component_id,
        "name": name,
        "version": version,
        "license_concluded": license_value,
        "url": source_url,
        "sha256": sha256,
        "cache_name": f"python-{filename}",
        "metadata_path": f"source-metadata/pypi/{metadata_destination.name}",
        "metadata_sha256": sha256_file(metadata_destination),
    }


def _source_archive_records(
    *,
    components: Sequence[Mapping[str, Any]],
    homebrew: Sequence[Mapping[str, Any]],
    rust: Sequence[Mapping[str, Any]],
    wheel_native: Sequence[Mapping[str, Any]],
    inputs: Mapping[str, Any],
    metadata_destination: Path,
) -> list[dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for item in homebrew:
        license_value = str(item.get("license_concluded") or "")
        if not _requires_corresponding_source(license_value):
            continue
        name = str(item["name"])
        version = str(item["version"])
        source_url = str(item["source_url"])
        suffix = Path(urllib.parse.urlparse(source_url).path).name
        record = {
            "component_id": str(item["component_id"]),
            "name": name,
            "version": version,
            "license_concluded": license_value,
            "url": source_url,
            "sha256": str(item["source_sha256"]),
            "cache_name": f"homebrew-{name}-{version}-{suffix}",
        }
        records[record["component_id"]] = record
    for item in rust:
        license_value = str(item["license_declared"])
        if not _requires_corresponding_source(license_value):
            continue
        name = str(item["name"])
        version = str(item["version"])
        component_id = f"rust-{name}-{version}"
        records[component_id] = {
            "component_id": component_id,
            "name": name,
            "version": version,
            "license_concluded": license_value,
            "url": str(item["source_url"]),
            "sha256": str(item["source_sha256"]),
            "cache_name": f"rust-{name}-{version}.crate",
        }
    for item in wheel_native:
        source = item["source"]
        component_id = str(item["component_id"])
        records[component_id] = {
            "component_id": component_id,
            "name": str(item["name"]),
            "version": str(item["version"]),
            "license_concluded": str(item["license_concluded"]),
            "url": str(source["url"]),
            "sha256": str(source["sha256"]),
            "cache_name": str(source["cache_name"]),
        }
    for component in components:
        component_id = str(component["component_id"])
        license_value = str(component["license_concluded"])
        if not component_id.startswith("python-") or not _requires_corresponding_source(
            license_value
        ):
            continue
        records[component_id] = _pypi_source_record(
            component_id=component_id,
            name=str(component["name"]),
            version=str(component["version"]),
            license_value=license_value,
            metadata_destination=metadata_destination / f"{component_id}.json",
        )
    baseline = inputs.get("baseline_pack")
    declared_sources = (
        baseline.get("source_archives") if isinstance(baseline, Mapping) else None
    )
    if not isinstance(declared_sources, list):
        raise TypeError("baseline source archive inventory is invalid")
    components_by_id = {
        str(component["component_id"]): component for component in components
    }
    for raw in declared_sources:
        if not isinstance(raw, Mapping):
            raise TypeError("declared baseline source archive is invalid")
        component_id = str(raw["component_id"])
        component = components_by_id.get(component_id)
        if component is None or not _requires_corresponding_source(
            str(component["license_concluded"])
        ):
            continue
        record = {
            **dict(raw),
            "name": str(component["name"]),
            "license_concluded": str(component["license_concluded"]),
        }
        cache_name = record.get("cache_name")
        if not isinstance(cache_name, str) or Path(cache_name).name != cache_name:
            url_name = Path(urllib.parse.urlparse(str(record["url"])).path).name
            record["cache_name"] = f"{component_id}-{url_name}"
        records[component_id] = record
    return [records[key] for key in sorted(records)]


def _embed_source_archives(
    records: Sequence[Mapping[str, Any]],
    *,
    cache: Path,
    destination: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    embedded = []
    blockers = []
    for record in records:
        try:
            archive = acquire_declared_archive(record, cache)
        except (OSError, RuntimeError, urllib.error.URLError) as error:
            blockers.append(
                {
                    "code": "source-archive-unavailable",
                    "detail": f"{record['component_id']}: {error}",
                }
            )
            continue
        copied = destination / str(record["cache_name"])
        _copy_compliance_file(archive, copied)
        embedded.append(
            {
                **dict(record),
                "path": copied.relative_to(destination.parent).as_posix(),
                "bytes": copied.stat().st_size,
            }
        )
    return embedded, blockers


def _python_native_inventory(
    native_files: Sequence[Mapping[str, Any]],
    manifest_files: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    owners = {
        str(item["path"]): item
        for item in manifest_files
        if isinstance(item, Mapping) and str(item.get("path", "")).startswith("python/")
    }
    records = []
    for item in native_files:
        path = str(item.get("path", ""))
        if not path.startswith("python/"):
            continue
        owner = owners.get(path)
        if owner is None:
            raise RuntimeError(f"Python native object lacks manifest ownership: {path}")
        component_id = str(owner["component_id"])
        wheel_owned = component_id.startswith("python-")
        nested_dependency = wheel_owned and (
            "/.dylibs/" in path or "/pypdfium2_raw/libpdfium.dylib" in path
        )
        records.append(
            {
                "path": path,
                "sha256": str(owner["sha256"]),
                "bytes": int(owner["bytes"]),
                "component_id": component_id,
                "wheel_owned": wheel_owned,
                "nested_dependency": nested_dependency,
                "description": str(item.get("description", "")),
                "dependencies": list(item.get("dependencies") or []),
            }
        )
    return records


def _unreconciled_nested_native(
    python_native: Sequence[Mapping[str, Any]],
    binary_compliance_records: Sequence[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    reconciled = {str(record["binary_path"]) for record in binary_compliance_records}
    inventory_paths = {str(record["path"]) for record in python_native}
    unknown = sorted(reconciled - inventory_paths)
    if unknown:
        raise RuntimeError(
            f"Python binary compliance paths are absent from native inventory: {unknown}"
        )
    return [
        record
        for record in python_native
        if record["nested_dependency"] and str(record["path"]) not in reconciled
    ]


def _component_license_ids(component: Mapping[str, Any]) -> list[str]:
    values = component.get("licenses")
    if not isinstance(values, list):
        return []
    identifiers = []
    for value in values:
        license_value = value.get("license") if isinstance(value, Mapping) else None
        identifier = (
            license_value.get("id") if isinstance(license_value, Mapping) else None
        )
        if isinstance(identifier, str) and identifier:
            identifiers.append(identifier)
    return sorted(identifiers)


def _wheel_native_component_inventory(
    *,
    repository: Path,
    runtime: Path,
    cache: Path,
    python_native: Sequence[Mapping[str, Any]],
    binary_compliance_records: Sequence[Mapping[str, Any]],
    runtime_components: Sequence[Mapping[str, Any]],
    signed: bool = False,
) -> tuple[list[dict[str, Any]], list[Mapping[str, Any]]]:
    document = json.loads(
        wheel_native_components_path(repository).read_text(encoding="utf-8")
    )
    if document.get("schema_version") != WHEEL_NATIVE_COMPONENTS_SCHEMA:
        raise RuntimeError("macOS wheel-native component inventory is incompatible")
    wheels = document.get("wheels")
    declared_components = document.get("components")
    remote_evidence = document.get("remote_evidence")
    if not isinstance(wheels, list) or not isinstance(declared_components, list):
        raise TypeError("macOS wheel-native component inventory is invalid")
    if not isinstance(remote_evidence, list):
        raise TypeError("macOS wheel-native evidence inventory is invalid")

    evidence_values: dict[str, bytes] = {}
    for item in remote_evidence:
        if not isinstance(item, Mapping):
            raise TypeError("macOS wheel-native evidence record is invalid")
        evidence_id = item.get("evidence_id")
        if not isinstance(evidence_id, str) or evidence_id in evidence_values:
            raise RuntimeError("macOS wheel-native evidence identifier is invalid")
        evidence_values[evidence_id] = acquire_declared_archive(
            item, cache
        ).read_bytes()

    native_by_path = {
        str(item["path"]): item
        for item in _unreconciled_nested_native(
            python_native,
            binary_compliance_records,
        )
    }
    runtime_by_id = {str(item["component_id"]): item for item in runtime_components}
    wheel_archives: dict[str, tuple[Mapping[str, Any], Path]] = {}
    wheel_ids: set[str] = set()
    for wheel in wheels:
        if not isinstance(wheel, Mapping):
            raise TypeError("macOS wheel-native wheel record is invalid")
        component_id = wheel.get("component_id")
        version = wheel.get("version")
        if not isinstance(component_id, str) or component_id in wheel_ids:
            raise RuntimeError("macOS wheel-native parent identifier is invalid")
        runtime_component = runtime_by_id.get(component_id)
        if runtime_component is None or runtime_component.get("version") != version:
            raise RuntimeError(f"macOS wheel-native parent drifted: {component_id}")
        wheel_ids.add(component_id)
        archive = acquire_declared_archive(wheel, cache)
        wheel_archives[component_id] = (wheel, archive)
        installed_evidence = wheel.get("installed_evidence")
        if not isinstance(installed_evidence, list) or not installed_evidence:
            raise RuntimeError(f"macOS wheel evidence is empty: {component_id}")
        with zipfile.ZipFile(archive) as source:
            for evidence in installed_evidence:
                if not isinstance(evidence, Mapping):
                    raise TypeError("macOS installed wheel evidence is invalid")
                member = str(evidence.get("member", ""))
                runtime_path = str(evidence.get("runtime_path", ""))
                expected = str(evidence.get("sha256", ""))
                installed = runtime / runtime_path
                source_bytes = source.read(member)
                if (
                    not _is_lower_hex(expected, 64)
                    or not installed.is_file()
                    or hashlib.sha256(source_bytes).hexdigest() != expected
                    or _artifact_source_binding(
                        source_bytes,
                        installed.read_bytes(),
                        signed=signed,
                    )
                    is None
                ):
                    raise RuntimeError(
                        f"macOS installed wheel evidence drifted: {component_id}"
                    )

    records = []
    flattened_paths: set[str] = set()
    site_prefix = "python/lib/python3.12/site-packages/"
    for raw in declared_components:
        if not isinstance(raw, Mapping):
            raise TypeError("macOS wheel-native component record is invalid")
        record = dict(raw)
        component_id = record.get("component_id")
        parent_id = record.get("parent_component_id")
        version = record.get("version")
        license_value = record.get("license_concluded")
        source = record.get("source")
        paths = record.get("paths")
        evidence = record.get("evidence")
        if (
            not isinstance(component_id, str)
            or any(item["component_id"] == component_id for item in records)
            or parent_id not in wheel_archives
            or not isinstance(version, str)
            or not version
            or not isinstance(license_value, str)
            or _spdx_license(license_value)[1]
            or not isinstance(source, Mapping)
            or not isinstance(paths, list)
            or not paths
            or not isinstance(evidence, list)
            or not evidence
        ):
            raise RuntimeError("macOS wheel-native component record is incomplete")
        if (
            not isinstance(source.get("url"), str)
            or not isinstance(source.get("cache_name"), str)
            or not _is_lower_hex(str(source.get("sha256", "")), 64)
        ):
            raise RuntimeError(f"macOS wheel-native source is invalid: {component_id}")

        wheel, wheel_path = wheel_archives[str(parent_id)]
        with zipfile.ZipFile(wheel_path) as archive:
            normalized_paths = []
            for path_record in paths:
                if not isinstance(path_record, Mapping):
                    raise TypeError("macOS wheel-native path record is invalid")
                path = str(path_record.get("path", ""))
                expected = str(path_record.get("sha256", ""))
                native = native_by_path.get(path)
                if (
                    not path.startswith(site_prefix)
                    or path in flattened_paths
                    or native is None
                    or native.get("component_id") != parent_id
                    or not _is_lower_hex(expected, 64)
                ):
                    raise RuntimeError(
                        f"macOS wheel-native path ownership drifted: {path}"
                    )
                member = path.removeprefix(site_prefix)
                installed = runtime / path
                staged_wheel_bytes = _staged_wheel_native_bytes(
                    member, archive.read(member)
                )
                actual_bytes = installed.read_bytes() if installed.is_file() else None
                installed_sha256 = (
                    hashlib.sha256(actual_bytes).hexdigest()
                    if actual_bytes is not None
                    else None
                )
                binding = (
                    _artifact_source_binding(
                        staged_wheel_bytes,
                        actual_bytes,
                        signed=signed,
                    )
                    if actual_bytes is not None
                    else None
                )
                if (
                    hashlib.sha256(staged_wheel_bytes).hexdigest() != expected
                    or native.get("sha256") != installed_sha256
                    or binding is None
                ):
                    raise RuntimeError(f"macOS wheel-native bytes drifted: {path}")
                flattened_paths.add(path)
                normalized_paths.append(
                    {
                        "path": path,
                        "sha256": expected,
                        "installed_sha256": installed_sha256,
                        "binding": binding,
                    }
                )

        for evidence_record in evidence:
            if not isinstance(evidence_record, Mapping):
                raise TypeError("macOS wheel-native component evidence is invalid")
            kind = evidence_record.get("kind")
            if kind == "build-version":
                value = json.loads(evidence_values[str(evidence_record["evidence_id"])])
                if value.get(evidence_record.get("key")) != version:
                    raise RuntimeError(
                        f"macOS wheel-native build version drifted: {component_id}"
                    )
            elif kind == "build-script-contains":
                text = evidence_values[str(evidence_record["evidence_id"])].decode()
                if str(evidence_record.get("text", "")) not in text:
                    raise RuntimeError(
                        f"macOS wheel-native build recipe drifted: {component_id}"
                    )
            elif kind == "cyclonedx-component":
                installed_evidence = wheel["installed_evidence"]
                sbom_path = runtime / str(installed_evidence[0]["runtime_path"])
                sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
                matches = [
                    item
                    for item in sbom.get("components", [])
                    if isinstance(item, Mapping)
                    and item.get("name") == evidence_record.get("name")
                    and item.get("version") == version
                ]
                expected_ids = sorted(evidence_record.get("license_ids") or [])
                if (
                    len(matches) != 1
                    or _component_license_ids(matches[0]) != expected_ids
                ):
                    raise RuntimeError(
                        f"macOS wheel-native SBOM evidence drifted: {component_id}"
                    )
            elif kind == "reviewed-binary-version":
                method = evidence_record.get("method")
                detail = evidence_record.get("detail")
                if (
                    not isinstance(method, str)
                    or not method
                    or not isinstance(detail, str)
                    or version not in detail
                ):
                    raise RuntimeError(
                        f"macOS wheel-native reviewed evidence drifted: {component_id}"
                    )
            else:
                raise RuntimeError(
                    f"macOS wheel-native evidence kind is unsupported: {component_id}"
                )
        records.append(
            {
                **record,
                "paths": normalized_paths,
                "wheel_url": str(wheel["url"]),
                "wheel_sha256": str(wheel["sha256"]),
            }
        )

    unresolved = [
        item for path, item in native_by_path.items() if path not in flattened_paths
    ]
    return records, unresolved


def _normalized_macho_signing_payload(data: bytes) -> tuple[bytes, int]:
    """Remove only Mach-O fields Apple code signing is allowed to rewrite."""

    header_size = 32
    if len(data) < header_size or data[:4] != b"\xcf\xfa\xed\xfe":
        raise RuntimeError("signed Python binary is not thin little-endian Mach-O 64")
    _, _, _, _, command_count, command_bytes, _, _ = struct.unpack_from(
        "<IiiIIIII", data
    )
    command_end = header_size + command_bytes
    if command_count > 4096 or command_end > len(data):
        raise RuntimeError("signed Python binary has an invalid Mach-O command table")
    normalized = bytearray(data)
    offset = header_size
    linkedit_offsets: list[tuple[int, int, int, int]] = []
    signature_offsets: list[tuple[int, int, int]] = []
    for _ in range(command_count):
        if offset + 8 > command_end:
            raise RuntimeError("signed Python binary has a truncated Mach-O command")
        command, size = struct.unpack_from("<II", data, offset)
        if size < 8 or offset + size > command_end:
            raise RuntimeError("signed Python binary has an invalid Mach-O command")
        if command == 0x19 and size >= 72:
            segment = data[offset + 8 : offset + 24].split(b"\0", 1)[0]
            if segment == b"__LINKEDIT":
                file_offset, file_size = struct.unpack_from("<QQ", data, offset + 40)
                linkedit_offsets.append(
                    (offset + 32, offset + 48, file_offset, file_size)
                )
        elif command == 0x1D and size == 16:
            signature_offset, signature_size = struct.unpack_from(
                "<II", data, offset + 8
            )
            signature_offsets.append((offset + 8, signature_offset, signature_size))
        offset += size
    if (
        offset != command_end
        or len(linkedit_offsets) != 1
        or len(signature_offsets) != 1
    ):
        raise RuntimeError(
            "signed Python binary has an ambiguous Mach-O signature boundary"
        )
    vmsize_offset, filesize_offset, linkedit_offset, linkedit_size = linkedit_offsets[0]
    signature_field, signature_offset, signature_size = signature_offsets[0]
    if (
        signature_offset < command_end
        or signature_offset + signature_size != len(data)
        or linkedit_offset + linkedit_size != len(data)
        or linkedit_offset > signature_offset
    ):
        raise RuntimeError(
            "signed Python binary has an invalid Mach-O signature extent"
        )
    normalized[vmsize_offset : vmsize_offset + 8] = b"\0" * 8
    normalized[filesize_offset : filesize_offset + 8] = b"\0" * 8
    normalized[signature_field : signature_field + 8] = b"\0" * 8
    return bytes(normalized[:signature_offset]), signature_offset


def _macho_signing_only_difference(unsigned: bytes, signed: bytes) -> bool:
    unsigned_payload, unsigned_signature_offset = _normalized_macho_signing_payload(
        unsigned
    )
    signed_payload, signed_signature_offset = _normalized_macho_signing_payload(signed)
    return (
        unsigned_signature_offset == signed_signature_offset
        and unsigned_payload == signed_payload
    )


def _artifact_source_binding(
    expected: bytes, actual: bytes, *, signed: bool
) -> str | None:
    if actual == expected:
        return "exact-source-bytes"
    if signed:
        try:
            if _macho_signing_only_difference(expected, actual):
                return "apple-code-signature-envelope"
        except RuntimeError:
            pass
    return None


def _python_binary_compliance_record(
    component: Mapping[str, Any],
    *,
    inputs: Mapping[str, Any],
    runtime: Path,
    cache: Path,
    signed: bool = False,
) -> dict[str, Any] | None:
    baseline = inputs.get("baseline_pack")
    overrides = (
        baseline.get("python_license_conclusions")
        if isinstance(baseline, Mapping)
        else None
    )
    if not isinstance(overrides, Mapping):
        raise TypeError("baseline Python license conclusions are invalid")
    normalized = str(component["name"]).lower().replace("_", "-")
    override = overrides.get(normalized)
    if not isinstance(override, Mapping) or "license_declared" not in override:
        return None
    version = str(component["version"])
    declared = override.get("license_declared")
    concluded = override.get("license_concluded")
    wheel_url = override.get("wheel_url")
    wheel_sha256 = override.get("wheel_sha256")
    binary_member = override.get("binary_member")
    binary_sha256 = override.get("binary_sha256")
    if (
        override.get("version") != version
        or component.get("license_concluded") != concluded
        or not isinstance(declared, str)
        or not declared
        or not isinstance(concluded, str)
        or not concluded.startswith("LicenseRef-")
        or not isinstance(wheel_url, str)
        or not wheel_url.startswith("https://files.pythonhosted.org/")
        or not isinstance(wheel_sha256, str)
        or not _is_lower_hex(wheel_sha256, 64)
        or not isinstance(binary_member, str)
        or Path(binary_member).is_absolute()
        or ".." in Path(binary_member).parts
        or not isinstance(binary_sha256, str)
        or not _is_lower_hex(binary_sha256, 64)
    ):
        raise RuntimeError(f"Python binary compliance record drifted: {normalized}")
    wheel_name = Path(urllib.parse.urlparse(wheel_url).path).name
    if not wheel_name.endswith(".whl") or Path(wheel_name).name != wheel_name:
        raise RuntimeError(f"Python binary wheel URL is invalid: {normalized}")
    wheel = acquire_declared_archive(
        {
            "cache_name": wheel_name,
            "url": wheel_url,
            "sha256": wheel_sha256,
        },
        cache,
    )
    site_prefix = Path("python/lib/python3.12/site-packages")
    license_prefix = (
        f"{str(component['name']).replace('-', '_')}-{version}.dist-info/licenses/"
    )
    with zipfile.ZipFile(wheel) as archive:
        names = sorted(
            name
            for name in archive.namelist()
            if not name.endswith("/") and name.startswith(license_prefix)
        )
        if not names or binary_member not in archive.namelist():
            raise RuntimeError(
                f"Python binary wheel license inventory is empty: {normalized}"
            )
        wheel_binary = archive.read(binary_member)
        if hashlib.sha256(wheel_binary).hexdigest() != binary_sha256:
            raise RuntimeError(f"Python binary payload hash drifted: {normalized}")
        selected = [binary_member, *names]
        installed = []
        binary_binding = "exact-source-bytes"
        for member in selected:
            relative = Path(member)
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError(f"Python binary wheel path is unsafe: {normalized}")
            target = runtime / site_prefix / relative
            expected_bytes = archive.read(member)
            actual_bytes = target.read_bytes() if target.is_file() else None
            binding = (
                _artifact_source_binding(
                    expected_bytes,
                    actual_bytes,
                    signed=signed,
                )
                if actual_bytes is not None
                else None
            )
            if binding is None:
                raise RuntimeError(
                    f"Python binary wheel bytes drifted: {normalized} {member}"
                )
            if member == binary_member:
                binary_binding = binding
            installed.append((site_prefix / relative).as_posix())
    binary_path = (site_prefix / binary_member).as_posix()
    installed_binary_sha256 = sha256_file(runtime / binary_path)
    license_paths = installed[1:]
    return {
        "component_id": str(component["component_id"]),
        "name": str(component["name"]),
        "version": version,
        "license_declared": declared,
        "license_concluded": concluded,
        "wheel_url": wheel_url,
        "wheel_sha256": wheel_sha256,
        "binary_path": binary_path,
        "binary_sha256": binary_sha256,
        "installed_binary_sha256": installed_binary_sha256,
        "binary_binding": binary_binding,
        "license_files": license_paths,
        "extracted_licensing_info": {
            "licenseId": concluded,
            "extractedText": (
                f"This LicenseRef identifies the exact {wheel_name} composite. "
                f"The pypdfium2 wrapper declares {declared}; the bundled PDFium "
                "binary and its third-party dependencies are governed by the "
                "complete license files carried in that hash-pinned wheel."
            ),
            "comment": (
                f"Wheel SHA-256: {wheel_sha256}. Binary member: {binary_member} "
                f"({binary_sha256}). All {len(license_paths)} wheel-declared "
                "license files were compared byte-for-byte with the staged runtime."
            ),
            "seeAlsos": [
                wheel_url,
                "https://github.com/pypdfium2-team/pypdfium2/tree/5.5.0",
            ],
        },
    }


def generate_compliance_preflight(
    app: Path,
    destination: Path,
    *,
    repository: Path | None = None,
    replace: bool = False,
    resolve_formulas: bool = False,
    download_sources: bool = False,
    signed: bool = False,
) -> dict[str, Any]:
    _require_host()
    bundle = app.resolve()
    repo = (repository or repository_root()).resolve()
    output = destination.resolve()
    archive = output.with_name(f"{output.name}.tar.gz")
    if (output.exists() or archive.exists()) and not replace:
        raise RuntimeError(f"desktop compliance output already exists: {output}")
    app_audit = audit_application(
        bundle,
        repository=repo,
        smoke=True,
        signed=signed,
    )
    runtime = bundle / "Contents" / "Resources" / "desktop-runtime"
    manifest_path = runtime / "bundle-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    components = manifest["components"]
    inputs = _load_inputs(repo)
    blockers: list[dict[str, str]] = []

    output.parent.mkdir(parents=True, exist_ok=True)
    previous = output.with_name(f"{output.name}.previous")
    if previous.exists():
        raise RuntimeError(f"stale compliance rollback directory exists: {previous}")
    if output.exists():
        os.replace(output, previous)
    try:
        with tempfile.TemporaryDirectory(
            prefix="doc-evidence-compliance-", dir=output.parent
        ) as raw:
            staged = Path(raw) / output.name
            staged.mkdir(parents=True)
            manifests = staged / "manifests"
            manifests.mkdir()
            for source in (
                manifest_path,
                runtime / "runtime-manifest.json",
                runtime / "baseline-pack" / "pack-manifest.json",
            ):
                _copy_compliance_file(source, manifests / source.name)
            _copy_compliance_file(
                runtime / "THIRD_PARTY_NOTICES.txt",
                staged / "THIRD_PARTY_NOTICES.txt",
            )
            _copy_compliance_file(repo / "LICENSE", staged / "LICENSE")

            copied_licenses: set[str] = set()
            binary_compliance_records = []
            extracted_licensing_info = []
            spdx_packages = [
                {
                    "SPDXID": "SPDXRef-Package-Doc-Evidence",
                    "name": PRODUCT_NAME,
                    "versionInfo": __version__,
                    "downloadLocation": "https://github.com/kzahel/doc-evidence",
                    "filesAnalyzed": False,
                    "licenseConcluded": "Apache-2.0",
                    "licenseDeclared": "Apache-2.0",
                    "copyrightText": "NOASSERTION",
                }
            ]
            relationships = []
            for component in components:
                component_id = str(component["component_id"])
                binary_compliance = _python_binary_compliance_record(
                    component,
                    inputs=inputs,
                    runtime=runtime,
                    cache=repo / "results" / "desktop" / "cache" / "wheels",
                    signed=signed,
                )
                if binary_compliance is not None:
                    binary_compliance_records.append(binary_compliance)
                    extracted_licensing_info.append(
                        binary_compliance["extracted_licensing_info"]
                    )
                license_value, unresolved = _spdx_license(
                    str(component["license_concluded"])
                )
                if unresolved:
                    blockers.append(
                        {
                            "code": "unresolved-license-expression",
                            "detail": (
                                f"{component_id} lacks a reviewed SPDX expression"
                            ),
                        }
                    )
                license_files = list(component.get("license_files") or [])
                if binary_compliance is not None:
                    license_files.extend(binary_compliance["license_files"])
                    license_files = sorted(set(license_files))
                if not license_files:
                    blockers.append(
                        {
                            "code": "missing-component-license-file",
                            "detail": f"{component_id} has no mapped license file",
                        }
                    )
                for relative_value in license_files:
                    relative = str(relative_value)
                    source = runtime / relative
                    resolved = source.resolve()
                    if (
                        not source.is_file()
                        or resolved == runtime.resolve()
                        or runtime.resolve() not in resolved.parents
                    ):
                        raise RuntimeError(
                            f"component license escapes the runtime: {relative}"
                        )
                    if relative in copied_licenses:
                        continue
                    copied_licenses.add(relative)
                    _copy_compliance_file(
                        source,
                        staged / "licenses" / "runtime" / relative,
                    )
                spdx_component_id = _spdx_id(f"Package-{component_id}")
                package = {
                    "SPDXID": spdx_component_id,
                    "name": str(component["name"]),
                    "versionInfo": str(component["version"]),
                    "downloadLocation": str(
                        component.get("source_url") or "NOASSERTION"
                    ),
                    "filesAnalyzed": False,
                    "licenseConcluded": license_value,
                    "licenseDeclared": (
                        binary_compliance["license_declared"]
                        if binary_compliance is not None
                        else license_value
                    ),
                    "copyrightText": "NOASSERTION",
                }
                if unresolved:
                    package["comment"] = "Original staged conclusion: " + str(
                        component["license_concluded"]
                    )
                spdx_packages.append(package)
                relationships.append(
                    {
                        "spdxElementId": "SPDXRef-Package-Doc-Evidence",
                        "relationshipType": "CONTAINS",
                        "relatedSpdxElement": spdx_component_id,
                    }
                )
            _write_json(
                staged / "python-binary-compliance.json",
                binary_compliance_records,
            )

            python_native = _python_native_inventory(
                app_audit["runtime"]["native_files"], manifest["files"]
            )
            wheel_native_records, unreconciled_nested_native = (
                _wheel_native_component_inventory(
                    repository=repo,
                    runtime=runtime,
                    cache=repo / "results" / "desktop" / "cache" / "wheels",
                    python_native=python_native,
                    binary_compliance_records=binary_compliance_records,
                    runtime_components=components,
                    signed=signed,
                )
            )
            _write_json(
                staged / "python-wheel-native-components.json",
                wheel_native_records,
            )
            for record in wheel_native_records:
                source = record["source"]
                nested_spdx_id = _spdx_id(f"Package-{record['component_id']}")
                license_value, unresolved = _spdx_license(
                    str(record["license_concluded"])
                )
                if unresolved:
                    raise RuntimeError(
                        "wheel-native license conclusion became unresolved: "
                        f"{record['component_id']}"
                    )
                spdx_packages.append(
                    {
                        "SPDXID": nested_spdx_id,
                        "name": str(record["name"]),
                        "versionInfo": str(record["version"]),
                        "downloadLocation": str(source["url"]),
                        "checksums": [
                            {
                                "algorithm": "SHA256",
                                "checksumValue": str(source["sha256"]),
                            }
                        ],
                        "filesAnalyzed": False,
                        "licenseConcluded": license_value,
                        "licenseDeclared": license_value,
                        "copyrightText": "NOASSERTION",
                        "comment": (
                            "Nested native library conveyed by exact wheel SHA-256 "
                            f"{record['wheel_sha256']}"
                        ),
                    }
                )
                relationships.append(
                    {
                        "spdxElementId": _spdx_id(
                            f"Package-{record['parent_component_id']}"
                        ),
                        "relationshipType": "CONTAINS",
                        "relatedSpdxElement": nested_spdx_id,
                    }
                )

            homebrew_records, homebrew_blockers = _homebrew_component_provenance(
                components,
                staged / "embedded-sboms" / "homebrew",
                resolve_formulas=resolve_formulas,
                formula_cache=repo / "results" / "desktop" / "cache" / "formulae",
            )
            blockers.extend(homebrew_blockers)
            _write_json(staged / "homebrew-source-records.json", homebrew_records)

            embedded_python_sboms = []
            site_packages = runtime / "python" / "lib" / "python3.12" / "site-packages"
            for source in sorted(site_packages.glob("*.dist-info/sboms/*")):
                if not source.is_file():
                    continue
                relative = source.relative_to(site_packages)
                copied = staged / "embedded-sboms" / "python" / relative
                _copy_compliance_file(source, copied)
                embedded_python_sboms.append(
                    {
                        "path": copied.relative_to(staged).as_posix(),
                        "sha256": sha256_file(copied),
                    }
                )
            _write_json(staged / "python-embedded-sboms.json", embedded_python_sboms)

            rust_records, rust_packages, rust_relationships, missing_rust_licenses = (
                _cargo_dependency_inventory(repo, staged)
            )
            node_records, node_packages, node_relationships = _npm_dependency_inventory(
                repo, staged
            )
            spdx_packages.extend(rust_packages)
            spdx_packages.extend(node_packages)
            relationships.extend(rust_relationships)
            relationships.extend(node_relationships)
            _write_json(staged / "rust-dependencies.json", rust_records)
            _write_json(staged / "node-dependencies.json", node_records)
            _write_dependency_notices(
                staged / "RUST_NODE_THIRD_PARTY_NOTICES.txt",
                rust_records,
                node_records,
            )
            if missing_rust_licenses:
                blockers.append(
                    {
                        "code": "missing-rust-license-texts",
                        "detail": (
                            f"{len(missing_rust_licenses)} crates declare a license "
                            "but omit its text from the published crate: "
                            + ", ".join(missing_rust_licenses)
                        ),
                    }
                )

            source_archives: list[dict[str, Any]] = []
            if download_sources:
                source_records = _source_archive_records(
                    components=components,
                    homebrew=homebrew_records,
                    rust=rust_records,
                    wheel_native=wheel_native_records,
                    inputs=inputs,
                    metadata_destination=staged / "source-metadata" / "pypi",
                )
                source_archives, source_blockers = _embed_source_archives(
                    source_records,
                    cache=repo / "results" / "desktop" / "cache" / "sources",
                    destination=staged / "corresponding-source",
                )
                blockers.extend(source_blockers)
                _write_json(staged / "corresponding-source.json", source_archives)

            recipe_paths = (
                "scripts/build-macos-desktop",
                "desktop/packaging/macos-arm64.json",
                "desktop/packaging/macos-rust-license-sources.json",
                "desktop/packaging/macos-wheel-native-components.json",
                "desktop/packaging/baseline-requirements.in",
                "desktop/packaging/baseline-requirements.txt",
                "desktop/src-tauri/Cargo.lock",
                "desktop/package-lock.json",
                "web/package-lock.json",
                "pyproject.toml",
                "uv.lock",
                "src/doc_evidence/desktop_packaging.py",
            )
            for relative in recipe_paths:
                _copy_compliance_file(
                    repo / relative,
                    staged / "build-recipes" / relative,
                )

            bundle_manifest_sha = sha256_file(manifest_path)
            spdx = {
                "spdxVersion": "SPDX-2.3",
                "dataLicense": "CC0-1.0",
                "SPDXID": "SPDXRef-DOCUMENT",
                "name": f"Doc-Evidence-{__version__}-macos-arm64-preflight",
                "documentNamespace": (
                    "https://doc-evidence.local/spdx/"
                    f"{__version__}/{bundle_manifest_sha}"
                ),
                "creationInfo": {
                    "created": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "creators": [f"Tool: doc-evidence-desktop-packaging-{__version__}"],
                },
                "documentDescribes": ["SPDXRef-Package-Doc-Evidence"],
                "packages": spdx_packages,
                "relationships": relationships,
            }
            if extracted_licensing_info:
                spdx["hasExtractedLicensingInfos"] = extracted_licensing_info
            _write_json(staged / "doc-evidence.spdx.json", spdx)

            _write_json(staged / "python-native-objects.json", python_native)
            wheel_native = [item for item in python_native if item["wheel_owned"]]
            nested_native = [
                item for item in python_native if item["nested_dependency"]
            ]
            if unreconciled_nested_native:
                blockers.append(
                    {
                        "code": "unflattened-python-wheel-native-components",
                        "detail": (
                            f"{len(unreconciled_nested_native)} nested native libraries "
                            "across "
                            "Python wheels need complete component/source "
                            "reconciliation"
                        ),
                    }
                )
            if not download_sources:
                blockers.append(
                    {
                        "code": "source-archives-not-embedded",
                        "detail": (
                            "Exact source records exist, but required copyleft/MPL "
                            "source archives are not yet embedded in this output"
                        ),
                    }
                )
            if not resolve_formulas:
                blockers.append(
                    {
                        "code": "missing-exact-homebrew-formula-recipes",
                        "detail": (
                            "Homebrew SPDX source/bottle records are preserved, but "
                            "the exact formula recipe revisions are not pinned"
                        ),
                    }
                )
            report = {
                "schema_version": "doc-evidence.desktop-compliance-preflight.v1",
                "status": "passed" if not blockers else "blocked",
                "release_ready": not blockers,
                "application_tree_sha256": app_audit["tree_sha256"],
                "bundle_manifest_sha256": bundle_manifest_sha,
                "component_count": len(components),
                "file_count": len(manifest["files"]),
                "homebrew_source_record_count": len(homebrew_records),
                "embedded_python_sbom_count": len(embedded_python_sboms),
                "python_binary_compliance_count": len(binary_compliance_records),
                "python_native_object_count": len(python_native),
                "python_wheel_native_object_count": len(wheel_native),
                "python_nested_native_dependency_count": len(nested_native),
                "python_wheel_native_component_count": len(wheel_native_records),
                "python_reconciled_nested_native_dependency_count": (
                    len(nested_native) - len(unreconciled_nested_native)
                ),
                "python_unreconciled_nested_native_dependency_count": len(
                    unreconciled_nested_native
                ),
                "rust_dependency_count": len(rust_records),
                "node_dependency_count": len(node_records),
                "rust_missing_license_text_count": len(missing_rust_licenses),
                "source_archive_count": len(source_archives),
                "source_archive_bytes": sum(
                    int(item["bytes"]) for item in source_archives
                ),
                "blockers": blockers,
            }
            _write_json(staged / "compliance-preflight.json", report)
            os.replace(staged, output)
    except BaseException:
        if previous.exists() and not output.exists():
            os.replace(previous, output)
        raise
    if previous.exists():
        shutil.rmtree(previous)
    archive.unlink(missing_ok=True)
    with tarfile.open(archive, "w:gz") as stream:
        stream.add(output, arcname=output.name)
    return {
        **json.loads((output / "compliance-preflight.json").read_text()),
        "output": str(output),
        "archive": str(archive),
        "archive_bytes": archive.stat().st_size,
        "archive_sha256": sha256_file(archive),
    }


def _cli(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="doc-evidence desktop-package")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    stage = subparsers.add_parser("stage")
    stage.add_argument("--replace", action="store_true")
    sign_runtime = subparsers.add_parser("sign-runtime")
    sign_runtime.add_argument(
        "--identity",
        default=os.environ.get("APPLE_SIGNING_IDENTITY"),
        required=os.environ.get("APPLE_SIGNING_IDENTITY") is None,
    )
    subparsers.add_parser("build")
    audit = subparsers.add_parser("audit")
    audit.add_argument("--smoke", action="store_true")
    review = subparsers.add_parser("review")
    review.add_argument("--app", type=Path)
    review.add_argument("--signed", action="store_true")
    dmg = subparsers.add_parser("dmg")
    dmg.add_argument("--app", type=Path)
    dmg.add_argument("--output", type=Path)
    dmg.add_argument("--replace", action="store_true")
    review_dmg = subparsers.add_parser("review-dmg")
    review_dmg.add_argument("--dmg", type=Path)
    review_dmg.add_argument("--signed", action="store_true")
    compliance = subparsers.add_parser("compliance-preflight")
    compliance.add_argument("--app", type=Path)
    compliance.add_argument("--output", type=Path)
    compliance.add_argument("--replace", action="store_true")
    compliance.add_argument("--resolve-formulas", action="store_true")
    compliance.add_argument("--download-sources", action="store_true")
    compliance.add_argument("--signed", action="store_true")
    args = parser.parse_args(arguments)
    repository = repository_root()
    if args.operation == "stage":
        result: Any = {
            "runtime_root": str(
                stage_runtime(root=repository, replace=bool(args.replace))
            )
        }
    elif args.operation == "sign-runtime":
        result = sign_runtime_for_distribution(
            stage_root(repository),
            identity=args.identity,
            repository=repository,
        )
    elif args.operation == "build":
        result = {"app": str(build_application(root=repository))}
    elif args.operation == "audit":
        result = audit_runtime(
            stage_root(repository),
            repository=repository,
            smoke=args.smoke,
        )
    elif args.operation == "review":
        app = args.app or application_bundle_path(repository)
        result = audit_application(
            app,
            repository=repository,
            smoke=True,
            signed=bool(args.signed),
        )
    elif args.operation == "dmg":
        result = create_unsigned_dmg(
            args.app or application_bundle_path(repository),
            args.output or unsigned_dmg_path(repository),
            repository=repository,
            replace=bool(args.replace),
        )
    elif args.operation == "review-dmg":
        result = audit_dmg(
            args.dmg or unsigned_dmg_path(repository),
            repository=repository,
            signed=bool(args.signed),
        )
    else:
        result = generate_compliance_preflight(
            args.app or application_bundle_path(repository),
            args.output or compliance_root(repository),
            repository=repository,
            replace=bool(args.replace),
            resolve_formulas=bool(args.resolve_formulas),
            download_sources=bool(args.download_sources),
            signed=bool(args.signed),
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    if (
        args.operation == "compliance-preflight"
        and result.get("release_ready") is not True
    ):
        return 1
    return 0


def main() -> None:
    raise SystemExit(_cli())


if __name__ == "__main__":
    main()
