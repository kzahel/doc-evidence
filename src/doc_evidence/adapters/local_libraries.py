"""Local application-home adapter for explicit library selection."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal

from doc_evidence.adapters.local_jobs import LocalExtractionJobs
from doc_evidence.adapters.local_workspace import LocalWorkspace
from doc_evidence.app_home import KnownLibrary, LibraryRegistry, legacy_library_id
from doc_evidence.application.jobs import BatchCancellation, JobRecord
from doc_evidence.application.libraries import LibraryManager
from doc_evidence.application.library import LibraryApplication
from doc_evidence.config import AppConfig
from doc_evidence.contracts.api import (
    AppSummary,
    KnownLibraryList,
    KnownLibrarySummary,
    LibraryActivation,
    LibraryCollection,
    LibraryDetail,
)
from doc_evidence.errors import ApplicationStateError, DocEvidenceError, NotFoundError
from doc_evidence.persistence import ensure_library_database
from doc_evidence.scheduler import LibraryScheduler

PREFLIGHT_KINDS = [
    "add_sibling",
    "replace_children",
    "already_covered",
    "same_root",
    "store_overlap",
    "unavailable",
]


@dataclass(frozen=True)
class _ResolvedLibrary:
    known: KnownLibrary
    config: AppConfig | None
    status: Literal["ready", "unavailable", "integrity_error"]
    detail: str | None


class LocalLibraryManager(LibraryManager):
    """Compose registered or explicit-config libraries into application services."""

    def __init__(
        self,
        *,
        registry: LibraryRegistry | None = None,
        explicit_config: AppConfig | None = None,
        explicit_library_id: str | None = None,
        explicit_name: str | None = None,
    ):
        if (registry is None) == (explicit_config is None):
            raise ValueError("provide exactly one registry or explicit configuration")
        self.registry = registry
        self.explicit_config = explicit_config
        self._applications: dict[str, LibraryApplication] = {}
        self._jobs: dict[str, LocalExtractionJobs] = {}
        self._schedulers: dict[str, LibraryScheduler] = {}
        if explicit_config is None:
            self.explicit_known = None
        else:
            self.explicit_known = KnownLibrary(
                library_id=explicit_library_id
                or legacy_library_id(explicit_config.path),
                name=explicit_name
                or explicit_config.path.parent.name
                or "Document Library",
                descriptor_path=explicit_config.path,
                store_mode="adopted",
                last_opened_at=None,
            )

    def _known(self) -> tuple[KnownLibrary, ...]:
        if self.registry is not None:
            return self.registry.load().libraries
        assert self.explicit_known is not None
        return (self.explicit_known,)

    def _active_ids(self) -> tuple[str | None, str | None, str | None]:
        if self.registry is not None:
            state = self.registry.load()
            active = state.last_library_id or state.default_library_id
            return active, state.default_library_id, state.last_library_id
        assert self.explicit_known is not None
        return self.explicit_known.library_id, self.explicit_known.library_id, None

    def _config(self, known: KnownLibrary) -> AppConfig:
        if self.registry is not None:
            _entry, _descriptor, config = self.registry.open(known.library_id)
            return config
        if (
            self.explicit_config is None
            or self.explicit_known is None
            or known.library_id != self.explicit_known.library_id
        ):
            raise ApplicationStateError(f"unknown library ID: {known.library_id}")
        return self.explicit_config

    @staticmethod
    def _database_status(
        config: AppConfig, library_id: str
    ) -> tuple[Literal["ready", "unavailable", "integrity_error"], str | None]:
        database = config.store / "doc-evidence.sqlite"
        legacy = config.store / "catalog.sqlite"
        if not database.is_file():
            if legacy.is_file():
                return "ready", "legacy catalog will be adopted on first open"
            return "unavailable", "inventory is required before this library can open"
        try:
            connection = sqlite3.connect(
                f"file:{database.resolve().as_posix()}?mode=ro", uri=True
            )
            try:
                row = connection.execute(
                    "SELECT library_id FROM library_metadata WHERE singleton = 1"
                ).fetchone()
                integrity = str(
                    connection.execute("PRAGMA integrity_check").fetchone()[0]
                )
            finally:
                connection.close()
        except sqlite3.Error:
            return "integrity_error", "the library database cannot be validated"
        if row is None or str(row[0]) != library_id:
            return "integrity_error", "descriptor and database identity disagree"
        if integrity != "ok":
            return "integrity_error", "the library database integrity check failed"
        return "ready", None

    def _resolve(self, known: KnownLibrary) -> _ResolvedLibrary:
        try:
            config = self._config(known)
            status, detail = self._database_status(config, known.library_id)
            return _ResolvedLibrary(known, config, status, detail)
        except DocEvidenceError:
            return _ResolvedLibrary(
                known,
                None,
                "integrity_error",
                "the registered descriptor or configuration cannot be opened",
            )

    def _summary(self, resolved: _ResolvedLibrary) -> KnownLibrarySummary:
        active, default, _last = self._active_ids()
        return KnownLibrarySummary(
            library_id=resolved.known.library_id,
            name=resolved.known.name,
            store_mode=resolved.known.store_mode,
            collection_count=(
                len(resolved.config.collections) if resolved.config is not None else 0
            ),
            last_opened_at=resolved.known.last_opened_at,
            status=resolved.status,
            status_detail=resolved.detail,
            is_default=resolved.known.library_id == default,
            is_active=resolved.known.library_id == active,
        )

    def app_summary(self) -> AppSummary:
        active, default, last = self._active_ids()
        return AppSummary(
            active_library_id=active,
            default_library_id=default,
            last_library_id=last,
        )

    def libraries(self) -> KnownLibraryList:
        return KnownLibraryList(
            items=[self._summary(self._resolve(known)) for known in self._known()]
        )

    def library(self, library_id: str) -> LibraryDetail:
        known = next(
            (item for item in self._known() if item.library_id == library_id),
            None,
        )
        if known is None:
            raise NotFoundError("library was not found")
        resolved = self._resolve(known)
        collections = (
            [
                LibraryCollection(
                    collection_id=collection.id,
                    source_label=collection.source.name or collection.id,
                    available=collection.source.is_dir(),
                )
                for collection in resolved.config.collections
            ]
            if resolved.config is not None
            else []
        )
        return LibraryDetail(
            library=self._summary(resolved),
            collections=collections,
            collection_preflight_kinds=PREFLIGHT_KINDS,
        )

    def activate(self, library_id: str) -> LibraryActivation:
        detail = self.library(library_id)
        if detail.library.status != "ready":
            raise ApplicationStateError(
                detail.library.status_detail or "library is unavailable"
            )
        if self.registry is not None:
            self.registry.activate(library_id)
        return LibraryActivation(active_library_id=library_id)

    def application(self, library_id: str) -> LibraryApplication:
        cached = self._applications.get(library_id)
        if cached is not None:
            return cached
        detail = self.library(library_id)
        if detail.library.status not in {"ready"}:
            raise ApplicationStateError(
                detail.library.status_detail or "library is unavailable"
            )
        known = next(item for item in self._known() if item.library_id == library_id)
        config = self._config(known)
        application = LibraryApplication(
            LocalWorkspace(
                config,
                library_id=known.library_id,
                library_name=known.name,
            )
        )
        self._applications[library_id] = application
        return application

    def jobs(self, library_id: str) -> LocalExtractionJobs:
        cached = self._jobs.get(library_id)
        if cached is not None:
            return cached
        detail = self.library(library_id)
        if detail.library.status != "ready":
            raise ApplicationStateError(
                detail.library.status_detail or "library is unavailable"
            )
        known = next(item for item in self._known() if item.library_id == library_id)
        config = self._config(known)
        database = ensure_library_database(
            config,
            library_id=library_id,
            name=known.name,
        )
        service = LocalExtractionJobs(
            library_id=library_id,
            config=config,
            database=database,
        )
        self._jobs[library_id] = service
        return service

    def start_jobs(self, library_id: str) -> bool:
        scheduler = self._schedulers.get(library_id)
        if scheduler is not None:
            return scheduler.running
        scheduler = LibraryScheduler(self.jobs(library_id))
        started = scheduler.start()
        if started:
            self._schedulers[library_id] = scheduler
        return started

    def cancel_job(self, library_id: str, job_id: str) -> JobRecord:
        scheduler = self._schedulers.get(library_id)
        if scheduler is not None and scheduler.running:
            scheduler.cancel(job_id)
            return self.jobs(library_id).get(job_id)
        return self.jobs(library_id).cancel(job_id)

    def cancel_batch(
        self, library_id: str, batch_id: str, *, cancel_running: bool
    ) -> BatchCancellation:
        service = self.jobs(library_id)
        for job in service.batch_jobs(batch_id):
            if job.state == "queued" or (
                cancel_running and job.state in {"starting", "running", "cancelling"}
            ):
                self.cancel_job(library_id, job.job_id)
        return BatchCancellation(
            batch=service.batch(batch_id),
            jobs=service.batch_jobs(batch_id),
            cancel_running=cancel_running,
        )

    def shutdown(self) -> None:
        for scheduler in list(self._schedulers.values()):
            scheduler.stop()
        self._schedulers.clear()
