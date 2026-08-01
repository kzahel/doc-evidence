# Instructions for Agents Working on doc-evidence

These instructions apply to this repository.

## Purpose and Boundary

Build a reusable local-first document inventory, extraction, benchmark,
search, and evidence-understanding pipeline. The system must preserve source
provenance and keep automated candidate observations distinct from reviewed
facts.

This repository contains generic code and public/synthetic fixtures only. Its
first downstream integration is the private tax workspace at
`/Users/kgraehl/Documents/taxes`, whose current case-side plan is
`docs/topics/document-evidence-pipeline.md` in that workspace.

Never copy, move, rename, commit, upload, or modify private source documents as
part of generic-tool development. Read an external collection only when the
task and an explicit configuration path place it in scope.

## Startup Routine

Before substantive work:

1. Read `README.md`.
2. Read `docs/product-vision-and-architecture.md`.
3. Read `docs/topics/application-platform.md` and
   `docs/topics/comparison-review-workspace.md` for application work. Consult
   `docs/topics/maintainer-feature-requests.md` before planning or changing
   the live review interface.
   Read `docs/topics/job-architecture.md` before changing job persistence,
   scheduling, workers, extraction execution, artifact publication,
   cancellation, recovery, or operational UI.
4. Read the active tactical under `docs/tactical/` before implementing its
   scope. `docs/tactical/000-read-only-library-comparison.md` is the implemented
   read-only execution record. The approved next implementation plan is
   `docs/tactical/001-durable-extraction-jobs.md`; implementation has not
   started.
5. Read `docs/master-plan.md`, `docs/architecture.md`, and
   `docs/data-contracts.md` for the affected core boundary.
6. Read `docs/benchmarking.md` for extractor/evaluation work and
   `docs/references.md` before relying on a sibling or external architecture.
7. Check the current Git status and preserve unrelated changes.

## Architectural Rules

- Treat source files as immutable and read-only.
- Identify content using SHA-256; paths are aliases, not identities.
- Key cached extraction runs by source hash, extractor name/version,
  configuration hash, and output-schema version.
- Store inspectable sidecars as well as a rebuildable SQLite catalog.
- Keep human review decisions outside regenerable extractor output.
- Every observation must retain file and page provenance. Page regions should
  be retained when an extractor supplies them.
- Never promote a model or OCR guess directly into an accepted downstream
  fact.
- Keep tax logic and other domain mappings in downstream adapters or case
  workspaces, not the generic extraction core.
- Add heavy extractors as optional adapters. The core package should remain
  useful with only standard local tools.
- Do not add a vector database without a measured retrieval problem that exact
  text search or SQLite full-text search cannot solve.

## Application Architecture

- Python owns the backend, application services, SQLite access, job
  orchestration, and extractor adapters.
- Domain and application modules do not depend on FastAPI, React, Tauri, or a
  concrete persistence implementation. Framework and platform adapters depend
  inward.
- Generate TypeScript wire types and a typed client from Python-owned API
  contracts. Keep a hand-owned `DocEvidenceRuntime` behavioral interface above
  generated transport types.
- React components consume the runtime interface rather than endpoint paths,
  filesystem paths, or platform APIs.
- TanStack Query owns server-derived state. Zustand owns narrow client-local
  selection, view, and interaction state. CSS Modules own new component
  presentation.
- The initial service binds to loopback. Do not add LAN/public binding,
  analytics, remote assets, hosted storage, or a remote-model fallback without
  an explicit tactical and user authorization.
- Protect the local API with the per-launch credential and origin rules in the
  active tactical. Never log, persist, or place that credential in a query
  string.
- Preserve the CLI and current artifact contracts while building vertical
  application slices. Do not mechanically reorganize all existing modules
  before a working consumer requires the boundary.
- A future Tauri shell remains thin lifecycle/security composition around the
  same Python application. Do not import Tauri into product components.

## Development Rules

- Target Python 3.12 unless compatibility testing supports widening the range.
- Prefer small typed modules and stable JSON-serializable contracts.
- Add or update tests with behavior changes.
- Record extractor and schema versions in output; never overwrite incompatible
  cached output in place.
- Benchmark quality and operational cost before changing the default
  extraction policy.
- Preserve raw extractor output when writing a normalization layer so failures
  can be diagnosed.
