# Application Platform

Topic: application-platform

**Last updated:** 2026-08-24

**Status:** Tactical 000 implemented and validated. Tactical 001 implementation
is complete; automated, isolated-browser, and authorized private-library gates
pass, with explicit maintainer interaction acceptance remaining. Tactical 002's
macOS arm64 unsigned foundation is implemented through the baseline pack,
final-byte app/DMG audit, and fail-closed compliance preflight. Tactical 003
implements the first signed release for macOS arm64 and Windows x86_64. Its
Machine Control entry gate and exact two-target shared desktop contracts are
implemented. Local implementation and validation are authorized; external
release actions remain separately unauthorized.

## Scope

This topic owns the continuing application boundary above the existing
inventory, artifact, extraction, comparison, and review core:

- Python domain/application services and HTTP composition;
- generated frontend wire contracts;
- React runtime and state ownership;
- localhost security and lifecycle;
- durable versus rebuildable SQLite state;
- Tauri sidecar composition and platform adaptation; and
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
  ephemeral per-launch credential. The Tauri shell launches the same
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
- Developer ID signing/notarization, Windows Authenticode/NSIS, updater
  artifacts, and two-platform release finalization move together under Tactical
  003. Its entry gates include Tactical 002's three unresolved compliance
  classes and Windows testbed readiness. That Windows gate now passes through
  disposable-workspace discard,
  but the available guest is Windows ARM64; native Windows x86_64 acceptance
  remains release-blocking. Linux and optional extractor-pack discovery/
  downloads remain later work.
- The built React product is embedded in the packaged desktop application;
  source-checkout serving remains a development composition.
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
Python ready record to report the same pack. The current 190,841,600-byte
ad-hoc local `.app` contains 3,825 files and passes real Ghostscript-free
synthetic OCR and packaged-sidecar smokes without the
checkout, Homebrew on `PATH`, or a system Python. Broader Poppler non-Latin
data behavior is not yet validated; a relocatable Poppler build or measured
PDFium replacement remains preferable before claiming that coverage.
A deterministic local DMG path avoids Finder automation, verifies the
compressed image, mounts it read-only, re-audits the contained application,
and detaches it. The rebuilt 72,498,487-byte unsigned image has SHA-256
`53116a0a261035df1228ada878b216e881b1f6487c5546ee788534ac6ca5dbef`
and contains the exact current
`60e62ea9ab3a7399be6e024e22792e1417fb1c6bd0fa76993d5ec5a23c4e0e90`
application tree. The mounted 3,825-file application, embedded runtime,
authenticated sidecar handshake, parent-EOF shutdown, and strict deep ad-hoc
signature verification all pass. This is validation evidence, not a release
artifact.

The first isolated macOS guest run caught two failures that the former local
review incorrectly accepted. Tauri's no-sign output retained only the linker's
Mach-O signature, so LaunchServices refused the unsealed bundle; local builds
now apply an outer ad-hoc seal after all resources are final, and the audit
requires the exact product identifier, no team, sealed resources, and a valid
strict deep signature. The subsequent launch exposed snake-case nested pack
identity fields inside an otherwise camel-case Tauri response. Rust now uses a
separate camel-case wire record for that nested value while preserving the
snake-case Python and manifest contracts, with an exact serialization test.
The corrected DMG matched its host hash in the guest, mounted read-only, copied
byte-for-byte, passed installed signature verification, reached the real empty-
home screen, retained one process on a second launch, and restarted normally.
The deeper create-library/OCR workflow therefore uses the deterministic
packaged-product harness because the guest's native accessibility tree exposes
the Tauri window but not its WebView contents.

That deterministic harness now exists below the UI automation boundary and
must execute under the packaged interpreter. Both its macOS arm64 staged-
runtime run and its exact copied-application run in an isolated guest created a
managed library, durably inventoried two synthetic read-only collections,
rendered a PNG page, executed English/German Ghostscript-free OCR, recovered
searchable text and the page representation, listed both inventory and
extraction activity, survived clean and forced-sidecar restarts, and preserved
both source hashes. Windows adds an installed-artifact run with an actual
greater-than-280-character fixture path.

