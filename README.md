# doc-evidence

`doc-evidence` is a local-first pipeline for indexing documents, comparing
extractors, preserving provenance, and promoting reviewed observations into
downstream structured-data systems.

The project is intentionally domain-neutral. Its first real downstream case is
a private U.S.–Swiss tax workspace, but private documents and case-specific
facts do not belong in this Git repository.

## Status

Phases 1 and 2 and the first read-only application slice are implemented. In
addition to deterministic inventory,
content-addressed Poppler extraction, duplicate detection, and SQLite/FTS
search, the tool can run OCRmyPDF/Tesseract, Docling, and Marker as isolated
experts; preserve each raw output; flag page- and number-level disagreements;
and generate a local human-calibration review pack and scorecard.

The repository now includes a Python-backed authenticated localhost
application with a React/TypeScript interface for browsing and searching the
cached library, opening rendered pages, grouping exact extractor output, and
reviewing versioned word/numeric comparisons. The approved next product
boundary is durable extraction jobs, atomic artifact publication, recovery,
and operational UI; durable human review state follows as a separate slice.

The implemented slice is
[Tactical 000: read-only library and extractor comparison](docs/tactical/000-read-only-library-comparison.md).
Its automated and private integration gates pass, but it remains open until
the maintainer explicitly accepts the live interaction. It stops before
durable review writes, pipeline execution, and desktop packaging.

The approved implementation plan for the next boundary is
[Tactical 001: durable extraction jobs and operational UI](docs/tactical/001-durable-extraction-jobs.md),
owned by the living [job architecture topic](docs/topics/job-architecture.md).
Implementation has not started.

Read these first:

1. [Product vision and application architecture](docs/product-vision-and-architecture.md)
2. [Master plan](docs/master-plan.md)
3. [Living topics](docs/topics/README.md)
4. [Durable job architecture](docs/topics/job-architecture.md)
5. [Implementation tacticals](docs/tactical/README.md)
6. [Architecture](docs/architecture.md)
7. [Data contracts](docs/data-contracts.md)
8. [Benchmark plan](docs/benchmarking.md)
9. [References](docs/references.md)
10. [Operations](docs/operations.md)

## Core Principles

- Source documents are read-only.
- Every document is identified by a cryptographic content hash.
- Extraction outputs are derived, versioned, and reproducible.
- Candidate observations retain document and page provenance.
- Automated observations are never silently promoted to accepted facts.
- Catalog projections remain rebuildable while job and future review state
  have separate durability policies inside one active workspace database.
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

Install and build the local application from a source checkout:

```sh
uv sync && npm ci --prefix web && npm run build --prefix web
```

Launch it against an external case configuration:

```sh
uv run doc-evidence serve --config /path/to/case.yaml
```

The launch command binds an ephemeral loopback port, opens a browser with an
in-memory credential, removes the credential from the displayed URL, and
never writes it to the case workspace.

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
doc-evidence serve --config PATH
doc-evidence benchmark-check --suite PATH
doc-evidence benchmark-run --config PATH --suite PATH
doc-evidence benchmark-score --report PATH --review PATH
```

`inventory` includes the Phase 1 Poppler extraction step. `benchmark-run`
invokes only the experts named by a private suite. It never treats agreement
as truth or changes a production extraction policy automatically.

Current routing limitation: ordinary inventory runs Poppler only for PDFs.
The configured `ocr_when` and `layout_when` values are validated and included
in cache/config identity, but they do not yet schedule OCR or layout jobs.
OCRmyPDF/Tesseract, Docling, and Marker outputs appear only for documents
explicitly processed by a benchmark suite. Standalone image files are indexed
but are not yet rendered or extracted by the read-only application.

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
