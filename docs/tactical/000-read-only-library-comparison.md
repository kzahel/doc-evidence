# 000 — Read-only Library and Extractor Comparison

Topic: application-platform

Topic: comparison-review-workspace

**Status:** Implemented; automated and private integration gates pass; awaiting
explicit maintainer acceptance of the live interaction.

## Motivation and Outcome

Replace the generated calibration page as the primary inspection experience
with the smallest honest product thread through the existing library.

After this tactical, a user can launch one local application against an
existing configured workspace, browse and search cached documents, open a
document page, inspect its extractor runs, see exact-equivalent outputs
collapsed, and compare two differing outputs with word and numeric differences
made explicit.

This is a read-only walking skeleton. It proves the Python/React/runtime
boundary and the core comparison interaction before introducing durable review
writes, job execution, tags, semantic observations, or Tauri packaging.

## Dependencies and References

- [Product vision and application architecture](../product-vision-and-architecture.md)
- [Core architecture](../architecture.md)
- [Data contracts](../data-contracts.md)
- [Application platform topic](../topics/application-platform.md)
- [Comparison and review workspace topic](../topics/comparison-review-workspace.md)
- [Extractor benchmarking](../benchmarking.md)
- [Sibling and external references](../references.md)

Before implementation, inspect the pinned `atpiano` contract, shared React,
Python application-core, and early Tauri tacticals listed in `references.md`.
Reuse their boundary lessons; do not copy their audio/session domain.

## Entry Evidence

- Phases 1 and 2 produce a content-addressed artifact store, rebuildable
  SQLite/FTS catalog, page-normalized extractor outputs, and a private
  five-document/four-extractor benchmark.
- An unchanged benchmark reuses all 20 cached extractor runs.
- The current calibration review exposed two concrete UX failures: identical
  output columns are difficult to distinguish, and representation/grading
  semantics are unclear.
- One inspected hybrid form page contains a raster form background plus native
  text overlay. The skip-existing-text OCR result is exactly equal to native
  Poppler output, while layout engines recover different visible content.
- The repository has no application server, frontend workspace, generated
  TypeScript client, or durable application database.

## Frozen Slice Decisions

### Application composition

- Add a framework-independent Python query layer over the existing catalog and
  artifact contracts.
- Use FastAPI as the Tactical 000 HTTP adapter and Pydantic 2 for API models.
- Generate checked OpenAPI, TypeScript wire types, and a typed HTTP client.
- Add a hand-owned `DocEvidenceRuntime` TypeScript interface above generated
  transport types.
- Add a React/TypeScript/Vite application under `web/`.
- TanStack Query owns server-derived data. Zustand owns only selected
  document/page/run groups, comparison choice, view mode, and pane layout.
- CSS Modules own component styling.
- The Python production composition serves the built frontend and versioned
  `/api/v1` routes. Development may use Vite with an explicit local proxy.
- Add `doc-evidence serve --config PATH` as the production-like local launch
  command. It binds to an ephemeral loopback port, generates at least 256 bits
  of random launch credential, and opens the exact local UI URL.
- The browser receives the credential through a non-query, non-server-visible
  launch fragment, captures it into runtime memory, and immediately removes it
  from the displayed/history URL. The generated HTTP adapter supplies it as a
  bearer header for API and artifact requests.

### Read-only state

- Tactical 000 does not create durable review or tag state.
- Existing `catalog.sqlite` and artifact sidecars remain authoritative for
  reads.
- No API route accepts an arbitrary filesystem path.
- The server resolves document hashes, run identities, artifact names, and
  configured source occurrences inside declared roots.

### Page renders

- Promote page rendering from benchmark-only code into a reusable adapter.
- Cache 144-DPI PNG pages under the content blob using a run key containing
  Poppler version, options, render schema, and source hash.
- Render only requested pages and preserve failures as inspectable run data.
- Page image routes stream only cached/validated render artifacts.

### Equivalence and comparison

- Group outputs only when normalized page text is exactly equal in v1.
- Name every extractor run in an equivalence group and choose a deterministic
  representative for display.
