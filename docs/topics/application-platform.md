# Application Platform

Topic: application-platform

**Status:** Accepted direction; Tactical 000 is proposed and application code
has not started.

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
- Domain and application services must not depend on FastAPI, a browser,
  Tauri, or a concrete persistence adapter.
- The initial composition is a single-user localhost application over an
  explicitly configured external workspace.
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

## State and Persistence Boundary

The application must distinguish:

- rebuildable catalog projections;
- immutable derived artifacts;
- durable user-authored tags, notes, policies, and review events; and
- exported portable review/evidence records.

Tactical 000 is read-only and can use the existing `catalog.sqlite` directly
through application queries. The first write-enabled tactical must choose and
migrate a durable workspace store before saving review decisions.

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

- No application package, HTTP surface, frontend workspace, or generated
  TypeScript client exists yet.
- The physical split and migration policy for durable workspace state remains
  undecided.
- The exact job event transport is deferred until the UI can start work.
- Tauri packaging, Python runtime staging, and optional extractor-pack
  discovery have not been prototyped.
- A hosted composition is a possible future adapter, not current scope.

## Recommended Next Work

Implement [Tactical 000](../tactical/000-read-only-library-comparison.md) as a
read-only walking skeleton. Use its evidence to update this topic before
opening durable review writes or pipeline execution.
