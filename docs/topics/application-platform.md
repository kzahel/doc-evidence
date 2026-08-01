# Application Platform

Topic: application-platform

**Status:** Tactical 000 implemented and validated. The maintainer selected
and approved Tactical 001 as the next write-enabled plan; implementation has
not started.

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

## Sibling Precedent: atpiano

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

- The unified-database and migration direction is approved but not yet
  implemented.
- Application-home resolution, `DOC_EVIDENCE_HOME`, known-library registry,
  explicit library identity, and non-overlapping collection management are
  approved but not implemented.
- Tactical 001 starts with bounded polling for job updates. A later event
  stream remains optional and does not own durable correctness.
- Tauri packaging, Python runtime staging, and optional extractor-pack
  discovery have not been prototyped.
- The source checkout serves a separately built `web/dist`; self-contained
  wheel/desktop asset packaging is deferred to a packaging tactical.
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

The external private integration opened all seven calibration pages while an
aggregate source digest remained unchanged. The complete command and test
record is in
[Tactical 000](../tactical/000-read-only-library-comparison.md#execution-record).

## Recommended Next Work

Implement [Tactical 001](../tactical/001-durable-extraction-jobs.md) only after
the maintainer explicitly asks to proceed. Its write, persistence, worker,
artifact, recovery, and UI boundaries are frozen in the
[durable job architecture](job-architecture.md) and
[desktop library management](library-management.md). Durable review events
remain the likely following tactical.
