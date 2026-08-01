# doc-evidence

`doc-evidence` is a local-first pipeline for indexing documents, comparing
extractors, preserving provenance, and promoting reviewed observations into
downstream structured-data systems.

The project is intentionally domain-neutral. Its first real downstream case is
a private U.S.–Swiss tax workspace, but private documents and case-specific
facts do not belong in this Git repository.

## Status

Phases 1 and 2 are implemented. In addition to deterministic inventory,
content-addressed Poppler extraction, duplicate detection, and SQLite/FTS
search, the tool can run OCRmyPDF/Tesseract, Docling, and Marker as isolated
experts; preserve each raw output; flag page- and number-level disagreements;
and generate a local human-calibration review pack and scorecard.

The next product milestone is a Python-backed localhost application with a
React/TypeScript interface for browsing the cached library, comparing
extractor output, and preserving durable human review decisions. The same
contracts should support future offline Tauri packaging.

The first proposed implementation slice is
[Tactical 000: read-only library and extractor comparison](docs/tactical/000-read-only-library-comparison.md).
It deliberately stops before durable review writes, pipeline execution, and
desktop packaging.

Read these first:

1. [Product vision and application architecture](docs/product-vision-and-architecture.md)
2. [Master plan](docs/master-plan.md)
3. [Living topics](docs/topics/README.md)
4. [Implementation tacticals](docs/tactical/README.md)
5. [Architecture](docs/architecture.md)
6. [Data contracts](docs/data-contracts.md)
7. [Benchmark plan](docs/benchmarking.md)
8. [References](docs/references.md)
9. [Operations](docs/operations.md)

## Core Principles

- Source documents are read-only.
- Every document is identified by a cryptographic content hash.
- Extraction outputs are derived, versioned, and reproducible.
- Candidate observations retain document and page provenance.
- Automated observations are never silently promoted to accepted facts.
- SQLite is a rebuildable catalog, not the sole home of review decisions.
- Extractors are adapters behind a stable contract.
- Use a fast deterministic baseline and escalate only difficult documents.
- Keep private datasets outside the Git repository.

## Development

This project targets Python 3.12 because current document/ML libraries may lag
the newest Python release. With `uv` installed:

```sh
uv sync
uv run doc-evidence doctor
uv run python -m unittest discover -s tests
```

The diagnostic command reports which external tools are currently available:

```sh
uv run doc-evidence doctor --json
```

Optional Docling and Marker environments can be created with the pinned local
bootstrap script after their system dependencies are available:

```sh
./scripts/bootstrap-phase2-extractors.sh
```

The first-class web application is planned but not implemented. Do not expect
the proposed `serve` command or `web/` workspace until Tactical 000 lands.

## Commands

Current commands:

```text
doc-evidence doctor
doc-evidence config-check --config PATH
doc-evidence inventory --config PATH [COLLECTION ...]
doc-evidence search --config PATH QUERY [--mode literal|fts]
doc-evidence duplicates --config PATH
doc-evidence benchmark-check --suite PATH
doc-evidence benchmark-run --config PATH --suite PATH
doc-evidence benchmark-score --report PATH --review PATH
```

`inventory` includes the Phase 1 Poppler extraction step. `benchmark-run`
invokes only the experts named by a private suite. It never treats agreement
as truth or changes a production extraction policy automatically.

## Configuration

Case configuration stays with the case, not this repository. See
[`config.example.yaml`](config.example.yaml) and
[`schemas/config.schema.json`](schemas/config.schema.json).

Relative paths are resolved relative to the configuration file, making a case
workspace movable without teaching this tool its layout.

## Phase 1 Output

The configured store contains:

```text
catalog.sqlite
blobs/<hash-prefix>/<sha256>/
  metadata.json
  runs/poppler/<run-key>/
    run.json
    text.txt
    pages.json
    raw Poppler stdout/stderr
manifests/<inventory-run-id>/
  manifest.jsonl
  run.json
  summary.json
  duplicates.json
  errors.jsonl
```

The catalog is a rebuildable snapshot of the collections selected by the most
recent inventory command. Successful extraction artifacts are reused when the
source hash, Poppler versions, extraction configuration, and output schema are
unchanged.

Phase 2 adds extractor-specific runs below each content blob and private review
runs below `benchmarks/<suite-id>/runs/<benchmark-run-id>/`. The generated
`review.html` embeds its selected page renders, works as a self-contained local
file or constrained preview, and exports a JSON review overlay.
An unchanged five-document/four-expert private benchmark reuses all 20 cached
expert artifacts and completes in seconds; the initial model-backed pass takes
minutes and is intended only for a small representative suite.
