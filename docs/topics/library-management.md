# Desktop Library Management

Topic: library-management

**Last updated:** 2026-08-24

**Status:** Tactical 001 implementation complete. Application-home,
known-library registry, adopted descriptors, CLI activation, unified library
persistence, inventory generations, and collection preflight are implemented.
Shared UI selection and explicit library-scoped job identity are implemented;
explicit maintainer interaction acceptance remains. Tactical 002's trusted
Python host-control operations, Tauri dialogs, packaged startup, and macOS
application-data injection are implemented. Tactical 003 now selects Windows
per-user local application data in the host and implements case/separator path
identity, fixed-drive admission, and reparse/offline traversal policy. Actual
long-path I/O and installed-app acceptance remain open. A durable,
library-scoped inventory job and authenticated API operation now close the
backend half of fresh-library indexing; the automatic React trigger and
settings control remain in progress. Store relocation remains later scope.

## Purpose

This topic owns the continuing product and architecture for creating,
registering, selecting, opening, configuring, and storing document libraries.
It also owns application-home resolution, explicit source collections,
library identity, collection overlap behavior, desktop-managed storage, and
the compatibility boundary for the current case-local configuration.

The primary mental model is an installed desktop application with a library
home screen. The localhost web composition and CLI exercise the same library
application services for development and automation; they do not define the
user model.

## Vocabulary

- **Application home** — app-owned settings and managed library directories.
- **Library** — one named document workspace with one SQLite database, one
  artifact store, and one or more collections.
- **Collection** — one explicitly authorized read-only source folder with an
  ID, display name, and include/exclude policy.
- **Library descriptor** — versioned inspectable configuration naming the
  library, collections, store, languages, and extraction/search policy.
- **Managed store** — the library-owned database, blobs, manifests, attempts,
  and diagnostics. It never contains source documents merely because they are
  indexed.
- **Application registry** — small app-level state listing known libraries and
  the last-opened/default library. It contains no document database or
  extracted content.
- **Virtual collection** — a future saved filter/tag/view over already indexed
  content, not another physical scan root.

## Desktop-First User Model

The installed application starts at a library home or reopens the last active
library:

```text
Doc Evidence

Libraries
+--------------------------------+
| Tax Documents                  |
| 4 collections · last opened now|
+--------------------------------+

[New Library] [Open Existing Library]
```

Inside a library, the application header always displays its name. Library
settings list explicit collection folders, indexing state, and managed-store
usage. Selecting, adding, expanding, or removing a collection is a deliberate
library operation; navigating the document workspace never changes library
scope.

The Tauri shell will eventually own native folder pickers, platform folder
authorization, sidecar lifecycle, and application-data path injection. React
product components consume a platform-neutral `DocEvidenceRuntime` library
contract and do not import Tauri APIs.

The proposed first macOS distribution keeps native paths out of the ordinary
browser API by giving Rust and Python a separate per-launch host-control
credential.
Rust chooses a folder or descriptor with a native dialog and submits it
directly to a bounded Python desktop-control adapter. Python still owns path
canonicalization, collection/store overlap policy, stable IDs, descriptors,
and registry writes. JavaScript receives the resulting library behavior, not
generic filesystem authority.

## Application Home

Production resolves an operating-system-appropriate app-owned data root. The
expected defaults are conceptually:

```text
macOS:   ~/Library/Application Support/doc-evidence
Linux:   $XDG_DATA_HOME/doc-evidence or ~/.local/share/doc-evidence
Windows: the per-user local application-data directory/doc-evidence
```

Use a platform-path resolver rather than hard-coding one operating system into
domain or application services.

Application-home resolution has one deterministic precedence order:

1. an explicit `DOC_EVIDENCE_HOME` environment override;
2. an app-data root injected by the desktop host; then
3. the operating system's standard per-user application-data location.

Diagnostics report which source selected the root without exposing sensitive
environment values unrelated to this application.

### Required override

`DOC_EVIDENCE_HOME` overrides the entire application-home root for development,
tests, isolated local launches, and sidecar validation:

```sh
DOC_EVIDENCE_HOME=/absolute/temporary/path uv run doc-evidence serve
```

The override is frozen with these semantics:

- it is read once during process composition;
- it must resolve to an absolute, writable application-owned directory;
- all registry, managed-library, temporary, and diagnostic paths that would
  normally use the production app home resolve below it;
