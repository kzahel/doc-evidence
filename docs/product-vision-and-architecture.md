# Product Vision and Application Architecture

**Last updated:** 2026-08-01  
**Status:** Approved direction; first read-only application slice implemented;
durable extraction-job architecture approved and planned

## Product Statement

`doc-evidence` is a local-first document evidence workbench. It scans
explicitly configured collections, preserves immutable source identity, runs
reproducible extraction and understanding pipelines, makes competing outputs
easy to compare, and lets a person promote reviewed observations into
structured data with complete provenance.

The product should help a person answer:

- What documents do I have, and where were they observed?
- Which files are duplicates, variants, or likely related?
- What did each extraction method actually recover?
- Where do methods agree, disagree, omit content, or invent content?
- Which output or correction did a reviewer accept, and for what purpose?
- What structured observations are supported by which page and region?
- What remains missing, conflicting, or unreviewed?
- Can every derived artifact and decision be reproduced or audited later?

The initial private tax collection is a demanding real-world integration, not
the product boundary. The core must remain useful for financial,
administrative, legal, research, and personal-record collections without
embedding tax rules.

Living application and comparison status is maintained in
[Application platform](topics/application-platform.md) and
[Comparison and review workspace](topics/comparison-review-workspace.md).
Bounded implementation plans live under [`tactical/`](tactical/README.md).

## Product Principles

### Local first and offline capable

The default product reads local files, runs local extractors, and stores local
artifacts. Core inventory, extraction, browsing, comparison, review, search,
and export must work without an internet connection.

Any future remote model or hosted service is an explicit adapter. The product
must identify what will leave the machine, require an intentional action, and
record the provider, model, and configuration in provenance.

### Sources are immutable evidence

Configured collections are read-only. The application never renames, moves,
rewrites, annotates, OCR-replaces, or deletes source documents. Paths are
aliases; SHA-256 content hashes are document identities.

### Derived work is inspectable

Raw extractor output, normalized output, comparison artifacts, candidate
observations, and review decisions are distinct layers. The interface must let
the user move backward from any proposed fact to the exact page, region,
extractor run, configuration, and original content hash.

### Agreement is not truth

Identical outputs may be grouped to reduce noise, but agreement never silently
promotes a result. A shared bad PDF text layer or a common OCR error can make
several methods agree incorrectly.

### Corrections do not erase history

Extractor output is immutable. A correction creates a review decision or a
reviewed replacement while retaining the original candidate and the reason it
was rejected or superseded.

### Human attention is allocated by risk

The product should collapse identical results, prioritize numeric and
structural disagreements, and create focused review queues. It should not ask
a reviewer to compare large undifferentiated text columns manually.

### Domain intelligence is extensible

The core provides documents, pages, regions, extraction runs, candidates,
reviews, and provenance. Domain packs can add document classes, schemas,
recognizers, validators, and exports without placing domain conclusions in the
generic core.

## What a Document Contains

A visually simple page can expose several distinct representations:

1. **Source bytes** — the immutable file.
2. **Visual page** — pixels produced by rendering those bytes.
3. **Native primitives** — text objects and coordinates, images, vector paths,
   annotations, form fields, and tags actually stored in the file.
4. **Inferred layout** — blocks, lines, tables, key-value regions, and reading
   order reconstructed by an extractor.
5. **Candidate semantics** — proposed typed observations such as a party,
   date, account balance, or field value.
6. **Reviewed evidence** — a person accepts, corrects, rejects, or supersedes a
   candidate for a stated purpose.

The application must show which representation the user is viewing. It must
not describe native page text as a parsed field, or an inferred field as an
accepted fact.

Hybrid pages deserve explicit detection. A page may contain an image of a
blank form with filled values overlaid as native text. A skip-existing-text
OCR policy can then recover only the overlay while missing every label in the
background. Page classification and escalation policy must account for this
case.

## Scope

### First-class capabilities

- Configure and scan read-only local collections.
- Browse documents, source occurrences, pages, and metadata.
- Search native and extracted text with page-level provenance.
- View page renders beside raw and normalized extraction artifacts.
- Compare any two extraction runs and group equivalent results.
- Review discrepancies, sparse assertions, and candidate observations.
- Tag, classify, annotate, and organize without modifying sources.
- Run, monitor, cancel, resume, and reproduce extraction pipelines.
- Promote reviewed observations through versioned domain adapters.
- Export portable reports, review overlays, and structured evidence ledgers.

### Initial non-goals

- Cloud hosting or multi-user collaboration.
- Editing or replacing original documents.
- A general-purpose document editor.
- A visual arbitrary-DAG pipeline designer.
- Automatic majority-vote truth selection.
- Direct tax, legal, or accounting conclusions in the generic core.
- A vector database without a measured retrieval need.
- Rewriting mature Python document tools in TypeScript.

