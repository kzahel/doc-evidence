# doc-evidence

`doc-evidence` is a local-first pipeline for indexing documents, comparing
extractors, preserving provenance, and promoting reviewed observations into
downstream structured-data systems.

The project is intentionally domain-neutral. Its first real downstream case is
an external tax-document workspace, but private documents and case-specific
facts do not belong in this Git repository.

## Product Direction

`doc-evidence` is being built as a distributable, local-first desktop library
application. The current CLI and authenticated localhost host are useful
development, automation, and headless interfaces, but they are compositions of
the same product services rather than the final ownership or distribution
model.

```text
Tauri desktop shell (thin; local unsigned arm64 proof assembled)
  native lifecycle, folder authorization, sidecar supervision, distribution
                              |
                              v
Shared React application + Python application services
                              |
                              v
Named local libraries
  one stable identity, one SQLite database, one artifact store,
  one or more explicit read-only source collections
```

Python remains the owner of library management, SQLite, durable jobs,
extractors, comparison, review, and provenance. React consumes those behaviors
through a platform-neutral runtime. The thin Tauri shell provides native
application-data paths, folder grants, process lifecycle, and desktop
composition without introducing a second document model or moving product
logic into Rust. The standalone core runtime is now packaged; the baseline
extractor pack and release-signing lane remain in progress.

The intended workflow is agent-assisted and human-accountable. Machines and
agents extract, validate, reconcile, and assemble provisional values and
downstream mappings. A person reviews consequential, conflicting, or sampled
values beside their exact source regions. Confidence, extractor agreement,
deterministic validation, agent assessment, and explicit human confirmation
remain distinct, and provisional outputs summarize their evidence coverage.

The delivery sequence is deliberate:

1. **Implemented:** deterministic inventory, content-addressed extraction and
   benchmarking, plus the read-only localhost library/comparison application.
2. **Implemented; awaiting maintainer acceptance:** desktop-style application
   home, remembered libraries, and unified per-library persistence. The typed
   extractor registry, private worker protocol, supervised process trees,
   validated staging, atomic artifact publication, durable queue, scheduler lease,
   bounded resource dispatcher, cancellation, and restart reconciliation are
   also implemented. Authenticated API contracts, generated clients, document
   extraction controls, bounded batches, and the global operational activity
   and diagnostics UI are implemented. Fault/restart, isolated-browser, and
   authorized private-integration gates pass for Tactical 001.
3. **In progress:** an Apache-2.0 macOS arm64 distribution with a thin Tauri
   shell, native folder authorization, standalone Python sidecar, and small
   Ghostscript-free Poppler/Tesseract/OCRmyPDF baseline pack. The current
   authorized lane covers unattended local unsigned/ad-hoc implementation and
   validation. Signing, notarization, updater credentials, GitHub setup, and
   publication remain deliberately unstarted.
4. **Later slices:** durable human review state; optional language/extractor
   packs; additional release channels; and platform-specific Windows and Linux
   applications.

Desktop distribution is therefore an explicit destination. Its first bounded
implementation plan is
[Tactical 002: macOS Tauri desktop distribution](docs/tactical/002-macos-tauri-desktop-application.md),
whose unattended local packaging lane is now being implemented. See
[Product vision and application architecture](docs/product-vision-and-architecture.md),
[Application platform](docs/topics/application-platform.md), and
[Desktop library management](docs/topics/library-management.md).

The researched direction for mapping extracted text to source-page boxes,
linking comparison differences to regions, and performing bounded regional
OCR is recorded in
[Spatial provenance and regional OCR](docs/topics/spatial-provenance-and-regional-ocr.md).
It is a shared-product direction, not part of the unstarted Tauri packaging
tactical and not yet an approved implementation slice.

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
reviewing versioned word/numeric comparisons. The next implemented product
boundary adds desktop-first library management and isolated app-home
configuration together with durable extraction jobs, atomic artifact
publication, recovery, and operational UI. Durable human review state follows
as a separate slice after explicit maintainer acceptance.

The implemented slice is
[Tactical 000: read-only library and extractor comparison](docs/tactical/000-read-only-library-comparison.md).
Its automated and private integration gates pass, but it remains open until
the maintainer explicitly accepts the live interaction. It stops before
durable review writes, pipeline execution, and desktop packaging.

