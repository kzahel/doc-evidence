"""Deterministic copied-out desktop workflow acceptance.

Run this module with the packaged interpreter. It drives the same authenticated
sidecar and trusted host-control boundary as Tauri while keeping source paths
out of the ordinary runtime API.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import queue
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from doc_evidence.platform_paths import extended_length_path

DESKTOP_PROTOCOL = "doc-evidence.desktop.v1"
Platform = Literal["macos", "windows"]
TERMINAL_JOB_STATES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})
MAX_RESPONSE_BYTES = 32 * 1024 * 1024


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_hashes(root: Path) -> dict[str, str]:
    filesystem_root = extended_length_path(root)
    return {
        path.relative_to(filesystem_root).as_posix(): _sha256(path)
        for path in sorted(filesystem_root.rglob("*"))
        if path.is_file()
    }


def _collection_hashes(collections: dict[str, Path]) -> dict[str, str]:
    return {
        f"{name}/{relative}": digest
        for name, root in collections.items()
        for relative, digest in _source_hashes(root).items()
    }


def _write_text_pdf(path: Path, text: str) -> None:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = f"BT /F1 16 Tf 72 700 Td ({escaped}) Tj ET\n".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(content)).encode("ascii")
        + b" >>\nstream\n"
        + content
        + b"endstream",
        b"<< /Producer (doc-evidence packaged acceptance) >>",
    ]
    output = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, value in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{number} 0 obj\n".encode("ascii"))
        output.extend(value)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 6 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode("ascii")
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(output)


def _write_image_pdf(path: Path) -> None:
    image_module = importlib.import_module("PIL.Image")
    draw_module = importlib.import_module("PIL.ImageDraw")
    font_module = importlib.import_module("PIL.ImageFont")

    image = image_module.new("RGB", (1800, 1100), "white")
    draw = draw_module.Draw(image)
    font = font_module.load_default(size=72)
    for index, line in enumerate(
        [
            "DOC EVIDENCE 12345",
            "LOCAL DOCUMENT REVIEW",
            "SOURCE PROVENANCE RECORD",
            "EXTRACTED TEXT VALIDATION",
        ]
    ):
        draw.text((80, 100 + index * 210), line, fill="black", font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PDF", resolution=200.0)


def _long_fixture_path(root: Path, *, enabled: bool) -> Path:
    current = root
    if enabled:
        index = 0
        while len(str(current / "image scan 12345.pdf")) <= 280:
            current /= f"nested evidence segment {index:02d}"
            index += 1
    return current / "image scan 12345.pdf"


def _runtime_environment(
    runtime_root: Path,
    writable_root: Path,
    *,
    platform_name: Platform,
    runtime_token: str,
    control_token: str,
) -> dict[str, str]:
    pack = runtime_root / "baseline-pack"
    cache = writable_root / "cache"
    temporary = writable_root / "tmp"
    cache.mkdir(parents=True, exist_ok=True)
    temporary.mkdir(parents=True, exist_ok=True)
    if platform_name == "macos":
        path = os.pathsep.join(
            [
                str(pack / "bin"),
                str(runtime_root / "python" / "bin"),
                "/usr/bin",
                "/bin",
            ]
        )
        inherited = {
            name: os.environ[name]
            for name in ("LANG", "LC_ALL", "TMPDIR")
            if os.environ.get(name)
        }
        inherited.setdefault("TMPDIR", str(temporary))
        architecture = "arm64"
    else:
        system_root = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
        if not system_root:
            raise RuntimeError("Windows system root is unavailable")
        user_home = writable_root / "user-home"
        user_home.mkdir(parents=True, exist_ok=True)
        path = os.pathsep.join(
            [
                str(pack / "bin"),
                str(runtime_root / "python"),
                str(Path(system_root) / "System32"),
                system_root,
            ]
        )
        inherited = {
            "SystemRoot": system_root,
            "WINDIR": system_root,
            "TEMP": str(temporary),
            "TMP": str(temporary),
            "USERPROFILE": str(user_home),
        }
        architecture = "x86_64"
    environment = {
        **inherited,
        "DOC_EVIDENCE_DESKTOP_RUNTIME_TOKEN": runtime_token,
        "DOC_EVIDENCE_DESKTOP_HOST_CONTROL_TOKEN": control_token,
        "DOC_EVIDENCE_DESKTOP_APP_HOME": str(writable_root / "app-home"),
        "DOC_EVIDENCE_DESKTOP_PLATFORM": platform_name,
        "DOC_EVIDENCE_DESKTOP_ARCHITECTURE": architecture,
        "DOC_EVIDENCE_BASELINE_PACK": str(pack),
        "PATH": path,
        "TESSDATA_PREFIX": str(pack / "tessdata"),
        "FONTCONFIG_FILE": str(pack / "etc" / "fonts" / "fonts.conf"),
        "FONTCONFIG_PATH": str(pack / "etc" / "fonts"),
        "XDG_CACHE_HOME": str(cache),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
    }
    return environment


def _readline_with_timeout(stream: Any, timeout: float) -> str:
    result: queue.Queue[str | BaseException] = queue.Queue(maxsize=1)

    def read() -> None:
        try:
            result.put(stream.readline())
        except BaseException as error:  # noqa: BLE001 - delivered to caller
            result.put(error)

    threading.Thread(target=read, name="desktop-ready-reader", daemon=True).start()
    try:
        value = result.get(timeout=timeout)
    except queue.Empty as error:
        raise RuntimeError("desktop sidecar ready record timed out") from error
    if isinstance(value, BaseException):
        raise TypeError("desktop sidecar ready record was unreadable") from value
    if not value:
        raise RuntimeError("desktop sidecar exited before its ready record")
    return value


@dataclass
class Sidecar:
    process: subprocess.Popen[str]
    base_url: str
    runtime_token: str
    control_token: str
    origin: str
    ready_line: str

    @classmethod
    def start(
        cls,
        runtime_root: Path,
        writable_root: Path,
        *,
        platform_name: Platform,
    ) -> Sidecar:
        runtime_token = secrets.token_hex(32)
        control_token = secrets.token_hex(32)
        origin = (
            "tauri://localhost"
            if platform_name == "macos"
            else "http://tauri.localhost"
        )
        environment = _runtime_environment(
            runtime_root,
            writable_root,
            platform_name=platform_name,
            runtime_token=runtime_token,
            control_token=control_token,
        )
        process = subprocess.Popen(
            [
                sys.executable,
                "-I",
                "-B",
                "-m",
                "doc_evidence.desktop_sidecar",
                "--expected-protocol",
                DESKTOP_PROTOCOL,
                "--desktop-origin",
                origin,
            ],
            cwd=runtime_root,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        if process.stdin is None or process.stdout is None or process.stderr is None:
            process.kill()
            raise RuntimeError("desktop sidecar pipes are unavailable")
        try:
            ready_line = _readline_with_timeout(process.stdout, 30)
            if len(ready_line.encode("utf-8")) > 16_384:
                raise RuntimeError("desktop sidecar ready record exceeded its bound")
            ready = json.loads(ready_line)
            if (
                ready.get("protocol_version") != DESKTOP_PROTOCOL
                or ready.get("platform") != platform_name
                or not isinstance(ready.get("port"), int)
                or ready["port"] < 1
            ):
                raise RuntimeError("desktop sidecar ready record is incompatible")
            return cls(
                process=process,
                base_url=f"http://127.0.0.1:{ready['port']}",
                runtime_token=runtime_token,
                control_token=control_token,
                origin=origin,
                ready_line=ready_line,
            )
        except Exception:
            process.kill()
            process.wait(timeout=5)
            raise

    def close(self, *, forced: bool = False) -> None:
        if self.process.poll() is None:
            if forced:
                self.process.kill()
            else:
                assert self.process.stdin is not None
                self.process.stdin.close()
        try:
            exit_code = self.process.wait(timeout=30)
        except subprocess.TimeoutExpired as error:
            self.process.kill()
            self.process.wait(timeout=5)
            raise RuntimeError(
                "desktop sidecar did not stop within its bound"
            ) from error
        assert self.process.stdout is not None
        assert self.process.stderr is not None
        stdout = self.process.stdout.read()
        stderr = self.process.stderr.read()
        if (
            self.runtime_token in self.ready_line + stdout + stderr
            or self.control_token in (self.ready_line + stdout + stderr)
        ):
            raise RuntimeError("desktop sidecar leaked a launch credential")
        if not forced and exit_code != 0:
            raise RuntimeError("desktop sidecar did not stop cleanly")

    def json_request(
        self,
        path: str,
        *,
        method: str = "GET",
        body: dict[str, Any] | None = None,
        control: bool = False,
    ) -> dict[str, Any]:
        token = self.control_token if control else self.runtime_token
        headers = {"Authorization": f"Bearer {token}"}
        if not control:
            headers["Origin"] = self.origin
        encoded = None
        if body is not None:
            encoded = json.dumps(body, ensure_ascii=True).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path,
            data=encoded,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                payload = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            detail = error.read(8_192).decode("utf-8", errors="replace")
            raise RuntimeError(
                f"desktop request {path} failed with HTTP {error.code}: {detail}"
            ) from error
        if len(payload) > MAX_RESPONSE_BYTES:
            raise RuntimeError("desktop JSON response exceeded its bound")
        value = json.loads(payload)
        if not isinstance(value, dict):
            raise TypeError("desktop JSON response was not an object")
        return value

    def bytes_request(self, path: str) -> bytes:
        request = urllib.request.Request(
            self.base_url + path,
            headers={
                "Authorization": f"Bearer {self.runtime_token}",
                "Origin": self.origin,
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise RuntimeError("desktop binary response exceeded its bound")
        return payload


def _wait_for_job(
    sidecar: Sidecar, library_id: str, job_id: str, timeout: float
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    encoded_library = urllib.parse.quote(library_id, safe="")
    encoded_job = urllib.parse.quote(job_id, safe="")
    while time.monotonic() < deadline:
        detail = sidecar.json_request(
            f"/api/v1/libraries/{encoded_library}/jobs/{encoded_job}"
        )
        job = detail.get("job")
        if isinstance(job, dict) and job.get("state") in TERMINAL_JOB_STATES:
            if job["state"] != "succeeded":
                raise RuntimeError(
                    f"desktop job {job_id} ended as {job['state']}: "
                    f"{job.get('error_summary') or job.get('outcome')}"
                )
            return detail
        time.sleep(0.2)
    raise RuntimeError(f"desktop job {job_id} did not finish within its bound")


def _enqueue_inventory(
    sidecar: Sidecar, library_id: str, *, full: bool, timeout: float
) -> dict[str, Any]:
    encoded_library = urllib.parse.quote(library_id, safe="")
    created = sidecar.json_request(
        f"/api/v1/libraries/{encoded_library}/jobs/inventories",
        method="POST",
        body={"full_hash_verification": full},
    )
    job = created.get("job")
    if not isinstance(job, dict) or not isinstance(job.get("job_id"), str):
        raise TypeError("desktop inventory response is invalid")
    return _wait_for_job(sidecar, library_id, job["job_id"], timeout)


def _workspace(sidecar: Sidecar, library_id: str) -> dict[str, Any]:
    encoded = urllib.parse.quote(library_id, safe="")
    return sidecar.json_request(f"/api/v1/libraries/{encoded}/workspace")


def _assert_persisted(
    sidecar: Sidecar, library_id: str, *, document_count: int
) -> None:
    workspace = _workspace(sidecar, library_id)
    if workspace.get("document_count") != document_count:
        raise RuntimeError("desktop restart lost inventory membership")
    encoded = urllib.parse.quote(library_id, safe="")
    search = sidecar.json_request(
        f"/api/v1/libraries/{encoded}/search?"
        + urllib.parse.urlencode({"query": "12345", "mode": "literal", "limit": 20})
    )
    if not search.get("items"):
        raise RuntimeError("desktop restart lost searchable OCR text")


def run_acceptance(
    runtime_root: Path,
    *,
    platform_name: Platform,
    timeout_seconds: float,
) -> dict[str, Any]:
    runtime_root = runtime_root.resolve()
    manifest = runtime_root / "bundle-manifest.json"
    pack_manifest = runtime_root / "baseline-pack" / "pack-manifest.json"
    if not manifest.is_file() or not pack_manifest.is_file():
        raise RuntimeError("desktop runtime manifests are missing")
    manifest_value = json.loads(manifest.read_text(encoding="utf-8"))
    if manifest_value.get("platform") != platform_name:
        raise RuntimeError("desktop runtime platform disagrees with acceptance target")
    expected_architecture = "arm64" if platform_name == "macos" else "x86_64"
    if manifest_value.get("architecture") != expected_architecture:
        raise RuntimeError(
            "desktop runtime architecture disagrees with acceptance target"
        )
    executable = Path(sys.executable).resolve()
    if not executable.is_relative_to(runtime_root):
        raise RuntimeError("acceptance must run with the packaged Python interpreter")

    with tempfile.TemporaryDirectory(prefix="doc-evidence-acceptance-") as raw:
        working = Path(raw)
        collection_one = working / "Synthetic ünicode collection"
        image_pdf = _long_fixture_path(
            collection_one,
            enabled=platform_name == "windows",
        )
        _write_image_pdf(extended_length_path(image_pdf))
        collection_two = working / "Second collection with spaces"
        text_pdf = collection_two / "native evidence.pdf"
        _write_text_pdf(text_pdf, "SECOND COLLECTION ACCEPTANCE 67890")
        collections = {
            "primary": collection_one,
            "secondary": collection_two,
        }
        source_hashes = _collection_hashes(collections)

        first = Sidecar.start(
            runtime_root,
            working,
            platform_name=platform_name,
        )
        try:
            handshake = first.json_request("/api/v1/desktop/handshake")
            if handshake.get("protocol_version") != DESKTOP_PROTOCOL:
                raise RuntimeError("desktop authenticated handshake is incompatible")
            created = first.json_request(
                "/desktop-control/v1/libraries/create-managed",
                method="POST",
                body={
                    "source_path": str(collection_one),
                    "name": "Packaged Acceptance",
                },
                control=True,
            )
            library_id = created.get("library_id")
            if not isinstance(library_id, str) or created.get("status") != "ready":
                raise RuntimeError("desktop managed-library creation failed")
            inventory = _enqueue_inventory(
                first,
                library_id,
                full=False,
                timeout=timeout_seconds,
            )
            encoded_library = urllib.parse.quote(library_id, safe="")
            documents = first.json_request(
                f"/api/v1/libraries/{encoded_library}/documents?offset=0&limit=40"
            )
            items = documents.get("items")
            if not isinstance(items, list) or len(items) != 1:
                raise RuntimeError(
                    "desktop first inventory did not expose one document"
                )
            document = items[0]
            if not isinstance(document, dict) or not isinstance(
                document.get("document_id"), str
            ):
                raise TypeError("desktop document contract is invalid")
            document_id = document["document_id"]
            encoded_document = urllib.parse.quote(document_id, safe="")
            rendered = first.bytes_request(
                f"/api/v1/libraries/{encoded_library}/documents/"
                f"{encoded_document}/pages/1/render"
            )
            if not rendered.startswith(b"\x89PNG\r\n\x1a\n"):
                raise RuntimeError("desktop page render is not a PNG")
            capabilities = first.json_request(
                f"/api/v1/libraries/{encoded_library}/extractors?"
                + urllib.parse.urlencode({"document_id": document_id})
            )
            ocr = next(
                (
                    item
                    for item in capabilities.get("items", [])
                    if isinstance(item, dict)
                    and item.get("extractor_id") == "ocrmypdf-tesseract"
                ),
                None,
            )
            if not isinstance(ocr, dict) or not ocr.get("available"):
                raise RuntimeError("desktop OCR extractor is unavailable")
            extraction = first.json_request(
                f"/api/v1/libraries/{encoded_library}/jobs/extractions",
                method="POST",
                body={
                    "document_id": document_id,
                    "extractor_id": "ocrmypdf-tesseract",
                    "settings": {"languages": ["eng", "deu"]},
                    "execution_mode": "reuse_or_execute",
                },
            )
            extraction_job = extraction.get("job")
            if not isinstance(extraction_job, dict) or not isinstance(
                extraction_job.get("job_id"), str
            ):
                raise TypeError("desktop extraction response is invalid")
            extraction_detail = _wait_for_job(
                first,
                library_id,
                extraction_job["job_id"],
                timeout_seconds,
            )
            search = first.json_request(
                f"/api/v1/libraries/{encoded_library}/search?"
                + urllib.parse.urlencode(
                    {"query": "12345", "mode": "literal", "limit": 20}
                )
            )
            if not search.get("items"):
                raise RuntimeError("desktop OCR text was not searchable")
            groups = first.json_request(
                f"/api/v1/libraries/{encoded_library}/documents/"
                f"{encoded_document}/pages/1/groups"
            )
            if not any(
                isinstance(run, dict)
                and run.get("extractor_id") == "ocrmypdf-tesseract"
                for group in groups.get("groups", [])
                if isinstance(group, dict)
                for run in group.get("runs", [])
            ):
                raise RuntimeError("desktop OCR representation was not published")

            added = first.json_request(
                "/desktop-control/v1/libraries/add-collection",
                method="POST",
                body={
                    "library_id": library_id,
                    "source_path": str(collection_two),
                    "confirm_parent_replacement": False,
                },
                control=True,
            )
            if not added.get("changed"):
                raise RuntimeError("desktop sibling collection was not added")
            second_inventory = _enqueue_inventory(
                first,
                library_id,
                full=False,
                timeout=timeout_seconds,
            )
            workspace = _workspace(first, library_id)
            if workspace.get("document_count") != 2:
                raise RuntimeError(
                    "desktop expanded inventory did not expose two documents"
                )
            jobs = first.json_request(
                f"/api/v1/libraries/{encoded_library}/jobs?offset=0&limit=50"
            )
            kinds = {
                item.get("request_kind")
                for item in jobs.get("items", [])
                if isinstance(item, dict)
            }
            if kinds != {"inventory", "extraction"}:
                raise RuntimeError("desktop activity omitted a workflow job kind")
        finally:
            first.close()

        second = Sidecar.start(
            runtime_root,
            working,
            platform_name=platform_name,
        )
        try:
            _assert_persisted(second, library_id, document_count=2)
        finally:
            second.close(forced=True)

        third = Sidecar.start(
            runtime_root,
            working,
            platform_name=platform_name,
        )
        try:
            _assert_persisted(third, library_id, document_count=2)
        finally:
            third.close()

        if _collection_hashes(collections) != source_hashes:
            raise RuntimeError("desktop workflow mutated a synthetic source collection")
        return {
            "schema_version": "doc-evidence.desktop-acceptance.v1",
            "status": "passed",
            "platform": platform_name,
            "architecture": expected_architecture,
            "application_version": manifest_value.get("version"),
            "bundle_manifest_sha256": _sha256(manifest),
            "pack_manifest_sha256": _sha256(pack_manifest),
            "source_file_count": len(source_hashes),
            "document_count": 2,
            "inventory_outcomes": [
                inventory["job"].get("outcome"),
                second_inventory["job"].get("outcome"),
            ],
            "extraction_outcome": extraction_detail["job"].get("outcome"),
            "search_text": "12345",
            "page_render": "png",
            "normal_restart": True,
            "forced_sidecar_restart": True,
            "source_hashes_unchanged": True,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m doc_evidence.desktop_acceptance",
        description="Run the deterministic packaged desktop workflow.",
    )
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--platform", choices=("macos", "windows"), required=True)
    parser.add_argument("--timeout-seconds", type=float, default=900)
    return parser


def run_cli(arguments: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(arguments)
    if not 60 <= args.timeout_seconds <= 3_600:
        raise SystemExit("--timeout-seconds must be between 60 and 3600")
    result = run_acceptance(
        args.runtime_root,
        platform_name=args.platform,
        timeout_seconds=args.timeout_seconds,
    )
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