The current compliance preflight accounts for 69 top-level staged components,
all 3,819 runtime manifest files, 24 exact Homebrew source/bottle SPDX records,
24 exact historical Homebrew formula revisions, five embedded Python-wheel
SBOMs, and 24 flattened components from the Pillow and pikepdf wheels. Formula
selection is bound to the installed package version, source hash, bottle hash,
architecture/OS tag, and historical formula bytes; verified recipes are
reusable from an ignored cache. All 30 nested Python native libraries are now
reconciled: PDFium is covered by its target-specific composite record, while
Pillow's 18 and pikepdf's 11 dylibs are bound to exact parent-wheel bytes,
final staged hashes, reviewed version evidence, SPDX conclusions, and source
archives. The former 19-crate Rust license-text blocker is closed by a tracked
exact-version inventory that binds each package's Cargo VCS revision and
repository path to hash-pinned upstream or SPDX 3.27.0 license texts. The
aggregate SPDX includes all 253 target-resolved Rust dependencies and 11
conservative production Node dependencies, with 426 available license files
and exact registry source checksums.

The exact `pi_heif` 1.4.0 wheel was removed from both release runtimes after
the flattening audit proved that it conveys libheif 1.23.0, a version affected
by upstream security advisory GHSA-xpw3-9rhw-482x. `pi-heif` is discontinued,
OCRmyPDF treats HEIF conversion as optional, and HEIF input is not a baseline
release promise. The platform manifests therefore exclude that distribution
after lock resolution, and runtime manifest generation and audits reject its
re-entry. The rebuilt macOS tree contains 41 Python distributions, 3,820 files,
and 109 Mach-O objects at
`0a50c76239b94864078333b8cd4daad696c677f6a386d6dba810c0a795f74db7`;
sidecar and real Ghostscript-free OCR smokes pass without `pi_heif`, libheif,
or libde265.

Explicit runtime replacement validates the old runtime against its own exact
manifest but does not require it to match a newly rebuilt current frontend;
otherwise frontend drift would make the transactional repair unreachable.
The new tree and all ordinary audits still require the current frontend hash.
The resulting local application contains 3,825 files at tree
`60e62ea9ab3a7399be6e024e22792e1417fb1c6bd0fa76993d5ec5a23c4e0e90`
and passes final application, embedded runtime, sidecar, OCR, and strict ad-hoc
bundle checks.

Pillow's 18 nested dylibs are flattened into 14 source components. The record
binds the exact 12.3.0 macOS arm64 wheel and every conveyed dylib hash to the
tagged Pillow build-version input, tagged wheel-build script, embedded
CycloneDX SBOM where that SBOM names the component, reviewed SPDX conclusion,
and a hash-pinned upstream source archive. Pikepdf's 11 nested dylibs are
flattened into 10 components under the exact 10.11.0 macOS arm64 wheel. The
tagged pikepdf notice names only pikepdf, qpdf, and libjpeg, so the verifier
does not treat that incomplete notice as the dependency closure; it instead
binds each actual dylib to the parent wheel, tagged build recipe, reviewed
binary-version evidence, final installed hash, license conclusion, and exact
source. Four pikepdf members retain Homebrew paths in their wheel bytes; the
preflight reproduces exactly the staging transform that replaces the prefix
and ad-hoc signs the modified Mach-O before comparing final bytes.

The full exact-source pass now reports `passed` and `release_ready: true` with
no blockers. It accounts for 74 Python Mach-O objects, reconciles all 30 nested
libraries, and embeds 43 source archives totaling 290,777,483 bytes after
historical Homebrew formula resolution. The resulting 287,122,309-byte
preflight archive has SHA-256
`555877c6960499cd3f318a9a22a948411ef4a2385493eec402012702471aff6a`
and remains bound to application tree
`60e62ea9ab3a7399be6e024e22792e1417fb1c6bd0fa76993d5ec5a23c4e0e90`.

