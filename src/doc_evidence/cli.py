"""Command-line entry point for the initial doc-evidence scaffold."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
from collections.abc import Sequence

from doc_evidence import __version__


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

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

    return 2


if __name__ == "__main__":
    sys.exit(main())