- it does not change external collection paths or an explicitly adopted
  external library store;
- an isolated run must not read or write the production app home;
- the resolved root is visible in local diagnostics but never includes a
  launch credential;
- tests and background/headless Playwright must always use a fresh temporary
  `DOC_EVIDENCE_HOME`; and
- no `.env` file is automatically loaded as hidden application state.

An explicit desktop-host bootstrap value may feed the same resolver when
Tauri owns the platform directory. Environment override remains required for
standalone testing and development.

Do not overload `HOME`, `XDG_DATA_HOME`, or another process-global system
option in tests. Use the product-specific override.

## App-Owned Layout

The default managed layout is:

```text
<DOC_EVIDENCE_HOME or platform app-data root>/
  app-state.json
  libraries/
    <library-id>/
      library.yaml
      doc-evidence.sqlite
      blobs/
      manifests/
      attempts/
      diagnostics/
```

`app-state.json` is a versioned, bounded, atomically written registry. It may
record:

- known library ID, name, and descriptor location;
- managed versus adopted/external store mode;
- last-opened time and last/default library ID; and
- a small compatibility/status summary.

It does not contain document text, source inventory, extraction output, jobs,
reviews, launch credentials, or unrestricted cached API responses. If the
registry is lost, managed library directories retain their own descriptors
and IDs so the app can offer bounded recovery rather than losing the library
data.

The registry is not a second SQLite database. There is exactly one SQLite
database per library. A user with one library has one document database; a
user who deliberately creates several independent libraries has one database
for each isolation/backup boundary.

## Library Identity and Descriptor

Every new library has:

- an immutable stable library ID;
- a mutable human-readable name;
- a versioned descriptor;
- one managed or explicitly adopted store; and
- one or more explicit collections.

The library ID appears in its descriptor, database metadata, registry entry,
jobs, API resources, diagnostics, and deep links. A descriptor, database, and
registry that disagree on identity produce a blocking integrity error rather
than silently opening the wrong documents.

New desktop-created libraries put `library.yaml` in their managed app-home
directory by default. The existing `.doc-evidence.yaml` contract remains an
import/automation format. Tactical 001 supports registering or adopting the
current external tax configuration and store without modifying source
documents, copying private documents, or rerunning existing successful
artifacts.

Importing a legacy descriptor that lacks stable library identity must not
silently rewrite the external file. The import records the assigned identity
in managed application state and the unified library database, and offers an
explicit later descriptor-upgrade/export action. Exact legacy migration and
rollback evidence belongs to Tactical 001.

## Explicit Collections

A library may contain several non-overlapping sibling collections:

```text
Tax Documents
  taxes-2023 -> /.../taxes/taxes2023
  taxes-2024 -> /.../taxes/taxes2024
  taxes-2025 -> /.../taxes/taxes2025
  inbox      -> /.../taxes/inbox
```

All collections share the library database, content-addressed artifacts,
search, jobs, and future review state. A collection does not create its own
database or extraction cache.

Collection roots are canonicalized and must not overlap each other or the
library store. Equivalent roots reached through aliases are rejected. Source
symlinks continue to be skipped under the existing evidence policy.

### Adding a parent of an existing collection

The application does not register both roots. It presents a scope-expansion
operation:

```text
Replace: /records/2023/TaxPacket
With:    /records/2023

Existing content and extractor artifacts will be reused.
Additional paths will be inventoried after confirmation.
```

Confirmation replaces the child root inside the same library. It creates a
new inventory membership generation and preserves library/database/artifact
identity.

### Adding a child of an existing collection

The app reports that the folder is already covered. If the user wants a named
subset, the later product should create a virtual collection, saved filter, or
tag rather than scanning the same files twice.

### Adding siblings

Non-overlapping sibling folders are normal collections and require no special
deduplication behavior. Byte-identical content across siblings still resolves
to one content identity with multiple legitimate source occurrences.

Configuration loading rejects overlapping canonical collection roots and
source/store overlap. The framework-independent preflight classifies sibling,
same-root, already-covered child, parent-replacement, unavailable, and store-
overlap outcomes without changing scope.

## Scope Changes and Artifact Reuse

Paths and collection membership are observations, not document identity.
Replacing a child collection with its parent, renaming a collection, or adding
siblings must not invalidate content-derived work.