The pypdfium2/PDFium aggregate now uses a version- and target-specific SPDX
`LicenseRef` rather than an invalid comma-separated pseudo-expression. Its
record separates the wrapper's declared `Apache-2.0 OR BSD-3-Clause` from the
concluded macOS arm64 binary composite, pins the exact PyPI wheel and PDFium
binary hashes, and compares the binary plus all 19 wheel-declared license files
byte-for-byte with the staged runtime. The aggregate SPDX carries matching
extracted-license provenance instead of pretending the many PDFium third-party
terms are one standard SPDX expression.

Tactical 003's first code checkpoint replaces the macOS-only shared launch
contract with an exact allowlist of `macos/arm64` and `windows/x86_64` across
Python ready/handshake models, Rust host validation, generated TypeScript, the
React desktop adapter, and strict bundle/pack schemas. Target-specific Tauri
origins, resource layouts, bundled interpreter paths, executable environments,
application-data selection, and pack identity are selected below the shared
product runtime. Crossed target pairs and a sidecar whose actual runtime target
disagrees with the host declaration fail before the loopback service is
exposed. Windows-native lifecycle, paths, runtime staging, and installer
acceptance remain open.

The next Tactical 003 checkpoint adds Windows Job Object ownership without
changing the shared scheduler or artifact state machine. Both the Rust-owned
sidecar tree and Python-owned extractor tree use an assign-before-launch gate
and kill-on-close handle; `taskkill` is not a correctness dependency. The
available Windows guest passes native attempt cancellation/timeout/descendant
cleanup and x86_64-emulated Rust Job Object tests.

The following checkpoint implements Windows case/separator path identity,
case-alias-safe library/configuration checks, local fixed-drive admission, and
fail-closed reparse/offline traversal policy in Python-owned services. Eight
focused target-native Windows tests pass, including Unicode, spaces, case
aliases, fixed-drive classification, and junction rejection/pruning. Long path
comparison passes, but greater-than-260-character filesystem I/O remains bound
to the forthcoming pinned standalone runtime and installed-app gate after the
guest development interpreter failed that fixture. Standalone runtime/pack
staging, exact installer bytes, and native x86_64 installed acceptance remain
open.

The Windows runtime/pack checkpoint now has its first reproducible input
boundary. A strict `windows-x86_64` manifest pins the CPython 3.12.12 archive,
Poppler distribution and source/data archives, the official Tesseract
installer and source, the shared language-data archive, a Microsoft 14.44 x64
app-local CRT input, all 55 selected native payload hashes, and the locked
Python requirements. A dependency-free PE
reader validates PE32/PE32+ structure, x86_64 machine identity, ordinary and
delay-import tables, and flat bundle closure against an explicit Windows
system-DLL allowlist. Both Windows distribution archives deliberately remain
`NOASSERTION` with named compliance blockers until every conveyed dependency
license/source is reconciled; this input checkpoint does not claim a staged or
release-ready pack. Exact selection from the three native archives produces a
complete flat PE dependency closure; Microsoft redistribution terms remain a
named compliance blocker. Target-native staging, Python-wheel PE closure,
copied-out OCR, and long-path I/O are the immediate remaining gates.

The safe pack assembler now selects only the declared files from those inputs,
validates the complete flat PE closure, compiles a tracked relocatable and
argument-safe OCRmyPDF launcher, and emits the platform-bound pack manifest.
The first real-archive structural run caught and corrected a provenance error:
the Windows language entries had used hashes from the macOS Homebrew payload
instead of the files in the pinned Tesseract 4.1.0 archive. All three declared
file hashes now match that archive. A local structural exercise produces the
expected five tools, three languages, two support files, 51 DLL records, and
56 x86_64 PE records, using an existing x86_64 executable only in the launcher
slot because the MSVC launcher build is target-native. Locked dry runs also
resolve 20 production and 27 baseline Python distributions for CPython 3.12 on
Windows x86_64. The locks were subsequently materialized for the target and,
after applying the runtime pruning contract, their standalone Python plus
baseline pack form a closed 123-file PE graph. Two hashed pikepdf private DLL
imports resolve outside ordinary loader roots; the target-native import and OCR
smokes remain mandatory rather than treating static uniqueness as execution
proof.

