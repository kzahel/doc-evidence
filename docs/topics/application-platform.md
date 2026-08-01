# Application Platform

Topic: application-platform

**Status:** Tactical 000 implemented and validated. Tactical 001 implementation
is complete; automated, isolated-browser, and authorized private-library gates
pass, with explicit maintainer interaction acceptance remaining. Tactical 002
unattended local unsigned/ad-hoc implementation is underway. Signing,
notarization, updater credentials, GitHub release setup, and publication have
not been authorized and their external targets still require confirmation.

## Scope

This topic owns the continuing application boundary above the existing
inventory, artifact, extraction, comparison, and review core:

- Python domain/application services and HTTP composition;
- generated frontend wire contracts;
- React runtime and state ownership;
- localhost security and lifecycle;
- durable versus rebuildable SQLite state;
- future Tauri sidecar composition; and
- portability between local web, desktop, and possible hosted adapters.

The durable product principles and complete system direction remain in
[Product vision and application architecture](../product-vision-and-architecture.md).
This topic records the current implementation posture as that direction is
tested through bounded tacticals.

## Current Decisions

- Python owns the backend, SQLite access, job orchestration, and extractor
  adapters.
- The product is designed as a desktop library application. The current
  localhost host and CLI are development/automation adapters over the same
  library and runtime contracts.
- The desktop model has an app-owned known-library registry and one SQLite/
  artifact store per library. Multiple collections share that library store.
- Platform-native application data is the production default;
  `DOC_EVIDENCE_HOME` is the required isolated override for development and
  tests.
- Domain and application services must not depend on FastAPI, a browser,
  Tauri, or a concrete persistence adapter.
- The initial composition is a single-user localhost implementation of the
  desktop-shaped library application over registered external collections.
- React and TypeScript provide the shared product UI.
- TanStack Query should own server-derived remote state. Zustand owns only
  client-local selection, view configuration, and transient interaction
  state.
- CSS Modules own component presentation. Do not begin a global stylesheet
  architecture for new product UI.
- Pydantic/API models generate OpenAPI and checked TypeScript wire types.
  Generated types do not replace a hand-owned behavioral runtime interface.
- The frontend consumes `DocEvidenceRuntime`; product components do not know
  endpoint paths, filesystem paths, or Tauri APIs.
- The localhost server binds only to loopback and protects its API with an
  ephemeral per-launch credential. A future Tauri shell launches the same
  Python application as an authenticated sidecar rather than embedding
  document logic in Rust.
- Existing CLI commands and content-addressed artifacts remain first-class
  interfaces. The application is additive.
- Source collections remain read-only under every composition.

## Sibling Precedents

The sibling repository at `~/code/atpiano` is directly relevant. It has
already implemented and reviewed a similar product shape:

- strict Pydantic contracts and generated OpenAPI/TypeScript;
- a hand-owned frontend runtime interface;
- React/Vite with TanStack Query for runtime state and narrow Zustand state;
- framework-independent Python application services behind thin FastAPI and
  CLI adapters;
- a thin Tauri 2 shell supervising an authenticated Python sidecar on an
  ephemeral loopback port; and
- product React components with no direct Tauri imports.

Use it as an implementation and failure-mode reference before inventing a
parallel boundary. The exact inspected documents and pinned revision are in
[References](../references.md).

For actual distribution, use the other mature local Tauri applications rather
than extending `atpiano`'s unsigned development boundary:

- `~/code/yepanywhere` owns the proven nested macOS signing, notarization,
  stapling, final signed-application smoke, and published-release QA sequence;
- `~/code/jstorrent` owns the established version/tag script, signed updater
  artifacts, `latest.json` validation, checksums, and release finalization;
  and
- `~/code/dotfiles/runbooks/desktop-code-signing.md` is the canonical
  credential-validation and GitHub Actions secret-provisioning runbook.