## Deployment Direction

### Initial shape: localhost application

Development begins as two local processes:

```text
browser
  |
  v
React development/build output
  |
  v
Python HTTP application on loopback
  |
  +-- SQLite workspaces
  +-- content-addressed artifacts
  +-- configured read-only collections
  +-- local extraction workers
```

The server binds only to loopback by default. Opening remote interfaces,
enabling network-backed adapters, or exposing document contents requires an
explicit configuration change.

### Later shape: desktop package

The same frontend and local HTTP API should be compatible with a future Tauri
desktop shell. Tauri may launch the packaged Python service as a sidecar,
select an available loopback port, pass an ephemeral session credential, and
manage startup and shutdown.

Desktop packaging is a deployment adapter, not a second application. The CLI
and localhost application remain supported for automation, development, and
headless operation.

Packaging the Python runtime and optional model-heavy extractors will require
an explicit prototype. The application architecture must not assume that all
extractors fit inside the desktop bundle; optional local environments can
remain externally managed when necessary.

## Technology Direction

### Backend: Python

The current architectural default is one Python application that owns:

- configuration and collection access policy;
- the HTTP API and generated API schema;
- SQLite transactions and migrations;
- inventory and artifact lookup;
- job scheduling and progress reporting;
- extraction adapter orchestration;
- comparison and review services; and
- export and downstream-adapter invocation.

This keeps orchestration beside the existing Python extraction ecosystem and
avoids a second TypeScript server merely to spawn Python workers. Heavy or
failure-prone extractors continue to run in isolated subprocesses.

The exact Python web framework is intentionally not yet locked. The selected
framework must support typed request/response models, OpenAPI generation,
streaming job progress, test clients, and controlled process lifetime. An
implementation spike can compare the smallest suitable ASGI options.

The first bounded application tactical proposes FastAPI and Pydantic 2 after
reviewing the directly relevant `atpiano` sibling. That choice becomes
established implementation evidence only after the vertical slice lands and
is reviewed. See [References](references.md).

### Shared frontend/backend types

Language sharing is not required for contract sharing. Python request and
response models are the authoritative API contract. The build generates:

- OpenAPI for the HTTP surface;
- TypeScript request, response, and enum types;
- a typed frontend API client; and
- JSON Schema where files or plugins consume contracts without HTTP.

Generated TypeScript is checked into or regenerated by a documented command,
never edited by hand, and verified in continuous integration so frontend and
backend drift is visible.

Stable persisted contracts such as manifests, extraction runs, observations,
and review events remain explicitly versioned. An API model is not
automatically a durable storage schema.

### Frontend: React and TypeScript

The first-class interface uses:

- React;
- TypeScript;
- Zustand for transient interaction and layout state; and
- CSS Modules for component-scoped styling.

Zustand should hold selection, pane layout, comparison choices, local filters,
and pending UI interactions. It should not mirror the complete SQLite domain
model or become an alternative persistence layer. Server-derived records are
loaded through the generated API client and an appropriate request-cache
layer.

The frontend build tool and component primitives remain implementation
choices. They must support static production assets that the Python server and
a future Tauri shell can both serve.

### SQLite and artifact storage

Large binaries, page renders, raw model output, and normalized sidecars remain
in the content-addressed artifact store. SQLite stores indexed metadata and
relationships rather than opaque copies of every artifact.

Durability classes must be explicit:

- **Rebuildable catalog data** — source occurrences, extraction projections,
  full-text indexes, and derived comparison indexes.
- **Durable workspace data** — tags, saved views, review decisions,
  corrections, accepted observations, pipeline policies, and user-authored
  notes.

The approved local composition uses one active SQLite database with separate
table groups and lifecycle policies rather than multiple active files:

```text
doc-evidence.sqlite
  catalog generations       # rebuildable projections
  jobs/attempts/events       # restartable bounded operational state
  future review state       # migrated and never automatically rebuilt
```

Catalog refresh builds and validates an inactive generation, then atomically
switches the active-generation pointer without replacing the database file.
Durable review and observation data must also support explicit portable
export. References use content hashes and run identities so they survive path
changes and catalog regeneration. The complete decision is in
[Durable job architecture](topics/job-architecture.md).

## Application Components

### Collection service

- Resolves explicitly configured roots.
- Enforces read-only collection access.
- Scans incrementally and records source occurrences.
- Detects disappeared, moved, new, and changed paths without confusing paths
  with content identity.

### Artifact service

- Resolves content-addressed metadata, renders, and extractor output.
- Validates artifact identity and schema version.
- Streams large artifacts rather than inserting them into ordinary API JSON.
- Never overwrites an incompatible successful run.