- Compute comparison data in Python from explicit page/run identities.
- Version the first algorithm as `word_numeric_diff_v1`.
- Tokenize Unicode words, numeric tokens, whitespace boundaries, and
  punctuation deterministically; align with a documented Python
  `SequenceMatcher` policy.
- Return equal, insert, delete, and replace segments. Numeric tokens remain
  explicit so the UI can prioritize them.
- Record input run IDs, page number, normalization version, algorithm version,
  and options in the response.
- Do not claim a winner or correctness from equality, similarity, or sparse
  assertions.

## User Interface Scope

### Library view

- Paginated document list from the current catalog.
- Literal/FTS search using the existing search semantics.
- Primary source-path hint, media type, page count, extraction status, and
  duplicate count.
- Loading, empty, and actionable failure states.

Folder-tree navigation, tags, saved views, document-class facets, and broad
collection management are deferred.

### Document workspace

- Source identity and source occurrences.
- One-based page navigation with total page count.
- Rendered page beside extraction output.
- Extractor groups labeled as native text, OCR/preprocessing, layout parser,
  or other representation.
- Exact versions, options, warnings, cache identity, and raw-artifact links.
- Raw versus normalized label; v1 may display normalized page text only when a
  raw artifact has no safe text representation, but must say so.

### Comparison workspace

- Exact-equivalent outputs collapsed into one group.
- Baseline and comparison group selectors.
- Differences-only as the default, with full aligned output available.
- Visually distinct insert, delete, replace, and equal context.
- Numeric-only navigation and a numeric discrepancy summary.
- Clear selected page and document scope.
- Sparse benchmark assertions shown as non-authoritative spot checks when the
  opened document belongs to a benchmark run.

The first slice optimizes for desktop inspection. It must remain functional at
a narrow browser width, but a final phone-first document-review layout is not
required.

## Python Ownership and Dependency Direction

```text
existing domain values + new API contracts
                    ^
                    |
read-only application queries + comparison service
                    ^
                    |
catalog / artifact / renderer / FastAPI adapters

React components
       ^
       |
DocEvidenceRuntime
       ^
       |
generated HTTP adapter or deterministic fixture adapter
```

- Application queries do not import FastAPI or frontend modules.
- Comparison logic does not read unrestricted paths or HTTP request objects.
- Existing CLI behavior continues to call existing core services; this slice
  does not mechanically move all current modules into the proposed long-term
  repository tree.
- Product React components import `DocEvidenceRuntime`, not endpoint strings,
  Tauri APIs, or filesystem paths.

## API Surface

The bounded v1 surface may include:

```text
GET /api/v1/workspace
GET /api/v1/documents
GET /api/v1/documents/{document_id}
GET /api/v1/documents/{document_id}/pages/{page}
GET /api/v1/documents/{document_id}/pages/{page}/render
GET /api/v1/documents/{document_id}/runs
GET /api/v1/documents/{document_id}/pages/{page}/groups
POST /api/v1/comparisons
GET /api/v1/artifacts/{artifact_id}
GET /api/v1/search
GET /api/v1/diagnostics
```

Exact route names may tighten during implementation if the runtime interface
and user-visible outcome remain unchanged. Arbitrary path access, mutations,
job starts, review writes, and source downloads are excluded.

## Security and Resource Bounds

- Bind to `127.0.0.1` by default. No wildcard or LAN binding in this tactical.
- Require the per-launch bearer credential on every API, page-render, and
  artifact request. It must not appear in server logs, query strings, retained
  files, API errors, or application state persistence.
- Accept only the configured frontend development origin and the server's own
  production origin.
- Resolve every artifact beneath the configured store after canonicalization.
- Resolve source occurrences only through manifest/catalog identities and
  configured collection roots.
- Stream page images and artifacts with bounded response headers; do not embed
  large document bytes in API JSON.
- Cap document page size, search limit, comparison input size, and rendered
  page dimensions with explicit errors.
- No route transmits content to a remote service, and the frontend loads no
  remote scripts, fonts, analytics, or assets.
- Source files are opened read-only. Integration validation records that their
  content hashes and metadata do not change.

