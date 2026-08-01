# Architecture

This document describes the existing extraction and evidence core. The
approved application direction, user experience, deployment path, and
Python/React boundary are defined in
[Product vision and application architecture](product-vision-and-architecture.md).
Current implementation posture is maintained in
[Application platform](topics/application-platform.md), and the closest
reviewed sibling precedent is recorded in [References](references.md).

## System Boundary

`doc-evidence` reads explicitly configured external collections and writes only
to an explicitly configured derived-artifact store. It does not reorganize,
rename, annotate, OCR-replace, or otherwise mutate source files.

```text
external collections (read-only)
        |
        v
inventory -> extractor adapters -> normalized artifacts -> observations
        |             |                    |                 |
        +-------------+--------------------+-----------------+
                              |
                              v
                 content-addressed file store
                              +
                   rebuildable SQLite catalog
                              |
                              v
                   external review overlays
                              |
                              v
                   downstream domain adapters
```

The first-class application adds a local interface without changing the
source or artifact boundaries:

```text
React + TypeScript UI
        |
        v
Python localhost API and job service
        |
        +-- durable workspace state
        +-- rebuildable catalog
        +-- content-addressed artifacts
        +-- configured read-only collections
        +-- isolated extraction subprocesses
```

Frontend request and response types are generated from Python-owned API
contracts. A future Tauri shell should launch and supervise the same local API
rather than introduce a separate desktop data model.

## Content Identity

The canonical content identity is `sha256:<hex digest>`. A source path is an
observation about where content was found, not its identity. One content object
may have multiple path aliases within or across configured collections.

Normalized-text hashes may identify content-equivalent documents, but they do
not replace the byte hash. Normalization algorithms must be versioned.

## Artifact Identity

An extraction artifact is identified by at least:

- source SHA-256;
- extractor name and version;
- relevant extractor configuration hash;
- normalization version; and
- output-schema version.

This makes cache invalidation explicit and permits side-by-side extractor
comparisons.

## Storage

The artifact store contains inspectable immutable successful run outputs under
`blobs/<hash-prefix>/<sha256>/runs/<extractor>/<run-key>/`. A SQLite catalog
projects those artifacts into convenient metadata, relationships, and
full-text tables. The database may be deleted and rebuilt from the source
collections and artifact sidecars.

Human review decisions are not extractor artifacts. They belong in a durable
review overlay that can refer to observations and source hashes while
surviving re-extraction.

Private benchmark reports and reviews live below
`benchmarks/<suite-id>/runs/<benchmark-run-id>/` in the external artifact store.
Extractor output remains under the content blob, so rerunning a suite reuses
an unchanged expert run while producing a new comparison/review snapshot.

## Components

### Configuration loader

- Resolves paths relative to the config file.
- Validates collection IDs and store boundaries.
- Produces a canonical configuration representation and hash.

### Inventory engine

- Traverses explicit collections.
- Records file metadata and SHA-256.
- Classifies media type by content where practical, not filename alone.
- Records read failures without stopping the full inventory.

### Extractor adapters

Each adapter declares:

- name and version;
- supported media types;
- required binaries, packages, models, or services;
- deterministic versus nondeterministic behavior;
- supported outputs; and
- invocation configuration included in its cache key.

Raw adapter output is retained. Normalizers create stable internal structures
without hiding information needed to diagnose failures.

Phase 2 adapters are deliberately independent experts:

- Poppler reads the existing text layer;
- OCRmyPDF/Tesseract creates a derived searchable PDF and then normalizes it
  through Poppler text extraction;
- Docling contributes document layout, reading order, and tables; and
- Marker contributes a separate block/layout/OCR pipeline.

No majority-vote merge is authoritative. Pairwise differences identify pages
for review; sparse verified assertions and human ratings establish accuracy.
Reliability is measured by document class because a parser's table performance
does not establish its scan or dense-form performance.

### Observation engine

Produces structured candidates tied to a document, page, and optional region.
It does not accept its own candidates. Promotion is a separate review action.

### Search

Start with exact text and SQLite FTS. Search results must identify the matching
document, page, extractor run, and text offsets when available.

The Phase 1 catalog is an atomic snapshot of the collections selected by the
latest inventory invocation. Running an inventory for a subset intentionally
replaces the searchable catalog snapshot, while prior content-addressed
artifacts and timestamped manifests remain available.

### Downstream adapters

Downstream integrations consume accepted facts or explicitly requested raw
artifacts. Tax rules, legal conclusions, and case-specific labels do not belong
in the generic core.

## Failure Model

Failures are data. A run should record unsupported files, encrypted PDFs,
timeouts, missing dependencies, OCR warnings, page failures, and parse errors
without claiming a document was successfully reviewed.

## Network Boundary

The default system is local. A future remote-model or hosted-extractor adapter
must be opt-in, visibly identify data transmission, and record provider/model
metadata. No fallback may silently send a document to a network service.