### Pipeline and job service

- Turns inventory, rendering, extraction, normalization, comparison, and
  candidate generation into explicit jobs.
- Computes deterministic cache keys before expensive work.
- Records version, options, environment, timestamps, status, warnings, and
  failure diagnostics.
- Supports progress, cancellation, restart, and interrupted-run recovery.
- Separates job execution from review decisions.

Pipelines begin as versioned code/config definitions, not a visual graph
editor. A typical progression is:

```text
inventory
  -> native inspection
  -> page classification
  -> selected extractor runs
  -> normalization
  -> disagreement computation
  -> candidate observations
  -> review queue
```

### Comparison service

Diff computation is a reproducible backend operation. Each comparison records
the two run identities, normalization version, diff algorithm version, and
options. The service produces multiple aligned views:

- exact and normalized equivalence;
- line and block alignment;
- word/token additions, omissions, and substitutions;
- numeric-token differences with high priority;
- character-level detail on demand;
- page-count and missing-page differences; and
- region or reading-order differences when spatial data exists.

The UI can choose a baseline and presentation without recomputing or mutating
extractor output.

### Observation and review service

Candidate observations are typed proposals with source provenance. A review
event records:

- the candidate or comparison being reviewed;
- accepted, rejected, corrected, unresolved, or superseded status;
- purpose and scope of the decision;
- reviewer identity or local profile;
- timestamp and notes; and
- any replacement value and its provenance.

Review is append-oriented. Current state is a projection over review history,
not an in-place mutation that erases prior decisions.

### Search and organization service

- Exact and SQLite full-text search.
- Filters for collection, path, media type, date, tag, document class,
  extractor status, review status, and unresolved discrepancies.
- User tags, saved searches, and review queues stored as durable workspace
  state.
- Results always identify the document, page, run, and matching location when
  available.

### Domain-pack boundary

A domain pack may provide:

- document-class definitions;
- field and observation schemas;
- deterministic recognizers and validators;
- model-assisted candidate generators;
- review templates; and
- exports to downstream systems.

Domain packs emit candidates, not accepted facts. They cannot remove core
provenance or bypass review policy.

## First-class User Interface

### Library

- Collection and folder navigation.
- Document grid/list with search and facets.
- Duplicate and variant grouping.
- Extraction, review, and error status at a glance.
- Tags and saved views.

### Document workspace

- Page thumbnails and full page viewer.
- Source occurrences and immutable content identity.
- Native PDF/file properties.
- All extractor runs, artifacts, versions, warnings, and timings.
- Raw, normalized, and spatial representations clearly labeled.
- Related documents, duplicates, and prior versions.

### Comparison and calibration workspace

This is the first product-defining vertical slice.

- Choose any two runs or use a recommended baseline.
- Collapse identical normalized outputs into one equivalence group.
- Show only differences or expand complete output.
- Switch among block, line, word, numeric, and character views.
- Distinguish omission, addition, substitution, and ordering differences.
- Keep numeric discrepancies visible even when surrounded by identical text.
- Compare against the rendered page and optional bounding-box overlays.
- Display exact engine descriptions, versions, options, and representation
  type: native text, OCR, layout parser, or semantic adapter.
- Show the selected page and total document page count.
- Present manually verified sparse assertions as focused checks.
- Create a review decision without pretending that agreement is correctness.

If two runs are equivalent, the interface should say so directly instead of
rendering two apparently identical columns.

### Observation workspace

- Candidate values grouped by document, field, or review queue.
- Source page and region beside the candidate.
- Supporting and conflicting extractors.
- Raw and normalized values.
- Accept, correct, reject, defer, or supersede actions.
- Batch review only when candidates share a justified policy.

### Pipeline and diagnostics workspace

- Active, queued, completed, cancelled, and failed jobs.
- Per-stage progress and logs.
- Cache-hit explanation.
- Dependency, model, and storage diagnostics.
- Explicit retry and escalation controls.

## API Boundary

The first API should be resource-oriented and narrow. Representative areas
include:

```text
/api/workspace
/api/collections
/api/documents
/api/documents/{id}/pages
/api/documents/{id}/runs
/api/artifacts/{id}
/api/comparisons
/api/observations
/api/reviews
/api/tags
/api/search
/api/jobs
/api/pipelines
/api/diagnostics
```

Artifact streaming, page images, downloads, and event streams are separate
from ordinary JSON records. File paths received from a client are never
trusted as unrestricted filesystem access.

## Local Security Model

- Bind to `127.0.0.1` or the platform-equivalent loopback address by default.
- Use an ephemeral session secret when the browser or Tauri shell launches the
  server.
- Permit file access only through configured collection and artifact roots.
- Resolve and validate paths server-side; do not expose arbitrary local-file
  endpoints.
