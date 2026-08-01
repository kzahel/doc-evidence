# Development

## Runtime

Use Python 3.12 for the initial extractor compatibility matrix. The host's
default Python may be newer; `uv` should manage the project interpreter.

```sh
uv sync
uv run doc-evidence doctor
uv run python -m unittest discover -s tests
```

## Dependency Policy

The core should remain small. Add large PDF, OCR, ML, or database packages
behind optional dependency groups or external-tool adapters. Document system
dependencies and model downloads in the adapter.

Initial external-tool expectations:

- `pdfinfo`, `pdftotext`, and `pdftoppm` for the Poppler baseline;
- `ocrmypdf`, Tesseract, and supporting language packs for OCR; and
- optional Python/model environments for Docling and Marker.

## Adapter Development

An adapter must:

- declare capabilities and dependencies;
- produce a stable run description;
- record the exact invocation/configuration;
- preserve stderr, warnings, and failure details;
- avoid mutating sources;
- write only within the configured artifact store; and
- return page-aware output when the source format supports pages.

## Tests

Run standard-library tests with:

```sh
PYTHONPATH=src python -m unittest discover -s tests
```

Integration tests requiring external tools should detect missing dependencies
and report a skip rather than silently changing behavior.
