"""Command-line entry point for the initial doc-evidence scaffold."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sqlite3
import sys
from collections.abc import Sequence
from pathlib import Path

from doc_evidence import __version__
from doc_evidence.app_home import LibraryRegistry, resolve_application_home
from doc_evidence.application.library_management import preflight_collection_root
from doc_evidence.benchmark import load_suite, run_benchmark, score_review
from doc_evidence.catalog import list_duplicate_groups, search_catalog
from doc_evidence.config import load_config
from doc_evidence.errors import DocEvidenceError
from doc_evidence.inventory import run_inventory

EXTERNAL_TOOLS = (
    "pdfinfo",
    "pdftotext",
    "pdftoppm",
    "ocrmypdf",
    "tesseract",
    "qpdf",
    "llama-server",
)


def _doctor_report() -> dict[str, object]:
    connection = sqlite3.connect(":memory:")
    try:
        try:
            connection.execute("CREATE VIRTUAL TABLE fts_probe USING fts5(text)")
        except sqlite3.Error:
            fts5_available = False
        else:
            fts5_available = True
    finally:
        connection.close()
    tools = {name: shutil.which(name) for name in EXTERNAL_TOOLS}
    repository_root = Path(__file__).parents[2]
    for name, relative in (
        ("docling", ".extractors/docling/bin/docling"),
        ("marker_single", ".extractors/marker/bin/marker_single"),
    ):
        local = repository_root / relative
        tools[name] = str(local.resolve()) if local.is_file() else shutil.which(name)
    return {
        "doc_evidence_version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "sqlite": {
            "version": sqlite3.sqlite_version,
            "fts5_available": fts5_available,
        },
        "tools": tools,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doc-evidence",
        description="Index and extract documents while preserving provenance.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor = subparsers.add_parser(
        "doctor",
        help="Report the Python runtime and available external document tools.",
    )
    doctor.add_argument(
        "--json",
        action="store_true",
        help="Emit a machine-readable JSON report.",
    )

    config_check = subparsers.add_parser(
        "config-check",
        help="Validate and summarize a case-local YAML configuration.",
    )
    config_check.add_argument("--config", required=True, type=Path)
    config_check.add_argument("--json", action="store_true")

    inventory = subparsers.add_parser(
        "inventory",
        help="Inventory collections and build derived artifacts and catalog.",
    )
    inventory.add_argument("--config", required=True, type=Path)
    inventory.add_argument(
        "collections",
        nargs="*",
        help="Collection IDs; omit to inventory every configured collection.",
    )
    inventory.add_argument(
        "--full-hash",
        action="store_true",
        help="Rehash every source instead of using strong local fingerprints.",
    )
    inventory.add_argument("--json", action="store_true")

    search = subparsers.add_parser(
        "search",
        help="Search page text in the latest SQLite catalog snapshot.",
    )
    search.add_argument("--config", required=True, type=Path)
    search.add_argument("query")
    search.add_argument(
        "--mode",
        choices=("literal", "fts"),
        default="literal",
        help="Literal substring search or SQLite FTS5 query syntax.",
    )
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--json", action="store_true")

    duplicates = subparsers.add_parser(
        "duplicates",
        help="List exact-byte and normalized-text duplicate groups.",
    )
    duplicates.add_argument("--config", required=True, type=Path)
    duplicates.add_argument("--json", action="store_true")

    suite_check = subparsers.add_parser(
        "benchmark-check",
        help="Validate and hash a private benchmark-suite YAML file.",
    )
    suite_check.add_argument("--suite", required=True, type=Path)
    suite_check.add_argument("--json", action="store_true")

    benchmark = subparsers.add_parser(
        "benchmark-run",
        help="Run extractors, compare outputs, and build a local review pack.",
    )
    benchmark.add_argument("--config", required=True, type=Path)
    benchmark.add_argument("--suite", required=True, type=Path)
    benchmark.add_argument("--json", action="store_true")

    score = subparsers.add_parser(
        "benchmark-score",
        help="Score a human review by extractor and document class.",
    )
    score.add_argument("--report", required=True, type=Path)
    score.add_argument("--review", required=True, type=Path)
    score.add_argument("--json", action="store_true")

    serve = subparsers.add_parser(
        "serve",
        help="Launch the authenticated local library and comparison application.",
    )
    serve.add_argument(
        "--config",
        type=Path,
        help="Explicit compatibility config; omit to open the last/default library.",
    )
    serve.add_argument(
        "--frontend-dir",
        type=Path,
        help="Override the built frontend directory (defaults to web/dist).",
    )
    serve.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open a browser (the launch token is never printed).",
    )

    library_register = subparsers.add_parser(
        "library-register",
        help="Register an existing external configuration in the application home.",
    )
    library_register.add_argument("--config", required=True, type=Path)
    library_register.add_argument("--name")
    library_register.add_argument(
        "--no-default",
        action="store_true",
        help="Register without replacing the default library selection.",
    )
    library_register.add_argument("--json", action="store_true")

    libraries = subparsers.add_parser(
        "libraries",
        help="List libraries known to the resolved application home.",
    )
    libraries.add_argument("--json", action="store_true")

    library_activate = subparsers.add_parser(
        "library-activate",
        help="Select a registered library for ordinary startup.",
    )
    library_activate.add_argument("library_id")
    library_activate.add_argument("--default", action="store_true")
    library_activate.add_argument("--json", action="store_true")

    collection_preflight = subparsers.add_parser(
        "collection-preflight",
        help="Classify a proposed collection root without changing library scope.",
    )
    collection_preflight.add_argument("--config", required=True, type=Path)
    collection_preflight.add_argument("--source", required=True, type=Path)
    collection_preflight.add_argument("--json", action="store_true")
    return parser


def _registry() -> LibraryRegistry:
    return LibraryRegistry(resolve_application_home())


def _print_library_register(
    config_path: Path,
    name: str | None,
    make_default: bool,
    as_json: bool,
) -> int:
    registry = _registry()
    descriptor = registry.register_config(
        config_path,
        name=name,
        make_default=make_default,
    )
    output = {
        **descriptor.value(),
        "descriptor_path": str(descriptor.descriptor_path),
        "application_home": str(registry.home.root),
        "application_home_source": registry.home.source,
    }
    if as_json:
        print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Registered library {descriptor.name}: {descriptor.library_id}")
        print(f"Descriptor: {descriptor.descriptor_path}")
        print(f"Application home: {registry.home.root}")
    return 0


def _print_libraries(as_json: bool) -> int:
    registry = _registry()
    state = registry.load()
    output = {
        "application_home": str(registry.home.root),
        "application_home_source": registry.home.source,
        **state.value(),
    }
    if as_json:
        print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Application home: {registry.home.root}")
        for library in state.libraries:
            markers = []
            if library.library_id == state.default_library_id:
                markers.append("default")
            if library.library_id == state.last_library_id:
                markers.append("last")
            suffix = f" ({', '.join(markers)})" if markers else ""
            print(f"{library.library_id}  {library.name}{suffix}")
        print(f"{len(state.libraries)} library/libraries")
    return 0


def _print_library_activate(library_id: str, make_default: bool, as_json: bool) -> int:
    registry = _registry()
    state = registry.activate(library_id, make_default=make_default)
    output = {
        "library_id": library_id,
        "default_library_id": state.default_library_id,
        "last_library_id": state.last_library_id,
    }
    if as_json:
        print(json.dumps(output, indent=2, sort_keys=True))
    else:
        print(f"Activated library: {library_id}")
    return 0


def _print_collection_preflight(
    config_path: Path,
    source: Path,
    as_json: bool,
) -> int:
    result = preflight_collection_root(load_config(config_path), source)
    output = {
        "kind": result.kind,
        "candidate": str(result.candidate),
        "affected_collection_ids": list(result.affected_collection_ids),
        "message": result.message,
    }
    if as_json:
        print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Outcome: {result.kind}")
        print(f"Candidate: {result.candidate}")
        if result.affected_collection_ids:
            print(f"Affected: {', '.join(result.affected_collection_ids)}")
        print(result.message)
    if result.kind in {"store_overlap", "unavailable"}:
        return 1
    return 0


def _print_config(config_path: Path, as_json: bool) -> int:
    config = load_config(config_path)
    output = {
        "schema_version": config.schema_version,
        "config_path": str(config.path),
        "config_hash": config.config_hash,
        "store": str(config.store),
        "collections": [
            {
                "id": collection.id,
                "source": str(collection.source),
                "include": list(collection.include),
                "exclude": list(collection.exclude),
            }
            for collection in config.collections
        ],
        "extraction": config.extraction.canonical(),
        "search": config.search.canonical(),
    }
    if as_json:
        print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Configuration valid: {config.path}")
        print(f"Config hash: {config.config_hash}")
        print(f"Store: {config.store}")
        for collection in config.collections:
            print(f"Collection {collection.id}: {collection.source}")
    return 0


def _print_inventory(
    config_path: Path,
    collections: list[str],
    full_hash: bool,
    as_json: bool,
) -> int:
    config = load_config(config_path)
    result = run_inventory(
        config,
        collections,
        full_hash_verification=full_hash,
    )
    output = {
        "run_id": result.run_id,
        "generation_id": result.generation_id,
        "collections": result.collection_ids,
        "manifest": str(result.manifest_path),
        "catalog": str(result.catalog_path),
        "summary": result.summary,
    }
    if as_json:
        print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Inventory complete: {result.run_id}")
        print(f"Manifest: {result.manifest_path}")
        print(f"Catalog: {result.catalog_path}")
        for key, value in result.summary.items():
            print(f"  {key}: {value}")
    return 1 if result.errors else 0


def _print_search(
    config_path: Path,
    query: str,
    mode: str,
    limit: int,
    as_json: bool,
) -> int:
    if limit < 1 or limit > 1000:
        raise DocEvidenceError("search limit must be between 1 and 1000")
    config = load_config(config_path)
    results = search_catalog(config.store, query, mode, limit)
    output = [
        {
            "document_id": result.document_id,
            "page": result.page_number,
            "paths": list(result.paths),
            "snippet": result.snippet,
            "score": result.score,
        }
        for result in results
    ]
    if as_json:
        print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        for result in results:
            paths = ", ".join(result.paths)
            print(f"{result.document_id[:23]}… page {result.page_number} — {paths}")
            print(f"  {result.snippet}")
        print(f"{len(results)} result(s)")
    return 0


def _print_duplicates(config_path: Path, as_json: bool) -> int:
    config = load_config(config_path)
    groups = list_duplicate_groups(config.store)
    if as_json:
        print(json.dumps(groups, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        for group in groups:
            print(f"{group['kind']} {group['group_key']}")
            for member in group["members"]:
                print(f"  {member['document_id']}")
                for path in member["paths"]:
                    print(f"    {path}")
        print(f"{len(groups)} duplicate group(s)")
    return 0


def _print_benchmark_check(suite_path: Path, as_json: bool) -> int:
    suite, suite_hash = load_suite(suite_path)
    output = {
        "suite_id": suite["suite_id"],
        "suite_hash": suite_hash,
        "documents": len(suite["documents"]),
        "extractors": suite["extractors"],
    }
    if as_json:
        print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Benchmark suite valid: {suite['suite_id']}")
        print(f"Suite hash: {suite_hash}")
        print(f"Documents: {len(suite['documents'])}")
        print("Extractors: " + ", ".join(suite["extractors"]))
    return 0


def _print_benchmark(config_path: Path, suite_path: Path, as_json: bool) -> int:
    result = run_benchmark(load_config(config_path), suite_path)
    output = {
        "benchmark_run_id": result.run_id,
        "run_dir": str(result.run_dir),
        "report": str(result.report_path),
        "review_template": str(result.review_path),
        "review_html": str(result.html_path),
        "summary": result.summary,
    }
    if as_json:
        print(json.dumps(output, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Benchmark complete: {result.run_id}")
        print(f"Report: {result.report_path}")
        print(f"Review UI: {result.html_path}")
        for key, value in result.summary.items():
            print(f"  {key}: {value}")
    return 1 if result.summary["extractor_failures"] else 0


def _print_score(report_path: Path, review_path: Path, as_json: bool) -> int:
    output_path, scorecard = score_review(report_path, review_path)
    if as_json:
        print(json.dumps(scorecard, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(f"Scorecard: {output_path}")
        for item in scorecard["scorecards"]:
            print(
                f"  {item['document_class']} / {item['extractor_id']}: "
                f"{item['combined_mean']:.3f} across {item['reviewed_pages']} page(s) — "
                f"{item['recommendation']}"
            )
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            report = _doctor_report()
            if args.json:
                print(json.dumps(report, indent=2, sort_keys=True))
            else:
                print(f"doc-evidence {report['doc_evidence_version']}")
                print(f"Python: {report['python']}")
                print(f"Platform: {report['platform']}")
                sqlite_report = report["sqlite"]
                assert isinstance(sqlite_report, dict)
                print(
                    "SQLite: "
                    f"{sqlite_report['version']} "
                    f"(FTS5: {sqlite_report['fts5_available']})"
                )
                print("External tools:")
                tools = report["tools"]
                assert isinstance(tools, dict)
                for name, path in tools.items():
                    print(f"  {name}: {path or 'not found'}")
            return 0
        if args.command == "config-check":
            return _print_config(args.config, args.json)
        if args.command == "inventory":
            return _print_inventory(
                args.config,
                args.collections,
                args.full_hash,
                args.json,
            )
        if args.command == "search":
            return _print_search(
                args.config,
                args.query,
                args.mode,
                args.limit,
                args.json,
            )
        if args.command == "duplicates":
            return _print_duplicates(args.config, args.json)
        if args.command == "benchmark-check":
            return _print_benchmark_check(args.suite, args.json)
        if args.command == "benchmark-run":
            return _print_benchmark(args.config, args.suite, args.json)
        if args.command == "benchmark-score":
            return _print_score(args.report, args.review, args.json)
        if args.command == "library-register":
            return _print_library_register(
                args.config,
                args.name,
                not args.no_default,
                args.json,
            )
        if args.command == "libraries":
            return _print_libraries(args.json)
        if args.command == "library-activate":
            return _print_library_activate(
                args.library_id,
                args.default,
                args.json,
            )
        if args.command == "collection-preflight":
            return _print_collection_preflight(
                args.config,
                args.source,
                args.json,
            )
        if args.command == "serve":
            from doc_evidence.server import serve_local

            if args.config is not None:
                config = load_config(args.config)
                registry = None
                library_id = None
                library_name = None
            else:
                registry = _registry()
                state = registry.load()
                if state.libraries:
                    known, _descriptor, config = registry.selected()
                    library_id = known.library_id
                    library_name = known.name
                else:
                    config = None
                    library_id = None
                    library_name = None
            return serve_local(
                config,
                library_registry=registry,
                library_id=library_id,
                library_name=library_name,
                frontend_dir=args.frontend_dir,
                open_browser=not args.no_open,
            )
    except DocEvidenceError as error:
        print(f"doc-evidence: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("doc-evidence: interrupted", file=sys.stderr)
        return 130

    return 2


if __name__ == "__main__":
    sys.exit(main())
