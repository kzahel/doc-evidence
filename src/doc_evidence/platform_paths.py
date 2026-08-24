"""Platform-aware path identity and Windows collection-root policy."""

from __future__ import annotations

import ctypes
import ntpath
import os
import posixpath
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path, PureWindowsPath
from typing import Any, Literal, cast

PlatformPathKind = Literal["posix", "windows"]

WINDOWS_DRIVE_FIXED = 3
WINDOWS_FILE_ATTRIBUTE_OFFLINE = 0x00001000
WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
WINDOWS_FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
WINDOWS_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000
WINDOWS_CLOUD_ATTRIBUTES = (
    WINDOWS_FILE_ATTRIBUTE_OFFLINE
    | WINDOWS_FILE_ATTRIBUTE_RECALL_ON_OPEN
    | WINDOWS_FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)


def _extended_windows_path(raw: str) -> str:
    """Return an absolute Win32 path that does not depend on MAX_PATH policy."""

    if not ntpath.isabs(raw):
        return raw
    absolute = ntpath.normpath(raw)
    if absolute.startswith(("\\\\?\\", "\\\\.\\")):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute[2:]
    return "\\\\?\\" + absolute


def extended_length_path(path: str | os.PathLike[str]) -> Path:
    """Use extended-length syntax for absolute Windows filesystem access."""

    raw = os.fspath(path)
    if os.name != "nt":
        return Path(raw)
    return Path(_extended_windows_path(raw))


@contextmanager
def long_path_temporary_directory(*, prefix: str) -> Iterator[Path]:
    """Create a temporary tree whose cleanup also works beyond MAX_PATH."""

    root = Path(tempfile.mkdtemp(prefix=prefix))
    try:
        yield root
    finally:
        shutil.rmtree(extended_length_path(root))


def _path_kind(kind: PlatformPathKind | None = None) -> PlatformPathKind:
    if kind is not None:
        return kind
    return "windows" if os.name == "nt" else "posix"


def path_identity(
    path: str | os.PathLike[str],
    *,
    kind: PlatformPathKind | None = None,
) -> tuple[str, ...]:
    """Return a comparison-only identity without changing the display alias."""

    if _path_kind(kind) == "windows":
        normalized = ntpath.normcase(ntpath.normpath(os.fspath(path)))
        return PureWindowsPath(normalized).parts
    normalized = posixpath.normpath(os.fspath(path))
    return Path(normalized).parts


def same_path(
    left: str | os.PathLike[str],
    right: str | os.PathLike[str],
    *,
    kind: PlatformPathKind | None = None,
) -> bool:
    return path_identity(left, kind=kind) == path_identity(right, kind=kind)


def path_contains(
    parent: str | os.PathLike[str],
    child: str | os.PathLike[str],
    *,
    kind: PlatformPathKind | None = None,
) -> bool:
    parent_parts = path_identity(parent, kind=kind)
    child_parts = path_identity(child, kind=kind)
    return (
        len(parent_parts) <= len(child_parts)
        and child_parts[: len(parent_parts)] == parent_parts
    )


def paths_overlap(
    left: str | os.PathLike[str],
    right: str | os.PathLike[str],
    *,
    kind: PlatformPathKind | None = None,
) -> bool:
    return path_contains(left, right, kind=kind) or path_contains(
        right, left, kind=kind
    )


def file_attributes(path: Path) -> int:
    if os.name != "nt":
        return 0
    try:
        result = path.lstat()
    except OSError:
        return 0
    return int(cast(Any, result).st_file_attributes)


def is_link_or_reparse_point(path: Path) -> bool:
    return path.is_symlink() or bool(
        file_attributes(path) & WINDOWS_FILE_ATTRIBUTE_REPARSE_POINT
    )


def is_offline_or_recalled(path: Path) -> bool:
    return bool(file_attributes(path) & WINDOWS_CLOUD_ATTRIBUTES)


def _windows_drive_type(path: Path) -> int:
    if os.name != "nt":
        raise OSError("Windows drive inspection is unavailable")
    root = path.anchor
    if not root:
        return 0
    kernel32 = cast(Any, ctypes).WinDLL("kernel32", use_last_error=True)
    get_drive_type = kernel32.GetDriveTypeW
    get_drive_type.argtypes = [wintypes.LPCWSTR]
    get_drive_type.restype = wintypes.UINT
    return int(get_drive_type(root))


def resolve_collection_root(candidate: Path) -> tuple[Path, str | None]:
    """Resolve a source root and classify unsupported Windows storage."""

    expanded = candidate.expanduser()
    if os.name == "nt":
        display_path = expanded.absolute()
        if is_link_or_reparse_point(expanded):
            return display_path, "Windows collection root may not be a reparse point"
        if is_offline_or_recalled(expanded):
            return (
                display_path,
                "Windows cloud or offline collection roots are unsupported",
            )
    resolved = expanded.resolve()
    if not resolved.is_dir():
        return resolved, "collection root is not an available directory"
    if os.name != "nt":
        return resolved, None
    if _windows_drive_type(resolved) != WINDOWS_DRIVE_FIXED:
        return resolved, "Windows collection root must be on a local fixed drive"
    return resolved, None