Their exact revisions and inspected files are pinned in
[References](../references.md). Secret values and credential source material
remain outside this repository.

### Direction to adopt

- Contracts point inward; HTTP, filesystem, database, and desktop adapters
  depend on them.
- A generated wire client and a hand-owned behavioral runtime solve different
  problems and should both exist.
- Frontend server state and local interaction state have different owners.
- Tauri is composition and lifecycle, not a product-component fork.
- Sidecar authentication, exact-origin access, startup handshake, bounded
  ready records, child monitoring, and app-close cleanup are designed before
  packaging.
- Artifact bodies stream through authorized endpoints rather than crossing a
  desktop bridge as large JSON or a single duplicated in-memory payload.
- Python packaging and heavyweight model/extractor packs are measured and
  manifested rather than assumed to fit.
- The first desktop distribution packages only Poppler, Tesseract language
  data, and a Ghostscript-free OCRmyPDF path. Docling, Marker,
  downloader/plugin behavior, and other operating systems remain later
  boundaries.
- Unsigned/ad-hoc builds are validation lanes. The release outcome follows the
  sibling convention: fail-closed credentials, explicit nested Mach-O signing,
  Tauri outer-bundle signing, notarization/stapling, final-app smoke, DMG,
  signed updater metadata, checksums, and release finalization.
- Native path selection uses a Rust-held host-control credential distinct from
  the bearer exposed to the desktop runtime. Product components request a
  behavioral library/collection operation and never submit an arbitrary path
  to the ordinary browser API.

### Intentional differences

- `doc-evidence` centers immutable document content, extractor-run identity,
  page/region provenance, and review history rather than audio sessions and a
  sample clock.
- The initial workspace is single-user and local. Family authentication and
  multi-user membership are not part of the first milestone.
- The current catalog is already rebuildable from source and artifact
  sidecars. Durable human review state must have a separate lifecycle.
- Extractors can be large isolated optional environments rather than one
  bundled model runtime.

No `atpiano` code is a dependency. Reuse concepts and validation lessons;
author `doc-evidence` contracts for its own domain.

The complete library-home, collection, managed-store, and application-path
contract is maintained in
[Desktop library management](library-management.md).

## State and Persistence Boundary

The application distinguishes:

- rebuildable catalog projections;
- immutable derived artifacts;
- durable user-authored tags, notes, policies, and review events; and
- exported portable review/evidence records.

Tactical 000 is read-only and uses the existing `catalog.sqlite` directly
through application queries. The approved
[durable job architecture](job-architecture.md) chooses one active
`doc-evidence.sqlite` for catalog generations, operational job state, and
future durable review state. These remain logically separate by table group
and retention policy while avoiding multiple active databases. Tactical 001
owns the migration from whole-file catalog replacement to atomic catalog
generations inside that database.

This is one database per library, not one global database spanning unrelated
libraries. App-level known/default/last library state is a bounded atomic JSON
registry beneath the application home rather than a second SQLite database.

## API and Runtime Direction

The initial implementation should test the same proven family of boundaries
as `atpiano`:

```text
domain values and persisted contracts
                ^
                |
framework-independent application queries/services
                ^
                |
SQLite / artifact / FastAPI / CLI adapters

React components
       ^
       |
DocEvidenceRuntime
       ^
       |
generated HTTP client or deterministic fixture runtime
```

Tactical 000 may select FastAPI, Pydantic 2, OpenAPI-generated TypeScript,
React, Vite, TanStack Query, Zustand, and CSS Modules for its bounded path.
Changing the durable domain or deployment direction requires a topic update;
ordinary library selection within those accepted boundaries belongs in the
tactical.

## Known Gaps

- Tactical 001 job, recovery, operational controls, production-like restart,
  headless-browser, and authorized private-integration gates pass; explicit
  maintainer interaction acceptance remains open.
- Tactical 001 starts with bounded polling for job updates. A later event
  stream remains optional and does not own durable correctness.
