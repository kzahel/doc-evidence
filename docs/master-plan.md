# Master Plan

**Last updated:** 2026-08-01
**Status:** Phase 2, read-only application, desktop library foundation, and
durable extraction jobs implemented; Tactical 001 maintainer acceptance
pending; macOS Tauri proof proposed in Tactical 002

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

The first authorized external-corpus run reconciled exactly to its independent
file/page baseline, including document identities, page counts, duplicates,
and image-only classification, without path or extraction errors. A second run
reused every unchanged PDF extraction. Private filenames and extracted content
remain in the external case workspace.

### Phase 2 — OCR and parser comparison — implemented

- Add OCRmyPDF/Tesseract scan preprocessing.
- Add Docling and Marker as optional layout adapters.
- Normalize extractor output without discarding raw output.
- Benchmark accuracy, provenance, determinism, runtime, memory, and operational
  complexity.
- Select a default/escalation policy from evidence.

The implementation keeps OCRmyPDF/Tesseract, Docling, and Marker in isolated
runtime environments and invokes them through versioned subprocess adapters.
It retains raw and normalized output, renders selected pages, computes pairwise
text/token/number disagreements, checks sparse manually verified assertions,
and generates a local review UI. Human review is scored per extractor and
document class. Agreement is a triage signal, not correctness, and scorecards
never change or retire an extractor automatically.

The first bounded external benchmark completed every expert run successfully,
checked sparse visually verified assertions, and emitted pairwise review flags.
A repeat run reused every expert artifact. These are smoke-test results, not
extractor rankings; human page-level calibration remains pending in the
external case workspace.

### Application milestone — read-only slice implemented

- Add a Python-owned localhost API over the existing catalog and artifact
  store. — implemented
- Add a React/TypeScript application for browsing and searching the cached
  library. — implemented
- Make extractor comparison and discrepancy review a first-class workspace.
  — implemented for read-only review
- Group equivalent outputs and provide versioned word and numeric diffs.
  — implemented; structural/spatial diff deferred
- Persist human tags and review decisions separately from extractor output.
- Generate frontend API types from Python-owned contracts. — implemented

The read-only vertical slice passes automated and private integration gates.
Durable extraction execution has since landed; explicit maintainer interaction
acceptance remains. Durable review writes, structured candidate observations,
domain packs, and desktop packaging remain separately authorized boundaries.
See [Product vision and application architecture](product-vision-and-architecture.md).
The bounded first implementation plan is
[Tactical 000](tactical/000-read-only-library-comparison.md).

The maintainer selected durable extraction execution before durable review
writes as the next product priority. That implementation establishes the
approved desktop-first ownership model: an app-owned
known/default-library registry, one SQLite database and artifact store per
library, and explicit read-only collections. The approved architecture is in
[Library management](topics/library-management.md) and
[Durable job architecture](topics/job-architecture.md). Their bounded
implementation plan is
[Tactical 001](tactical/001-durable-extraction-jobs.md). Implementation and its
machine-verifiable gates are complete; explicit maintainer interaction
acceptance remains.

The maintainer next selected a bounded Apache-2.0 macOS arm64 desktop proof.
[Tactical 002](tactical/002-macos-tauri-desktop-application.md) proposes the
same React/Python application inside a thin Tauri 2 shell with native folder
authorization, a standalone Python runtime, and only a Ghostscript-free
Poppler/Tesseract/OCRmyPDF baseline pack. Heavy extractors, downloads/plugins,
signing/notarization, installers, Windows, and Linux remain later scope.
Tactical 002 implementation has not been authorized or started.

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
- Distinguish human confirmation from agent assessment, deterministic
  validation, extractor confidence, and agreement.
- Support provisional computations that retain input review coverage and
  unresolved conflicts.
- Version jurisdiction/year/form mappings and preserve reverse provenance from
  every mapped output through its calculation to source pages and regions.
- Produce reproducibility and unresolved-conflict reports.

### Phase 5 — Operational maturity

- Incremental updates and interrupted-run recovery.
- Database and schema migrations.
- Diagnostics and artifact garbage-collection planning.
- Mature the local application, workspace backup, and review-data migration.
- Package the same local application contracts in a Tauri desktop shell after
  a Python-sidecar prototype succeeds.
- Evaluate semantic retrieval only if measured needs justify it.

## Initial Implementation Order

1. Config loader and schema validation.
2. Content hashing and collection traversal.
3. Manifest sidecars.
4. Poppler metadata and text extraction.
5. SQLite catalog and exact search.
6. Duplicate analysis.
7. Benchmark runner. — complete
8. OCR and advanced parser adapters. — complete
9. Local application foundation and read-only library. — implemented
10. First-class comparison workspace. — read-only interaction implemented;
    durable review pending
11. Desktop library foundation, durable extraction jobs, and operational UI.
    — implemented; explicit maintainer acceptance pending
12. macOS arm64 Tauri application proof. — proposed; implementation not
    authorized or started
13. Observation and downstream-promotion workflows.

## Open Implementation Decisions

- Measure safe default concurrency for light, OCR, and model-heavy resource
  classes rather than inferring it from CPU count alone.
- Whether the directional v1 token diff should gain a symmetric summary, plus
  the initial spatial diff contract.
- Turn the declarative `ocr_when` and `layout_when` policy into explicit,
  resumable catalog-wide routing. Today only Poppler runs during inventory;
  heavy experts require an explicit document action, confirmed bounded OCR
  batch, or benchmark selection.
- Add first-class extraction/rendering for standalone image documents rather
  than merely inventorying them.
- Measure the proposed standalone Python and small baseline extractor bundle
  through Tactical 002; heavyweight-extractor packaging remains a separate
  future decision.
- Whether a vector index ever provides enough benefit to maintain.
- Which advanced extractor becomes the preferred table/layout parser.
- Which model-assisted observation adapters are worth supporting.
