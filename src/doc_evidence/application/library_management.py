"""Framework-independent collection-scope validation and preflight."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from doc_evidence.config import AppConfig
from doc_evidence.contracts.desktop import (
    DesktopAddCollectionRequest,
    DesktopCollectionResult,
    DesktopCreateLibraryRequest,
    DesktopLibraryResult,
    DesktopRegisterLibraryRequest,
)
from doc_evidence.platform_paths import (
    path_contains,
    paths_overlap,
    resolve_collection_root,
    same_path,
)

CollectionPreflightKind = Literal[
    "add_sibling",
    "replace_children",
    "already_covered",
    "same_root",
    "store_overlap",
    "unavailable",
]


@dataclass(frozen=True)
class CollectionPreflight:
    kind: CollectionPreflightKind
    candidate: Path
    affected_collection_ids: tuple[str, ...]
    message: str


class DesktopLibraryControl(Protocol):
    """Trusted native-path operations; never expose this port to browser auth."""

    def register_existing(
        self, request: DesktopRegisterLibraryRequest
    ) -> DesktopLibraryResult: ...

    def create_managed(
        self, request: DesktopCreateLibraryRequest
    ) -> DesktopLibraryResult: ...

    def add_collection(
        self, request: DesktopAddCollectionRequest
    ) -> DesktopCollectionResult: ...


def preflight_collection_root(
    config: AppConfig, candidate: Path
) -> CollectionPreflight:
    """Classify a trusted native/CLI folder grant without changing scope."""

    resolved, issue = resolve_collection_root(candidate)
    if issue is not None:
        return CollectionPreflight(
            kind="unavailable",
            candidate=resolved,
            affected_collection_ids=(),
            message=issue,
        )
    if paths_overlap(resolved, config.store.resolve()):
        return CollectionPreflight(
            kind="store_overlap",
            candidate=resolved,
            affected_collection_ids=(),
            message="candidate collection root overlaps the library store",
        )
    same = tuple(
        collection.id
        for collection in config.collections
        if same_path(collection.source, resolved)
    )
    if same:
        return CollectionPreflight(
            kind="same_root",
            candidate=resolved,
            affected_collection_ids=same,
            message="candidate is already registered as a collection root",
        )
    covering = tuple(
        collection.id
        for collection in config.collections
        if path_contains(collection.source, resolved)
    )
    if covering:
        return CollectionPreflight(
            kind="already_covered",
            candidate=resolved,
            affected_collection_ids=covering,
            message="candidate is already covered by an existing collection",
        )
    children = tuple(
        collection.id
        for collection in config.collections
        if path_contains(resolved, collection.source)
    )
    if children:
        return CollectionPreflight(
            kind="replace_children",
            candidate=resolved,
            affected_collection_ids=children,
            message=(
                "candidate expands collection scope; replace the covered child "
                "roots and reuse content-addressed artifacts"
            ),
        )
    return CollectionPreflight(
        kind="add_sibling",
        candidate=resolved,
        affected_collection_ids=(),
        message="candidate is a non-overlapping sibling collection",
    )
