"""Strict inputs and native-byte audits for the Windows x86_64 desktop lane."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from doc_evidence.windows_pe import PE_X86_64_MACHINE, inspect_pe

BUILD_INPUTS_SCHEMA = "doc-evidence.desktop-build-inputs.v1"
WINDOWS_PLATFORM = "windows"
WINDOWS_ARCHITECTURE = "x86_64"
EXPECTED_NATIVE_COMPONENTS = {"poppler", "tesseract"}
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        _validate_source_archives(raw.get("source_archives"), f"Windows {component_id}")

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