The implementation and execution record for that boundary is
[Tactical 001: durable extraction jobs and operational UI](docs/tactical/001-durable-extraction-jobs.md),
owned by the living [library management](docs/topics/library-management.md)
and [job architecture](docs/topics/job-architecture.md) topics.
Implementation is complete and its automated, isolated-browser, and authorized
private-library gates pass; explicit maintainer interaction acceptance remains.
Its landed boundaries provide platform
app-home resolution, an atomic known-library registry, stable adopted-library
identity, ordinary startup from the last/default registered library, and one
schema-versioned SQLite database with atomic inventory generations. The
localhost API, generated client, React runtime, queries, and deep links now
carry explicit library identity, with known-library selection and collection
settings in the shared UI. Extractor capabilities and bounded settings now
come from a server-owned registry, and extraction attempts run in supervised
private process groups before validated output is atomically published into a
canonical content-addressed run. Schema-versioned jobs, attempts, events, and
batches now live beside the library catalog, with idempotent/coalesced enqueue,
cache fulfillment, a process-locked per-library scheduler, priority aging,
resource limits, cancellation, one bounded transient retry, and startup
reconciliation. The library-scoped v1 API and generated React runtime now
expose capabilities, single-document and confirmed-batch enqueue, activity,
attempt/event detail, cancellation, retry, queue control, bounded log
diagnostics, and catalog projection repair without accepting client paths or
executables. The document workspace provides explicit cache/fresh extraction
actions and representation refresh; the application header provides a polling
activity center with resource lanes, liveness/deadline detail, batch preflight,
and cancellation.

The maintainer has selected an Apache-2.0 macOS arm64 desktop distribution as
the next planned boundary. Tactical 002 freezes a thin Tauri shell, separate
runtime and host-control credentials, preservation of the existing application
home, native library/collection selection through Python-owned services, a
standalone CPython runtime, and only the Poppler/Tesseract/OCRmyPDF baseline
pack. It excludes Ghostscript, Docling, Marker, heavyweight model runtimes,
and downloads/plugins. It adapts the proven sibling conventions for nested
Mach-O signing, Developer ID notarization, DMG and updater generation, release
finalization, and published checksums. Windows/Linux packaging remains later.
Tactical 002 now has the thin shell, native authorization, authenticated
standalone sidecar, pinned CPython staging/audit entry point, and a copied-out
unsigned arm64 `.app` proof. The baseline extractor pack remains the next local
slice. No signing credential, GitHub release, updater, notarization, or
publication action has been performed.

The external acceptance harness used an explicitly authorized registered
library in the platform-default application home. It exercised a missing OCR
identity, exact OCR and layout cache reuse, and bounded batch preflight while
verifying that source bytes and the application registry remained unchanged.
Synthetic automation continues to use a fresh temporary `DOC_EVIDENCE_HOME`.

Read these first:

1. [Product vision and application architecture](docs/product-vision-and-architecture.md)
2. [Master plan](docs/master-plan.md)
3. [Living topics](docs/topics/README.md)
4. [Product landscape and use cases](docs/topics/product-landscape-and-use-cases.md)
5. [Spatial provenance and regional OCR](docs/topics/spatial-provenance-and-regional-ocr.md)
6. [Library management](docs/topics/library-management.md)
7. [Durable job architecture](docs/topics/job-architecture.md)
8. [Implementation tacticals](docs/tactical/README.md)
9. [Architecture](docs/architecture.md)
10. [Data contracts](docs/data-contracts.md)
11. [Benchmark plan](docs/benchmarking.md)
12. [References](docs/references.md)
13. [Operations](docs/operations.md)

## Core Principles

- Source documents are read-only.
- Every document is identified by a cryptographic content hash.
- Extraction outputs are derived, versioned, and reproducible.
- Candidate observations retain document and page provenance.
- Automated observations are never silently promoted to accepted facts.
- Each user-facing library owns one SQLite database and artifact store.
  Generation-independent content is reused across collection-scope changes,
  while membership projections remain rebuildable.
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

On macOS arm64, the current intermediate unsigned desktop proof is built with
one entry point. `stage` downloads the exact hash-pinned standalone CPython
input, installs the hash-locked Python baseline, and copies the exact declared
Poppler 26.03.0 and Tesseract 5.5.3 Homebrew inputs into a self-contained
bundle. Repeat staging requires the explicit `--replace` flag.

```sh
npm ci --prefix desktop
./scripts/build-macos-desktop stage
./scripts/build-macos-desktop build
./scripts/build-macos-desktop review
./scripts/build-macos-desktop dmg
./scripts/build-macos-desktop review-dmg
./scripts/build-macos-desktop compliance-preflight --resolve-formulas
```

