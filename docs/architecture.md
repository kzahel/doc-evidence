# Architecture

This document describes the existing extraction and evidence core. The
approved application direction, user experience, deployment path, and
Python/React boundary are defined in
[Product vision and application architecture](product-vision-and-architecture.md).
Current implementation posture is maintained in
[Application platform](topics/application-platform.md), and the closest
reviewed sibling precedent is recorded in [References](references.md).
Desktop library ownership, application-data placement, and collection scope
are defined in [Library management](topics/library-management.md).

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
                  selected-library SQLite
                 with membership generations
                              |
                              v
                   external review overlays
                              |
                              v
                   downstream domain adapters
```

The first-class product is a desktop-shaped library application. The current
localhost host and CLI are adapters around the same services and do not change
the source or artifact boundaries:

```text
desktop shell or localhost host
        |
        v
React + TypeScript UI + Python application services
        |
        +-- bounded app registry
        +-- selected library
              +-- one SQLite database
              |     +-- stable content, extraction, page, and FTS data
              |     +-- generation-scoped collection membership
              |     +-- durable operational/review state
              +-- content-addressed artifacts
              +-- configured read-only collections
              +-- isolated extraction subprocesses
```

Frontend request and response types are generated from Python-owned API
contracts. A future Tauri shell should supply the platform application-data
directory, authorize collection folders, and supervise the same local API
rather than introduce a separate desktop data model. `DOC_EVIDENCE_HOME`
overrides the complete app-owned data root for isolated development, tests,
and portable local runs.

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

Each library store contains inspectable immutable successful run outputs under
`blobs/<hash-prefix>/<sha256>/runs/<extractor>/<run-key>/`. Catalog tables in
that library's `doc-evidence.sqlite` project those artifacts into convenient
metadata, relationships, and full-text indexes. Content identity, extraction
runs, normalized pages, and full-text rows are generation-independent.
Collection occurrences and active membership are generation-scoped so scope
changes do not duplicate expensive work. The database also contains
operational and future user-authored state and therefore is not deleted to
rebuild the catalog.

The app-wide known/default-library registry is a bounded, atomically replaced
JSON file in the application home, not a second database. Each library owns
exactly one SQLite database and one artifact store. The complete ownership and
scope model is maintained in [Library management](topics/library-management.md).

Human review decisions are not extractor artifacts. They belong in a durable
logical workspace store that can refer to observations and source hashes while
surviving re-extraction. Durable jobs and worker attempts use separate tables
and retention policy in the same active database. The complete worker,
artifact-publication, and recovery boundary is maintained in
[Durable job architecture](topics/job-architecture.md).

Private benchmark reports and reviews live below
`benchmarks/<suite-id>/runs/<benchmark-run-id>/` in the external artifact store.
Extractor output remains under the content blob, so rerunning a suite reuses
an unchanged expert run while producing a new comparison/review snapshot.

## Components

### Configuration loader

- Resolves the application home, app registry, selected library, and stable
  library identity.
- Resolves paths relative to the config file.
- Validates collection IDs, parent/child collection overlap, and store
  boundaries.
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

The legacy Phase 1 implementation used an atomic whole-file catalog snapshot
of the collections selected by the latest inventory invocation. Tactical 001
replaced that mechanism with generation-independent content, extraction, page,
and FTS rows plus generation-scoped occurrence and collection-membership rows. An
atomic active-generation pointer selects the visible membership without
discarding reusable content-addressed artifacts.

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
