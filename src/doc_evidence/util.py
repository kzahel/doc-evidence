"""Small deterministic helpers shared by the Phase 1 pipeline."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class FileHash:
    content_sha256: str
    size_bytes: int
    modified_ns: int


def utc_now() -> datetime:
    return datetime.now(UTC)


def isoformat_z(value: datetime | None = None) -> str:
    current = value or utc_now()
    return (
        current.astimezone(UTC)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def compact_timestamp(value: datetime | None = None) -> str:
    current = value or utc_now()
    return current.astimezone(UTC).strftime("%Y%m%dT%H%M%S.%fZ")


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def hash_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def hash_file(path: Path, chunk_size: int = 1024 * 1024) -> FileHash:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        before = os.fstat(source.fileno())
        while chunk := source.read(chunk_size):
            digest.update(chunk)
        after = os.fstat(source.fileno())
    if (before.st_size, before.st_mtime_ns) != (
        after.st_size,
        after.st_mtime_ns,
    ):
        raise OSError(f"file changed while hashing: {path}")
    return FileHash(
        content_sha256=digest.hexdigest(),
        size_bytes=after.st_size,
        modified_ns=after.st_mtime_ns,
    )


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    return hash_file(path, chunk_size).content_sha256


def normalize_text_for_duplicate_hash(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    return _WHITESPACE.sub(" ", normalized).strip()


def normalized_text_hash(text: str) -> str | None:
    normalized = normalize_text_for_duplicate_hash(text)
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def non_whitespace_character_count(text: str) -> int:
    return sum(not character.isspace() for character in text)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as destination:
            destination.write(content)
            destination.flush()
            os.fsync(destination.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def atomic_write_text(path: Path, content: str) -> None:
    atomic_write_bytes(path, content.encode("utf-8"))


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def relative_posix(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()
