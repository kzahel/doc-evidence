"""Versioned contracts for the thin macOS desktop host boundary."""

from __future__ import annotations

import platform
import sys
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from doc_evidence import __version__
from doc_evidence.app_home import AppHomeSource
from doc_evidence.errors import RequestError

DESKTOP_PROTOCOL_VERSION = "doc-evidence.desktop.v1"
DESKTOP_READY_SCHEMA_VERSION = "doc-evidence.desktop-ready.v1"
DESKTOP_HANDSHAKE_SCHEMA_VERSION = "doc-evidence.desktop-handshake.v1"
DESKTOP_CONTROL_SCHEMA_VERSION = "doc-evidence.desktop-control.v1"
DESKTOP_ORIGIN = "tauri://localhost"
MAX_DESKTOP_READY_BYTES = 64 * 1024
MAX_DESKTOP_ERROR_BYTES = 8 * 1024


class DesktopContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DesktopPackIdentity(DesktopContractModel):
    pack_id: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DesktopReady(DesktopContractModel):
    schema_version: Literal["doc-evidence.desktop-ready.v1"] = (
        DESKTOP_READY_SCHEMA_VERSION
    )
    protocol_version: Literal["doc-evidence.desktop.v1"] = DESKTOP_PROTOCOL_VERSION
    application_version: str = Field(min_length=1, max_length=100)
    api_version: Literal[1] = 1
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(ge=1, le=65535)
    platform: Literal["macos"] = "macos"
    architecture: Literal["arm64"] = "arm64"
    application_home_source: Literal["environment", "desktop_host", "platform_default"]
    baseline_pack: DesktopPackIdentity | None


class DesktopHandshake(DesktopContractModel):
    schema_version: Literal["doc-evidence.desktop-handshake.v1"] = (
        DESKTOP_HANDSHAKE_SCHEMA_VERSION
    )
    compatible: Literal[True] = True
    protocol_version: Literal["doc-evidence.desktop.v1"] = DESKTOP_PROTOCOL_VERSION
    application_version: str = Field(min_length=1, max_length=100)
    api_version: Literal[1] = 1
    platform: Literal["macos"] = "macos"
    architecture: Literal["arm64"] = "arm64"
    application_home_source: Literal["environment", "desktop_host", "platform_default"]
    baseline_pack: DesktopPackIdentity | None
    capabilities: list[
        Literal[
            "known_libraries",
            "durable_extraction_jobs",
            "native_library_authorization",
        ]
    ]


class DesktopControlHandshake(DesktopContractModel):
    schema_version: Literal["doc-evidence.desktop-control.v1"] = (
        DESKTOP_CONTROL_SCHEMA_VERSION
    )
    compatible: Literal[True] = True
    protocol_version: Literal["doc-evidence.desktop.v1"] = DESKTOP_PROTOCOL_VERSION
    capabilities: list[
        Literal[
            "register_existing_library",
            "create_managed_library",
            "add_collection",
        ]
    ]


def require_macos_arm64() -> tuple[Literal["macos"], Literal["arm64"]]:
    machine = platform.machine().casefold()
    if sys.platform != "darwin" or machine not in {"arm64", "aarch64"}:
        raise RequestError("the desktop sidecar requires macOS arm64")
    return "macos", "arm64"


def create_desktop_handshake(
    *,
    application_home_source: AppHomeSource,
    baseline_pack: DesktopPackIdentity | None,
    native_library_authorization: bool = False,
) -> DesktopHandshake:
    capabilities: list[
        Literal[
            "known_libraries",
            "durable_extraction_jobs",
            "native_library_authorization",
        ]
    ] = ["known_libraries", "durable_extraction_jobs"]
    if native_library_authorization:
        capabilities.append("native_library_authorization")
    return DesktopHandshake(
        application_version=__version__,
        application_home_source=application_home_source,
        baseline_pack=baseline_pack,
        capabilities=capabilities,
    )


def create_desktop_ready(
    handshake: DesktopHandshake,
    *,
    port: int,
) -> DesktopReady:
    return DesktopReady(
        application_version=handshake.application_version,
        port=port,
        application_home_source=handshake.application_home_source,
        baseline_pack=handshake.baseline_pack,
    )
