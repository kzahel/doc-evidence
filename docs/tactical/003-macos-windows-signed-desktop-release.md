# 003 — macOS and Windows Signed Desktop Release

Topic: application-platform

Topic: library-management

Topic: job-architecture

**Status:** Product direction selected and implementation plan drafted on
2026-08-23. This documentation change does not authorize implementation,
credential provisioning, repository creation, release publication, or other
external mutation. Begin implementation only after an explicit maintainer
request.

## Motivation and User-Visible Outcome

Ship the first supported Doc Evidence desktop release for both of the
maintainer's intended first-release platforms rather than treating the
existing macOS-only proof as the product boundary.

At the end of this tactical, a person can install the same Doc Evidence
version on a supported Apple Silicon Mac or Windows x86_64 PC, create or open a
local library through native folder authorization, inventory and search a
read-only document collection, render PDFs, run the bundled Poppler and
Ghostscript-free OCR/Tesseract baseline, inspect durable activity, restart the
application without losing state, and uninstall the application without
removing libraries or source documents.

The release is self-contained and works offline after installation. It does
not require a system Python, Homebrew, MSYS2, Visual Studio, `uv`, the source
checkout, or a development environment. The same React product and
Python-owned services run behind a thin Tauri shell on both platforms.

The first release matrix is deliberately:

| Platform | Architecture | Direct installer | Updater artifact |
| --- | --- | --- | --- |
| macOS | arm64 | signed, notarized, stapled DMG | signed `.app.tar.gz` and signature |
| Windows | x86_64 | signed per-user NSIS setup executable | signed NSIS updater artifact and signature |

Linux, Intel/universal macOS, Windows arm64, MSI, Microsoft Store, and Mac App
Store distribution are not first-release targets.

## Entry Evidence and Dependencies

This tactical builds on completed local work rather than restarting desktop
packaging:

- [Tactical 001](001-durable-extraction-jobs.md) owns the platform-neutral
  library, persistence, execution, recovery, and operational contracts.
- [Tactical 002](002-macos-tauri-desktop-application.md) is the macOS arm64
  unsigned-foundation execution record. Its thin Tauri shell, native path
  authorization, dual credentials, standalone CPython 3.12.12 runtime,
  Poppler/Tesseract/OCRmyPDF/PDFium baseline pack, final-byte audit, real OCR
  smoke, and unsigned DMG proof have landed.
- Tactical 002's compliance preflight currently blocks release on a reviewed
  pypdfium2 SPDX conclusion, 32 nested wheel libraries, and 19 Rust crate
  license texts. Those are entry work for this tactical, not acceptable
  release exceptions.
- The repository does not yet have a release remote, tag workflow, updater
  configuration, product-specific updater key/route, or release finalizer.
