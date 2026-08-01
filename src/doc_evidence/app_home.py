"""Application-home discovery and bounded known-library persistence."""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, cast

import yaml

from doc_evidence.config import AppConfig, load_config
from doc_evidence.errors import ApplicationStateError
from doc_evidence.util import atomic_write_json, atomic_write_text, isoformat_z

APP_STATE_SCHEMA_VERSION = 1
LIBRARY_DESCRIPTOR_SCHEMA_VERSION = 1
MAX_REGISTERED_LIBRARIES = 100
LEGACY_LIBRARY_NAMESPACE = uuid.UUID("63faf6f2-c052-4e23-b992-cdeeb7e52af4")

AppHomeSource = Literal["environment", "desktop_host", "platform_default"]
StoreMode = Literal["managed", "adopted"]


def _managed_collection_id(name: str) -> str:
    identifier = re.sub(r"[^a-z0-9_-]+", "-", name.casefold()).strip("-_")
    return (identifier or "documents")[:80].rstrip("-_") or "documents"


def legacy_library_id(config_path: Path) -> str:
    """Assign stable identity to a legacy descriptor without rewriting it."""

    return str(uuid.uuid5(LEGACY_LIBRARY_NAMESPACE, str(config_path.resolve())))


@dataclass(frozen=True)
class ApplicationHome:
    root: Path
    source: AppHomeSource


@dataclass(frozen=True)
class LibraryDescriptor:
    library_id: str
    name: str
    store_mode: StoreMode
    config_path: Path
    store_path: Path
    descriptor_path: Path

    def value(self) -> dict[str, object]:
        return {
            "schema_version": LIBRARY_DESCRIPTOR_SCHEMA_VERSION,
            "library_id": self.library_id,
            "name": self.name,
            "store_mode": self.store_mode,
            "config_path": str(self.config_path),
            "store_path": str(self.store_path),
        }


@dataclass(frozen=True)
class KnownLibrary:
    library_id: str
    name: str
    descriptor_path: Path
    store_mode: StoreMode
    last_opened_at: str | None

    def value(self) -> dict[str, object]:
        return {
            "library_id": self.library_id,
            "name": self.name,
            "descriptor_path": str(self.descriptor_path),
            "store_mode": self.store_mode,
            "last_opened_at": self.last_opened_at,
        }


@dataclass(frozen=True)
class AppState:
    libraries: tuple[KnownLibrary, ...] = ()
    default_library_id: str | None = None
    last_library_id: str | None = None

    def value(self) -> dict[str, object]:
        return {
            "schema_version": APP_STATE_SCHEMA_VERSION,
            "default_library_id": self.default_library_id,
            "last_library_id": self.last_library_id,
            "libraries": [library.value() for library in self.libraries],
        }


def _platform_default(
    *,
    platform_name: str,
    environ: Mapping[str, str],
    home_directory: Path,
) -> Path:
    if platform_name == "darwin":
        return home_directory / "Library" / "Application Support" / "doc-evidence"
    if platform_name.startswith("win"):
        local_app_data = environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "doc-evidence"
        return home_directory / "AppData" / "Local" / "doc-evidence"
    xdg_data_home = environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home) / "doc-evidence"
    return home_directory / ".local" / "share" / "doc-evidence"


def resolve_application_home(
    *,
    desktop_host_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
    platform_name: str | None = None,
    home_directory: Path | None = None,
) -> ApplicationHome:
    """Resolve the app-owned root once at process composition."""

    values = environ if environ is not None else os.environ
    explicit = values.get("DOC_EVIDENCE_HOME")
    if explicit:
        root = Path(explicit).expanduser()
        source: AppHomeSource = "environment"
        if not root.is_absolute():
            raise ApplicationStateError("DOC_EVIDENCE_HOME must be an absolute path")
    elif desktop_host_root is not None:
        root = desktop_host_root.expanduser()
        source = "desktop_host"
        if not root.is_absolute():
            raise ApplicationStateError(
                "desktop-host application-data root must be absolute"
            )
    else:
        root = _platform_default(
            platform_name=platform_name or sys.platform,
            environ=values,
            home_directory=(home_directory or Path.home()).expanduser(),
        )
        source = "platform_default"
    return ApplicationHome(root=root.resolve(), source=source)


def _required_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ApplicationStateError(f"application state field {field!r} is invalid")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _required_string(value, field)


def _parse_store_mode(value: object) -> StoreMode:
    if value not in {"managed", "adopted"}:
        raise ApplicationStateError("library store_mode must be managed or adopted")
    return cast(StoreMode, value)


