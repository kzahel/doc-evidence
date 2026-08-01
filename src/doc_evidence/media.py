"""Small content-aware media type classifier for the Phase 1 inventory."""

from __future__ import annotations

import mimetypes
from pathlib import Path

_OFFICE_TYPES = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


def detect_media_type(path: Path) -> str:
    with path.open("rb") as source:
        header = source.read(1024)

    if b"%PDF-" in header:
        return "application/pdf"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"
    if header.startswith(b"PK\x03\x04") and path.suffix.casefold() in _OFFICE_TYPES:
        return _OFFICE_TYPES[path.suffix.casefold()]

    guessed, _encoding = mimetypes.guess_type(path.name)
    return guessed or "application/octet-stream"
