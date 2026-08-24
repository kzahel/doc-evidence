"""Trusted desktop-host adapter for native-selected library paths."""

from __future__ import annotations

import re
import threading
import uuid
from pathlib import Path
from typing import Literal

import yaml

from doc_evidence.adapters.local_libraries import LocalLibraryManager
from doc_evidence.app_home import LibraryRegistry
from doc_evidence.application.library_management import (
    DesktopLibraryControl,
    preflight_collection_root,
)
from doc_evidence.config import AppConfig, load_config
from doc_evidence.contracts.api import LibraryDetail
from doc_evidence.contracts.desktop import (
    DesktopAddCollectionRequest,
    DesktopCollectionResult,
    DesktopCreateLibraryRequest,
    DesktopLibraryResult,
    DesktopRegisterLibraryRequest,
)
from doc_evidence.errors import ApplicationStateError, RequestError
from doc_evidence.persistence import ensure_library_database
from doc_evidence.platform_paths import same_path
from doc_evidence.util import atomic_write_text


def _trusted_absolute_path(raw: str, label: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise RequestError(f"native-selected {label} must be absolute")
    return path.resolve()


def _collection_id(name: str, existing: set[str]) -> str:
    base = re.sub(r"[^a-z0-9_-]+", "-", name.casefold()).strip("-_")
    base = (base or "documents")[:72].rstrip("-_") or "documents"
    candidate = base
    suffix = 2
    while candidate in existing:
        candidate = f"{base[:68]}-{suffix}"
        suffix += 1
    return candidate


def _library_result(
    detail: LibraryDetail,
    *,
    outcome: Literal["created", "registered", "already_registered", "updated"],
) -> DesktopLibraryResult:
    return DesktopLibraryResult(
        outcome=outcome,
        library_id=detail.library.library_id,
        name=detail.library.name,
        store_mode=detail.library.store_mode,
        status=detail.library.status,
        status_detail=detail.library.status_detail,
        collection_count=detail.library.collection_count,
    )


def _validated_managed_config(config: AppConfig, raw: dict[str, object]) -> AppConfig:
    candidate = config.path.with_name(f".{config.path.name}.{uuid.uuid4()}.candidate")
    try:
        atomic_write_text(candidate, yaml.safe_dump(raw, sort_keys=False))
        load_config(candidate)
        atomic_write_text(config.path, yaml.safe_dump(raw, sort_keys=False))
        return load_config(config.path)
    finally:
        candidate.unlink(missing_ok=True)


class LocalDesktopLibraryControl(DesktopLibraryControl):
    """Apply paths received only from the authenticated native host."""

    def __init__(
        self,
        *,
        registry: LibraryRegistry,
        manager: LocalLibraryManager,
    ):
        self.registry = registry
        self.manager = manager
        self._lock = threading.Lock()

    def register_existing(
        self, request: DesktopRegisterLibraryRequest
    ) -> DesktopLibraryResult:
        with self._lock:
            config_path = _trusted_absolute_path(request.config_path, "configuration")
            existing = {
                self.registry.descriptor(known).config_path.resolve()
                for known in self.registry.load().libraries
            }
            descriptor = self.registry.register_config(
                config_path,
                name=request.name,
            )
            outcome = (
                "already_registered"
                if any(same_path(config_path, item) for item in existing)
                else "registered"
            )
            return _library_result(
                self.manager.library(descriptor.library_id),
                outcome=outcome,
            )

    def create_managed(
        self, request: DesktopCreateLibraryRequest
    ) -> DesktopLibraryResult:
        with self._lock:
            source = _trusted_absolute_path(request.source_path, "source folder")
            descriptor = self.registry.create_managed_library(
                source,
                name=request.name,
            )
            config = load_config(descriptor.config_path)
            ensure_library_database(
                config,
                library_id=descriptor.library_id,
                name=descriptor.name,
            )
            return _library_result(
                self.manager.library(descriptor.library_id),
                outcome="created",
            )

    def add_collection(
        self, request: DesktopAddCollectionRequest
    ) -> DesktopCollectionResult:
        with self._lock:
            _known, descriptor, config = self.registry.open(request.library_id)
            if descriptor.store_mode != "managed":
                raise ApplicationStateError(
                    "desktop collection changes require a managed library"
                )
            source = _trusted_absolute_path(request.source_path, "collection folder")
            preflight = preflight_collection_root(config, source)
            unchanged = preflight.kind in {"same_root", "already_covered"}
            confirmation_required = (
                preflight.kind == "replace_children"
                and not request.confirm_parent_replacement
            )
            if preflight.kind in {"store_overlap", "unavailable"}:
                raise RequestError(preflight.message)
            if unchanged or confirmation_required:
                return DesktopCollectionResult(
                    preflight_kind=preflight.kind,
                    changed=False,
                    confirmation_required=confirmation_required,
                    affected_collection_ids=list(preflight.affected_collection_ids),
                    library=_library_result(
                        self.manager.library(request.library_id),
                        outcome="updated",
                    ),
                )

            self.manager.prepare_configuration_change(request.library_id)
            raw = yaml.safe_load(config.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or not isinstance(
                raw.get("collections"), list
            ):
                raise ApplicationStateError(
                    "managed library configuration is malformed"
                )
            collections = [
                item for item in raw["collections"] if isinstance(item, dict)
            ]
            if len(collections) != len(raw["collections"]):
                raise ApplicationStateError("managed library collections are malformed")
            affected = set(preflight.affected_collection_ids)
            if preflight.kind == "replace_children":
                remaining = [
                    item for item in collections if item.get("id") not in affected
                ]
            else:
                remaining = list(collections)
            existing_ids = {
                str(item["id"]) for item in remaining if isinstance(item.get("id"), str)
            }
            if preflight.kind == "replace_children" and len(affected) == 1:
                identifier = next(iter(affected))
            else:
                identifier = _collection_id(source.name, existing_ids)
            remaining.append(
                {
                    "id": identifier,
                    "source": str(source),
                    "include": ["**/*"],
                    "exclude": ["**/.DS_Store"],
                }
            )
            raw["collections"] = remaining
            updated_config = _validated_managed_config(config, raw)
            ensure_library_database(
                updated_config,
                library_id=descriptor.library_id,
                name=descriptor.name,
            )
            return DesktopCollectionResult(
                preflight_kind=preflight.kind,
                changed=True,
                confirmation_required=False,
                affected_collection_ids=list(preflight.affected_collection_ids),
                library=_library_result(
                    self.manager.library(request.library_id),
                    outcome="updated",
                ),
            )
