"""Deterministic traversal of configured external collections."""

from __future__ import annotations

import os
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path

from doc_evidence.config import CollectionConfig
from doc_evidence.platform_paths import (
    extended_length_path,
    is_link_or_reparse_point,
    is_offline_or_recalled,
)


@dataclass(frozen=True)
class DiscoveredFile:
    collection_id: str
    root: Path
    path: Path
    relative_path: str


def _matches(relative_path: str, patterns: tuple[str, ...]) -> bool:
    for pattern in patterns:
        if fnmatchcase(relative_path, pattern):
            return True
        if pattern.startswith("**/") and fnmatchcase(relative_path, pattern[3:]):
            return True
    return False


def discover_files(
    collection: CollectionConfig,
    warnings: list[dict[str, str]],
) -> list[DiscoveredFile]:
    discovered: list[DiscoveredFile] = []
    filesystem_root = extended_length_path(collection.source)
    for directory, directory_names, file_names in os.walk(
        filesystem_root,
        topdown=True,
        followlinks=False,
    ):
        directory_path = Path(directory)
        retained_directories: list[str] = []
        for name in sorted(directory_names):
            candidate = directory_path / name
            relative = candidate.relative_to(filesystem_root).as_posix()
            if candidate.is_symlink():
                warnings.append(
                    {
                        "collection_id": collection.id,
                        "path": relative,
                        "warning": "symlink directory skipped",
                    }
                )
                continue
            if is_link_or_reparse_point(candidate):
                warnings.append(
                    {
                        "collection_id": collection.id,
                        "path": relative,
                        "warning": "reparse-point directory skipped",
                    }
                )
                continue
            if is_offline_or_recalled(candidate):
                warnings.append(
                    {
                        "collection_id": collection.id,
                        "path": relative,
                        "warning": "offline or recalled directory skipped",
                    }
                )
                continue
            if _matches(relative, collection.exclude) or _matches(
                relative + "/", collection.exclude
            ):
                continue
            retained_directories.append(name)
        directory_names[:] = retained_directories

        for name in sorted(file_names):
            candidate = directory_path / name
            relative = candidate.relative_to(filesystem_root).as_posix()
            if candidate.is_symlink():
                warnings.append(
                    {
                        "collection_id": collection.id,
                        "path": relative,
                        "warning": "symlink file skipped",
                    }
                )
                continue
            if is_link_or_reparse_point(candidate):
                warnings.append(
                    {
                        "collection_id": collection.id,
                        "path": relative,
                        "warning": "reparse-point file skipped",
                    }
                )
                continue
            if is_offline_or_recalled(candidate):
                warnings.append(
                    {
                        "collection_id": collection.id,
                        "path": relative,
                        "warning": "offline or recalled file skipped",
                    }
                )
                continue
            if _matches(relative, collection.exclude):
                continue
            if not _matches(relative, collection.include):
                continue
            discovered.append(
                DiscoveredFile(
                    collection_id=collection.id,
                    root=collection.source,
                    path=candidate,
                    relative_path=relative,
                )
            )
    discovered.sort(key=lambda item: (item.collection_id, item.relative_path))
    return discovered
