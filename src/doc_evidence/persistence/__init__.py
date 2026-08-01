"""SQLite persistence adapters for durable library state."""

from doc_evidence.persistence.library_database import (
    LibraryDatabase,
    ensure_library_database,
)

__all__ = ["LibraryDatabase", "ensure_library_database"]
