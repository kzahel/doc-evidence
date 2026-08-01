"""Framework-independent collection-scope validation and preflight."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from doc_evidence.config import AppConfig

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


def _overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def preflight_collection_root(
    config: AppConfig, candidate: Path
) -> CollectionPreflight:
    """Classify a trusted native/CLI folder grant without changing scope."""

    resolved = candidate.expanduser().resolve()
    if not resolved.is_dir():
        return CollectionPreflight(
            kind="unavailable",
            candidate=resolved,
            affected_collection_ids=(),
            message="candidate collection root is not an available directory",
        )
    if _overlap(resolved, config.store.resolve()):
        return CollectionPreflight(
            kind="store_overlap",
            candidate=resolved,
            affected_collection_ids=(),
            message="candidate collection root overlaps the library store",
        )
    same = tuple(
        collection.id
        for collection in config.collections
        if collection.source == resolved
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
        if resolved.is_relative_to(collection.source)
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
        if collection.source.is_relative_to(resolved)
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