The transactional Windows builder now owns standalone archive extraction with
case-collision/link rejection, frozen production and baseline installation,
project installation, GUI/test/installer pruning, exact pypdfium2 license
selection, package/component/file manifests, schema and target validation, and
rollback. It audits every staged PE as x86_64 and records its bounded loader,
package-private, or Windows-system closure. Before publication, a copied
runtime must execute all five tools, a real English/German OCR round trip, the
authenticated sidecar handshake and parent-EOF shutdown, and an actual path
longer than 260 characters. These gates are implemented but have not yet run
on the Windows target, so no target-native runtime or OCR acceptance is
claimed.

Windows candidate packaging is now explicit rather than inheriting the macOS
`app` target. The platform Tauri overlay selects only NSIS, current-user
installation, English UI, LZMA compression, an embedded non-silent WebView2
bootstrapper, and downgrade rejection. The target-only build command fixes the
Rust target to `x86_64-pc-windows-msvc`, remaps source/Cargo paths, refuses
signing, requires the exact `Doc Evidence_0.4.0_x64-setup.exe` output, validates
the x86_64 application PE, records both hashes, and requires `NotSigned`
Authenticode state for this local proof. It re-runs copied runtime smokes before
accepting the installer. Installed-byte and uninstall preservation remain
Machine Control gates; an unsigned installer-file audit is not presented as
either.

Local release-finalization guards now enforce the Doc Evidence subset of the
pinned `desktop-update-v1` contract. They accept only a synchronized draft
`desktop-vMAJOR.MINOR.PATCH` release with GitHub digests, the two direct
installers, the exact-source compliance archive, and updater metadata for
exactly `darwin-aarch64` and `windows-x86_64`. Each updater URL and detached
signature must resolve inside the same tagged release, and deterministic
checksum output omits signature assets. The remote workflow, product updater
key and route, installed client surface, signing, and publication remain open
and separately authorized boundaries.

The current-HEAD macOS arm64 application has now been rebuilt after the shared
packaged-runtime fixes. Its 3,825 files occupy 190,854,648 bytes at tree
`1cd69a4a8af70ca37ebf494cea549b6d9a36d69d688d0c46a5daaf6823cb4fb2`;
the embedded runtime tree is
`3f0a27c7515e50112dbbf9dcd44e37e30a39faba117070ad5ab605ed0f472fd2`.
Strict deep ad-hoc verification, final application/runtime/native-dependency
review, sidecar and OCR smokes, and the complete packaged two-library workflow
pass. The workflow performed two inventories, one executed OCR run, PNG page
rendering, searchable text, normal and forced-sidecar restart, and unchanged
source-byte verification.

The first installed Windows x86_64-emulation candidate proved the per-user
NSIS layout, manifest-bound runtime, greater-than-260-character Unicode source
inventory, page rendering, and uninstall preservation of application data and
external source collections. It also exposed two bounded product issues before
release: an OCRmyPDF version probe could hang by launching the command shim,
and the console-subsystem Python child opened a visible Windows Terminal. The
runtime now reads the installed distribution version without executing that
shim, and the Rust launcher starts Python with `CREATE_NO_WINDOW`. That
intermediate installer is explicitly not a final candidate; a current-HEAD
runtime and installer rebuild must contain both corrections before its UI and
uninstall evidence can close.

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
[Tactical 001](../tactical/001-durable-extraction-jobs.md). Continue the locally
authorized [Tactical 003](../tactical/003-macos-windows-signed-desktop-release.md)
with platform-aware desktop contracts and the existing macOS compliance
blockers, using the restored Windows testbed throughout. Stop before credential
provisioning, remote/release setup, tagging, signing, or publication without
separate authorization. Durable review events remain a separate later tactical.