- Tauri packaging, Python runtime staging, and the small baseline extractor
  pack are implemented locally through Tactical 002's unattended lane. A
  copied-out unsigned application passes manifest, architecture, host-path,
  authenticated-sidecar, and real synthetic OCR audits.
- Developer ID signing, notarization/stapling, DMG/updater artifacts, and
  release finalization are also Tactical 002 scope, following the pinned
  sibling conventions. Optional extractor-pack discovery/downloads and
  Windows/Linux packaging remain later work.
- The source checkout serves a separately built `web/dist`; self-contained
  wheel/desktop asset packaging is deferred to Tactical 002.
- A hosted composition is a possible future adapter, not current scope.

## Implementation Evidence

Tactical 000 now provides:

- framework-independent Python application queries and comparison services;
- a concrete read-only SQLite/artifact adapter with identity- and root-bounded
  lookups;
- a versioned Pydantic/FastAPI surface protected by a per-launch in-memory
  bearer credential and exact loopback origin policy;
- checked OpenAPI plus generated TypeScript wire types/client;
- a hand-owned runtime consumed by React product components;
- TanStack Query server state, narrow Zustand interaction state, and CSS
  Modules; and
- a production-like `doc-evidence serve --config PATH` composition.

Tactical 001 now additionally provides the first desktop-shaped ownership
boundary: deterministic platform app-home resolution, an absolute
`DOC_EVIDENCE_HOME` override, an atomic bounded `app-state.json`, app-managed
wrapper descriptors for adopted legacy configurations, stable library IDs,
last/default activation, and ordinary `serve` startup without a repeated
configuration path. Explicit `--config` launch remains a registry-neutral
compatibility path.

The next landed boundaries replace catalog-file swapping with stable unified
projections and atomic membership generations, then carry explicit library ID
through Python application resolution, authenticated resource routes,
generated TypeScript, the hand-owned runtime, TanStack Query keys, Zustand
selection, and document/page deep links. The shared UI provides an actionable
empty-library home, stable-ID library selection, active-library naming, and
collection availability/settings without accepting a browser-supplied path.

The current landed boundary adds explicit document extraction actions above
the generated/runtime contract and a global activity center backed by bounded
polling. It exposes queue and resource state, confirmed OCR batch preflight,
pending/running batch cancellation, process liveness separately from progress
age and deadline, bounded retained log tails, event history, and repair of a
valid artifact whose catalog projection failed. React still consumes only the
hand-owned runtime; Python retains scheduler, filesystem, database, and
process ownership.

Tactical 002 now adds a dedicated macOS arm64 desktop-sidecar composition. It
uses independent runtime and Rust/Python-only host credentials, a strict
ephemeral-port ready record, an authenticated versioned runtime handshake, an
originless host-control handshake, and parent-EOF shutdown. Its trusted Python
control adapter now implements managed-library creation, idempotent existing-
config registration, and bounded managed collection changes without returning
absolute paths to React. The shared runtime now exposes matching behavioral
native operations, and the isolated desktop adapter validates the authenticated
handshake before composing the unchanged HTTP runtime. Empty-home and managed-
library settings surfaces consume those operations without a path or Tauri
import. A thin Tauri 2 shell now owns dual-secret generation, app-data
injection, strict ready/control validation, single-instance focus, Rust-owned
folder dialogs, sidecar supervision, app-close cleanup, and bounded failure
events. The ordinary localhost composition remains unchanged; standalone
runtime and extractor-pack staging remain owned by the desktop packaging
boundary.

