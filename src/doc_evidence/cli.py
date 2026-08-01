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
    return parser


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


def _print_inventory(config_path: Path, collections: list[str], as_json: bool) -> int:
    config = load_config(config_path)
    result = run_inventory(config, collections)
    output = {
        "run_id": result.run_id,
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
            return _print_inventory(args.config, args.collections, args.json)
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
    except DocEvidenceError as error:
        print(f"doc-evidence: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("doc-evidence: interrupted", file=sys.stderr)
        return 130

    return 2


if __name__ == "__main__":
    sys.exit(main())