- Keep local API routes versioned and bounded. Never expose unrestricted local
  file access through a path supplied by a client.
- Add or update generated-contract drift checks when API contracts change.
- For frontend changes, run TypeScript, component, production-build, and
  relevant rendered-browser validation established by the active tactical.

## Browser Automation

- Do not use the built-in interactive browser or control the maintainer's
  browser for application inspection or validation; doing so interferes with
  their use of the computer.
- Use Playwright in a separate background/headless browser process instead.
  Start and stop any required local application server without opening a
  visible browser window.
- Only use the maintainer's interactive browser when they explicitly request
  it or when a task expressly depends on its existing authenticated state.

## Documentation Ownership

- `README.md` is the product and maintainer entry point.
- `docs/product-vision-and-architecture.md`, `docs/architecture.md`, and
  `docs/data-contracts.md` own durable system shape and contracts.
- `docs/topics/` owns current truth for continuing focused concerns.
- `docs/tactical/` owns numbered bounded implementation plans and execution
  records.
- `docs/references.md` owns sibling/external reference provenance and the
  boundary between adopted lessons and copied architecture.

Before changing a continuing concern, read its topic and update it when work
changes status, decisions, evidence, gaps, or recommended next work. Do not
create a topic for every standalone change.

New tacticals use zero-padded names such as `000-first-slice.md`. State scope,
non-goals, dependencies, invariants, validation, rollback, and one falsifiable
stopping condition before implementation. Update the tactical with actual
evidence as work lands; completed tacticals remain execution records.

An approved tactical authorizes ordinary internal naming, proportionate
refactoring, tests implied by its invariants, generated-type updates, and fixes
at the same ownership boundary. Stop for direction when evidence requires a
material product, durable-data, security, dependency, external-service, or
scope decision outside the tactical.

## Sibling Reference Discipline

`~/code/atpiano` is the primary application-architecture sibling. Before
implementing generated Python/TypeScript contracts, the React runtime boundary,
framework-independent Python services, local hosting, artifact export, or
Tauri sidecar packaging, read the exact pinned documents in
`docs/references.md` and inspect the current sibling source where relevant.

Adopt proven boundaries and failure lessons, not its audio/session domain. Do
not add a source dependency or copy code mechanically. Record intentional
differences in the owning topic or tactical.

## Private Data and Git

Common private document extensions and runtime stores are ignored. Do not use
`git add -f` for a private document. Public fixtures require an explicit
repository decision and should document their source and redistribution terms.

Local case configuration, model caches, extracted text, databases, rendered
pages, and benchmark runs remain untracked.

## Current Phase

Phases 1 and 2 implement the read-only Poppler-backed inventory,
content-addressed artifacts, duplicate detection, SQLite/FTS catalog, search,
OCRmyPDF/Tesseract, Docling and Marker adapters, private benchmark suites,
disagreement flags, local review packs, and per-class human scorecards. Phase 1
reconciled against the initial private 2023 tax corpus on 2026-08-01. Phase 2
calibration is now accumulating reviewed evidence. Do not select or retire a
heavyweight expert from agreement metrics or an under-supported aggregate
score.

The Python-owned localhost API and React/TypeScript read-only library and
extractor-comparison slice are implemented and pass automated/private
integration gates. Tactical 000 retains its explicit maintainer-acceptance
record, while the maintainer has selected durable extraction execution as the
next product priority.

`docs/tactical/001-durable-extraction-jobs.md` is the approved next scope but
has not been started. Do not begin its implementation until the maintainer
explicitly asks to proceed. Persistent review writes and Tauri packaging
remain outside both implemented Tactical 000 and planned Tactical 001.

## Validation and Commits

The current Python baseline is:

```bash
uvx ruff format --check src tests
uvx ruff check src tests
uv run python -m unittest discover -v
uvx pyright
uv build
```

Application tacticals add generated-contract, TypeScript, frontend-test,
production-build, and browser-review gates. Report exactly what ran and do not
claim optional private/model/manual lanes as automated passes.

Aim for a commit subject of 65 characters or fewer and wrap nontrivial commit
bodies at 72 columns. For a commit series implementing a living topic, append
the exact `Topic: <slug>` trailer. Do not add AI co-author or generation
trailers. Do not push, publish, tag, release, or add a remote without explicit
user authorization.
