"""Load, validate, normalize, and hash case-local YAML configuration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from doc_evidence.errors import ConfigError
from doc_evidence.util import hash_json


@dataclass(frozen=True)
class CollectionConfig:
    id: str
    source: Path
    include: tuple[str, ...]
    exclude: tuple[str, ...]


@dataclass(frozen=True)
class ExtractionConfig:
    baseline: str = "poppler"
    ocr_when: str = "image_only"
    layout_when: str = "complex"
    normalized_text_duplicates: bool = True

    def canonical(self) -> dict[str, object]:
        return {
            "baseline": self.baseline,
            "ocr_when": self.ocr_when,
            "layout_when": self.layout_when,
            "normalized_text_duplicates": self.normalized_text_duplicates,
        }


@dataclass(frozen=True)
class SearchConfig:
    sqlite_fts: bool = True
    vector_index: bool = False

    def canonical(self) -> dict[str, object]:
        return {
            "sqlite_fts": self.sqlite_fts,
            "vector_index": self.vector_index,
        }


@dataclass(frozen=True)
class AppConfig:
    path: Path
    schema_version: int
    collections: tuple[CollectionConfig, ...]
    store: Path
    languages: tuple[str, ...]
    extraction: ExtractionConfig
    search: SearchConfig
    config_hash: str
    extraction_config_hash: str

    def select_collections(
        self, requested: list[str] | tuple[str, ...]
    ) -> tuple[CollectionConfig, ...]:
        if not requested:
            return self.collections
        by_id = {collection.id: collection for collection in self.collections}
        unknown = sorted(set(requested) - set(by_id))
        if unknown:
            raise ConfigError(
                "unknown collection ID(s): "
                + ", ".join(unknown)
                + "; configured: "
                + ", ".join(sorted(by_id))
            )
        if len(set(requested)) != len(requested):
            raise ConfigError("collection IDs may not be repeated")
        return tuple(by_id[identifier] for identifier in requested)


def _load_schema() -> dict[str, Any]:
    schema_resource = resources.files("doc_evidence").joinpath(
        "schema_files/config.schema.json"
    )
    try:
        schema = json.loads(schema_resource.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    except (OSError, json.JSONDecodeError, SchemaError) as error:
        raise ConfigError(
            f"cannot load packaged configuration schema: {error}"
        ) from error
    return schema


def _validate(raw: object) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConfigError("configuration root must be a YAML mapping")
    validator = Draft202012Validator(_load_schema())
    errors = sorted(validator.iter_errors(raw), key=lambda item: list(item.path))
    if errors:
        messages = []
        for error in errors:
            location = ".".join(str(part) for part in error.absolute_path) or "<root>"
            messages.append(f"{location}: {error.message}")
        raise ConfigError("invalid configuration:\n  - " + "\n  - ".join(messages))
    return raw


def _resolve_path(base: Path, raw_path: str) -> Path:
    candidate = Path(raw_path).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    if not config_path.is_file():
        raise ConfigError(f"configuration file does not exist: {config_path}")

    try:
        raw_loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise ConfigError(
            f"cannot read YAML configuration {config_path}: {error}"
        ) from error
    raw = _validate(raw_loaded)
    base = config_path.parent

    collections: list[CollectionConfig] = []
    seen_ids: set[str] = set()
    for raw_collection in raw["collections"]:
        identifier = raw_collection["id"]
        if identifier in seen_ids:
            raise ConfigError(f"duplicate collection ID: {identifier}")
        seen_ids.add(identifier)
        source = _resolve_path(base, raw_collection["source"])
        if not source.is_dir():
            raise ConfigError(
                f"collection {identifier!r} source is not a directory: {source}"
            )
        collections.append(
            CollectionConfig(
                id=identifier,
                source=source,
                include=tuple(raw_collection.get("include", ["**/*"])),
                exclude=tuple(raw_collection.get("exclude", [])),
            )
        )

    store = _resolve_path(base, raw["store"]["path"])
    for collection in collections:
        if _paths_overlap(store, collection.source):
            raise ConfigError(
                "derived store and source collection may not overlap: "
                f"store={store}, collection={collection.id}:{collection.source}"
            )
    for index, left in enumerate(collections):
        for right in collections[index + 1 :]:
            if _paths_overlap(left.source, right.source):
                raise ConfigError(
                    "source collections may not overlap: "
                    f"{left.id}:{left.source}, {right.id}:{right.source}"
                )

    raw_extraction = raw.get("extraction", {})
    extraction = ExtractionConfig(
        baseline=raw_extraction.get("baseline", "poppler"),
        ocr_when=raw_extraction.get("ocr_when", "image_only"),
        layout_when=raw_extraction.get("layout_when", "complex"),
        normalized_text_duplicates=raw_extraction.get(
            "normalized_text_duplicates", True
        ),
    )
    if extraction.baseline != "poppler":
        raise ConfigError(
            "Phase 1 supports only extraction.baseline=poppler; "
            f"received {extraction.baseline!r}"
        )

    raw_search = raw.get("search", {})
    search = SearchConfig(
        sqlite_fts=raw_search.get("sqlite_fts", True),
        vector_index=raw_search.get("vector_index", False),
    )
    if search.vector_index:
        raise ConfigError("Phase 1 does not support a vector index")

    canonical = {
        "schema_version": raw["schema_version"],
        "collections": [
            {
                "id": collection.id,
                "source": str(collection.source),
                "include": list(collection.include),
                "exclude": list(collection.exclude),
            }
            for collection in collections
        ],
        "store": str(store),
        "languages": raw.get("languages", []),
        "extraction": extraction.canonical(),
        "search": search.canonical(),
    }

    return AppConfig(
        path=config_path,
        schema_version=raw["schema_version"],
        collections=tuple(collections),
        store=store,
        languages=tuple(raw.get("languages", [])),
        extraction=extraction,
        search=search,
        config_hash=hash_json(canonical),
        extraction_config_hash=hash_json(extraction.canonical()),
    )
