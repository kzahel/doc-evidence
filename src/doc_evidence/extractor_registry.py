"""Typed server-owned extractor capabilities and bounded settings validation."""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from doc_evidence.errors import DependencyError, RequestError
from doc_evidence.extraction import command_version

ResourceClass = Literal["light", "ocr", "model_heavy"]


@dataclass(frozen=True)
class DependencySpec:
    name: str
    executable: str
    version_arguments: tuple[str, ...]
    repo_relative: str | None = None
    version_sibling: str | None = None

    def resolve(self) -> Path | None:
        if self.repo_relative is not None:
            local = Path(__file__).parents[2] / self.repo_relative
            if local.is_file():
                return local.resolve()
        found = shutil.which(self.executable)
        return Path(found).resolve() if found else None


@dataclass(frozen=True)
class DependencyCapability:
    name: str
    available: bool
    version: str | None
    reason: str | None

    def value(self) -> dict[str, object]:
        return {
            "name": self.name,
            "available": self.available,
            "version": self.version,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ExtractorSpec:
    extractor_id: str
    display_name: str
    category: Literal["native_text", "ocr_preprocessing", "layout_parser", "other"]
    supported_media_types: tuple[str, ...]
    dependencies: tuple[DependencySpec, ...]
    resource_class: ResourceClass
    settings_schema: dict[str, Any]
    default_timeout_seconds: int
    deterministic: bool
    output_kinds: tuple[str, ...]


@dataclass(frozen=True)
class ExtractorCapability:
    spec: ExtractorSpec
    dependencies: tuple[DependencyCapability, ...]

    @property
    def available(self) -> bool:
        return all(item.available for item in self.dependencies)

    @property
    def version_label(self) -> str | None:
        versions = [item.version for item in self.dependencies if item.version]
        return " / ".join(versions) if versions else None

    def value(self) -> dict[str, object]:
        return {
            "extractor_id": self.spec.extractor_id,
            "display_name": self.spec.display_name,
            "category": self.spec.category,
            "supported_media_types": list(self.spec.supported_media_types),
            "dependencies": [item.value() for item in self.dependencies],
            "available": self.available,
            "version_label": self.version_label,
            "resource_class": self.spec.resource_class,
            "settings_schema": self.spec.settings_schema,
            "default_timeout_seconds": self.spec.default_timeout_seconds,
            "deterministic": self.spec.deterministic,
            "output_kinds": list(self.spec.output_kinds),
        }


@dataclass(frozen=True)
class ExtractorExecution:
    extractor_id: str
    settings: dict[str, Any]
    timeout_seconds: int
    resource_class: ResourceClass
    deterministic: bool


@dataclass(frozen=True)
class PreparedExtraction:
    execution: ExtractorExecution
    descriptor: dict[str, Any]
    run_key: str
    run_id: str


_LANGUAGE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{1,15}$")


def _language_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "languages": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "uniqueItems": True,
                "items": {"type": "string", "pattern": _LANGUAGE.pattern},
            }
        },
    }


def _empty_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {},
    }


DEFAULT_EXTRACTORS = (
    ExtractorSpec(
        extractor_id="poppler",
        display_name="Poppler native text",
        category="native_text",
        supported_media_types=("application/pdf",),
        dependencies=(
            DependencySpec("pdfinfo", "pdfinfo", ("-v",)),
            DependencySpec("pdftotext", "pdftotext", ("-v",)),
        ),
        resource_class="light",
        settings_schema=_empty_schema(),
        default_timeout_seconds=240,
        deterministic=True,
        output_kinds=("normalized_page_text", "pdf_metadata", "raw_logs"),
    ),
    ExtractorSpec(
        extractor_id="ocrmypdf-tesseract",
        display_name="OCRmyPDF + Tesseract",
        category="ocr_preprocessing",
        supported_media_types=("application/pdf",),
        dependencies=(
            DependencySpec("ocrmypdf", "ocrmypdf", ("--version",)),
            DependencySpec("tesseract", "tesseract", ("--version",)),
            DependencySpec("pdfinfo", "pdfinfo", ("-v",)),
            DependencySpec("pdftotext", "pdftotext", ("-v",)),
        ),
        resource_class="ocr",
        settings_schema=_language_schema(),
        default_timeout_seconds=1_200,
        deterministic=True,
        output_kinds=(
            "normalized_page_text",
            "searchable_pdf",
            "ocr_sidecar",
            "raw_logs",
        ),
    ),
    ExtractorSpec(
        extractor_id="tesseract-raster",
        display_name="Tesseract raster OCR",
        category="ocr_preprocessing",
        supported_media_types=("image/jpeg", "image/png", "image/tiff"),
        dependencies=(DependencySpec("tesseract", "tesseract", ("--version",)),),
        resource_class="ocr",
        settings_schema=_language_schema(),
        default_timeout_seconds=900,
        deterministic=True,
        output_kinds=("normalized_page_text", "tsv", "raw_logs"),
    ),
    ExtractorSpec(
        extractor_id="docling-standard",
        display_name="Docling standard layout",
        category="layout_parser",
        supported_media_types=("application/pdf",),
        dependencies=(
            DependencySpec(
                "docling",
                "docling",
                ("--version",),
                repo_relative=".extractors/docling/bin/docling",
            ),
        ),
        resource_class="model_heavy",
        settings_schema=_empty_schema(),
        default_timeout_seconds=1_800,
        deterministic=True,
        output_kinds=("normalized_page_text", "tables", "raw_document"),
    ),
    ExtractorSpec(
        extractor_id="marker-fast",
        display_name="Marker fast layout",
        category="layout_parser",
        supported_media_types=("application/pdf",),
        dependencies=(
            DependencySpec(
                "marker_single",
                "marker_single",
                (
                    "-c",
                    "import importlib.metadata as m; print(m.version('marker-pdf'))",
                ),
                repo_relative=".extractors/marker/bin/marker_single",
                version_sibling="python",
            ),
        ),
        resource_class="model_heavy",
        settings_schema=_empty_schema(),
        default_timeout_seconds=1_800,
        deterministic=True,
        output_kinds=("normalized_page_text", "tables", "raw_document"),
    ),
)


