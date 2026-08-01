"""Authenticated loopback sidecar supervised by the macOS Tauri shell."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sys
import threading
from collections.abc import MutableMapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import uvicorn

from doc_evidence.adapters.local_desktop import LocalDesktopLibraryControl
from doc_evidence.adapters.local_libraries import LocalLibraryManager
from doc_evidence.api.app import create_app
from doc_evidence.app_home import LibraryRegistry, resolve_application_home
from doc_evidence.contracts.desktop import (
    DESKTOP_ORIGIN,
    DESKTOP_PROTOCOL_VERSION,
    MAX_DESKTOP_ERROR_BYTES,
    MAX_DESKTOP_READY_BYTES,
    DesktopControlHandshake,
    create_desktop_handshake,
    create_desktop_ready,
    require_macos_arm64,
)
from doc_evidence.errors import DocEvidenceError, RequestError

RUNTIME_TOKEN_ENV = "DOC_EVIDENCE_DESKTOP_RUNTIME_TOKEN"
HOST_CONTROL_TOKEN_ENV = "DOC_EVIDENCE_DESKTOP_HOST_CONTROL_TOKEN"
DESKTOP_HOME_ENV = "DOC_EVIDENCE_DESKTOP_APP_HOME"
_TOKEN_BYTES = 32


@dataclass(frozen=True)
class DesktopCredentials:
    runtime_token: str
    host_control_token: str

    @classmethod
    def consume(cls, environ: MutableMapping[str, str]) -> DesktopCredentials:
        runtime_token = environ.pop(RUNTIME_TOKEN_ENV, "")
        host_control_token = environ.pop(HOST_CONTROL_TOKEN_ENV, "")
        if not _valid_token(runtime_token) or not _valid_token(host_control_token):
            raise RequestError("desktop launch credentials are missing or malformed")
        if secrets.compare_digest(runtime_token, host_control_token):
            raise RequestError("desktop launch credentials must be independent")
        return cls(runtime_token, host_control_token)


def _valid_token(value: str) -> bool:
    return len(value) == _TOKEN_BYTES * 2 and all(
        character in "0123456789abcdef" for character in value
    )


def _desktop_home(environ: MutableMapping[str, str]) -> Path:
    raw = environ.pop(DESKTOP_HOME_ENV, "")
    if not raw:
        raise RequestError("desktop application-data root is missing")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise RequestError("desktop application-data root must be absolute")
    return path.resolve()


def _start_parent_watcher(server: uvicorn.Server) -> None:
    def watch() -> None:
        try:
            sys.stdin.buffer.read(1)
        finally:
            server.should_exit = True

    threading.Thread(
        target=watch,
        name="doc-evidence-desktop-parent",
        daemon=True,
    ).start()


def run(
    *,
    expected_protocol: str = DESKTOP_PROTOCOL_VERSION,
    desktop_origin: str = DESKTOP_ORIGIN,
    monitor_parent_stdin: bool = True,
    environ: MutableMapping[str, str] | None = None,
) -> int:
    values = environ if environ is not None else os.environ
    credentials = DesktopCredentials.consume(values)
    desktop_home = _desktop_home(values)
    if expected_protocol != DESKTOP_PROTOCOL_VERSION:
        raise RequestError("desktop protocol is incompatible")
    if desktop_origin != DESKTOP_ORIGIN:
        raise RequestError("desktop origin is incompatible")
    require_macos_arm64()

    home = resolve_application_home(
        desktop_host_root=desktop_home,
        environ=values,
    )
    registry = LibraryRegistry(home)
    manager = LocalLibraryManager(registry=registry)
    state = registry.load()
    selected_id = state.last_library_id or state.default_library_id
    application = manager.application(selected_id) if selected_id is not None else None
    handshake = create_desktop_handshake(
        application_home_source=home.source,
        baseline_pack=None,
    )
    control_handshake = DesktopControlHandshake(
        capabilities=[
            "register_existing_library",
            "create_managed_library",
            "add_collection",
        ]
    )
    library_control = LocalDesktopLibraryControl(
        registry=registry,
        manager=manager,
    )

    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(2048)
    port = int(listener.getsockname()[1])
    application_adapter = create_app(
        application,
        library_manager=manager,
        launch_token=credentials.runtime_token,
        allowed_origins={desktop_origin},
        desktop_handshake=handshake,
        host_control_token=credentials.host_control_token,
        desktop_control_handshake=control_handshake,
        desktop_library_control=library_control,
    )
    server = uvicorn.Server(
        uvicorn.Config(
            application_adapter,
            host="127.0.0.1",
            port=port,
            access_log=False,
            log_level="warning",
        )
    )
    ready = create_desktop_ready(handshake, port=port)
    encoded_ready = ready.model_dump_json()
    if len(encoded_ready.encode("utf-8")) + 1 > MAX_DESKTOP_READY_BYTES:
        listener.close()
        manager.shutdown()
        raise RequestError("desktop ready record exceeds its size bound")
    print(encoded_ready, flush=True)
    if monitor_parent_stdin:
        _start_parent_watcher(server)
    try:
        server.run(sockets=[listener])
    finally:
        listener.close()
        manager.shutdown()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="doc-evidence desktop-sidecar")
    parser.add_argument(
        "--expected-protocol",
        default=DESKTOP_PROTOCOL_VERSION,
    )
    parser.add_argument(
        "--desktop-origin",
        default=DESKTOP_ORIGIN,
    )
    parser.add_argument(
        "--no-parent-stdin",
        action="store_true",
        help="keep serving when the supervising process closes standard input",
    )
    return parser


def run_cli(arguments: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(arguments)
    return run(
        expected_protocol=args.expected_protocol,
        desktop_origin=args.desktop_origin,
        monitor_parent_stdin=not args.no_parent_stdin,
    )


def _bounded_error(error: BaseException) -> str:
    record = {
        "schema_version": "doc-evidence.desktop-error.v1",
        "error_type": type(error).__name__,
        "error": str(error),
    }
    encoded = json.dumps(record, ensure_ascii=True, sort_keys=True)
    if len(encoded.encode("utf-8")) <= MAX_DESKTOP_ERROR_BYTES:
        return encoded
    return json.dumps(
        {
            "schema_version": "doc-evidence.desktop-error.v1",
            "error_type": "DesktopStartupError",
            "error": "desktop startup failure exceeded its diagnostic bound",
        },
        sort_keys=True,
    )


def main() -> None:
    try:
        raise SystemExit(run_cli())
    except (DocEvidenceError, OSError, RuntimeError, ValueError) as error:
        print(_bounded_error(error), file=sys.stderr, flush=True)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
