"""Domain-specific errors surfaced cleanly by the command-line interface."""


class DocEvidenceError(Exception):
    """Base class for expected operational failures."""


class ConfigError(DocEvidenceError):
    """Raised when a configuration file is missing, invalid, or unsafe."""


class DependencyError(DocEvidenceError):
    """Raised when an explicitly requested extractor dependency is missing."""


class CatalogError(DocEvidenceError):
    """Raised when a catalog cannot be created, read, or queried."""


class BenchmarkError(DocEvidenceError):
    """Raised when a benchmark suite or extractor run is invalid."""


class NotFoundError(DocEvidenceError):
    """Raised when a requested product identity is not present."""


class RequestError(DocEvidenceError):
    """Raised when a bounded user request is invalid."""


class ApplicationStateError(DocEvidenceError):
    """Raised when application-home or library registry state is invalid."""
