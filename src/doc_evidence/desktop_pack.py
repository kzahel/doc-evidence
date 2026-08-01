"""Runtime validation for the bundled baseline extractor pack."""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from doc_evidence.contracts.desktop import DesktopPackIdentity
from doc_evidence.errors import RequestError
from doc_evidence.util import sha256_file

BASELINE_PACK_ENV = "DOC_EVIDENCE_BASELINE_PACK"
MAX_PACK_MANIFEST_BYTES = 8 * 1024 * 1024


def _pack_schema() -> dict[str, Any]:
    value = resources.files("doc_evidence").joinpath(
        "schema_files/extractor-pack-manifest.schema.json"
    )
    return json.loads(value.read_text(encoding="utf-8"))


def _contained_file(root: Path, relative: str) -> Path:
    path = root / relative
    resolved = path.resolve()
    if not path.is_file() or (resolved != root and root not in resolved.parents):
        raise RequestError(
            f"baseline pack file is missing or escapes its root: {relative}"
        )
    return path


def load_baseline_pack(root: Path) -> DesktopPackIdentity:
    pack = root.resolve()
    manifest_path = pack / "pack-manifest.json"
    if not manifest_path.is_file():
        raise RequestError("baseline pack manifest is missing")
    if manifest_path.stat().st_size > MAX_PACK_MANIFEST_BYTES:
        raise RequestError("baseline pack manifest exceeds its size bound")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RequestError("baseline pack manifest is unreadable") from error
    errors = sorted(
        Draft202012Validator(_pack_schema()).iter_errors(manifest),
        key=lambda item: list(item.absolute_path),
    )
    if errors:
        raise RequestError(f"baseline pack manifest is invalid: {errors[0].message}")

    seen: set[str] = set()
    tools = {item["tool_id"]: item for item in manifest["tools"]}
    expected_tools = {"ocrmypdf", "pdfinfo", "pdftoppm", "pdftotext", "tesseract"}
    if set(tools) != expected_tools:
        raise RequestError("baseline pack tool set is incompatible")
    languages = {item["language"] for item in manifest["language_data"]}
    if languages != {"eng", "deu", "osd"}:
        raise RequestError("baseline pack language set is incompatible")
    for group, path_key in (
        (manifest["tools"], "executable"),
        (manifest["language_data"], "path"),
        (manifest["support_files"], "path"),
        (manifest["native_libraries"], "path"),
    ):
        for item in group:
            relative = str(item[path_key])
            if relative in seen:
                raise RequestError(f"baseline pack path is repeated: {relative}")
            seen.add(relative)
            path = _contained_file(pack, relative)
            if sha256_file(path) != item["sha256"]:
                raise RequestError(f"baseline pack file identity changed: {relative}")
    return DesktopPackIdentity(
        pack_id=manifest["pack_id"],
        version=manifest["version"],
        manifest_sha256=sha256_file(manifest_path),
    )
