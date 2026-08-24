# Instructions for Agents Working on doc-evidence

These instructions apply to this repository.

## Purpose and Boundary

Build a reusable local-first document inventory, extraction, benchmark,
search, and evidence-understanding pipeline. The system must preserve source
provenance and keep automated candidate observations distinct from reviewed
facts.

This repository contains generic code and public/synthetic fixtures only. Its
first downstream integration is an external tax-document workspace whose
case-side plan remains in that private workspace.

Never copy, move, rename, commit, upload, or modify private source documents as
part of generic-tool development. Read an external collection only when the
task and an explicit configuration path place it in scope.

## Product Destination and Delivery Sequence

The intended product is a distributable, local-first desktop document-evidence
application, not a permanently CLI-only tool or a browser product that happens
to read local files. Preserve this direction in architecture, planning, and
implementation decisions:

- The shared product is the React interface over framework-independent Python
  library, persistence, job, extraction, comparison, review, and provenance
  services.
- The current authenticated loopback server and CLI are development,
  automation, and headless compositions of those same services. They are not a
  separate product model.
- The Tauri shell is intentionally thin. It owns native lifecycle,
  application-data injection, folder authorization, Python-sidecar
  supervision, and desktop distribution concerns without moving document or
  evidence logic into Rust or importing Tauri into React product components.
- The durable user-facing unit is a named library with a stable ID, one SQLite
  database, one artifact store, and one or more explicit read-only source
  collections. App-wide known/default/last-library state is bounded metadata
  beneath the platform application-data directory.
- Tactical 001 is the implemented desktop foundation and durable-job slice: it
  adds application-home isolation, remembered libraries, unified per-library
  persistence, durable execution, recovery, and operational UI. Its automated
  and private-integration gates pass; explicit maintainer interaction
  acceptance remains. Durable human review state follows separately.
- Tactical 002 is the implemented macOS arm64 unsigned desktop foundation. It
  lands Apache-2.0 project licensing, the thin Tauri shell, separate runtime
  and host-control credentials, native folder authorization through
  Python-owned services, standalone CPython, the small Ghostscript-free
  Poppler/Tesseract/OCRmyPDF baseline pack, strict audits, unsigned DMG, and
  fail-closed compliance preflight. Its originally planned macOS-only signed
  lane is superseded by Tactical 003.
- Tactical 003 is the documented implementation plan for the paired macOS arm64
  and Windows x86_64 first signed release, with Linux deferred. It owns the
  Windows platform adaptation, process-tree and path semantics, runtime/pack,
  per-user NSIS installer, two-platform updater/release finalization, and exact
  installed-artifact acceptance through Machine Control. Local implementation
  and validation were authorized on 2026-08-24; external release actions still
  require explicit maintainer authorization.
- Optional heavyweight-extractor packs, download/plugin management,
  alternative release channels, and Linux distribution require later approved
  tacticals.

Do not let a short-term localhost or CLI implementation create a competing
ownership model, embed platform APIs in product components, or make later
desktop packaging depend on private case paths or source mutation.

## Startup Routine

Before substantive work:

1. Read `README.md`.
2. Read `docs/product-vision-and-architecture.md`.
3. Read `docs/topics/application-platform.md` and
   `docs/topics/comparison-review-workspace.md` for application work. Consult
   `docs/topics/maintainer-feature-requests.md` before planning or changing
   the live review interface.
   Read `docs/topics/spatial-provenance-and-regional-ocr.md` before changing
   page coordinates, normalized spatial spans, source/text overlays, spatial
   comparison, regional extraction, or region-linked observations and review.
   Read `docs/topics/product-landscape-and-use-cases.md` before changing
   product positioning, durable review, candidate observations, domain packs,
   source-to-form mapping, agent workflows, or external product integration.
   Read `docs/topics/job-architecture.md` before changing job persistence,
   scheduling, workers, extraction execution, artifact publication,
   cancellation, recovery, or operational UI.
   Read `docs/topics/library-management.md` before changing application-home
   discovery, library registration or selection, configuration persistence,
   store/database ownership, collection scope, desktop startup, or collection
   overlap behavior.
