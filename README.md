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

Read these first:

1. [Master plan](docs/master-plan.md)
2. [Architecture](docs/architecture.md)
3. [Data contracts](docs/data-contracts.md)
4. [Benchmark plan](docs/benchmarking.md)
5. [Operations](docs/operations.md)

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
`review.html` works locally in a browser and exports a JSON review overlay.
An unchanged five-document/four-expert private benchmark reuses all 20 cached
expert artifacts and completes in seconds; the initial model-backed pass takes
minutes and is intended only for a small representative suite.