The unified database therefore separates:

```text
generation-independent content data
  content_objects
  extraction_runs
  run_pages
  pages_fts
  registered_artifacts

generation-scoped library membership
  inventory_generations
  collection_snapshots
  source_occurrences
  generation_documents
  duplicate_members
```

An expanded inventory hashes or safely reuses the hash of each observed file,
links known content to existing runs/pages/FTS, and executes extractors only
for new content or a genuinely new extractor identity. Activating the new
generation changes searchable membership without duplicating normalized page
text for every generation.

Incremental scan metadata may reuse a prior SHA-256 when resolved path,
filesystem identity, size, modification time, and change time all remain
consistent. SHA-256 remains canonical. A full verification mode must rehash
every source and never trust metadata alone.

Removing or narrowing a collection does not immediately delete successful
blobs. Explicit garbage collection must consider active and retained
generations, manifests, jobs, attempts, reviews/observations, pins, and a grace
period. Scope changes report orphan candidates rather than destroying reusable
work.

## Store Policy

New desktop libraries default to a managed store below application home. This
keeps app data outside source collections and permits selecting a broad source
folder without indexing the database or derived artifacts.

Existing libraries may adopt an explicit external store. The current tax
library can continue using its case-local `working/document-index` store during
Tactical 001. Adoption does not copy documents or recompute successful runs.

Store relocation, managed/external conversion, cross-volume copying, and
verified rollback are later scope. They require an explicit operation that
checks database integrity and artifact hashes; merely editing a path must not
pretend relocation succeeded.

## Application and Runtime Boundary

Library identity is explicit in application operations, API resources, job
targets, scheduler leases, deep links, and TanStack Query keys. Selecting a
different library cannot retarget an already created job or document request.

The shared runtime supports:

- list known libraries;
- report the last/default and active library;
- activate a registered library;
- inspect library and collection settings;
- register/import an existing descriptor through an authorized platform or
  development adapter; and
- preflight collection addition/replacement without performing extraction; and
- enqueue an incremental or full-verification inventory refresh without
  accepting a browser-supplied path.

Tactical 001's localhost implementation provides the platform-neutral
registry, selection, identity, and known-library UI. It uses an explicit
CLI/development bootstrap to register external paths because an ordinary web
page cannot safely provide a native filesystem grant. It must not add an API
that accepts arbitrary browser-supplied paths. The Tauri adapter supplies
authorized folder selections through the same application service.

Existing unscoped Tactical 000 routes may remain temporary compatibility
aliases, but new runtime operations and durable jobs use explicit library IDs.
Document deep links include the library ID as well as content identity and
page.

## Desktop and Platform Security

- External collections are read-only under every composition.
- Managed stores and registry files are app-owned and written atomically.
- The registry never stores the per-launch API credential.
- Library removal unregisters by default; deleting a managed store is a
  separate destructive operation with explicit confirmation and later
  recoverability design.
- Tauri/native folder grants remain platform adapter data. Portable library
  descriptors do not pretend an absolute path grants sandbox permission.
- The localhost API exposes registered identities, not arbitrary path access.
- A library descriptor cannot point its store inside a collection or make a
  collection contain its store.

## Required Validation

- Every test and background/headless Playwright process receives an isolated
  temporary `DOC_EVIDENCE_HOME`.
- The production app-home path remains absent or byte-for-byte unchanged
  during isolated tests.
- App-state writes are atomic and recover cleanly from interrupted replacement
  or malformed state.
- Two independent app homes cannot see or mutate each other's registries or
  managed libraries.
- Multiple libraries in one app home retain distinct IDs, stores, databases,
  active query keys, and job targets.
- A descriptor/database/registry identity mismatch blocks opening.
- Sibling collections are accepted; parent/child overlaps are rejected or
  converted through the explicit expansion flow.
- Expanding a child root to its parent starts no extractor for unchanged
  content, leaves existing artifacts byte-for-byte unchanged, reuses indexed
  pages/FTS, and extracts only new content.
- A full verification scan detects changed bytes even when a fast metadata
  path would otherwise be considered.
- Removing and re-adding scope within retention reuses prior successful
  artifacts.
- Existing external config/store adoption preserves source and artifact
  hashes and requires no broad recomputation.

## Implementing Tactical and Later Work

