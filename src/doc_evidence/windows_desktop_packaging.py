"""Strict inputs and native-byte audits for the Windows x86_64 desktop lane."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

import jsonschema

from doc_evidence.windows_pe import PE_X86_64_MACHINE, inspect_pe

BUILD_INPUTS_SCHEMA = "doc-evidence.desktop-build-inputs.v1"
WINDOWS_PLATFORM = "windows"
WINDOWS_ARCHITECTURE = "x86_64"
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
    capture_output: bool = False,
    timeout_seconds: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(argument) for argument in arguments],
        cwd=cwd,
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
    }


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
