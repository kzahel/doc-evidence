"""Reproducible staging and audit for the local macOS desktop application."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import plistlib
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
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import jsonschema

from doc_evidence import __version__
from doc_evidence.contracts.desktop import DESKTOP_ORIGIN, DESKTOP_PROTOCOL_VERSION

BUNDLE_MANIFEST_SCHEMA = "doc-evidence.desktop-bundle-manifest.v1"
RUNTIME_MANIFEST_SCHEMA = "doc-evidence.desktop-runtime-manifest.v1"
BUILD_INPUTS_SCHEMA = "doc-evidence.desktop-build-inputs.v1"
PRODUCT_NAME = "Doc Evidence"
PRODUCT_IDENTIFIER = "io.github.kzahel.doc-evidence"
SYSTEM_LOAD_PREFIXES = ("/System/Library/", "/usr/lib/")
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
) -> None:
    python_root = runtime_root / "python"
    packages = _distribution_inventory(python_root)
    if not packages:
        raise RuntimeError("staged Python package inventory is empty")
    forbidden = {
        str(name).lower().replace("_", "-")
        for name in inputs["forbidden_python_distributions"]
    }
    for package in packages:
        normalized = str(package["name"]).lower().replace("_", "-")
        if normalized in forbidden:
            raise RuntimeError(
                f"development distribution entered desktop runtime: {package['name']}"
            )
        if not package["files"] or not package["license_files"]:
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
    file_owners: dict[str, str] = {}
    for package in packages:
        component_id = _component_id(str(package["name"]))
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
                "license_files": [
                    f"python/{path}" for path in package["license_files"]
                ],
                "bundled_paths": [f"python/{path}" for path in package["files"]],
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
            "dependency_lock": "uv.lock",
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
        "extractor_packs": [],
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
        audit_runtime(target, repository=repository, smoke=False)
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
            _prune_runtime(python_root)
            staged = temporary / "desktop-runtime"
            staged.mkdir()
            os.replace(python_root, staged / "python")
            _write_manifests(repository, staged, archive, inputs)
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


def _validate_bundle_manifest(runtime_root: Path, repository: Path) -> dict[str, Any]:
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


def smoke_sidecar(runtime_root: Path) -> dict[str, Any]:
    runtime_token = secrets.token_hex(32)
    control_token = secrets.token_hex(32)
    with tempfile.TemporaryDirectory(prefix="doc-evidence-desktop-smoke-") as raw:
        working = Path(raw)
        environment = {
            "DOC_EVIDENCE_DESKTOP_RUNTIME_TOKEN": runtime_token,
            "DOC_EVIDENCE_DESKTOP_HOST_CONTROL_TOKEN": control_token,
            "DOC_EVIDENCE_DESKTOP_APP_HOME": str(working / "app-home"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONUTF8": "1",
            "LANG": "en_US.UTF-8",
            "TMPDIR": str(working / "tmp"),
        }
        (working / "tmp").mkdir()
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
) -> dict[str, Any]:
    root = runtime_root.resolve()
    repo = (repository or repository_root()).resolve()
    if not root.is_dir():
        raise RuntimeError(f"desktop runtime does not exist: {root}")
    manifest = _validate_bundle_manifest(root, repo)
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