class ExtractorRegistry:
    def __init__(self, specs: tuple[ExtractorSpec, ...] = DEFAULT_EXTRACTORS):
        self._specs = {spec.extractor_id: spec for spec in specs}
        if len(self._specs) != len(specs):
            raise ValueError("extractor registry repeats an identifier")
        self._capabilities: dict[str, ExtractorCapability] = {}

    def spec(self, extractor_id: str) -> ExtractorSpec:
        try:
            return self._specs[extractor_id]
        except KeyError as error:
            raise RequestError(f"unknown extractor: {extractor_id}") from error

    def capability(self, extractor_id: str) -> ExtractorCapability:
        cached = self._capabilities.get(extractor_id)
        if cached is not None:
            return cached
        spec = self.spec(extractor_id)
        dependencies: list[DependencyCapability] = []
        for dependency in spec.dependencies:
            executable = dependency.resolve()
            if executable is None:
                dependencies.append(
                    DependencyCapability(
                        name=dependency.name,
                        available=False,
                        version=None,
                        reason=f"{dependency.name} is not installed",
                    )
                )
                continue
            version_executable = (
                executable.parent / dependency.version_sibling
                if dependency.version_sibling is not None
                else executable
            )
            version = command_version(
                [str(version_executable), *dependency.version_arguments],
                timeout_seconds=120,
            )
            dependencies.append(
                DependencyCapability(
                    name=dependency.name,
                    available=True,
                    version=version,
                    reason=None,
                )
            )
        capability = ExtractorCapability(spec, tuple(dependencies))
        self._capabilities[extractor_id] = capability
        return capability

    def capabilities(self) -> tuple[ExtractorCapability, ...]:
        return tuple(self.capability(identifier) for identifier in self._specs)

    def execution(
        self,
        *,
        extractor_id: str,
        media_type: str,
        settings: dict[str, Any],
        default_languages: tuple[str, ...] = (),
    ) -> ExtractorExecution:
        spec = self.spec(extractor_id)
        capability = self.capability(extractor_id)
        if not capability.available:
            missing = ", ".join(
                item.name for item in capability.dependencies if not item.available
            )
            raise DependencyError(f"extractor dependencies are unavailable: {missing}")
        if media_type not in spec.supported_media_types:
            raise RequestError(
                f"extractor {extractor_id} does not support media type {media_type}"
            )
        allowed = set(spec.settings_schema["properties"])
        if set(settings) - allowed:
            raise RequestError("extractor settings contain unsupported fields")
        normalized: dict[str, Any] = {}
        if "languages" in allowed:
            raw_languages = settings.get(
                "languages", list(default_languages) or ["eng"]
            )
            if (
                not isinstance(raw_languages, list)
                or not 1 <= len(raw_languages) <= 8
                or len(set(raw_languages)) != len(raw_languages)
                or not all(
                    isinstance(item, str) and _LANGUAGE.fullmatch(item)
                    for item in raw_languages
                )
            ):
                raise RequestError("extractor languages are invalid")
            normalized["languages"] = raw_languages
        return ExtractorExecution(
            extractor_id=extractor_id,
            settings=normalized,
            timeout_seconds=spec.default_timeout_seconds,
            resource_class=spec.resource_class,
            deterministic=spec.deterministic,
        )

    def prepare(
        self,
        *,
        extractor_id: str,
        media_type: str,
        settings: dict[str, Any],
        extraction_config_hash: str,
        default_languages: tuple[str, ...] = (),
    ) -> PreparedExtraction:
        """Resolve the exact canonical identity without launching extraction."""

        execution = self.execution(
            extractor_id=extractor_id,
            media_type=media_type,
            settings=settings,
            default_languages=default_languages,
        )
        from doc_evidence.docling_adapter import DoclingExtractor
        from doc_evidence.marker_adapter import MarkerExtractor
        from doc_evidence.ocrmypdf_adapter import OcrMyPdfExtractor
        from doc_evidence.poppler import PopplerExtractor
        from doc_evidence.tesseract_raster_adapter import TesseractRasterExtractor

        languages = tuple(str(item) for item in execution.settings.get("languages", []))
        if extractor_id == "poppler":
            adapter = PopplerExtractor(
                extraction_config_hash,
                timeout_seconds=execution.timeout_seconds,
            )
        elif extractor_id == "ocrmypdf-tesseract":
            adapter = OcrMyPdfExtractor(
                languages=languages,
                timeout_seconds=execution.timeout_seconds,
            )
        elif extractor_id == "tesseract-raster":
            adapter = TesseractRasterExtractor(
                languages=languages,
                timeout_seconds=execution.timeout_seconds,
            )
        elif extractor_id == "docling-standard":
            adapter = DoclingExtractor(timeout_seconds=execution.timeout_seconds)
        elif extractor_id == "marker-fast":
            adapter = MarkerExtractor(timeout_seconds=execution.timeout_seconds)
        else:  # pragma: no cover - execution() rejects unknown identifiers
            raise RequestError(f"unknown extractor: {extractor_id}")
        return PreparedExtraction(
            execution=execution,
            descriptor=dict(adapter.descriptor),
            run_key=adapter.run_key,
            run_id=adapter.run_id,
        )
