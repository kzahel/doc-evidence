"""Desktop library-selection use-case boundary independent of transport/storage."""

from __future__ import annotations

from typing import Protocol

from doc_evidence.application.library import LibraryApplication
from doc_evidence.contracts.api import (
    AppSummary,
    KnownLibraryList,
    LibraryActivation,
    LibraryDetail,
)


class LibraryManager(Protocol):
    """Resolve explicit library identities without mutable request-global state."""

    def app_summary(self) -> AppSummary: ...

    def libraries(self) -> KnownLibraryList: ...

    def library(self, library_id: str) -> LibraryDetail: ...

    def activate(self, library_id: str) -> LibraryActivation: ...

    def application(self, library_id: str) -> LibraryApplication: ...