- The pinned [Desktop Release Kit](../references.md#desktop-release-kit-cross-platform-release-reference)
  contract and canary prove the shared macOS/Windows updater and signed-release
  mechanics. Doc Evidence still owns its product-specific key, repository,
  route, version, UI, lifecycle, and acceptance.
- The pinned [Machine Control](../references.md#machine-control-desktop-testbed-reference)
  common client provides accepted macOS and Windows guest execution,
  candidate/disposable workspaces, semantic native UI, captures, and lifecycle
  control. It validates installed artifacts; it is not a packaging or signing
  implementation.
- The canonical signing credential locations, shared publisher identities,
  secret names, and validation sequence remain in the private dotfiles
  runbook. No credential value or private machine inventory may enter this
  repository.

Read the owning living topics before implementation:

- [Application platform](../topics/application-platform.md)
- [Desktop library management](../topics/library-management.md)
- [Durable job architecture](../topics/job-architecture.md)
- [Product vision and application architecture](../product-vision-and-architecture.md)
- [References](../references.md)

## Current Testbed Readiness

The common Machine Control client was inspected read-only on 2026-08-23.

- The accepted macOS platform exposes persistent, candidate, and isolated
  workspaces. Its current target is stopped but available.
- The configured Windows target cannot currently resolve its exact private
  target identity. Readiness therefore reports unknown/unavailable and a
  disposable or candidate workspace is not yet safely acquirable.
- No VM was started or mutated while planning this tactical.

The first infrastructure gate is to repair or re-pin the private Windows
inventory, run the common target doctor, and prove one disposable/candidate
workspace acquire/release cycle. Concrete private target names, addresses,
paths, and credentials remain outside this public repository. Failure of that
gate blocks Windows acceptance work; it does not silently reduce the release
matrix to macOS.

## Frozen Product and Distribution Decisions

### One Product and One Version

- macOS and Windows ship the same Doc Evidence application version, Python
  data contracts, generated TypeScript contracts, database schema, library
  identity, artifact identity, and release notes.
- The desktop tag convention is `desktop-vX.Y.Z` and must agree with Python,
  frontend, Tauri, updater, bundle-manifest, and pack-manifest versions before
  a tag can be created.
- Platform-specific adapters may differ, but React product components do not
  branch on filesystem paths, installer types, credentials, or Tauri APIs.
- A library created by one platform remains portable at the contract level.
  This tactical does not promise that an absolute source alias remains valid
  after manually moving a library to another operating system.

### Supported Platform Floor

- macOS support is Apple Silicon only for the first release. The exact minimum
  supported macOS version must be declared once, in the Tauri/build contract,
  and tested on the matching Machine Control guest before the release
  candidate freezes.
- Windows support is Windows 11 x86_64. Windows 10, Windows on ARM emulation,
  server editions, Wine, and domain-managed enterprise deployment are not
  claimed without separate evidence.
- Linux stays deferred until a later tactical can choose formats, signing,
  desktop integration, baseline-pack sources, and testbed coverage deliberately.

### Native Installation and Updates

- macOS distributes a Developer ID-signed, notarized, and stapled application
  in a signed/notarized DMG. The corresponding Tauri updater bundle is also
  produced from the same final application bytes.
- Windows distributes one current-user NSIS installer. It must not require
  administrator privileges for the normal install/update path. The installer,
  installed executables, sidecar, and updater artifact are Authenticode-signed
  according to the canonical desktop-signing runbook.
- MSI, machine-wide installation, Store packaging, portable ZIPs, and a second
  release channel are excluded until actual deployment requirements justify
  them.
- Uninstall removes app-owned program bytes and updater state but preserves
  application data, libraries, artifact stores, source collections, and review
  state. A destructive data-removal option is not added to the uninstaller.

### Updater and Release Ownership

- Reuse the `desktop-update-v1` release-feed contract validated by Desktop
  Release Kit. Do not fork a Doc Evidence-specific updater protocol.
- Provision a new Doc Evidence updater signing key and route. Never reuse
  another application's private updater key.
- The feed contains exactly `darwin-aarch64` and `windows-x86_64` for the first
  release. Missing, duplicate, stale, unsigned, or unexpected platform entries
  block finalization.
- CI creates a draft release first. A finalizer verifies exact asset names,
  checksums, updater signatures, platform coverage, notarization/Authenticode
  evidence, and release version before it may publish.
- Credential provisioning, remote creation, pushing, tagging, and publication
  each remain explicit external actions. A local implementation request alone
  does not authorize them.

### Filesystem and Folder Authorization

- Rust owns native folder dialogs and passes selected paths directly to the
  separately authenticated Python host-control adapter. Absolute paths never
  enter ordinary React state or the loopback browser API.
- Windows application data uses the per-user local application-data directory
  injected by Tauri. `DOC_EVIDENCE_HOME` remains the explicit isolated-test and
  developer override on both platforms.
- The first Windows release supports local fixed-drive collections and managed
  libraries selected through the native dialog. UNC paths, mapped network
  drives, removable-media guarantees, and cloud-files placeholder semantics
  are not claimed.
- Windows path comparison is case-insensitive and separator-normalized at the
  platform adapter boundary while preserved display aliases remain
  user-readable. Collection/store overlap checks operate on resolved canonical
  paths, not string prefixes.
- Symlinks, junctions, mount points, and other reparse points are not traversed
  by default. A selected root that is itself a reparse point fails with an
  actionable explanation until a later policy safely distinguishes supported
  cases.
- Long paths and non-ASCII names must pass automated fixtures and installed-app
  acceptance. The implementation must use path-safe process invocation and
  must not assemble command strings for a shell.

### Process and Job Ownership

- Tauri owns the Python sidecar lifecycle; Python owns schedulers and extractor
  attempts. Neither platform changes durable job states or artifact
  publication contracts to simplify shutdown.
- On macOS, the existing process-group and bounded-termination behavior remains
  required.
- On Windows, both the host/sidecar boundary and each Python attempt tree use a
  kill-on-close Job Object or an equivalently proven native process-tree
  primitive. `taskkill` may be a last-resort diagnostic fallback, not the sole
  correctness mechanism.
- Cancellation, sidecar crash, app exit, updater restart, and VM shutdown must
  leave no surviving extractor descendants. Startup reconciliation must expose
  interrupted work using the same durable rules as Tactical 001.

### Runtime and Baseline Extractor Pack

- Each platform has a hash-pinned standalone CPython 3.12 runtime and a
  platform-native baseline pack. No cross-compilation claim replaces execution
  on the target OS.
- The baseline remains Poppler, Tesseract, OCRmyPDF, PDFium, English, German,
  orientation data, and required rendering/configuration assets. Ghostscript,
  Docling, Marker, model runtimes, language downloads, and plugin management
  remain excluded.
- Windows staging must pin exact upstream artifacts and hashes for CPython and
  every native tool/DLL. Build inputs, transformations, licenses, source offers,
  final files, architectures, and dynamic dependencies must reconcile through
  the same strict manifest model as macOS.
- Runtime discovery is bundle-relative. Ambient `PATH`, registry tool
  discovery, developer DLLs, package managers, and current-working-directory
  assumptions are forbidden.
- The pack must pass real image-only PDF OCR and text recovery on each final
  installed artifact with network access and development tools unavailable.

### Compliance and Provenance

- The current three macOS compliance blockers must be closed with reviewed,
  version-bound records. Signing does not waive them.
- Windows introduces a fresh component and source audit; it cannot inherit a
  macOS license conclusion merely because a package has the same name.
- The aggregate SBOM, human notices, license texts, corresponding-source
  artifacts, component inventory, build recipes, and checksums must identify
  which obligations apply to shared source versus each conveyed platform
  binary.
- Release compliance is fail-closed. Unknown licenses, unowned native
  libraries, missing source offers, or unreconciled files prevent signed public
  publication.

## Implementation Plan

### 1. Close the Existing macOS Foundation

1. Resolve the pypdfium2 SPDX conclusion with a reviewed, version-bound record.
2. Flatten and identify all 32 nested wheel libraries, their versions,
   licenses, sources, hashes, and corresponding-source obligations.
3. Retain authoritative license texts for the 19 Rust crates whose published
   archives omit them, bound to exact locked versions and source revisions.
4. Make `compliance-preflight` return release-ready only when every current and
   newly introduced condition is actually satisfied.
5. Rebuild the unsigned macOS candidate and repeat the final mounted-DMG audit
   so later cross-platform work starts from a clean, reproducible foundation.

### 2. Restore the Windows Testbed Gate

1. Repair or re-pin the private Windows target inventory without committing
   private values here.
2. Pass the common target doctor and Windows platform doctor.
3. Acquire, identify, and release a disposable or candidate workspace without
   mutating the guarded base.
4. Prove guest command execution, file transfer, resident application status,
   semantic UI snapshot/action, capture, and safe shutdown through the common
   Machine Control surface.
5. Record only public capability results and failure classes in this tactical.

### 3. Remove macOS Assumptions from Shared Desktop Contracts

1. Replace `require_macos_arm64()` and hard-coded macOS/arm64 ready/handshake
   values with an allowlisted build target supplied by a strict platform
   manifest.
2. Keep platform and architecture in the Python ready record, host-control
   handshake, Rust validation, bundle manifest, pack manifest, and audit report;
   reject any disagreement before exposing the runtime.
3. Move `.app/Contents/Resources` and executable suffix assumptions behind
   platform resource-layout adapters.
4. Add Windows application-home, path canonicalization, native dialog, and
   single-instance/focus behavior without leaking paths into React.
5. Preserve exact-origin runtime authentication, originless host-control
   authentication, per-launch credentials, parent-channel shutdown, and bounded
   logging on both platforms.

### 4. Prove Windows Process-Tree Correctness

1. Add target-native process-tree ownership for the Tauri sidecar and Python
   attempt supervisor.
2. Test normal completion, user cancellation, retry, parent EOF, forced
   sidecar exit, forced extractor exit, app close, updater-requested restart,
   and VM shutdown/restart reconciliation.
3. Assert no descendant retains a source, database, artifact, log, or
   application binary handle after bounded shutdown.
4. Preserve atomic staging/publication and never report an interrupted attempt
   as successful merely because its child exited during teardown.

### 5. Build the Windows Runtime and Extractor Pack

1. Add strict `windows-x86_64` runtime and baseline-pack manifests with exact
   URLs, hashes, versions, architectures, file owners, licenses, and sources.
2. Stage a standalone Python runtime and locked production dependencies without
   pip, test/build tools, caches, checkout paths, or ambient interpreters in the
   final tree.
3. Stage Poppler, Tesseract, OCRmyPDF dependencies, PDFium, language data, and
   configuration with bundle-relative resolution.
4. Add PE/DLL inventory and dependency-closure auditing. Reject missing DLLs,
   unexpected architectures, absolute build-machine paths, writable program
   resources, undeclared executables, and unowned final bytes.
5. Run the sidecar authentication/shutdown smoke and real Ghostscript-free OCR
   from a copied-out staged tree before invoking Tauri.

### 6. Produce Reproducible Unsigned Candidates

1. Extend the build entry point into explicit platform-native stage, build,
   audit, review, and clean-rebuild operations without hiding target-specific
   commands behind an unsafe generic shell layer.
2. Generate macOS DMG/updater and Windows NSIS/updater candidates from clean
   trees with synchronized versions and strict expected asset names.
3. Audit the exact DMG-mounted and NSIS-installed bytes, not only staging
   directories or pre-installer bundles.
4. Emit checksums, bundle/pack manifests, SBOMs, notices, compliance artifacts,
   and machine-readable validation reports for both platforms.
5. Require two clean builds of each platform to agree on the declared
   reproducibility boundary or document every expected non-deterministic field
   before signing is allowed.

### 7. Add Updater and Release Automation

1. Add the Tauri updater plugin and a platform-neutral React update surface
   above narrow runtime operations. Product components receive release status,
   version, progress, and restart intent—not platform paths or secrets.
2. Add clean-tree version/changelog preparation and `desktop-vX.Y.Z` tag
   validation, but do not push or tag during ordinary implementation.
3. Add a tag-triggered workflow with fail-closed credential gates, separate
   macOS arm64 and Windows x86_64 build jobs, and a draft-release finalizer.
4. On macOS, sign nested Mach-O objects inside-out, verify each layer, seal the
   app, notarize, staple, construct final DMG/updater artifacts, and audit the
   final delivered bytes.
5. On Windows, sign nested executables/DLLs according to policy, build and sign
   NSIS/updater artifacts, verify Authenticode identity and timestamp, install
   them in a clean guest, and audit the final installed bytes.
6. Validate `desktop-update-v1` metadata against exactly two supported targets,
   the intended version, valid signatures, downloadable assets, and published
   checksums before a release can leave draft state.

### 8. Add Deterministic Packaged Acceptance Harnesses

1. Extend the existing headless/runtime harness to cover create/open library,
   inventory, search, page render, extraction, activity, restart, and shutdown
   without depending on OS pointer interaction.
2. Add seeded public/synthetic fixtures for Windows case-insensitive aliases,
   overlap checks, non-ASCII names, long paths, spaces, and reparse-point
   rejection.
3. Exercise the same product workflow against copied-out macOS and installed
   Windows artifacts before using interactive native automation.
4. Reserve Machine Control for behavior that genuinely crosses the OS shell:
   installers, Gatekeeper/SmartScreen, native dialogs, focus/single-instance,
   app lifecycle, updater restart, uninstall, and final capture evidence.

### 9. Validate Unsigned Candidates in Disposable Guests

For both platforms, acquire a fresh candidate/disposable workspace through
Machine Control and validate the exact candidate artifact:

1. install or mount/copy the application using the platform's normal user
   flow;
2. launch with network access disabled and no development runtime available;
3. create a managed library and add a local synthetic collection through the
   native picker;
4. inventory, search, render a PDF, run bundled OCR, and inspect durable job
   activity;
5. restart after normal exit and after forced sidecar termination;
6. open a second instance and confirm the existing window receives focus;
7. cancel an active extraction and confirm no descendants survive;
8. uninstall or remove the application and confirm library/source bytes remain;
9. capture application identity, version, installer state, relevant native
   trust UI, and the public validation report; and
10. release the workspace through the common control surface.

Tauri WebView accessibility may expose only the outer frame on Windows. In
that case, use the deterministic application harness for React content and
Machine Control for the native shell flow. Lack of semantic WebView DOM access
is not permission to fall back to brittle screen-coordinate automation for
ordinary product behavior.

### 10. Run the Signed Release Rehearsal

After explicit authorization for credentials and external setup:

1. provision the Doc Evidence repository/route and a new updater key using the
   canonical runbook;
2. validate shared and per-app credentials without exposing secret values;
3. prepare a release commit and tag only from a clean, reviewed tree;
4. let CI create signed artifacts and a draft release;
5. download each exact draft asset by checksum into fresh guests;
6. repeat the full installed acceptance matrix, including Gatekeeper,
   notarization/stapling, Authenticode, SmartScreen behavior, updater metadata,
   restart, and uninstall preservation;
7. reconcile artifact names, signatures, checksums, SBOM/compliance assets,
   version, and two-target updater metadata; and
8. stop for explicit maintainer acceptance before making the draft public.

Because there is no older signed Doc Evidence release, the first release does
not fabricate an `N -> N+1` result. The first patch release must exercise a
real signed old-to-new update on both platforms before the updater channel is
called proven in production.

## Validation Gates

### Shared Automated Gates

Run the current repository baseline plus the desktop-specific contracts:

```bash
uvx ruff format --check src tests
uvx ruff check src tests
uv run python -m unittest discover -v
uvx pyright
uv build
npm --prefix web run check:generated
npm --prefix web run typecheck
npm --prefix web test
npm --prefix web run build
cargo fmt --manifest-path desktop/src-tauri/Cargo.toml --check
cargo clippy --manifest-path desktop/src-tauri/Cargo.toml --all-targets -- -D warnings
cargo test --manifest-path desktop/src-tauri/Cargo.toml
```

Target-native desktop gates must additionally prove:

- strict runtime, bundle, extractor-pack, SBOM, license, source, architecture,
  and final-file manifest validation;
- macOS Mach-O dependency closure and nested signature verification;
- Windows PE/DLL dependency closure and Authenticode verification;
- copied-out or installed sidecar authentication, independent host-control
  authentication, ready/handshake agreement, parent-EOF shutdown, and forced
  cleanup;
- real Poppler extraction and English/German Ghostscript-free OCR from final
  delivered bytes;
- clean app-home launch, native library creation/opening, inventory, search,
  rendering, durable job execution/cancellation/recovery, and preservation of
  source bytes;
- exact two-platform updater metadata, asset names, signatures, checksums, and
  versions; and
- no network, package manager, development runtime, build-path, home-path, or
  repository dependency during installed use.

### Machine Control Evidence

The release record may include public capability and result summaries, exact
artifact hashes, screenshots/captures that contain only synthetic data, and
workspace cleanup results. It must not include private inventory identifiers,
host addresses, account names, credential paths, or VM storage paths.

Every acceptance workspace must be acquired and released through the common
client. A persistent or guarded base may not be mutated for convenience. VM
availability alone is not a pass; the exact signed artifact must run in the
guest and satisfy the product workflow.

### Manual Maintainer Acceptance

Before publication, the maintainer reviews both exact signed candidates for:

- understandable install, first-run, native folder, error, update, restart,
  and uninstall flows;
- readable application identity and publisher/trust presentation;
- responsive library, document, extraction, and activity interactions;
- acceptable idle/active CPU, memory, launch time, OCR duration, and installed
  size on representative guests;
- preservation of application data and source documents across update and
  uninstall; and
- release notes, checksums, licenses/notices, and support limitations that
  match the actual matrix.

## Security and Privacy Invariants

- Bind only to loopback and preserve the independent runtime and host-control
  credentials. Never log, persist, return, or place either credential in a URL.
- The runtime origin remains exact and per-launch. Native path operations
  remain originless, narrow, separately authenticated, and Python-owned.
- No unrestricted path, executable, shell command, URL, installer option, or
  environment mapping is accepted from React or the loopback API.
- Source collections are immutable. Acceptance compares source hashes before
  and after inventory, extraction, update, restart, and uninstall.
- The desktop app does not add analytics, remote assets, hosted storage,
  automatic model downloads, or a remote-model fallback.
- Signed release logs and evidence must redact credentials and private target
  inventory even when a build or guest fails.

## Non-Goals

- Linux, Intel/universal macOS, Windows arm64, Windows 10, mobile, or hosted
  application distribution.
- MSI, Store, Mac App Store, machine-wide, enterprise policy, managed
  deployment, or portable ZIP channels.
- Network shares, cloud placeholder hydration, removable-media guarantees, or
  automatic traversal of reparse points.
- Ghostscript, Docling, Marker, model runtimes, optional language/extractor
  downloads, plugins, or a second release channel.
- Durable human review, candidate-observation, spatial highlighting, regional
  OCR, domain-pack, or downstream-form work.
- A new release protocol, remote service, scheduler model, library identity,
  artifact identity, or database ownership model.
- Treating Machine Control as application test logic, a build farm, a secret
  store, or a substitute for target-native packaging and deterministic tests.

## Rollback and Recovery

- Tactical 002's unsigned macOS build remains the reproducible fallback while
  cross-platform work is incomplete. Do not overwrite its execution evidence.
- Platform manifests and adapters are additive. A failed Windows slice must not
  weaken macOS manifest validation, authentication, compliance, or final-byte
  audit.
- Never mutate a user's library schema solely to support packaging. Any future
  schema migration requires its own compatibility and backup evidence.
- A failed CI release remains draft. Revoke or rotate only the affected
  product-specific secret, preserve diagnostics without values, correct the
  source, and create a new version/tag; never replace published signed bytes
  under an existing asset name.
- A bad updater release is withdrawn from the feed without deleting user data.
  Rollback/downgrade database compatibility must be decided explicitly before
  advertising downgrade support.

## Falsifiable Stopping Condition

Implementation stops before public publication unless the maintainer
separately authorizes that action.

The release candidate is ready for that decision only when one synchronized
version produces the exact macOS arm64 and Windows x86_64 artifact matrix; all
runtime, native-dependency, compliance, signature, checksum, updater, and
final-byte audits pass; each exact signed artifact completes the installed
workflow in a fresh Machine Control guest without development dependencies,
source mutation, data loss, credential exposure, or surviving descendants; and
the draft-release finalizer reports exactly two valid updater targets.

If either platform, compliance, or testbed gate fails, do not publish a
macOS-only first release under this tactical. Fix the gate or return to the
maintainer to revise the product matrix explicitly.

## Next-Slice Boundary

After publication and explicit acceptance, the next release slice is a small
signed patch that proves a real `N -> N+1` updater round trip on both macOS and
Windows using the exact public feed and installed old version. Linux and
optional extractor packs remain independent tacticals rather than additions to
that updater proof.
