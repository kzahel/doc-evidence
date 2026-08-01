# 002 — macOS Tauri Desktop Distribution

Topic: application-platform

Topic: library-management

Topic: job-architecture

**Status:** Product and distribution direction approved. The maintainer
authorized unattended local unsigned/ad-hoc implementation and validation on
2026-08-01. Signing, notarization, credential provisioning, GitHub release
setup, updater setup, and publication remain deliberately unstarted. The exact
GitHub release target and updater route must be confirmed before that external
lane begins.

## Motivation and User-Visible Outcome

Turn the implemented desktop-shaped localhost application into one
self-contained macOS arm64 application without creating another product or
data model.

At the end of this tactical, the maintainer can launch `Doc Evidence.app`
outside the repository, reopen an existing registered library or create a new
managed library through a native folder picker, browse and search documents,
render PDF pages, run the baseline Poppler and OCR/Tesseract extractors, inspect
durable activity, close and reopen the application, and retain the same
library, jobs, and artifacts.

Core application use runs fully offline and does not depend on a system
Python, Homebrew, `uv`, the repository checkout, a development virtual
environment, or an anonymous model cache. The distribution packages the
existing React product and Python-owned application services behind a thin
Tauri 2 lifecycle and security shell.

This tactical ends at a Developer ID-signed and notarized macOS arm64
application with a stapled ticket, packaged as a direct-download DMG with
signed Tauri updater artifacts, validated release metadata, and a tag-driven
CI path following the established sibling applications. Unsigned and ad-hoc-
signed builds remain local and pull-request validation lanes; they are not the
product milestone. Intel macOS, Windows, Linux, and optional extractor-pack
distribution require later approved tacticals.

## Dependencies and References

