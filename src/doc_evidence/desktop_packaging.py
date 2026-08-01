"""Reproducible staging and audit for the local macOS desktop application."""

from __future__ import annotations

import argparse
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
import subprocess
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import jsonschema

from doc_evidence import __version__
from doc_evidence.contracts.desktop import DESKTOP_ORIGIN, DESKTOP_PROTOCOL_VERSION
from doc_evidence.desktop_pack import BASELINE_PACK_ENV, load_baseline_pack

BUNDLE_MANIFEST_SCHEMA = "doc-evidence.desktop-bundle-manifest.v1"
RUNTIME_MANIFEST_SCHEMA = "doc-evidence.desktop-runtime-manifest.v1"
BUILD_INPUTS_SCHEMA = "doc-evidence.desktop-build-inputs.v1"
PRODUCT_NAME = "Doc Evidence"
PRODUCT_IDENTIFIER = "io.github.kzahel.doc-evidence"
SYSTEM_LOAD_PREFIXES = ("/System/Library/", "/usr/lib/")
HOMEBREW_BUILD_PREFIX = b"/opt/homebrew"
NEUTRAL_BUILD_PREFIX = b"/__doc_evid__"
MAX_READY_BYTES = 64 * 1024
_LICENSE_NAMES = ("license", "copying", "notice")


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def build_inputs_path(root: Path | None = None) -> Path:
    base = root or repository_root()
    return base / "desktop" / "packaging" / "macos-arm64.json"


def stage_root(root: Path | None = None) -> Path:
    base = root or repository_root()
    return base / "desktop" / "src-tauri" / "resources" / "desktop-runtime"


def cache_root(root: Path | None = None) -> Path:
    base = root or repository_root()
    return base / "results" / "desktop" / "cache"


def _run(
    arguments: Sequence[str | Path],
    *,
    cwd: Path | None = None,
    environment: Mapping[str, str] | None = None,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(argument) for argument in arguments],
        cwd=cwd,
        env=None if environment is None else dict(environment),
        check=True,
        text=True,
        capture_output=capture_output,
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
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
            root,
        ],
        cwd=root,
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
    (site_packages / "doc_evidence" / "desktop_packaging.py").unlink(missing_ok=True)
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
    return _locked_requirements(requirements)


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
            raise RuntimeError(f"baseline tool version changed: {name}")
        source = Path(record["prefix"]) / "bin" / name
        if not source.is_file() or sha256_file(source) != raw["input_sha256"]:
            raise RuntimeError(f"baseline tool input identity changed: {name}")
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
    components.append(
        {
            "component_id": "tesseract-language-data",
            "name": "Tesseract language data",
            "version": "4.1.0/5.5.3",
            "license_concluded": "Apache-2.0",
            "source_url": ("https://github.com/tesseract-ocr/tessdata/tree/4.1.0"),
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
    tesseract_component = next(
        item for item in components if item["component_id"] == "homebrew-tesseract"
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
        lowered = Path(item).name.lower()
        if any(name in lowered for name in ("license", "copying", "notice")):
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
    }
    package_license_files = baseline_metadata.get("package_license_files")
    if not isinstance(package_license_files, dict):
        raise TypeError("baseline Python license inventory is invalid")
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
        conclusion = _license_conclusion(package)
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
                "license_concluded": _license_conclusion(package),
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
                    if path.endswith("doc_evidence-0.4.0.dist-info/licenses/LICENSE")
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
    if manifest["frontend_sha256"] != sha256_tree(repository / "web" / "dist"):
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
            "pdfinfo": "26.03.0",
            "pdftotext": "26.03.0",
            "pdftoppm": "26.03.0",
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
                DESKTOP_ORIGIN,
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
                url, headers={"Origin": DESKTOP_ORIGIN}
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
                    "Origin": DESKTOP_ORIGIN,
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
) -> dict[str, Any]:
    root = runtime_root.resolve()
    repo = (repository or repository_root()).resolve()
    if not root.is_dir():
        raise RuntimeError(f"desktop runtime does not exist: {root}")
    manifest = _validate_bundle_manifest(
        root,
        repo,
        require_baseline=require_baseline,
    )
    packages = _distribution_inventory(root / "python")
    forbidden = {
        str(name).lower().replace("_", "-")
        for name in _load_inputs(repo)["forbidden_python_distributions"]
    }
    included = {str(package["name"]).lower().replace("_", "-") for package in packages}
    unexpected = sorted(forbidden & included)
    if unexpected:
        raise RuntimeError(
            f"development packages entered desktop runtime: {unexpected}"
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


def audit_application(
    app: Path,
    *,
    repository: Path | None = None,
    smoke: bool = True,
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
    forbidden_hits = _files_containing(
        bundle,
        [str(repo), str(Path.home()), "/opt/homebrew"],
    )
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
    if signature.returncode == 0:
        raise RuntimeError("unsigned desktop proof unexpectedly has a strict signature")
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
            "status": "expected-unsigned-local-proof",
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
            f"--remap-path-prefix={Path.home() / '.cargo'}=/cargo",
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
    app = (
        repository
        / "desktop"
        / "src-tauri"
        / "target"
        / "release"
        / "bundle"
        / "macos"
        / f"{PRODUCT_NAME}.app"
    )
    if not app.is_dir():
        raise RuntimeError("Tauri did not produce the expected application bundle")
    return app


def _cli(arguments: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="doc-evidence desktop-package")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    stage = subparsers.add_parser("stage")
    stage.add_argument("--replace", action="store_true")
    subparsers.add_parser("build")
    audit = subparsers.add_parser("audit")
    audit.add_argument("--smoke", action="store_true")
    review = subparsers.add_parser("review")
    review.add_argument("--app", type=Path)
    args = parser.parse_args(arguments)
    repository = repository_root()
    if args.operation == "stage":
        result: Any = {
            "runtime_root": str(
                stage_runtime(root=repository, replace=bool(args.replace))
            )
        }
    elif args.operation == "build":
        result = {"app": str(build_application(root=repository))}
    elif args.operation == "audit":
        result = audit_runtime(
            stage_root(repository),
            repository=repository,
            smoke=args.smoke,
        )
    else:
        app = args.app or (
            repository
            / "desktop"
            / "src-tauri"
            / "target"
            / "release"
            / "bundle"
            / "macos"
            / f"{PRODUCT_NAME}.app"
        )
        result = audit_application(app, repository=repository, smoke=True)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def main() -> None:
    raise SystemExit(_cli())


if __name__ == "__main__":
    main()