[Tactical 001](../tactical/001-durable-extraction-jobs.md) owns application-home
resolution, isolated testing, the registry/library contracts, legacy library
adoption, explicit identity, non-overlapping collections, generation/content
separation, and the initial known-library web UI needed by the job system.

Tactical 002 owns the implemented native Tauri creation/open/folder-picker
flow and macOS application-data composition. Tactical 003 owns its Windows
x86_64 adaptation: per-user local application data, case-insensitive canonical
overlap checks, non-ASCII/long-path fixtures, local fixed-drive support, and
default rejection of selected reparse-point roots. Later tacticals own
security-scoped bookmarks, network/removable/cloud-placeholder collections,
library/store relocation, managed-store deletion and recovery, portable
library export/import polish, and multi-window behavior.

## Implementation Evidence

The first Tactical 001 slice implements the frozen resolver precedence,
including the absolute `DOC_EVIDENCE_HOME` override and platform defaults. It
adds a bounded, strictly parsed, atomically replaced `app-state.json`; stable
library IDs; app-managed versioned wrapper descriptors for adopted legacy
configs; last/default activation; source-root overlap rejection; CLI
registration and inspection; and ordinary `serve` startup from the selected
library. Adoption does not rewrite the external configuration or relocate its
store. Malformed registry or descriptor identity disagreement blocks opening
without silently replacing state.

The second slice establishes one WAL-backed, schema-versioned
`doc-evidence.sqlite` per adopted library. Inventory builds and validates an
inactive membership generation, then switches the active pointer in one short
transaction; an interrupted build leaves the prior generation visible.
Content, extraction-run, normalized-page, and FTS projections remain stable
across scope changes. Strong local fingerprints can reuse a prior SHA-256,
while `inventory --full-hash` bypasses every hint. Parent expansion, legacy
catalog import without mutation or dual writes, database/descriptor identity,
and search/inventory reuse are covered by focused integration tests.

The third slice adds a framework-independent explicit-library manager and a
local registry adapter, resource routes beneath `/api/v1/libraries/{library_id}`,
checked generated TypeScript, and matching fixture/HTTP runtime operations.
React restores library identity before document selection, scopes server-state
queries by library ID, includes it in deep links, lists/selects ready libraries,
shows unavailable/integrity states, and exposes collection availability plus
the trusted CLI/native preflight boundary. An empty registry now launches an
actionable library home instead of failing during server composition.

Tactical 002 now implements the trusted half of the native path boundary.
The separately authenticated, originless desktop-control adapter can register
an existing configuration without rewriting it, create an app-owned managed
library and database from a selected source folder, and apply sibling or
confirmed parent-replacement collection changes only to managed libraries.
It never returns an absolute path to the product runtime. Collection changes
are rejected while jobs are queued/running, preserve library identity, and
atomically replace a validated managed configuration.

The shared React empty-home and managed-library settings surfaces now consume
path-free `DocEvidenceRuntime` operations for new, existing, and added-
collection flows. The desktop runtime invokes narrow Rust commands; localhost
and fixture runtimes honestly report native authorization unavailable. Native
folder/config dialogs now live in the Rust shell, including native confirmation
before replacing covered child roots. Selected paths travel directly from Rust
to the originless host-control surface and never cross the JavaScript bridge.

Tactical 003 now implements the Python-owned Windows filesystem policy used by
configuration loading and every trusted collection change. Comparison-only
identities normalize Windows separators and case without lowercasing stored or
displayed aliases. Source roots must be available local fixed-drive
directories; selected reparse/offline roots fail before scope changes, while
inventory prunes nested reparse points and offline/recall-marked descendants.
The target-native Windows suite passes Unicode names, spaces, case-alias
overlap, fixed/non-fixed classification, and junction cases. Long comparison
aliases pass; actual greater-than-260-character I/O remains a standalone-
runtime and installed-app acceptance gate.

The next Tactical 003 release-readiness slice found that native library
creation produced a valid empty database but exposed no in-app inventory
operation, leaving a first-time user with an indefinitely empty workspace.
Inventory is now a durable library job above the existing atomic membership
generation protocol. Its request records no source path, coalesces while
active, reports bounded progress, responds to cancellation, and reconciles
both post-publication and interrupted-building restart cases. The typed React
trigger and automatic post-completion workspace refresh remain next.