4. Read the active tactical under `docs/tactical/` before implementing its
   scope. `docs/tactical/000-read-only-library-comparison.md` is the implemented
   read-only execution record. `docs/tactical/001-durable-extraction-jobs.md`
   is implementation-complete and awaiting explicit maintainer acceptance.
   `docs/tactical/002-macos-tauri-desktop-application.md` is the implemented
   macOS unsigned-foundation execution record.
   `docs/tactical/003-macos-windows-signed-desktop-release.md` is the documented
   paired-platform plan and active local implementation boundary. Do not
   perform its external release actions or implement the durable-review
   successor without explicit maintainer authorization.
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
- Keep extractor confidence, cross-extractor agreement, deterministic
  validation, agent assessment, and explicit human confirmation separate.
  Durable review records must identify actor and purpose; an agent decision is
  never presented as human confirmation.
- Provisional downstream calculations and form mappings must retain unresolved
  inputs, reverse provenance, and an evidence-coverage summary.
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
- The Tauri shell remains thin lifecycle/security composition around the
  same Python application. Do not import Tauri into product components.
- Treat a library as the durable user-facing unit: one stable library identity,
  one SQLite database, one artifact store, and one or more explicit read-only
  collections. The app registry is bounded metadata, not another database.
- Resolve all app-owned state beneath the platform application-data directory,
  or beneath `DOC_EVIDENCE_HOME` when that explicit override is set. Tests and
  isolated development runs must use a fresh temporary override and must not
  touch the maintainer's main application state.
- The authorized private acceptance lane is the deliberate exception to the
  previous sentence: it uses the already registered default-home library only
  through `scripts/run-private-integration.py --expected-config PATH`, verifies
  the selected configuration, and compares source hashes and registry bytes
  before and after. Do not generalize that authority to other external data.

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

`~/code/atpiano` is the primary application-architecture and Python-sidecar
sibling. `~/code/yepanywhere` is the primary nested macOS signing,
notarization, and final-application validation sibling. `~/code/jstorrent` is
the primary release/tag, updater-metadata, checksum, and publication sibling.
The canonical credential-provisioning instructions live in
`~/code/dotfiles/runbooks/desktop-code-signing.md`. Before
implementing generated Python/TypeScript contracts, the React runtime boundary,
framework-independent Python services, local hosting, artifact export, Tauri
sidecar packaging, desktop signing, or release automation, read the exact
pinned documents in
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
reconciled against an authorized external corpus. Phase 2
calibration is now accumulating reviewed evidence. Do not select or retire a
heavyweight expert from agreement metrics or an under-supported aggregate
score.

The Python-owned localhost API and React/TypeScript read-only library and
extractor-comparison slice are implemented and pass automated/private
integration gates. Tactical 000 retains its own explicit acceptance status,
while the maintainer selected durable extraction execution as the next product
priority.

`docs/tactical/001-durable-extraction-jobs.md` is implementation-complete after
the maintainer explicitly authorized end-to-end execution. Application-home
resolution, an atomic known-library registry, legacy-config adoption, and
ordinary launch from the last/default library are the first landed boundary.
The unified per-library database, stable content/run/page/FTS projections,
atomic inventory generations, incremental/full hashing, legacy catalog import,
and collection preflight are the second landed boundary.
Explicit library-scoped API resources, generated/runtime operations, query
keys, deep links, empty-home behavior, selection UI, and collection settings
are the third landed boundary.
The typed extractor registry, private supervised worker protocol, exact-source
recheck, bounded process-tree execution, staged validation, and atomic
canonical artifact publication are the fourth landed boundary. Worker protocol
v2 binds adapter output to the run ID/key planned at enqueue in both worker and
supervisor, so a self-consistent but unplanned staged run cannot be published.
Schema-versioned jobs/attempts/events, exact cache fulfillment, idempotent and
coalesced enqueue, process-locked scheduler leasing, priority aging, bounded
resource dispatch, cancellation, one transient retry, and restart/integrity
reconciliation are the fifth landed boundary.
Extractor capability, single-job, confirmed-batch, activity, attempt/event,
cancel, and retry contracts are the sixth landed boundary, including checked
OpenAPI/TypeScript generation and the hand-owned React runtime operations.
Explicit document extraction controls and post-publication representation
refresh are the seventh landed boundary. The global activity center, bounded
OCR batch preflight, queue control, batch cancellation, resource/liveness
diagnostics, bounded logs, and catalog-projection repair are the eighth landed
boundary. Deterministic crash/restart and isolated headless-browser gates pass.
The authorized default-home integration also passes: one missing configured-
language OCR run executed, exact OCR and layout cache reuse worked, broad OCR
stayed at preflight, and source and registry integrity checks remained
unchanged. Only explicit maintainer interaction acceptance remains.
Persistent review writes and Tauri packaging remain outside Tactical 001.