- [Product vision and application architecture](../product-vision-and-architecture.md)
- [Application platform](../topics/application-platform.md)
- [Desktop library management](../topics/library-management.md)
- [Durable job architecture](../topics/job-architecture.md)
- [Core architecture](../architecture.md)
- [Data contracts](../data-contracts.md)
- [Tactical 001 execution record](001-durable-extraction-jobs.md)
- [Sibling and external references](../references.md)
- [Tauri 2 distribution documentation](https://v2.tauri.app/distribute/)
- [Tauri macOS application bundles](https://v2.tauri.app/distribute/macos-application-bundle/)
- [GNU guidance on separate programs](https://www.gnu.org/licenses/gpl-faq.en.html#GPLInProprietarySystem)
- [OCRmyPDF Ghostscript alternatives](https://ocrmypdf.readthedocs.io/en/stable/introduction.html#ghostscript-considerations)

Use three sibling repositories for distinct, proven boundaries rather than
designing a Doc Evidence-specific release system:

- `~/code/atpiano` at revision
  `87b77e9b0679f770a5f55e69546c7a1cb72fde46` owns the standalone CPython,
  authenticated sidecar, thin-Tauri lifecycle, outside-repository launch,
  process cleanup, Mach-O inventory, and installed-byte precedent. Inspect:

  - `docs/tactical/030-early-tauri-sidecar-boundary.md`;
  - `app/src-tauri/tauri.conf.json`;
  - `app/src-tauri/src/lib.rs`;
  - `app/src/runtime/desktop-runtime.ts`;
  - `src/atpiano/desktop.py`;
  - `src/atpiano/desktop_sidecar.py`; and
  - `scripts/build-atpiano-desktop`.
- `~/code/yepanywhere` at revision
  `2610c24ad2c5abc3b6979a6913b0d5908404e975` owns the strongest current
  macOS release precedent: required credential gates, temporary signing
  keychain, explicit nested Mach-O signing, Tauri assembly and notarization,
  bounded DMG retry/diagnostics, final signed-application smoke, updater
  metadata finalization, and published-release QA. Inspect:
  - `topics/desktop-v0.md`;
  - `.github/workflows/desktop-ci.yml`;
  - `scripts/release-desktop.sh`;
  - `packages/desktop/README.md`;
  - `docs/tactical/067-v0-desktop-baseline.md`; and
  - `docs/testing/desktop-release-qa-log.md`.
- `~/code/jstorrent` at revision
  `9895410beeed6aff554053769bd006a3fbd373ef` owns the mature release/tag and
  publication precedent: synchronized version bump, changelog and tag script,
  signed installers, Tauri updater output, `latest.json` validation, release
  finalization, published SHA-256 checksums, and download tables. Inspect:
  - `docs/topics/releases.md`;
  - `scripts/release-tauri-app.sh`;
  - `.github/workflows/tauri-app-ci.yml`;
  - `desktop/README.md`; and
  - `desktop/tauri-app/src/updater.ts`.

The exact rationale and pinned sources are recorded in
[References](../references.md). Use `atpiano` for Python-sidecar composition,
Yep Anywhere for the nested macOS signing/notarization and final-app test
sequence, and JSTorrent for release mechanics. Do not copy their audio,
agent-session, torrent, provider, or multi-platform product models. Doc
Evidence needs a distinct host-control credential because folder choices must
never become arbitrary browser-supplied paths.

Credential provisioning follows the canonical personal runbook at
`~/code/dotfiles/runbooks/desktop-code-signing.md`, pinned in
[References](../references.md). Its companion
`runbooks/validate-signing-secrets.sh` validates source credentials locally
and can set the GitHub Actions secrets only after every check passes. Override
its target repository, desktop directory, and per-application Tauri updater
key for Doc Evidence. Never copy secret values, credential source paths, or
password-manager material into this repository, logs, manifests, or tactical
execution evidence.

## Entry Evidence

- Tactical 001 implemented named libraries, platform application-home
  resolution, one database/artifact store per library, durable extraction
  jobs, supervised subprocess trees, restart reconciliation, API contracts,
  the hand-owned React runtime, and operational UI.
- `doc-evidence serve` already provides an authenticated loopback composition
  and the React production build. It remains the development, automation, and
  headless composition.
- The shared React product imports `DocEvidenceRuntime`; it does not depend on
  Tauri, native path APIs, or direct filesystem access.
- The Python resolver already accepts a desktop-host application-data root
  beneath the `DOC_EVIDENCE_HOME` override.
- The current baseline requires `pdfinfo`, `pdftotext`, and `pdftoppm` from
  Poppler; OCR uses OCRmyPDF, Tesseract, and the same Poppler text projection.
- OCRmyPDF is invoked with ordinary PDF output and optimization disabled.
  OCRmyPDF 17 can use PDFium paths without Ghostscript for this use case, but
  the absence of Ghostscript must be proven by a staged-runtime execution.
- Docling and Marker are optional, isolated, model-heavy extractors. Their
  installed development environments and models are measured in gigabytes and
  are not suitable for the initial application.
- Marker model weights also carry use, redistribution, and output terms that
  are unacceptable for a silently bundled default.
- Apache-2.0 project licensing and checked desktop bundle/extractor-pack
  manifest schemas landed as the first implementation slice. The repository
  still has no Tauri project, standalone runtime staging, desktop sidecar
  command, generated bundle manifest, SBOM, or third-party notices.
- This checkout currently has no Git remote. Before generating a release tag,
  provisioning GitHub Actions secrets, configuring the update route, or
  publishing an artifact, confirm the exact Doc Evidence GitHub repository and
  receive explicit authorization for those external changes. Do not infer the
  target from the bundle identifier alone.
- The current build host is Apple Silicon and has Xcode, Rust, Node, and the
  existing Python toolchain. Release signing does not depend on a persistent
  local identity: the sibling workflows install the shared Developer ID
  material into a temporary CI keychain and use App Store Connect API
  credentials for notarization.
- Yep Anywhere has shipped signed and notarized Apple Silicon DMGs and verifies
  the final installed application. JSTorrent has a tag-driven signed release,
  updater metadata, checksum, and finalization path. Their repeated CI fixes
  are the release precedent; the unsigned `atpiano` application is only the
  Python-sidecar precedent.

## Frozen Decisions

### Product and platform

- Target macOS arm64 only with a minimum supported system version of macOS 13.
- Use Tauri 2 under `desktop/` and the existing Vite production output under
  `web/dist`.
- Use `Doc Evidence` as the product name and
  `io.github.kzahel.doc-evidence` as the initial bundle identifier. The first
  signed release and every updater artifact must preserve that identity unless
  an explicit migration is approved before publication.
- Derive the desktop version from the Python project version and fail the
  build if Python, frontend, Rust, or bundle metadata drift.
- The application is a direct-download desktop product, not an App Store
  sandboxed product. Security-scoped bookmarks and App Store entitlements are
  outside this distribution.
- Reuse the sibling version/changelog/tag convention and a tag-driven GitHub
  Actions release. A tagged release fails closed if Developer ID,
  notarization, or Tauri updater credentials are absent; it never publishes an
  unsigned or partially finalized release.
- Configure a per-application Tauri updater key and checked public key. Release
  finalization validates signed updater metadata before making the release
  complete. The updater does not install extractor packs or change library
  data.
- Reuse the existing sibling `simple-app-update-server` convention after a Doc
  Evidence route is deliberately allocated. Do not create another updater
  service merely for this application. Until that endpoint and repository are
  confirmed, keep them explicit configuration inputs rather than guessed
  production constants.
- The desktop shell does not replace `doc-evidence serve`, CLI commands, or
  library/artifact contracts.

### Project and third-party licensing

- License original `doc-evidence` source under Apache License 2.0.
- Add the complete root `LICENSE`, SPDX `Apache-2.0` metadata to Python,
  frontend, and Rust package declarations, and a concise README license
  statement.
- The application license does not relicense bundled third-party components.
  Every staged component retains its own license and notices.
- Keep Poppler utilities as separately invoked programs. Do not link Poppler
  into Rust or Python extension code.
- The staged bundle must contain human-readable third-party notices and exact
  component license texts. The build also emits an SPDX 2.3 JSON SBOM and a
  machine-readable file/component manifest.
- A reviewed override file may resolve incomplete upstream package metadata,
  but each override must name an exact component version, source URL, observed
  license file hash, conclusion, and review note. `NOASSERTION` is not accepted
  silently for a shipped runtime component.
- GPL components are allowed only as identified, separately executable tools
  with the applicable license and corresponding-source materials. The
  compliance output records exact source archives, patches, and build/staging
  recipes sufficient to reproduce the conveyed binaries.
- The bundle audit rejects AGPL, noncommercial, field-of-use, OpenRAIL, unknown,
  and unreviewed custom licenses. This specifically excludes Ghostscript and
  Marker model weights.
- Adding Apache-2.0 is a durable grant for copies already received and is not
  treated as a reversible packaging artifact.

The reviewed direct-component baseline is:

| Component | License posture for this tactical |
| --- | --- |
| Original Doc Evidence code and assets | Apache-2.0 |
| Tauri 2 | MIT or Apache-2.0 |
| CPython | PSF-2.0 plus incorporated-component notices |
| Python standalone build tooling | MPL-2.0; conveyed runtime retains its component licenses |
| React, frontend runtime, and core Python dependencies | Permissive licenses, subject to exact final-byte audit |
| Poppler utilities | GPL-2.0-only or GPL-3.0-only; separate executables with corresponding source |
| OCRmyPDF 17.8.1 | MPL-2.0 |
| Tesseract and bundled `eng`/`deu`/`osd` data | Apache-2.0 |
| Leptonica | BSD-2-Clause |
| qpdf and other OCRmyPDF native dependencies | Exact staged versions and licenses must be inventoried; current qpdf is Apache-2.0 |
| pypdfium2/PDFium | Apache-2.0 or BSD-style wrapper/runtime plus complete PDFium third-party notices |
| Ghostscript | AGPL-3.0-or-later or commercial; excluded |
| `unpaper`, `pngquant`, `jbig2enc` | Optional cleanup/optimization tools; excluded regardless of individual license |
| Docling code/models | Permissive but heavyweight; excluded |
| Marker/Surya code and model weights | Version-sensitive code terms and restrictive model/output terms; excluded |

This table is a reviewed starting constraint, not a substitute for inspecting
the exact bytes produced by the build. A transitive component absent from the
table is neither approved nor ignored; the final audit must classify it before
the application passes.

### Thin desktop shell and Python ownership

- Rust owns native lifecycle, operating-system randomness, application-data
  injection, native folder/file dialogs, packaged-resource location,
  sidecar supervision, and bounded bootstrap/failure presentation.
- Python retains libraries, descriptors, configuration, SQLite, inventory,
  scheduler leases, jobs, workers, extraction adapters, artifacts, comparison,
  and provenance.
- React remains the shared product. Product components consume only
  `DocEvidenceRuntime`; Tauri imports are confined to desktop composition and
  its runtime adapter.
- Add a dedicated `doc-evidence desktop-sidecar` launch surface. It does not
  open a browser or serve remote assets and is not a generic command runner.
- The sidecar binds `127.0.0.1:0`, emits one bounded versioned ready record,
  and serves a versioned authenticated handshake before the runtime becomes
  available.
- The shell owns one GUI process per application home. A second launch focuses
  the existing application or exits with a bounded explanation; it does not
  start another scheduler against the same last-selected library.

### Credentials and native filesystem authorization

- Rust generates two independent credentials with at least 256 bits of
  operating-system randomness per launch:
  - a runtime bearer credential returned only to the desktop runtime adapter;
    and
  - a host-control credential retained by Rust and Python and never exposed to
    JavaScript.
- Credentials pass to the sidecar through inherited environment and are
  removed from the Python environment immediately after validation. They never
  appear in arguments, URLs, logs, ready/handshake records, diagnostics,
  retained files, crash messages, or application state.
- Ordinary library/document/job/artifact routes require the runtime bearer and
  the exact bundled Tauri origin.
- A separate bounded desktop-control surface requires the host-control
  credential, rejects browser-origin requests, and accepts only operations
  whose path was selected by the native shell.
- React invokes behavioral runtime operations such as “create a library from a
  chosen folder” or “register an existing descriptor.” Rust opens the native
  dialog and submits the chosen canonical path directly to the host-control
  surface. The selected absolute path is not returned to a product component
  merely so JavaScript can echo it back to Python.
- The Rust command allowlist contains no generic read, write, shell, execute,
  environment, or arbitrary-HTTP operation.
- The localhost/development runtime reports native selection as unavailable
  and continues to use explicit CLI registration. No ordinary HTTP route gains
  a browser-supplied path.

### Application home and user data

- Preserve the existing macOS application home exactly:
  `~/Library/Application Support/doc-evidence`, unless the explicit
  `DOC_EVIDENCE_HOME` override is set.
- Rust resolves the platform application-support base and injects the
  `doc-evidence` child as the desktop-host root; it does not silently switch
  existing users to a bundle-identifier-specific directory.
- Packaged validation always uses a fresh temporary `DOC_EVIDENCE_HOME`.
  Deliberate private-library acceptance is separate and may use the default
  home only when explicitly authorized.
- Application state, logs, caches, and mutable extraction output never write
  into `Doc Evidence.app`.
- Source collections remain read-only. Native selection authorizes observation
  of a collection; it never authorizes moving, renaming, annotating, replacing,
  or uploading source documents.
- Uninstalling the application does not delete the application home, managed
  libraries, adopted stores, or external collections.

### Packaged Python runtime

- Stage a pinned, hash-verified macOS arm64 CPython 3.12 standalone
  `install_only` distribution rather than copying `.venv`.
- Install the locked production application and desktop dependencies without
  test, benchmark, Playwright, typechecking, build, or heavyweight-extractor
  environments.
- Launch Python with isolated-mode behavior and bytecode writes disabled.
  Clear `PYTHONHOME`, `PYTHONPATH`, user-site, virtualenv, and unrelated
  package-manager variables before spawn.
- The packaged composition resolves extractors only through explicit bundle
  roots. It never falls back to the checkout-relative `.extractors`, the
  ambient `PATH`, Homebrew, or an anonymous Hugging Face cache.
- Worker subprocesses inherit only the bounded environment required for the
  selected registered extractor, app home, locale, temporary directory, and
  process supervision.

### Baseline extractor pack

The application includes one versioned `baseline-macos-arm64` pack containing:

- Poppler `pdfinfo`, `pdftotext`, and `pdftoppm` plus their required non-system
  dynamic-library closure;
- Tesseract and Leptonica plus required non-system dynamic libraries;
- Tesseract `eng`, `deu`, and `osd` trained data;
- OCRmyPDF 17.8.1 and its required Python/native runtime dependencies;
- PDFium/pypdfium2 support needed by the Ghostscript-free OCR path; and
- exact license, source, version, architecture, and hash manifests.

The pack intentionally excludes:

- Ghostscript;
- `unpaper`, `pngquant`, and `jbig2enc` optimization/cleanup helpers;
- Docling, Marker, PyTorch, Transformers, heavyweight model weights, and their
  remote-provider clients;
- every other Tesseract language; and
- any network downloader or auto-install action.

The packaged registry continues to describe Docling and Marker as recognized
capabilities but reports them as unavailable and not included. It must not
suggest that missing heavy extractors are application corruption.

If a library requests a Tesseract language outside `eng` and `deu`, preflight
fails before enqueue with the exact missing language and an explanation that
additional language packs are not implemented yet. It never downloads data
or silently substitutes a language.

Do not replace Poppler extraction with PDFium inside this tactical. Preserving
the measured extractor and cache identity is lower risk for the first desktop
distribution. A future tactical may benchmark a permissively licensed PDFium
native-text adapter before changing the baseline.

### Pack construction and reproducibility

- Use version-pinned, checksum-verified source archives or arm64 bottle/build
  inputs. Homebrew may be a build-time source of pinned inputs, following the
  atpiano prototype, but no Homebrew path or runtime dependency may survive in
  the application.
- Record the input URL, version, SHA-256, source revision, staging/build
  command, license evidence, and output hashes for every direct component.
- Relocate non-system Mach-O dependencies into the pack, rewrite load paths to
  bundle-relative locations, and inspect the complete transitive closure after
  relocation.
- Treat every executable, dynamic library, Python native extension, framework,
  and other Mach-O object beneath the standalone runtime and extractor pack as
  explicit signing input. File suffixes are not a sufficient inventory.
- Local and pull-request builds may ad-hoc sign after relocation. Tagged
  release CI signs nested Mach-O objects from the inside out with the Developer
  ID identity and hardened runtime before Tauri signs the enclosing executable
  and application. `codesign --deep` may be used as a final verification, not
  as a substitute for explicit nested signing.
- Verify each nested signature immediately, then verify the complete
  application strictly. Do not modify, thin, relocate, rewrite, or regenerate
  any signed byte afterward. A missing or invalid nested signature is a failed
  release, not permission to weaken hardened-runtime or library-validation
  settings.
- CPython, Poppler, Tesseract, and the baseline utilities receive no JIT or
  broad executable-memory entitlement unless an exact staged component proves
  it is required and the maintainer approves the change. Follow the minimal
  entitlement pattern established by Yep Anywhere, without copying Bun's
  JavaScriptCore-specific `allow-jit` exception.
- Generate embedded component/license manifests before signing when they are
  inputs to the bundle. Generate the external final-byte inventory, artifact
  hashes, notarization evidence, and distribution report after signing and
  notarization so the recorded release bytes are the bytes users receive.
- Generated Python runtimes, native prefixes, caches, `.app` bundles, SBOMs,
  inventories, and compliance archives remain ignored build output. Staging
  scripts, schemas, reviewed license conclusions, and compact manifests are
  tracked.
- A build may access the network only to retrieve declared, checksum-verified
  inputs and to perform the configured signing, notarization, release, and
  updater operations. Core library use remains offline-capable. The packaged
  product may contact only its explicit update endpoint for an update check;
  it does not load remote product assets or download extractors/models.

### Bundle-size and startup policy

Smallness is measured rather than asserted. The final report includes:

- installed and compressed bytes by Tauri/Rust shell, frontend, Python
  interpreter, Python packages, baseline native tools, native libraries,
  Tesseract data, licenses/notices, and other resources;
- the twenty largest files and distributions;
- cold sidecar-ready, handshake, first-library, first-page, Poppler-job, and
  OCR-job timings;
- peak resident memory for idle, Poppler, and OCR paths;
- every Mach-O architecture and non-system dependency; and
- an explicit absence scan for heavyweight extractors, model caches,
  Ghostscript, optional OCR optimization tools, dev/test packages, private
  paths, repository paths, and credentials.

No arbitrary size ceiling is frozen before the first build. The tactical fails
if bytes cannot be reconciled or if an unexplained dependency dominates the
bundle. Size optimization that changes extractor output, cache identity, or
the durable artifact contract requires a measured follow-up rather than an
unrecorded packaging substitution.

## Exact Implementation Scope

### 1. Apache-2.0 and distribution metadata

- Add the Apache License 2.0 text and copyright notice at repository root.
- Add consistent SPDX license metadata to `pyproject.toml`, `web/package.json`,
  and the new Rust package.
- Add the README license statement and third-party-component boundary.
- Define schemas for the desktop bundle manifest, extractor-pack manifest,
  reviewed license conclusions, and file inventory.
- Add drift tests covering application version, bundle identity, pack identity,
  manifest schemas, and license metadata.

### 2. Desktop sidecar and handshake

Add framework-independent desktop contracts plus a launch adapter that:

- validates and removes both inherited credentials;
- resolves the injected application home through the existing resolver;
- validates the packaged runtime and baseline-pack manifests before opening a
  library or scheduler;
- starts the existing ASGI application on an ephemeral loopback port;
- emits one newline-terminated ready record with a strict byte limit and
  startup deadline;
- provides a runtime-authenticated handshake and a host-control-authenticated
  health check;
- reports application, contract, protocol, database-schema, platform,
  architecture, Python, baseline-pack, and manifest identities;
- never returns credentials, unrestricted paths, private filenames, or library
  contents in bootstrap records; and
- performs graceful scheduler/worker shutdown on EOF, signal, or a host-control
  shutdown request before the Rust grace period expires.

The desktop protocol is versioned independently from the existing HTTP API.
The shell rejects incompatible ready or handshake records rather than opening
a partially functional product.

### 3. Native library and collection operations

Add narrow application operations and desktop-control adapters for:

- creating a new managed library with one natively selected collection;
- registering/adopting an existing `.doc-evidence.yaml` selected in a native
  file dialog without rewriting that external descriptor;
- adding a natively selected sibling collection;
- preflighting and confirming an existing-child to selected-parent scope
  replacement through the current collection-overlap policy; and
- cancelling a native dialog without changing application state.

Python application services still canonicalize, validate overlap, validate
store boundaries, allocate stable identities, and persist descriptors. Rust
cannot construct or edit a library descriptor directly.

### 4. Shared React desktop runtime

- Add a desktop bootstrap and `DocEvidenceRuntime` adapter under the existing
  frontend API/runtime boundary.
- Confine Tauri imports to desktop bootstrap, native-library operations, and
  bounded shell-event handling.
- Use the existing generated HTTP client and runtime bearer for ordinary
  application operations.
- Add platform-neutral runtime capabilities for native library creation,
  descriptor registration, and collection selection. The localhost and
  fixture runtimes implement explicit unsupported/deterministic behavior.
- Render actionable empty-home, startup, incompatible-runtime, sidecar-exit,
  pack-integrity, and native-selection failure states.
- Add a bounded About/Licenses surface that reads the embedded application,
  baseline-pack, and human third-party notice manifests without exposing an
  arbitrary resource reader.
- Preserve existing document, comparison, extraction, and activity product
  components without desktop-specific branches.

### 5. Thin Tauri shell

Add `desktop/` with:

- a minimal Tauri 2 Rust application and restrictive capability allowlist;
- an original repository-owned development icon and required macOS icon
  variants under the same Apache-2.0 project license, without implying final
  brand approval;
- an embedded `web/dist` production build and restrictive content security
  policy with no remote scripts, fonts, images, frames, or navigation;
- native folder and descriptor dialogs exposed only through bounded commands;
- application-home resolution and one-GUI-instance behavior;
- two-credential generation and sidecar environment construction;
- packaged runtime/manifest discovery with debug-only explicit overrides;
- bounded ready-record parsing, compatibility validation, startup timeout,
  authenticated handshake, and bootstrap response;
- the standard Tauri updater capability bound to the checked Doc Evidence
  public key and explicit release endpoint, with no generic network bridge;
- unexpected-sidecar-exit monitoring and one bounded failure event;
- graceful close followed by complete process-group termination and reaping;
  and
- no generic filesystem, shell, arbitrary URL, environment, downloader, or
  unrelated plugin capability.

The content security policy may connect only to Tauri IPC/assets and the exact
ephemeral loopback sidecar. Artifact bodies continue to stream through
authorized HTTP and bounded blob URLs rather than crossing Rust as unbounded
JSON.

### 6. Standalone runtime and baseline-pack staging

Add reproducible build commands that:

- download or accept a cached exact standalone CPython archive and verify its
  SHA-256;
- install the locked production Python application into an isolated staging
  prefix;
- stage the exact baseline native-tool dependency closure and Tesseract data;
- include all required component licenses, notices, source records, and
  corresponding-source material;
- build `web/dist`, Rust, and the `.app` in the correct order;
- relocate and audit every Mach-O before applying local ad-hoc signatures or
  handing the exact staged tree to release signing;
- generate the SPDX SBOM, human notices, bundle/pack manifests, file hashes,
  and byte report from the applicable unsigned staging or final signed release
  phase rather than an ambiguous mixture of both; and
- reject a dirty or partially inventoried resource staging directory.

The build command supports `stage`, `build`, `audit`, and `review` modes with
one documented entry point. It never deletes an application home or library.

### 7. Signing, notarization, and release automation

Adapt the working Yep Anywhere and JSTorrent conventions rather than creating
a separate release framework:

- add a synchronized version/changelog script and one explicit macOS desktop
  tag family;
- configure tag-triggered GitHub Actions with a temporary keychain, Developer
  ID Application identity, App Store Connect notarization, Tauri updater
  signing, and release finalization;
- require every tagged-release credential before packaging begins and refuse
  an unsigned partial release;
- generate a fresh per-application Tauri updater key outside the repository,
  commit only its public key, and provision secrets only through the pinned
  dotfiles signing runbook and validation script;
- sign and strictly verify every nested Mach-O in the prepared Python and
  extractor resources before Tauri signs the enclosing bundle;
- build the application and DMG, submit for notarization, staple, and validate
  Gatekeeper acceptance;
- smoke the Python sidecar and baseline extraction tools from the final signed
  and notarized `.app` before upload or release finalization;
- emit and validate signed updater artifacts and `latest.json` with the exact
  target, URL, and nonempty signature;
- publish external final-byte SHA-256 checksums, SBOM, notices, source-
  compliance material, and a download table; and
- retain actionable phase-aware diagnostics so an inner signing failure, app
  assembly failure, notarization rejection, DMG flake, updater-signing error,
  or finalization error is not mislabeled as another phase.

The canonical credential names, source locations, validation sequence,
secret-upload command, expiry notes, and known failure signatures remain in
`~/code/dotfiles/runbooks/desktop-code-signing.md`; this repository records no
secret value. The associated `validate-signing-secrets.sh --set` operation is
an explicit maintainer release-setup action and must target the confirmed Doc
Evidence GitHub repository and per-app updater key.

### 8. Packaged acceptance harness

Add a deterministic public/synthetic review collection and harness that:

- copies only public fixture inputs to a temporary collection;
- starts both a local unsigned/ad-hoc application and the final signed
  application from outside the repository under a fresh temporary
  `DOC_EVIDENCE_HOME`;
- removes repository, virtualenv, Homebrew, Python, Node, Rust, and package-
  manager assistance from the child environment;
- verifies no non-loopback socket is opened;
- creates/registers the test library through the same application service used
  by the native command;
- inventories, searches, renders, runs Poppler, runs PDF OCR in `eng` and
  `deu`, and runs standalone-image Tesseract OCR;
- exercises cancellation or forced sidecar exit while a supervised job owns
  descendants;
- restarts the application and verifies library identity, database integrity,
  completed artifacts, job reconciliation, and source hashes; and
- confirms all child processes exit when the application closes.

Native dialog rendering itself remains a manual gate, but the Rust command and
Python authorization boundary must be covered without bypassing validation.

## Automated Validation

### Python and application services

- Ready and handshake schemas accept only the supported desktop/API/database/
  pack versions and reject extra or malformed fields.
- Missing, swapped, or wrong runtime and host-control credentials fail with no
  library or path operation.
- Token values are absent from captured logs, errors, records, manifests,
  diagnostics, process arguments, and URLs.
- Desktop application-home injection matches the existing macOS platform
  default byte-for-byte; `DOC_EVIDENCE_HOME` still has documented precedence.
- Native-selected library/collection services exercise same-root, child,
  parent-replacement, sibling, unavailable, and store-overlap policy.
- A browser bearer cannot invoke host-control path operations.
- Sidecar EOF, graceful signal, forced termination, scheduler activity, and
  worker descendants reconcile through the existing durable-job rules.
- Packaged extractor resolution uses only declared bundle roots and rejects
  ambient executables or checkout-relative heavy environments.
- Missing configured Tesseract data blocks before enqueue and names the exact
  missing languages.

### Rust and frontend

- Rust unit/integration tests cover credential independence, ready size and
  timeout, compatibility, duplicate bootstrap, single-instance behavior,
  dialog cancellation, control-route authentication, process exit, graceful
  shutdown, forced tree cleanup, and bounded failures.
- Frontend tests cover desktop detection, bootstrap/handshake validation,
  authenticated runtime construction, native-operation capability states,
  empty-home flow, dialog cancellation, and visible sidecar/pack failure.
- Dependency checks reject Tauri imports outside the desktop bootstrap/runtime
  boundary and reject desktop imports from product components.
- The production frontend contains no remote asset URL or development server
  fallback.

### Build, bundle, and compliance

- Existing Ruff format/check, unit, Pyright, and wheel-build gates pass.
- Generated OpenAPI/TypeScript drift, frontend typecheck, component tests,
  production build, and isolated Playwright gates pass.
- `cargo fmt --check`, `cargo test`, and
  `cargo clippy --all-targets -- -D warnings` pass.
- Every staged file is represented by one final-file SHA-256 and byte count;
  the inventory total equals the application bundle total.
- Every Python distribution, Node production dependency, Rust production
  crate, native executable/library, trained-data file, and embedded resource
  maps to an SBOM component and reviewed license conclusion.
- Every Mach-O is arm64 or universal with arm64 support. Every non-system load
  path resolves inside the application. No staging symlink escapes the bundle.
- No load command, shebang, manifest, source map, configuration, or retained
  text contains `/opt/homebrew`, the repository path, a development virtualenv,
  a private collection path, or a temporary staging root.
- The absence scan rejects Ghostscript, Docling, Marker, PyTorch, Transformers,
  Hugging Face caches, `unpaper`, `pngquant`, `jbig2enc`, test/dev packages,
  and unsupported-architecture binaries.
- Poppler, Tesseract, OCRmyPDF, Leptonica, PDFium, CPython, Tauri, and every
  transitive conveyed component have the required licenses/notices. Poppler
  has exact corresponding-source/build material in the compliance output.
- Tagged release CI refuses to build when the Developer ID, App Store Connect,
  or Tauri updater credential set is incomplete. Pull requests never publish
  release artifacts or gain access to release secrets.
- Every Mach-O beneath the final app is explicitly inventoried. Nested Python
  executables, `.dylib` files, `.so` extensions, frameworks, Poppler,
  Tesseract, and their libraries carry valid Developer ID signatures before
  the outer application is sealed.
- Per-file strict signature verification passes; strict complete-application
  verification passes; stapler validation passes on the application before
  DMG assembly; and Gatekeeper reports a notarized Developer ID source for the
  application installed from that DMG.
- The final signed `.app` is smoked in place before upload. The DMG and updater
  assets correspond to that application rather than a separately rebuilt or
  post-signing-mutated runtime.
- Release finalization rejects a missing or malformed `latest.json`, an empty
  updater signature, an unexpected target or URL, missing checksums, or an
  incomplete license/source archive.

### Packaged behavior

- `Doc Evidence.app` reaches authenticated ready state with no system Python,
  `uv`, Homebrew, repository, development environment, or network.
- The public fixture collection remains byte-identical before and after every
  inventory, render, extraction, cancellation, crash, and restart action.
- Page rendering uses packaged `pdftoppm`; native text uses packaged
  `pdfinfo`/`pdftotext`; PDF OCR and image OCR use only the packaged baseline
  pack.
- OCR succeeds without Ghostscript and with optional optimization helpers
  absent. Any hidden dependency on them is a stopping failure, not permission
  to add them.
- Durable jobs, attempts, events, artifacts, and the active catalog remain
  valid across forced sidecar exit and application restart.
- App close leaves no sidecar, scheduler, worker, OCR, Tesseract, or Poppler
  descendant.
- Cold-start, extraction, memory, installed-byte, and compressed-byte evidence
  is recorded without claiming a universal performance result.
- Installing from the stapled DMG and launching through Finder succeeds under
  Gatekeeper without a quarantine bypass, terminal fallback, or security
  warning.
- A manual update check reaches only the configured updater endpoint and
  handles current/no-update, unavailable, and invalid-signature responses
  without affecting the library. The first live `N -> N+1` updater exercise is
  recorded against the next signed release if no prior Doc Evidence release
  exists to serve as `N`.

## Manual Acceptance

Provide one release candidate with the signed/notarized `.app` and stapled
ticket, DMG, signed updater metadata, build/audit report, SBOM, third-party
notices, compliance archive, checksums, exact commands, and commit/test map.
The maintainer verifies:

1. The DMG opens normally, the app installs and opens from Finder, and
   Gatekeeper identifies a notarized Developer ID build without a bypass.
2. An empty application home explains libraries and opens a native folder
   picker rather than asking for a YAML path.
3. Creating a managed library and registering an existing descriptor both
   produce the expected stable library identity and read-only collection.
4. Search, PDF viewing, extraction comparison, Poppler execution, OCR
   execution, activity, cancellation, and restart feel like the existing
   product rather than a Tauri-specific fork.
5. Cancelling a picker or extraction has an honest, recoverable result.
6. Killing the sidecar produces one useful failure state; relaunch recovers
   durable library and job state.
7. Heavy extractors are clearly unavailable/not installed without a broken-app
   presentation or a surprise download.
8. License and component information is readable from inside the application
   and from the review bundle.
9. Core library use succeeds with network access disabled; no unexpected
   network access, source mutation, private-path leakage, or surviving child
   process is observed.
10. The published/downloaded artifact hashes match the final report, updater
    metadata is valid, and the size/startup result is acceptable for the first
    macOS distribution.

An authorized external library may be used for an additional deliberate
maintainer review after the synthetic gate passes. That lane must verify the
selected registered library, hash source bytes before and after, avoid copying
private documents into the application or repository, and record only bounded
aggregate evidence. It is not an automated public-fixture gate and is not
implicitly authorized merely by building the application.

## Security and Resource Bounds

- Bind only to IPv4 loopback for this tactical. No LAN, wildcard, Unix-socket,
  hosted, or remote-model composition is added.
- Require exact Tauri origin plus the correct credential on every runtime
  operation. Host-control routes reject browser-origin requests even if a
  runtime token is valid.
- Ready records, handshakes, host-control bodies, logs, and Rust events have
  explicit byte limits and timeouts.
- Do not expose unrestricted source or artifact paths to JavaScript. Continue
  to stream artifacts through identity-bounded Python routes.
- Restrict native dialogs to folder selection and `.yaml` descriptor selection
  required by frozen operations.
- Preserve current source canonicalization, collection overlap, store overlap,
  artifact-root, API page-size, render-size, batch-size, scheduler concurrency,
  worker deadline, log, and event-retention limits.
- Run source-reading and extractor descendants with a minimal explicit
  environment and working directory. Do not inherit shell startup files.
- Treat bundled PDFs and images as hostile local input. Packaging does not
  claim that Poppler, PDFium, OCRmyPDF, or Tesseract is a sandbox.
- Load no analytics, telemetry, remote font, remote image, remote script,
  hosted product API, or model download. The only release-time network surface
  added here is the explicitly configured signed Tauri update path; core
  startup and library operation remain functional when it is unavailable.

## Explicit Non-goals

- No Mac App Store, App Sandbox, security-scoped bookmarks, iCloud container,
  login item, file association, Quick Look extension, or background daemon.
- No Intel or universal macOS build; no Windows, Linux, iOS, or Android work.
- No Docling, Marker, PyTorch, Transformers, model-heavy parser, extra
  Tesseract-language download, extractor marketplace, plugin manager, or pack
  updater.
- No Ghostscript or commercial third-party license purchase.
- No PDFium replacement for Poppler and no extraction/cache-identity change.
- No remote model/service fallback, upload, sync, account, collaboration,
  analytics, or telemetry.
- No durable human review writes, observation promotion, domain pack, or tax
  logic.
- No application-wide visual redesign. Bounded empty-home, bootstrap, native
  selection, failure, and license surfaces are included only as required for
  the desktop path.
- No managed-store relocation, backup redesign, garbage collection, or source
  deletion.
- No promise that arbitrary third-party extractor environments can be dropped
  into this first application.

## Rollback and Compatibility

- `desktop/`, the desktop runtime adapter, desktop-sidecar composition, host-
  control adapter, and staging scripts are additive. Removing them does not
  change source collections, the localhost server, CLI commands, library IDs,
  database schema, or existing artifact identities.
- Native library operations call the existing application services and write
  the same descriptors/registry/database state as their CLI equivalents. A
  library created by the app remains usable by the CLI after the app is
  removed.
- The packaged baseline uses existing extractor IDs and versioned descriptors.
  Different bundled tool versions create normal side-by-side run identities;
  they do not overwrite old output.
- Generated staging directories and application bundles can be discarded.
  User application-home and library stores are never build outputs and are not
  rollback targets.
- Desktop protocol or pack-manifest incompatibility blocks startup with a
  bounded error; it does not attempt a database or artifact migration.
- Apache-2.0 publication cannot be revoked for already distributed copies.
  Changing the project license or adding dual licensing later is a separate
  maintainer/legal decision.

## Planned Commit Slices

Each implementation commit that changes a continuing concern uses the exact
applicable `Topic: application-platform`, `Topic: library-management`, or
`Topic: job-architecture` trailer.

1. Open Tactical 002 and synchronize living product/distribution direction.
2. Add Apache-2.0, package metadata, manifest schemas, and license drift tests.
3. Add the versioned desktop sidecar, two-credential handshake, and shutdown
   tests.
4. Add host-authorized native library/collection application operations.
5. Add desktop runtime capabilities and bounded bootstrap/failure UI.
6. Add the thin Tauri shell, dialogs, single-instance behavior, and process
   supervision.
7. Stage the standalone Python runtime and build the first self-contained
   application without extractors.
8. Stage the baseline Poppler/Tesseract/OCRmyPDF pack and license/source
   compliance output.
9. Adapt the sibling release workflow, generate the Doc Evidence updater key,
   validate/provision credentials through the canonical runbook, and sign
   nested Mach-O resources explicitly.
10. Add notarization/stapling, DMG, updater metadata, checksum, SBOM,
    forbidden-dependency, offline, crash/restart, and outside-repository gates.
11. Build and verify the signed release candidate, update execution evidence
    and living docs, and stop for explicit maintainer release acceptance.

## Falsifiable Stopping Condition

Stop this tactical at explicit maintainer review when tag-driven CI produces a
Developer ID-signed and notarized macOS arm64 `Doc Evidence.app` with a stapled
ticket, packaged in a DMG with valid signed updater metadata and release
checksums; the exact final application, launched from outside the repository
under a fresh application home and with network/system-development assistance
absent, can create a library through the native authorization boundary,
inventory and search a synthetic collection, render a PDF, execute packaged
Poppler and Ghostscript-free English/German OCR, survive a forced sidecar exit and restart
with valid durable state, and close without surviving descendants or source
mutation, while every bundled byte, nested Mach-O signature, component,
license, architecture, dynamic dependency, notarization result, and GPL source
obligation reconciles in the generated audit.

If the app needs Ghostscript, a heavyweight extractor, an ambient executable,
an unrestricted client path, a remote download, an unreviewed license, or a
change to source/library/artifact identity to pass, stop and return to the
maintainer instead of expanding the bundle.

## Next-Slice Boundary

After explicit acceptance, normal patch releases reuse the checked sibling-
style version, tag, signing, notarization, updater, checksum, and finalization
workflow. The next release should record the first live signed `N -> N+1`
updater round trip when no older Doc Evidence release existed during Tactical
002. Rollback-channel policy, delta-update optimization, additional release
hosts, and App Store distribution remain separate decisions.

Optional language/extractor-pack discovery and downloads require their own
security, signature, compatibility, license-acceptance, storage, update, and
rollback design. Docling and especially Marker remain separate decisions.
Windows and Linux packaging follow later platform-specific tacticals; this
macOS distribution must not create assumptions that their process, filesystem,
signing, installer, or dynamic-library models are identical.

## Execution Record

Implementation began on 2026-08-01 under an explicitly bounded unattended
local lane. The maintainer asked for the implementation and validation to go as
far as possible without signing credentials or GitHub secret setup.

The first landed slice:

- licenses original project source under Apache-2.0;
- records SPDX metadata in the Python and frontend packages;
- adds strict documented and wheel-packaged desktop bundle and extractor-pack
  manifest schemas; and
- adds drift tests for project license declarations, schema parity, JSON
  Schema validity, required license conclusions, and bundle-contained paths.

Validation for that slice passed its focused Ruff checks, three focused unit
tests, and `uv build`. No credential, remote, signing, notarization, updater,
release, or publication operation was attempted.

The second landed slice adds the versioned Python desktop process and
transport boundary:

- two independent 256-bit inherited credentials are validated, removed from
  the child environment, and never emitted in ready or handshake records;
- the sidecar binds one ephemeral IPv4 loopback port, emits a strict bounded
  ready record, and exposes an authenticated runtime handshake only to the
  exact Tauri origin;
- a separate originless host-control handshake proves that the Rust/Python-
  only credential cannot be replaced by the browser runtime credential;
- platform, architecture, protocol, application-home source, capabilities,
  and optional baseline-pack identity are strict Pydantic/OpenAPI contracts;
  and
- parent stdin closure stops the real server cleanly and shuts down library
  schedulers through the existing manager lifecycle.

The focused sidecar tests passed against a real subprocess and ephemeral HTTP
server, including credential swapping, browser-origin rejection, secret/path
absence in retained startup evidence, and parent-EOF shutdown. The full 66-
test Python suite, Ruff format/check, Pyright, generated-contract drift,
frontend typecheck, and all 26 frontend tests pass at this boundary.

The third landed slice implements the Python side of native library
authorization:

- an originless host-control surface accepts absolute paths only under the
  independent Rust/Python credential and never exposes those paths in its
  result contracts;
- a selected source folder can create a named managed library with stable ID,
  app-owned descriptor/config/store, initialized unified database, and the
  frozen `eng`/`deu` baseline policy;
- an existing configuration is registered idempotently without rewriting the
  external file;
- managed libraries support sibling collection addition and confirmed parent
  replacement after the existing overlap preflight; adopted configurations
  remain read-only; and
- active/queued extraction work blocks a configuration refresh, while an idle
  cached composition is safely stopped and reloaded after atomic validation.

The full suite now has 70 passing Python tests. Focused tests verify source and
adopted-config immutability, response path secrecy, app-home store ownership,
database creation, idempotent registration, parent-replacement confirmation,
stable library identity, credential separation, and browser-origin rejection.
Ruff, Pyright, contract drift, frontend typecheck, and all 26 frontend tests
also pass.
