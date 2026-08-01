"""Command-line entry point for the initial doc-evidence scaffold."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from doc_evidence import __version__
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
)


def _doctor_report() -> dict[str, object]:
    return {
        "doc_evidence_version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "tools": {name: shutil.which(name) for name in EXTERNAL_TOOLS},
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
    except DocEvidenceError as error:
        print(f"doc-evidence: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("doc-evidence: interrupted", file=sys.stderr)
        return 130

    return 2


if __name__ == "__main__":
    sys.exit(main())