Tactical 002's unattended local unsigned/ad-hoc macOS implementation was
authorized on 2026-08-01. Apache-2.0 source licensing and strict bundle/pack
manifest schemas are the first landed slice. A dedicated macOS arm64 Python
sidecar now adds independent runtime/host credentials, bounded ready and
handshake records, exact-origin runtime access, originless host control, and
parent-EOF shutdown. The trusted Python control adapter now creates managed
libraries, registers existing configurations without rewriting them, and
applies bounded managed collection changes without returning paths to React.
The React runtime now exposes matching path-free native operations, with Tauri
imports isolated to the lazy desktop adapter and bounded empty-home/settings
controls in the shared product.
The thin Tauri 2 shell now generates both credentials, injects the preserved
application-data root, validates ready/control records, owns native dialogs
and single-instance focus, supervises the Python child, and closes stdin before
bounded termination on app exit. A hash-pinned CPython 3.12.12 standalone
runtime, frozen production dependencies, license/file manifests, staged/native
audits, and copied-out unsigned `.app` smoke now pass. The baseline extractor
pack, unsigned DMG, real mounted-artifact OCR smoke, and fail-closed compliance
preflight now pass. The preflight still blocks release on the reviewed
pypdfium2 SPDX conclusion, 32 nested wheel libraries, and 19 Rust crate license
texts. `docs/tactical/002-macos-tauri-desktop-application.md` is the durable
execution record for that foundation.

On 2026-08-23 the maintainer selected a paired macOS arm64 and Windows x86_64
first signed release, with Linux deferred. The documented plan is
`docs/tactical/003-macos-windows-signed-desktop-release.md`. Its first gates are
the existing macOS compliance blockers and Windows Machine Control readiness.
Local implementation and validation were authorized on 2026-08-24. The Windows
identity and disposable-workspace gate now pass, including semantic action,
independent effect, target-native capture, bounded artifact retrieval, and
discard verification. Exact paired desktop contracts and Windows kill-on-close
Job Object ownership for both the Rust sidecar and Python attempt trees are now
implemented. The available Windows ARM64 guest passes target-native attempt
cleanup and x86_64-emulated Rust process-tree tests. Python-owned Windows path
identity, fixed-drive admission, and reparse/offline traversal policy also pass
target-native tests; actual greater-than-260-character I/O remains bound to the
standalone runtime and installed-app gate. The exact Windows runtime/pack input
manifest and dependency-free PE import/delay-import audit have landed, with 55
selected native payload hashes. The exact Microsoft app-local CRT input closes
that flat native dependency graph. Safe exact pack assembly, corrected archive-
bound language hashes, the Windows pack manifest, and the relocatable OCRmyPDF
launcher source have landed. Exact Windows wheels form a closed 123-file PE
graph after pruning. The transactional target-only runtime builder and copied-
location OCR, sidecar, and long-path gates are implemented but have not run on
Windows. The current-user NSIS overlay and exact unsigned app/installer audits
have also landed without executing a target build. Microsoft redistribution
review, third-party Windows dependency compliance, target-native assembly/
execution, and native Windows x86_64 installed-artifact acceptance remain
release-blocking. Do not touch signing
credentials, repository/release setup, notarization, updater setup, tags, or
publication without explicit maintainer authorization. Heavy extractor packs
and alternative release channels remain outside it.

The maintainer has also selected bidirectional text/page highlighting and
bounded regional OCR as an accepted product direction. The researched
extractor capabilities, coordinate-space contract, proposed UI, job identity,
and machine-versus-human trust boundary live in
`docs/topics/spatial-provenance-and-regional-ocr.md`; no implementing tactical
has been authorized.

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