Tactical 000 validates the browser launch boundary only. Tauri still requires
a separate tactical for Rust-owned secret generation, authenticated startup
handshake, child supervision, and exact webview-origin policy before
packaging.

## Staged Implementation

### 1 — contracts and application queries

- Define API models from the next executable UI needs.
- Add read-only workspace, document, page, run, group, search, and diagnostic
  queries.
- Add shared representative contract fixtures.
- Generate OpenAPI, TypeScript types, and the HTTP adapter deterministically.

### 2 — reusable page render and comparison services

- Extract versioned 144-DPI page rendering from benchmark composition.
- Add exact page-output grouping.
- Add `word_numeric_diff_v1` and deterministic tests.
- Preserve current benchmark behavior through the new render service.

### 3 — React library and document workspace

- Scaffold Vite, runtime boundary, query composition, narrow Zustand state,
  and CSS Modules.
- Implement library/search, document/page, output-group, and artifact views.
- Cover loading, empty, failed, and direct-link states.

### 4 — comparison interaction and integration evidence

- Implement group selection, differences-only/full modes, and numeric
  navigation.
- Exercise a generated public fixture and the external private calibration
  workspace without copying private data.
- Prepare a live review command and compact evidence packet.

## Automated Validation

### Python

- Existing unit and integration tests remain green.
- API tests cover pagination, lookup, missing identities, path traversal,
  launch authentication, origin policy, credential redaction, render
  caching/failure, grouping, and diff segments.
- A generated synthetic hybrid PDF provides a raster background and native
  text overlay without committing private content.
- Exact-equivalent outputs group; one changed numeric token produces an
  explicit numeric replacement.
- Application and comparison modules pass dependency-direction tests without
  importing FastAPI.
- Ruff, formatting, static typing, schema validation, and build checks pass.

### Contracts and frontend

- OpenAPI and generated TypeScript/client drift checks pass.
- Shared representative payloads validate in Python and TypeScript.
- TypeScript typecheck, frontend unit/component tests, and production build
  pass.
- Component tests cover empty/error states, exact grouping, baseline changes,
  differences-only/full output, and numeric navigation.
- No product component contains endpoint strings or imports a platform API.

### External private integration

- Launch against the existing private case configuration without modifying or
  copying source documents.
- Browse the indexed library and open every selected calibration page.
- Confirm the known native-text and skip-text-OCR outputs collapse into one
  exact-equivalence group on the inspected hybrid form.
- Compare that group with at least one layout parser and navigate every
  numeric discrepancy.
- Record only counts, timings, versions, errors, and UI screenshots that are
  safe for the private workspace; commit no private content.

## Manual Review Gate

Before Tactical 001, the maintainer reviews the live local application at a
desktop width and a narrow browser width. The handoff includes:

- one install command and one launch command;
- the library and search view;
- one document/page workspace;
- an exact-equivalence group;
- one word/numeric comparison;
- raw/normalized and extractor-category labels;
- loading, empty, and failure examples;
- the private-data/write/network boundary; and
- automated validation results.

The review asks whether the information hierarchy, terminology, diff density,
and page/output split make document inspection materially easier than the
generated HTML. Silence is not acceptance.

## Explicit Non-goals

- No persistent review decisions, corrections, tags, notes, or saved views.
- No workspace migration or durable review database.
- No inventory, extraction, or pipeline jobs started from the UI.
- No observation candidates or domain-specific field mapping.
- No spatial overlay diff beyond displaying existing coordinates in metadata.
- No file watching, background daemon, cloud service, authentication system,
  accounts, collaboration, or sync.
- No Tauri shell, Python bundle, signing, updater, or desktop installer.
- No source-file mutation, document upload, reorganization, or deletion.
- No broad refactor of existing extractor modules solely to match the proposed
  repository tree.

## Rollback and Compatibility

The application, API, render cache, and frontend are additive. Existing CLI
commands, schemas, manifests, catalog layout, extractor runs, benchmark suites,
and generated review pages remain usable.

The Tactical 000 API is explicitly versioned `v1` but not yet a compatibility
promise to external consumers. Breaking it before the next accepted tactical
requires regenerating the checked client and fixtures, not migrating private
source or extractor artifacts.