The standalone-runtime and baseline-pack boundary is now landed locally. One
tracked entry point pins the upstream macOS arm64 CPython 3.12.12
`install_only_stripped` archive by URL and SHA-256, exports only frozen
production dependencies, removes installer and build-only material, records
component licenses and every staged file, and audits architecture, load paths,
symlinks, build-host paths, authentication, and parent-EOF shutdown. The pack
pins OCRmyPDF 17.8.1, PDFium 5.5.0, Poppler 26.03.0, Tesseract 5.5.3,
English/German/orientation data, and the exact small Tesseract renderer
configurations. All copied native inputs are arm64-only, have bundle-relative
load paths, and have ambient Homebrew defaults neutralized before nested ad-hoc
signing. Tauri verifies the bundle/pack identity before launch and requires the
Python ready record to report the same pack. An unsigned 192,070,647-byte
copied-out `.app` containing 3,840 files and 112 Mach-O objects passed real
Ghostscript-free synthetic OCR and packaged-sidecar smokes without the
checkout, Homebrew on `PATH`, or a system Python. Broader Poppler non-Latin
data behavior is not yet validated; a relocatable Poppler build or measured
PDFium replacement remains preferable before claiming that coverage.
A deterministic local DMG path avoids Finder automation, verifies the
compressed image, mounts it read-only, re-audits the contained application,
and detaches it. The current 73,267,094-byte unsigned image contains the exact
current `64baad23...` application tree and is validation evidence, not a
release artifact.

The first compliance preflight accounts for 70 top-level staged components,
all 3,835 runtime manifest files, 24 exact Homebrew source/bottle SPDX records,
24 exact historical Homebrew formula revisions, and five embedded Python-wheel
SBOMs. Formula selection is bound to the installed package version, source
hash, bottle hash, architecture/OS tag, and historical formula bytes; verified
recipes are reusable from an ignored cache. The preflight remains fail-closed
for publication: pypdfium2 needs a reviewed composite SPDX conclusion; 32
third-party libraries nested in Python wheels need flattened component/source
reconciliation (the other 45 Python native objects now have exact top-level
ownership);
19 Rust crates need repository-level license texts that their published crate
archives omit. Required top-level copyleft/MPL source archives are now
hash-verified and embedded. The
aggregate SPDX already includes all 253 target-resolved Rust dependencies and
11 conservative production Node dependencies, with 426 available license
files and exact registry source checksums.

The baseline wheel audit overrides `pi_heif` 1.4.0's wrapper-only BSD package
metadata with `BSD-3-Clause AND LGPL-3.0-only`, as required by the wheel's own
bundled notice for libheif/libde265. The exact-version override fails closed on
dependency drift and keeps both license files in the component manifest.

Maintainer review added session-local Small, Normal, and Large typography
presets. Normal is the default 120% root scale, Small preserves the original
100% scale, and Large uses 130%. The UI exposes names rather than percentages;
all rem-based application typography and spacing respond together.

The same session-local Zustand boundary now owns library collapse, the bounded
source/output split, and extraction-text presentation. The accessible desktop
separator supports pointer and keyboard adjustment without adding backend or
durable state; narrow evidence layouts remain stacked.

It also owns Focused, Stacked, and Compare review modes, the active
representation, and Diff versus Raw comparison presentation. These remain
transient layout choices; switching modes does not create a durable review
event or invoke a backend job.

Deep links use the SHA-256 document identity rather than a source path. The
catalog and document-detail contract provide the reverse mapping to every
`collection_id`/`relative_path` occurrence. This keeps links stable across
renames and correctly represents one content identity observed at multiple
paths.

The external private integration opened all selected calibration pages while an
aggregate source digest remained unchanged. The complete command and test
record is in
[Tactical 000](../tactical/000-read-only-library-comparison.md#execution-record).

## Recommended Next Work

Complete the explicit maintainer interaction acceptance in
[Tactical 001](../tactical/001-durable-extraction-jobs.md). Continue the
authorized unattended local unsigned/ad-hoc lane in
[Tactical 002](../tactical/002-macos-tauri-desktop-application.md), stopping
before credential provisioning, GitHub release setup, signing, notarization,
updater setup, or publication. Durable review events remain a separate later
tactical and are not authorized by the packaging plan.