The resulting application is
`desktop/src-tauri/target/release/bundle/macos/Doc Evidence.app`. `review`
audits its final bytes and runs both an authenticated packaged-sidecar smoke
and real synthetic OCR from the application resources. The current baseline
contains Poppler, Tesseract with English/German/orientation data, OCRmyPDF, and
PDFium; Ghostscript and heavyweight model extractors are absent. This
intermediate artifact intentionally has no Developer ID signature,
notarization, updater metadata, or release publication yet. The local `dmg`
command deliberately avoids Finder automation: it creates a simple image with
the application and an `/Applications` link, verifies and mounts it read-only,
audits the mounted application, and detaches it. Its ignored output is under
`results/desktop/distribution/`; it is a local proof, not a public substitute
for the eventual signed and notarized release image.

`compliance-preflight` emits an ignored preliminary SPDX 2.3 document,
licenses/notices, exact Homebrew source and bottle SBOMs, exact historical
formula recipes, embedded Python-wheel SBOMs, manifests, and build recipes.
Formula resolution is explicit because it reads bounded public Homebrew/GitHub
metadata and then reuses a verified ignored cache. The report currently keeps
`release_ready: false`: do not publish until every listed native-wheel,
supplemental crate-license, source-archive, and reviewed-license blocker is
closed.

Register an external case configuration once, then launch the selected
last/default library:

```sh
uv run doc-evidence library-register --config /path/to/case.yaml
uv run doc-evidence serve
```

An explicit `serve --config /path/to/case.yaml` remains available for
automation and compatibility and does not modify the app registry.

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
doc-evidence inventory --config PATH [COLLECTION ...] [--full-hash]
doc-evidence search --config PATH QUERY [--mode literal|fts]
doc-evidence duplicates --config PATH
doc-evidence library-register --config PATH [--name NAME]
doc-evidence libraries
doc-evidence library-activate LIBRARY_ID [--default]
doc-evidence collection-preflight --config PATH --source PATH
doc-evidence serve [--config PATH]
doc-evidence desktop-sidecar [HOST-SUPERVISED OPTIONS]
doc-evidence benchmark-check --suite PATH
doc-evidence benchmark-run --config PATH --suite PATH
doc-evidence benchmark-score --report PATH --review PATH
```

`inventory` includes the Phase 1 Poppler extraction step. `benchmark-run`
invokes only the experts named by a private suite. It never treats agreement
as truth or changes a production extraction policy automatically.

Current routing limitation: ordinary inventory still runs Poppler only for
PDFs. The configured `ocr_when` and `layout_when` values are validated and
included in cache/config identity, but they do not automatically schedule OCR
or layout jobs. OCRmyPDF/Tesseract, Tesseract raster OCR, Docling, and Marker
can now be requested explicitly through the authenticated application job
surface; benchmark suites remain a separate explicit path. Standalone image
rendering and automatic catalog-wide routing remain later work.

## Configuration

Case configuration stays with the case, not this repository. See
[`config.example.yaml`](config.example.yaml) and
[`schemas/config.schema.json`](schemas/config.schema.json).

Relative paths are resolved relative to the configuration file, making a case
workspace movable without teaching this tool its layout.

The desktop library foundation remembers known and default libraries in the
platform application-data directory. Setting `DOC_EVIDENCE_HOME` overrides
that complete app-owned directory for isolated testing and development
without relocating external collections.

## Phase 1 Output

The configured store contains:

```text
doc-evidence.sqlite
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

The active catalog membership is an atomically selected generation inside the
single library database. Stable content, extractor runs, pages, and FTS rows
are reused across membership generations when their identities are unchanged.
An untouched legacy `catalog.sqlite`, when present, remains rollback material
and is never dual-written.

Phase 2 adds extractor-specific runs below each content blob and private review
runs below `benchmarks/<suite-id>/runs/<benchmark-run-id>/`. The generated
`review.html` embeds its selected page renders, works as a self-contained local
file or constrained preview, and exports a JSON review overlay.
An unchanged small multi-extractor benchmark reuses all cached expert artifacts
and completes in seconds; the initial model-backed pass takes minutes and is
intended only for a representative suite.

## License

Original Doc Evidence source is licensed under the
[Apache License 2.0](LICENSE). Bundled extractors, runtimes, language data, and
other third-party components retain their own licenses; desktop distributions
include a component manifest, corresponding notices, and applicable source
material rather than treating the project license as a relicense of those
components.