Removing the slice deletes only code and derived render/diff caches. It must
not require a source-document or review-state migration.

## Stopping Condition and Next Slice

Tactical 000 is complete when the read-only application meets the automated
gates, the private calibration integration works without source changes or
network access, and the maintainer explicitly accepts the live library and
comparison interaction.

The expected Tactical 001 adds durable review events, correction history, and
portable review export over the accepted comparison workspace. It does not
begin automatically if the interaction review identifies a different product
shape.

## Execution Record

Implementation was approved and completed on 2026-08-01 in three reviewable
slices:

1. `1bb234b` — framework-independent read-only application services,
   Pydantic contracts, bounded local workspace adapter, FastAPI composition,
   authenticated loopback launch, render cache, and versioned comparison
   service;
2. `edd5803` — checked OpenAPI/TypeScript contracts, hand-owned runtime,
   React/Vite application, TanStack Query/Zustand state split, library,
   document, equivalence, comparison, assertion, and fixture-test views; and
3. `df94d73` — final integration and polish covering direct links,
   unsupported-file selection,
   sandboxed raw-artifact preview, zero-byte artifacts, responsive validation,
   and documentation; and
4. `a067754` — maintainer-review follow-up adding global typography scaling,
   distinct comparison-side enforcement, direction swapping, cached-run
   coverage labels, and explicit image-only/OCR limitations.

### Automated evidence

- Ruff formatting and lint checks pass.
- 18 Python unit/integration tests pass, including authentication, origin
  policy, bounded identities, traversal rejection, rendering, cache reuse,
  source immutability, exact grouping, and numeric replacements.
- Pyright reports zero errors and `uv build` succeeds.
- Checked OpenAPI and generated TypeScript/client drift checks pass.
- TypeScript typecheck passes; 12 frontend tests pass; the Vite production
  build succeeds.
- The dependency boundary checks confirm that application/comparison modules
  do not import FastAPI and product components do not contain endpoint paths,
  Tauri imports, or filesystem imports.

### External private integration evidence

The production build was exercised locally against the external 2023 tax
configuration without copying private data into this repository:

- the library reported 80 unique documents and 81 source occurrences;
- all seven selected calibration pages across five documents rendered,
  exposed extractor groups, accepted direct document/page links, and opened a
  comparison workspace without browser-console errors;
- a known hybrid form collapsed the Poppler and skip-existing-text OCR runs
  into one exact-equivalence group while keeping the layout-parser output
  separate;
- a representative literal query returned 14 page-level matches;
- differences-only/full switching, numeric navigation, baseline/comparison
  swapping, and the narrow stacked layout passed in headless Playwright;
- raw artifacts, including a valid zero-byte stderr artifact, opened in a
  bounded sandboxed preview with a download option; and
- an aggregate SHA-256 digest over every configured private source file was
  identical before and after the seven-page integration run.

The integration pass found and fixed four concrete issues before handoff: an
unsupported Word document being chosen before the first renderable PDF,
successful zero-byte artifacts being mistaken for failed responses,
asynchronous artifact previews being blocked as popups, and direct-link query
state being written but not restored.

### Remaining gate

The code and integration gates are complete. Tactical 000 remains open only
for the maintainer's explicit live acceptance of the information hierarchy,
terminology, diff density, and page/output split. That review determines
whether the next tactical should add durable review events or first revise the
read-only interaction.

### Maintainer review follow-up

The first live maintainer pass found two interaction problems and one pipeline
expectation gap:

- global typography was too fixed, so the header now exposes an 80%–150%
  root-scale adjustment;
- baseline and comparison could select the same representation, so opposite
  selections are disabled, identical state is normalized defensively, and an
  explicit swap-direction control was added; and
- the UI did not explain why most documents show only one extraction. It now
  displays cached run/representation counts, says that the view does not
  launch missing extractors, and explains image-only PDFs.

The underlying gap is recorded rather than hidden: inventory currently runs
Poppler for PDFs only. The four-expert outputs exist for the five-document
private benchmark suite, not the full catalog, and standalone images are only
inventoried. Turning the declared OCR/layout policy into resumable broad
execution remains outside Tactical 000's read-only UI scope.
