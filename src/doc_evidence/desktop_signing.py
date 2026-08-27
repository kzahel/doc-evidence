"""Refresh signed desktop runtime manifests after native signatures change bytes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def refresh_signed_runtime_manifests(runtime_root: Path) -> dict[str, str]:
    """Rebind pack and bundle inventories to already-signed native files.

    Native signing intentionally changes executable bytes. The staged manifests
    remain fail-closed by refreshing them only after signing and before the
    outer application bundle is sealed.
    """

    runtime = runtime_root.resolve()
    pack = runtime / "baseline-pack"
    pack_manifest_path = pack / "pack-manifest.json"
    bundle_manifest_path = runtime / "bundle-manifest.json"
    runtime_manifest_path = runtime / "runtime-manifest.json"
    pack_manifest = json.loads(pack_manifest_path.read_text(encoding="utf-8"))
    for item in pack_manifest["tools"]:
        item["sha256"] = sha256_file(pack / item["executable"])
    for section in ("language_data", "support_files", "native_libraries"):
        for item in pack_manifest[section]:
            item["sha256"] = sha256_file(pack / item["path"])
    _write_json(pack_manifest_path, pack_manifest)

    bundle_manifest = json.loads(bundle_manifest_path.read_text(encoding="utf-8"))
    owners = {item["path"]: item["component_id"] for item in bundle_manifest["files"]}
    actual_paths = sorted(
        path
        for path in runtime.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and path.name != "bundle-manifest.json"
    )
    actual_names = {path.relative_to(runtime).as_posix() for path in actual_paths}
    if actual_names != set(owners):
        raise RuntimeError("signed runtime file set changed before manifest refresh")
    bundle_manifest["runtime_manifest_sha256"] = sha256_file(runtime_manifest_path)
    bundle_manifest["extractor_packs"] = [
        {
            "pack_id": pack_manifest["pack_id"],
            "version": pack_manifest["version"],
            "manifest_sha256": sha256_file(pack_manifest_path),
        }
    ]
    bundle_manifest["files"] = [
        {
            "path": path.relative_to(runtime).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "component_id": owners[path.relative_to(runtime).as_posix()],
        }
        for path in actual_paths
    ]
    _write_json(bundle_manifest_path, bundle_manifest)
    return {
        "pack_manifest_sha256": sha256_file(pack_manifest_path),
        "bundle_manifest_sha256": sha256_file(bundle_manifest_path),
    }
