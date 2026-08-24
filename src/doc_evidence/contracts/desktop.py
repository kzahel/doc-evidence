"""Versioned contracts for the thin desktop host boundary."""

from __future__ import annotations

import platform as runtime_platform
import sys
from typing import Literal, Self, TypeAlias, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from doc_evidence import __version__
from doc_evidence.app_home import AppHomeSource
from doc_evidence.errors import RequestError

DESKTOP_PROTOCOL_VERSION = "doc-evidence.desktop.v1"
DESKTOP_READY_SCHEMA_VERSION = "doc-evidence.desktop-ready.v1"
DESKTOP_HANDSHAKE_SCHEMA_VERSION = "doc-evidence.desktop-handshake.v1"
DESKTOP_CONTROL_SCHEMA_VERSION = "doc-evidence.desktop-control.v1"
DesktopPlatform: TypeAlias = Literal["macos", "windows"]
DesktopArchitecture: TypeAlias = Literal["arm64", "x86_64"]
DesktopTarget: TypeAlias = tuple[DesktopPlatform, DesktopArchitecture]

SUPPORTED_DESKTOP_TARGETS: frozenset[DesktopTarget] = frozenset(
    {("macos", "arm64"), ("windows", "x86_64")}
)
MACOS_DESKTOP_ORIGIN = "tauri://localhost"
WINDOWS_DESKTOP_ORIGIN = "http://tauri.localhost"
DESKTOP_PLATFORM_ENV = "DOC_EVIDENCE_DESKTOP_PLATFORM"
DESKTOP_ARCHITECTURE_ENV = "DOC_EVIDENCE_DESKTOP_ARCHITECTURE"
MAX_DESKTOP_READY_BYTES = 64 * 1024
MAX_DESKTOP_ERROR_BYTES = 8 * 1024


class DesktopContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DesktopTargetContract(DesktopContractModel):
    platform: DesktopPlatform
    architecture: DesktopArchitecture

    @model_validator(mode="after")
    def require_supported_pair(self) -> Self:
        if (self.platform, self.architecture) not in SUPPORTED_DESKTOP_TARGETS:
            raise ValueError("unsupported desktop target pair")
        return self


class DesktopPackIdentity(DesktopContractModel):
    pack_id: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=100)
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DesktopReady(DesktopTargetContract):
    schema_version: Literal["doc-evidence.desktop-ready.v1"] = (
        DESKTOP_READY_SCHEMA_VERSION
    )
    protocol_version: Literal["doc-evidence.desktop.v1"] = DESKTOP_PROTOCOL_VERSION
    application_version: str = Field(min_length=1, max_length=100)
    api_version: Literal[1] = 1
    host: Literal["127.0.0.1"] = "127.0.0.1"
    port: int = Field(ge=1, le=65535)
    application_home_source: Literal["environment", "desktop_host", "platform_default"]
    baseline_pack: DesktopPackIdentity | None


class DesktopHandshake(DesktopTargetContract):
    schema_version: Literal["doc-evidence.desktop-handshake.v1"] = (
        DESKTOP_HANDSHAKE_SCHEMA_VERSION
    )
    compatible: Literal[True] = True
    protocol_version: Literal["doc-evidence.desktop.v1"] = DESKTOP_PROTOCOL_VERSION
    application_version: str = Field(min_length=1, max_length=100)
    api_version: Literal[1] = 1
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


class DesktopRegisterLibraryRequest(DesktopContractModel):
    config_path: str = Field(min_length=1, max_length=4096)
    name: str | None = Field(default=None, min_length=1, max_length=200)


class DesktopCreateLibraryRequest(DesktopContractModel):
    source_path: str = Field(min_length=1, max_length=4096)
    name: str = Field(min_length=1, max_length=200)


class DesktopAddCollectionRequest(DesktopContractModel):
    library_id: str = Field(min_length=1, max_length=200)
    source_path: str = Field(min_length=1, max_length=4096)
    confirm_parent_replacement: bool = False


class DesktopLibraryResult(DesktopContractModel):
    schema_version: Literal[1] = 1
    outcome: Literal["created", "registered", "already_registered", "updated"]
    library_id: str
    name: str
    store_mode: Literal["managed", "adopted"]
    status: Literal["ready", "unavailable", "integrity_error"]
    status_detail: str | None
    collection_count: int = Field(ge=0)


class DesktopCollectionResult(DesktopContractModel):
    schema_version: Literal[1] = 1
    preflight_kind: Literal[
        "add_sibling",
        "replace_children",
        "already_covered",
        "same_root",
        "store_overlap",
        "unavailable",
    ]
    changed: bool
    confirmation_required: bool
    affected_collection_ids: list[str]
    library: DesktopLibraryResult


def desktop_origin_for(platform: DesktopPlatform) -> str:
    if platform == "macos":
        return MACOS_DESKTOP_ORIGIN
    if platform == "windows":
        return WINDOWS_DESKTOP_ORIGIN
    raise RequestError("the desktop platform is unsupported")


def require_supported_desktop_target(
    *,
    expected_platform: str,
    expected_architecture: str,
    platform_name: str | None = None,
    machine_name: str | None = None,
) -> DesktopTarget:
    expected = (expected_platform, expected_architecture)
    if expected not in SUPPORTED_DESKTOP_TARGETS:
        raise RequestError("the desktop target manifest is unsupported")

    system = platform_name if platform_name is not None else sys.platform
    machine = (
        machine_name if machine_name is not None else runtime_platform.machine()
    ).casefold()
    if system == "darwin" and machine in {"arm64", "aarch64"}:
        actual: tuple[str, str] = ("macos", "arm64")
    elif system == "win32" and machine in {"amd64", "x86_64"}:
        actual = ("windows", "x86_64")
    else:
        raise RequestError("the desktop sidecar is running on an unsupported target")
    if actual != expected:
        raise RequestError("the desktop sidecar target disagrees with its manifest")
    return cast(DesktopTarget, actual)


def create_desktop_handshake(
    *,
    platform: DesktopPlatform,
    architecture: DesktopArchitecture,
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
        platform=platform,
        architecture=architecture,
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
        platform=handshake.platform,
        architecture=handshake.architecture,
        application_home_source=handshake.application_home_source,
        baseline_pack=handshake.baseline_pack,
    )