- Apply origin and request-forgery protections even on localhost.
- Make network-backed adapters disabled and visible by default.
- Never include private source content in application logs unnecessarily.
- Record destructive maintenance operations separately and require explicit
  targets.

## Proposed Repository Shape

The current package can grow without a rewrite:

```text
src/doc_evidence/
  api/             # typed HTTP routes and schemas
  application/     # use cases and orchestration
  domain/          # durable domain models and policies
  jobs/            # job lifecycle and workers
  persistence/     # SQLite repositories and migrations
  extractors/      # existing adapters migrated incrementally
  comparisons/     # versioned diff engines
  observations/    # candidate and review services
web/
  src/
    api/           # generated client and types
    components/
    features/
    pages/
    state/         # transient Zustand stores
    styles/
schemas/           # persisted JSON contracts
desktop/           # future Tauri shell
```

Existing modules should move only when a feature needs the new boundary.
Avoid a mechanical repository rewrite before the application has a working
vertical slice.

## Delivery Workstreams

These workstreams extend the extraction phases in `master-plan.md`; they do
not discard the existing CLI or artifacts.

### A. Application foundation

- Define API, job, durable-review, and migration contracts.
- Prototype the Python ASGI server and generated TypeScript client.
- Establish frontend build, test, and development commands.
- Serve production frontend assets from the Python application.

### B. Read-only library

- Browse the current SQLite catalog and content-addressed artifacts.
- Search and filter the cached document library.
- View source occurrences, pages, renders, and extraction runs.
- Add diagnostics without changing source collections.

### C. Comparison vertical slice

- Implement versioned diff artifacts.
- Group equivalent outputs.
- Build the page/output comparison workspace.
- Persist review decisions outside extractor runs.
- Import/export portable review overlays.

### D. Pipeline operations

- Run inventory and extraction jobs from the application.
- Stream progress and diagnostics.
- Support cancellation, resumption, escalation, and cache explanations.

### E. Structured observations

- Preserve native coordinates and inferred regions.
- Add candidate generation and review queues.
- Implement domain-pack contracts.
- Promote accepted observations through downstream adapters.

### F. Desktop packaging

- Prototype the Python sidecar lifecycle under Tauri.
- Package a minimal offline extractor set.
- Define optional heavyweight-extractor discovery.
- Verify installation, upgrade, backup, and workspace migration behavior.

## First Product Milestone

The first milestone is a useful read-only application plus durable comparison
review—not a complete document-understanding platform.

It is complete when a user can:

1. Open an existing external workspace without copying its documents.
2. Browse and search the cached library.
3. Open a document and inspect its pages and extractor runs.
4. See equivalent outputs collapsed.
5. Compare two differing outputs with word and numeric differences emphasized.
6. Switch between normalized and raw representations.
7. Record and reload a review decision without modifying extractor artifacts.
8. Trace every displayed result to a content hash, page, run, version, and
   artifact.
9. Use the application with network access disabled.
10. Continue using the CLI against the same workspace.

Running new extraction jobs, candidate semantic fields, domain packs, and
desktop packaging follow this milestone.

## Decisions

### Decided

- `doc-evidence` is a standalone, domain-neutral product.
- It is local-first and must support fully offline use.
- The initial application is a single-user localhost web application.
- A future Tauri desktop shell should reuse the same application contracts.
- Source collections remain immutable and read-only.
- Python owns the backend, SQLite, job orchestration, and extractor adapters.
- React and TypeScript provide the first-class UI.
- Zustand manages transient frontend interaction state.
- CSS Modules provide component-scoped styling.
- Frontend API types are generated from Python-owned contracts.
- The existing CLI, artifact store, and Python extractors are retained.
- The comparison and review workspace is the first defining vertical slice.
- One active `doc-evidence.sqlite` contains logically distinct catalog
  generations, operational job state, and future durable review state.
- The first job executor is a bounded local scheduler over supervised
  subprocesses, not Celery or an external broker.

### Open implementation decisions

- Tactical 001 must implement and validate the approved unified SQLite
  migrations and catalog-generation mechanism. Tactical 000 validated the
  FastAPI/Pydantic adapter.
- Tactical 000 validated the Vite, React, TanStack Query, narrow Zustand, and
  CSS Modules frontend composition; the maintainer interaction gate remains.
- Measured default concurrency for light, OCR, and model-heavy resource
  classes on supported local environments.
- The first diff algorithms and alignment libraries.
- Polling, explicit refresh, or filesystem watching for collection changes.
- The initial plugin discovery and isolation mechanism for domain packs.
- Python and heavyweight-model packaging strategy for Tauri.

These choices should be made through small vertical prototypes and recorded as
architecture decision records rather than hidden in implementation commits.
