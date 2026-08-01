# Master Plan

**Last updated:** 2026-08-01
**Status:** Phase 1 implemented and operationally validated

## Objective

Create a reusable local-first system that can inventory heterogeneous document
collections, compare extraction engines, search derived content, propose
structured observations, and preserve enough provenance for a person or agent
to verify every accepted fact.

The system should be useful for financial, tax, legal, administrative, and
personal record collections without embedding any one domain's rules in the
core.

## Success Criteria

- Re-running an unchanged collection does not redo unchanged expensive work.
- Renaming or moving a document does not change its content identity.
- Original documents are never modified.
- Every extraction can be reproduced from recorded versions and config.
- Every proposed fact links back to the source document and page.
- Review decisions survive extractor upgrades and cache rebuilds.
- Multiple extractors can be evaluated through one normalized interface.
- Private collections stay outside the Git repository.
- Downstream systems consume reviewed source facts, not raw model output.

## Phases

### Phase 0 — Contracts and scaffold — complete

- Establish repository and data boundaries.
- Define configuration, manifest, and observation schemas.
- Provide a minimal CLI, tests, and diagnostics.
- Specify benchmark categories and metrics.

### Phase 1 — Deterministic inventory — implemented

- Load and validate case configuration.
- Traverse explicitly configured collections.
- Compute SHA-256 and record path aliases and metadata.
- Extract PDF metadata and embedded text with Poppler.
- Detect byte-identical and normalized-text-equivalent documents.
- Write content-addressed sidecars and a rebuildable SQLite catalog.
- Add exact and SQLite full-text search.

The implementation is covered by generated-PDF integration tests for source
immutability, exact duplicates, normalized-text duplicates, image-only
classification, artifact-cache reuse, schema-valid manifests, literal search,
and SQLite FTS5 search.

On 2026-08-01, the first private-corpus run reconciled exactly to its independent
file/page baseline: 81 source files, 79 PDF paths, and 421 PDF source pages. It
produced 80 unique content hashes, 78 unique PDFs, 10 unique image-only PDFs,
one exact-byte duplicate group, two distinct-byte normalized-text duplicate
groups, and no path or extraction errors. A second run reused all 78 unique PDF
extractions. Private filenames and extracted content remain in the external
case workspace.

### Phase 2 — OCR and parser comparison

- Add OCRmyPDF/Tesseract scan preprocessing.
- Add Docling and Marker as optional layout adapters.
- Normalize extractor output without discarding raw output.
- Benchmark accuracy, provenance, determinism, runtime, memory, and operational
  complexity.
- Select a default/escalation policy from evidence.

### Phase 3 — Candidate understanding

- Add versioned document-type and observation schemas.
- Extract parties, institutions, dates, identifiers, currencies, quantities,
  and tables with page provenance.
- Support deterministic rules and model-assisted adapters.
- Cache models by exact provider/model/prompt/schema identity.
- Keep candidates separate from review overlays.

### Phase 4 — Downstream adapters

- Define promotion APIs for accepted observations.
- Support domain adapters without importing domain rules into the core.
- Preserve raw, normalized, accepted, and superseded values.
- Produce reproducibility and unresolved-conflict reports.

### Phase 5 — Operational maturity

- Incremental updates and interrupted-run recovery.
- Database and schema migrations.
- Diagnostics and artifact garbage-collection planning.
- Optional local review UI if CLI/HTML reports are insufficient.
- Evaluate semantic retrieval only if measured needs justify it.

## Initial Implementation Order

1. Config loader and schema validation.
2. Content hashing and collection traversal.
3. Manifest sidecars.
4. Poppler metadata and text extraction.
5. SQLite catalog and exact search.
6. Duplicate analysis.
7. Benchmark runner.
8. OCR and advanced parser adapters.
9. Observation and review workflows.

## Deferred Decisions

- The final human-review interface.
- The exact boundary between JSON sidecars and SQLite projections.
- Whether a vector index ever provides enough benefit to maintain.
- Which advanced extractor becomes the preferred table/layout parser.
- Which model-assisted observation adapters are worth supporting.