class LibraryRegistry:
    """Own the small atomic registry and app-managed library descriptors."""

    def __init__(self, home: ApplicationHome):
        self.home = home
        self.state_path = home.root / "app-state.json"
        self.libraries_root = home.root / "libraries"

    def load(self) -> AppState:
        if not self.state_path.exists():
            return AppState()
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ApplicationStateError(
                f"cannot read application registry {self.state_path}: {error}"
            ) from error
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            raise ApplicationStateError("unsupported or malformed application registry")
        allowed = {
            "schema_version",
            "default_library_id",
            "last_library_id",
            "libraries",
        }
        if set(raw) - allowed:
            raise ApplicationStateError("application registry has unknown fields")
        raw_libraries = raw.get("libraries")
        if not isinstance(raw_libraries, list):
            raise ApplicationStateError("application registry libraries must be a list")
        if len(raw_libraries) > MAX_REGISTERED_LIBRARIES:
            raise ApplicationStateError(
                "application registry exceeds its library limit"
            )
        libraries: list[KnownLibrary] = []
        seen: set[str] = set()
        for index, item in enumerate(raw_libraries):
            if not isinstance(item, dict):
                raise ApplicationStateError(f"library entry {index} is invalid")
            if set(item) != {
                "library_id",
                "name",
                "descriptor_path",
                "store_mode",
                "last_opened_at",
            }:
                raise ApplicationStateError(f"library entry {index} has invalid fields")
            library_id = _required_string(item.get("library_id"), "library_id")
            if library_id in seen:
                raise ApplicationStateError("application registry repeats a library ID")
            seen.add(library_id)
            descriptor_path = Path(
                _required_string(item.get("descriptor_path"), "descriptor_path")
            )
            if not descriptor_path.is_absolute():
                raise ApplicationStateError("library descriptor path must be absolute")
            libraries.append(
                KnownLibrary(
                    library_id=library_id,
                    name=_required_string(item.get("name"), "name"),
                    descriptor_path=descriptor_path,
                    store_mode=_parse_store_mode(item.get("store_mode")),
                    last_opened_at=_optional_string(
                        item.get("last_opened_at"), "last_opened_at"
                    ),
                )
            )
        default_library_id = _optional_string(
            raw.get("default_library_id"), "default_library_id"
        )
        last_library_id = _optional_string(
            raw.get("last_library_id"), "last_library_id"
        )
        for selected in (default_library_id, last_library_id):
            if selected is not None and selected not in seen:
                raise ApplicationStateError(
                    "application registry selection names an unknown library"
                )
        return AppState(
            libraries=tuple(libraries),
            default_library_id=default_library_id,
            last_library_id=last_library_id,
        )

    def save(self, state: AppState) -> None:
        if len(state.libraries) > MAX_REGISTERED_LIBRARIES:
            raise ApplicationStateError(
                "application registry exceeds its library limit"
            )
        atomic_write_json(self.state_path, state.value())

    def descriptor(self, known: KnownLibrary) -> LibraryDescriptor:
        try:
            raw = yaml.safe_load(known.descriptor_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as error:
            raise ApplicationStateError(
                f"cannot read library descriptor {known.descriptor_path}: {error}"
            ) from error
        if not isinstance(raw, dict) or raw.get("schema_version") != 1:
            raise ApplicationStateError("unsupported or malformed library descriptor")
        required = {
            "schema_version",
            "library_id",
            "name",
            "store_mode",
            "config_path",
            "store_path",
        }
        if set(raw) != required:
            raise ApplicationStateError("library descriptor has invalid fields")
        library_id = _required_string(raw.get("library_id"), "library_id")
        name = _required_string(raw.get("name"), "name")
        store_mode = _parse_store_mode(raw.get("store_mode"))
        config_path = Path(_required_string(raw.get("config_path"), "config_path"))
        store_path = Path(_required_string(raw.get("store_path"), "store_path"))
        if not config_path.is_absolute() or not store_path.is_absolute():
            raise ApplicationStateError(
                "descriptor config and store paths must be absolute"
            )
        if (
            library_id != known.library_id
            or name != known.name
            or store_mode != known.store_mode
        ):
            raise ApplicationStateError(
                "registry and library descriptor identity disagree"
            )
        return LibraryDescriptor(
            library_id=library_id,
            name=name,
            store_mode=store_mode,
            config_path=config_path,
            store_path=store_path,
            descriptor_path=known.descriptor_path,
        )

    def register_config(
        self,
        config_path: Path,
        *,
        name: str | None = None,
        make_default: bool = True,
    ) -> LibraryDescriptor:
        config = load_config(config_path)
        resolved_config = config.path.resolve()
        state = self.load()
        for known in state.libraries:
            descriptor = self.descriptor(known)
            if descriptor.config_path.resolve() == resolved_config:
                if make_default:
                    self.activate(known.library_id, make_default=True)
                return descriptor
        if len(state.libraries) >= MAX_REGISTERED_LIBRARIES:
            raise ApplicationStateError("application registry is full")
        library_id = legacy_library_id(config.path)
        library_name = (name or config.path.parent.name or "Document Library").strip()
        if not library_name or len(library_name) > 200:
            raise ApplicationStateError("library name must contain 1-200 characters")
        descriptor_path = self.libraries_root / library_id / "library.yaml"
        descriptor = LibraryDescriptor(
            library_id=library_id,
            name=library_name,
            store_mode="adopted",
            config_path=resolved_config,
            store_path=config.store.resolve(),
            descriptor_path=descriptor_path,
        )
        atomic_write_text(
            descriptor_path,
            yaml.safe_dump(descriptor.value(), sort_keys=False),
        )
        now = isoformat_z()
        known = KnownLibrary(
            library_id=library_id,
            name=library_name,
            descriptor_path=descriptor_path,
            store_mode="adopted",
            last_opened_at=now,
        )
        self.save(
            AppState(
                libraries=(*state.libraries, known),
                default_library_id=(
                    library_id
                    if make_default or state.default_library_id is None
                    else state.default_library_id
                ),
                last_library_id=library_id,
            )
        )
        return descriptor

    def create_managed_library(
        self,
        source: Path,
        *,
        name: str,
    ) -> LibraryDescriptor:
        """Create app-owned descriptor/config state for one trusted source root."""

        resolved_source = source.expanduser().resolve()
        if not resolved_source.is_dir():
            raise ApplicationStateError(
                "managed library source must be an available directory"
            )
        if (
            resolved_source == self.home.root
            or resolved_source.is_relative_to(self.home.root)
            or self.home.root.is_relative_to(resolved_source)
        ):
            raise ApplicationStateError(
                "managed library source may not overlap the application home"
            )
        library_name = name.strip()
        if not library_name or len(library_name) > 200:
            raise ApplicationStateError("library name must contain 1-200 characters")
        state = self.load()
        if len(state.libraries) >= MAX_REGISTERED_LIBRARIES:
            raise ApplicationStateError("application registry is full")

        library_id = str(uuid.uuid4())
        library_root = self.libraries_root / library_id
        if library_root.exists():
            raise ApplicationStateError("new managed library identity already exists")
        config_path = library_root / "config.yaml"
        descriptor_path = library_root / "library.yaml"
        collection_id = _managed_collection_id(resolved_source.name)
        config_value = {
            "schema_version": 1,
            "collections": [
                {
                    "id": collection_id,
                    "source": str(resolved_source),
                    "include": ["**/*"],
                    "exclude": ["**/.DS_Store"],
                }
            ],
            "store": {"path": "."},
            "languages": ["eng", "deu"],
            "extraction": {
                "baseline": "poppler",
                "ocr_when": "image_only",
                "layout_when": "complex",
                "normalized_text_duplicates": True,
            },
            "search": {"sqlite_fts": True, "vector_index": False},
        }
        atomic_write_text(
            config_path,
            yaml.safe_dump(config_value, sort_keys=False),
        )
        config = load_config(config_path)
        descriptor = LibraryDescriptor(
            library_id=library_id,
            name=library_name,
            store_mode="managed",
            config_path=config.path,
            store_path=config.store,
            descriptor_path=descriptor_path,
        )
        atomic_write_text(
            descriptor_path,
            yaml.safe_dump(descriptor.value(), sort_keys=False),
        )
        now = isoformat_z()
        known = KnownLibrary(
            library_id=library_id,
            name=library_name,
            descriptor_path=descriptor_path,
            store_mode="managed",
            last_opened_at=now,
        )
        self.save(
            AppState(
                libraries=(*state.libraries, known),
                default_library_id=library_id,
                last_library_id=library_id,
            )
        )
        return descriptor

    def activate(self, library_id: str, *, make_default: bool = False) -> AppState:
        state = self.load()
        if library_id not in {library.library_id for library in state.libraries}:
            raise ApplicationStateError(f"unknown library ID: {library_id}")
        now = isoformat_z()
        libraries = tuple(
            replace(library, last_opened_at=now)
            if library.library_id == library_id
            else library
            for library in state.libraries
        )
        updated = AppState(
            libraries=libraries,
            default_library_id=(
                library_id if make_default else state.default_library_id
            ),
            last_library_id=library_id,
        )
        self.save(updated)
        return updated

    def open(
        self, library_id: str
    ) -> tuple[KnownLibrary, LibraryDescriptor, AppConfig]:
        """Resolve one registered identity without changing active selection."""

        state = self.load()
        known = next(
            (
                library
                for library in state.libraries
                if library.library_id == library_id
            ),
            None,
        )
        if known is None:
            raise ApplicationStateError(f"unknown library ID: {library_id}")
        descriptor = self.descriptor(known)
        config = load_config(descriptor.config_path)
        if config.store.resolve() != descriptor.store_path.resolve():
            raise ApplicationStateError(
                "library descriptor and configuration store disagree"
            )
        return known, descriptor, config

    def selected(self) -> tuple[KnownLibrary, LibraryDescriptor, AppConfig]:
        state = self.load()
        selected_id = state.last_library_id or state.default_library_id
        if selected_id is None:
            raise ApplicationStateError(
                "no library is registered; run doc-evidence library-register --config PATH"
            )
        return self.open(selected_id)
