# 003 — macOS and Windows Signed Desktop Release

Topic: application-platform

Topic: library-management

Topic: job-architecture

**Status:** Local implementation and validation authorized on 2026-08-24.
Credential provisioning, repository creation, signing, tagging, release
publication, and other external mutations remain separately unauthorized.

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
- Tactical 002's compliance preflight entered this tactical blocked on a
  reviewed pypdfium2 SPDX conclusion, 32 nested wheel libraries, and 19 Rust
  crate license texts. All three classes are now closed, and the full macOS
  exact-source preflight reports release-ready with no compliance blockers.
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

The first Machine Control gate passed on 2026-08-24 without committing private
inventory or using outer UI:

- Windows exact private identity, PowerShell administration, interactive
  desktop, resident control, semantic UI, capture, and input all pass the
  common doctor.
- An isolated Windows workspace was acquired through a provider disposable
  overlay, reached full common readiness, executed a synthetic guest marker,
  launched the deterministic native fixture, produced a semantic snapshot,
  pressed its named control, confirmed the independent counter effect, captured
  the target-native window, and returned a hash-checked PNG through bounded
  artifact retrieval.
- The first workspace release failed closed when its clean shutdown envelope
  expired. Machine Control retained the receipt and running overlay rather than
  forcing or discarding it. One explicit clean-shutdown retry succeeded; the
  subsequent release discarded the overlay, left no temporary workspace or
  claim, and the restored persistent guest did not contain the marker.
- The persistent Windows target was returned to its initial running state and
  again passes every common doctor check. Its post-start development audit also
  reports the guest agent, OpenSSH, resident, interactive probe, Python, .NET,
  firewall, and reboot state healthy.
- The macOS target is suspended and exact persistent/candidate/isolated
  workspace capabilities remain available. It was not started or mutated for
  this gate.

The available Windows guest reports Windows ARM64. It is a valid target-native
Windows implementation and x86_64-emulation testbed, but it cannot alone prove
native Windows x86_64 performance or compatibility. Tactical 003 therefore
uses it immediately for Windows contracts, lifecycle, installer, and x86_64
emulation validation while retaining one native Windows x86_64 installed-
artifact run as a release-blocking acceptance gate. Concrete target names,
addresses, paths, handles, claims, and credentials remain outside this public
repository.

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
npm --prefix web run contracts:check
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

## Execution Record

Implementation was explicitly authorized on 2026-08-24 with a request to
commit coherent checkpoints as work proceeds. The first checkpoint restores
and proves the Machine Control gate described in
[Current Testbed Readiness](#current-testbed-readiness). It makes no application
code, credential, signing, remote, tag, or publication change.

The second checkpoint removes the macOS-only assumptions from the shared
desktop launch contract. Python, Rust, generated TypeScript, and React now
recognize exactly `macos/arm64` and `windows/x86_64`, reject crossed target
pairs, bind each target to its Tauri custom-protocol origin, and require the
sidecar's actual runtime target to agree with the host-supplied manifest
values. Bundle and extractor-pack schemas carry the same exact target pairs;
the sidecar additionally binds a loaded pack to that target before serving.

The Rust shell now selects target-specific resource layout, bundled Python
path, executable search path, inherited environment, baseline-pack identity,
and ready-record validation at compile time. Windows uses per-user local
application data and the standard Tauri Windows origin; unsupported shell
targets fail compilation. React still receives only a behavioral runtime and
no filesystem path or platform API.

This checkpoint passed 19 focused Python desktop/packaging/CLI tests, generated-
contract drift, TypeScript typechecking, four desktop-runtime tests, JSON
Schema syntax/copy agreement, Rust formatting, Clippy with warnings denied,
and all six Rust tests on macOS arm64. Target-native Windows execution and the
remaining Windows path, process-tree, runtime-pack, and installer work stay in
later checkpoints; this host-side result is not presented as Windows release
acceptance.

The third checkpoint implements Windows kill-on-close process ownership at
both native boundaries. The Rust shell creates an unnamed Job Object for the
sidecar tree, sets `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, assigns a tiny copy of
its own executable before sending a one-byte launch gate, and only then lets
that launcher start the packaged Python sidecar. Graceful close still uses
parent stdin and the existing scheduler-cleanup envelope; forced close
terminates the Job Object and closing its final handle is the fail-safe.

Python applies the same ordering to every extractor attempt. A private gated
launcher cannot start the worker until the supervisor has assigned it to a
fresh kill-on-close Job Object. The launcher records the actual worker PID,
all descendants inherit the job, and cancellation, timeout, supervisor crash,
or final handle close removes the complete tree without `taskkill`. Windows
process-liveness diagnostics now use `OpenProcess` plus a zero-time wait rather
than POSIX `kill(pid, 0)` semantics. Target testing also found that Windows
rejects `fsync` on the read-only handles previously used for staged artifacts;
app-owned staged files are now opened read/write for the same flush-before-
publication invariant.

The isolated Windows ARM64 guest ran the exact source and an x86_64 Rust build
under Windows emulation. Five focused Python scenarios passed: normal atomic
publication, launch failure, timeout/crash handling, cancellation with a noisy
descendant, and ignored cancellation with forced descendant cleanup. The
x86_64 Rust target passed `cargo check`, Clippy with warnings denied, seven
tests including an independently counted two-process Job Object tree, and a
built launcher smoke. The guest encountered intermittent, bounded
administration-route rediscovery failures during repeated builds and cleanup;
each recovered through the common readiness surface, and the final common
doctor fully passes. Guest staging was removed before release. The first
receipt-bound release again failed closed at its clean-shutdown bound; one
explicit shutdown retry allowed the overlay to be discarded, left no temporary
workspace or claim, and restored the persistent target to its initial running,
ready state. This is target-native Windows lifecycle evidence and
x86_64-emulation build evidence, not the still-required native Windows x86_64
installed-artifact acceptance.

The fourth checkpoint makes collection and library path identity platform-
aware without rewriting user-visible aliases. Windows comparisons normalize
separators and case by path component; configuration loading, managed-library
creation, existing-library registration, collection preflight, and descriptor/
store integrity checks all use that shared identity. Prefix collisions and
different drive roots remain distinct.

Windows source admission now accepts only available local fixed-drive roots.
It rejects a selected symlink, junction, mount point, other reparse point,
offline/recall placeholder, mapped/network drive, removable drive, or unknown
drive class before changing library scope. Inventory traversal preserves the
existing symlink warnings, prunes other reparse points, and skips offline or
recall-marked descendants rather than following or hydrating them. The checks
remain in Python-owned services, below the path-free React runtime.

Eight focused tests pass on the target-native Windows guest: separator/case
identity, component-safe prefix and drive behavior, long comparison aliases,
Unicode names with spaces, case-alias overlap during configuration loading,
fixed-drive admission, fail-closed non-fixed/offline classification, and both
selected-root and nested-junction behavior. The first native run usefully
showed that the guest's development Python cannot create a greater-than-260-
character fixture. Actual long-path I/O therefore remains an explicit gate for
the pinned standalone Python runtime and installed application; the comparison
test alone is not presented as that acceptance.

Two fresh disposable overlay boots reached the Windows desktop but did not
recover administration within the documented readiness window while UTM
registration alternated between verified and unavailable. Both were cleanly
shut down and discarded. The same exact test subset then ran from removable
temporary staging on the restored persistent appliance, which passed the full
common doctor before and after the run. Staging was verified absent, the
persistent target was left in its initial running/ready state, and final
inventory showed no temporary workspace or live claim. Disposable exact-
artifact acceptance remains release-blocking despite the target-native path
evidence.

The fifth checkpoint begins the Windows runtime and extractor-pack boundary
with exact, reviewable inputs rather than a target-local package-manager
installation. The Windows x86_64 build manifest pins CPython 3.12.12 build
20260114, the locked production requirements, a Poppler 26.02.0 distribution,
an official Tesseract 5.5.3 installer, the exact Microsoft 14.44 x64 app-local
CRT payload, the selected English/German/orientation data, their available
source archives, and every one of the 55 selected native payload hashes.
Poppler's 271-file data tree also has a deterministic tree identity.

A dependency-free PE parser reads architecture, PE32/PE32+ identity, ordinary
imports, and delay imports without requiring Visual Studio or LLVM during the
audit. The flat-directory audit rejects non-x86_64 native bytes and any import
that is neither a bundled file, an API-set contract, nor an explicitly
allowlisted Windows system DLL. Eighteen focused manifest, extraction,
launcher-source, pruning, parser, and closure tests pass, and the parser reads
the actual pinned Poppler binaries locally.

This is an input and audit checkpoint, not a staged runtime pass. The two
upstream Windows distributions bundle many third-party DLLs, so each remains
`NOASSERTION` with an explicit file-level license/source blocker instead of
inheriting the Poppler or Tesseract top-level license. Poppler's required
`msvcp140`, `vcruntime140`, and `vcruntime140_1` files now come from a pinned
Microsoft Visual Studio 17.14/CRT 14.44 VSIX; the latter two exactly match the
pinned CPython archive. Selecting all 55 declared files from the three real
archives produces a complete flat PE dependency closure. Microsoft app-local
redistribution terms remain an explicit compliance blocker rather than an
assumed license conclusion.

The safe pack assembler now selects only the declared native, Poppler-data,
Tesseract-support, and language files; compiles a tracked relocatable Rust
OCRmyPDF launcher without a command shell; validates the entire flat PE
closure; and writes the platform-bound pack manifest. Its first real-archive
structural run caught that the three Windows language hashes had incorrectly
described the macOS Homebrew payload rather than the pinned 4.1.0 archive. The
corrected hashes all reconcile to that archive. With an existing x86_64 PE
substituted only for the not-yet-target-compiled launcher, the structural run
produces five tools, three language records, two support records, 51 DLL
records, and 56 total PE records. Windows x86_64 dry runs of the frozen locks
resolve 20 production and 27 baseline Python distributions. Materializing the
exact target wheels beside the standalone archive and applying the pruning
contract leaves a closed 123-file PE graph. Two imports resolve to unique,
hashed pikepdf private DLLs outside ordinary loader roots; execution remains a
required target-native gate rather than being inferred from static uniqueness.

The transactional Windows runtime builder now owns standalone extraction with
link and Windows case-collision rejection, frozen production/baseline and
project installation, deterministic GUI/test/installer pruning, exact
pypdfium2 license selection, runtime/component/file manifests, full-tree PE
audit, and rollback. It then copies the staged runtime to a different path and
requires all five tool versions, three Tesseract languages, a real Ghostscript-
free English/German OCR round trip, authenticated sidecar handshake and parent-
EOF shutdown, and actual greater-than-260-character standalone-Python I/O.
These gates are implemented but not yet executed on Windows. Target-native
launcher/dependency installation, copied-out sidecar/OCR smoke, long-path I/O,
and final Windows x86_64 installed acceptance remain open.

The Windows-specific Tauri overlay now selects only a current-user English
NSIS installer, rejects downgrades, uses LZMA compression, and embeds the
visible WebView2 bootstrapper. The target-only unsigned build fixes
`x86_64-pc-windows-msvc`, remaps repository and Cargo paths, and refuses
signing. Its audit requires the exact
`Doc Evidence_0.4.0_x64-setup.exe` name, a valid installer PE, an x86_64 PE32+
application, exact hashes, and `NotSigned` Authenticode state for both app and
installer, after re-running the staged runtime smoke. The merged Tauri config
passes the pinned CLI schema locally. No target build, install, or uninstall
claim is made yet.

The first macOS compliance closure removes the 19-crate missing-license-text
blocker without treating a package's declared SPDX expression as the license
text itself. A tracked inventory binds each exact crate name/version to the
Git revision and repository path preserved in Cargo's packaged
`.cargo_vcs_info.json`, then to hash-pinned license documents from that exact
upstream revision. Where an upstream workspace notice links to standard texts
instead of carrying them, the inventory additionally pins SPDX License List
3.27.0 texts; the `selectors` crate's absent repository-level MPL copy uses the
same canonical source. A bounded cache permits later compliance runs without
network access while hash and VCS drift still fail closed.

All 253 target-resolved Rust dependencies were re-inventoried locally. The 19
previously missing packages recovered exact license material and the missing
set is now empty. Twelve focused macOS packaging tests and Ruff pass. This
checkpoint does not close the remaining pypdfium2 or 32 nested-wheel-native
component blockers, and it does not claim a rebuilt application or DMG yet.

The next macOS compliance closure replaces pypdfium2's comma-separated package
metadata with a target- and version-specific SPDX `LicenseRef`. The record
keeps the wrapper's declared `Apache-2.0 OR BSD-3-Clause` separate from the
concluded wheel composite, pins the exact macOS arm64 PyPI wheel and bundled
PDFium binary hashes, and compares the binary plus every wheel-declared license
file against the staged runtime. The real 5.5.0 wheel and existing runtime
match byte-for-byte across the binary and all 19 license files. The aggregate
SPDX will include the corresponding extracted-license record after the runtime
and application are rebuilt. The 32 nested-wheel-native component records
remain the only one of Tactical 002's three compliance blocker classes still
open.

Flattening the remaining wheel libraries found a security defect before it
became release paperwork. The exact `pi_heif` 1.4.0 macOS wheel contains
libheif 1.23.0, which upstream identifies as affected by
[GHSA-xpw3-9rhw-482x](https://github.com/strukturag/libheif/security/advisories/GHSA-xpw3-9rhw-482x)
and fixes in 1.23.1. The upstream `pi-heif` package is discontinued at 1.4.0,
while OCRmyPDF documents HEIF conversion as an optional feature whose absence
does not break its PDF pipeline. HEIF input is not part of this tactical's
baseline promise, so both platform manifests now explicitly exclude
`pi-heif` after resolving the frozen lock. Runtime manifest generation and
ordinary audits reject its re-entry on either platform. Only the read-only
pre-replacement audit accepts that one newly excluded distribution, allowing
the transactional builder to migrate an older staged tree without weakening
the new output gate.

The rebuilt macOS runtime contains 41 Python distributions, 3,819 files, and
109 Mach-O objects at tree
`23adac429b1b7a5ae1dc943b8c8c53c3b5ad7f36001e2be8e8a55a50b59531b4`.
Neither `pi_heif`, libheif, nor libde265 is present. The exact copied-out
sidecar authentication/parent-EOF smoke and real Ghostscript-free OCR smoke
pass. This removes two nested libraries; PDFium's separately reconciled dylib
is no longer counted as unresolved, leaving 29 Pillow/pikepdf native-library
records to flatten.

The first app rebuild usefully exercised another transactional edge: the
frontend production build changed `web/dist` after the previous runtime was
staged, so the old runtime's current-checkout identity check prevented the
explicit replacement that was needed to repair it. Pre-replacement audits on
both platforms now skip only the current frontend comparison while still
checking the old tree's schema, internal manifest hashes, complete file
inventory, target, pack, native closure, and forbidden development packages.
Every new staged tree and ordinary audit still requires the exact current
frontend identity. After restaging, the unsigned 3,823-file application at
tree `42f35959eb4b24c63835ef9f08a328f36f85a78a3cf362d9acc606890a8c194e`
passed its final application audit, including the embedded runtime smokes and
the expected unsigned-signature check.

The Pillow sub-boundary flattens all 18 of that wheel's nested dylibs into 14
components. Each record binds the exact Pillow 12.3.0 macOS arm64 wheel,
installed dylib hashes, tagged build-version JSON, tagged wheel-build script,
embedded CycloneDX component where present, reviewed SPDX conclusion, and a
hash-pinned upstream source archive. The verifier compares the wheel members
byte-for-byte with the final application runtime and fails on missing,
repeated, unowned, or drifted paths or evidence. The aggregate SPDX represents
the nested packages as children of Pillow rather than attributing them to the
wrapper's MIT-CMU license.

The pikepdf sub-boundary closes the final macOS component blocker without
trusting its incomplete tagged wheel notice as an inventory. The exact
10.11.0 macOS arm64 wheel conveys 11 dylibs represented by 10 components:
qpdf, GnuTLS and its transitive closure, and libjpeg-turbo. Each record binds
the parent wheel, exact final dylib hash, tagged pikepdf build recipe where it
provides version evidence, reviewed binary-version evidence, a conservative
SPDX conclusion, and a hash-pinned source archive. The verifier also
reproduces the one permitted staging transform for four wheel members:
Homebrew's build prefix is replaced with the neutral equal-length prefix and
the modified Mach-O is ad-hoc signed before its bytes are compared.

The full preflight now contains 69 top-level components, 24 flattened Pillow/
pikepdf components, 74 Python Mach-O objects, and 253 Rust plus 11 Node
dependencies. It reconciles all 30 nested libraries, resolves all 24 exact
historical Homebrew formula recipes, and embeds 43 exact source archives
totaling 290,777,483 bytes. It reports `passed`, `release_ready: true`, and no
blockers. The 287,122,122-byte preflight archive has SHA-256
`e0de8d6babd75946d4ebea0a6d7d5e82714353a08e4da7d6ed7ca421bde96873`
and is bound to application tree
`42f35959eb4b24c63835ef9f08a328f36f85a78a3cf362d9acc606890a8c194e`
and bundle manifest
`b815834985bbe3b8fab7b6ffed17955431484ccd0d5ee276e60cddb49ae9e647`.

The unsigned DMG was then rebuilt from that exact application and independently
mounted read-only for final review. The 72,305,879-byte image has SHA-256
`d8b924230f9b3e9c05430a5852d3fa3b5e5fd8e9241e79c4fc2e654a28156488`.
Its 3,823-file application, 41-package embedded runtime, authenticated sidecar
handshake, and parent-EOF shutdown all pass. The mounted application tree and
runtime tree remain exactly
`42f35959eb4b24c63835ef9f08a328f36f85a78a3cf362d9acc606890a8c194e`
and `23adac429b1b7a5ae1dc943b8c8c53c3b5ad7f36001e2be8e8a55a50b59531b4`.
Strict signature verification exits nonzero with the expected
unsigned-local-proof classification; no signing credential was accessed.

That local signature classification proved too weak in the first isolated
macOS workspace. The exact DMG hash matched after transfer and its application
copied byte-for-byte, but LaunchServices refused the app because Tauri's
no-sign output retained a linker signature without an outer resource seal.
The builder now applies a final ad-hoc bundle seal only after Tauri has placed
all resources. Review requires the exact application identifier, no team,
sealed resources, and successful strict deep verification; an arbitrary
signature failure is no longer accepted as proof of an unsigned lane.

The first launch after that repair exposed a second final-composition bug. The
outer Tauri response used camel case while its nested baseline-pack identity
still serialized the internal snake-case record. React correctly rejected the
incompatible value. A dedicated camel-case wire type now converts that nested
identity without changing the Python ready/handshake or JSON-manifest
contracts, and a Rust regression test checks the exact serialized field names.

The final rebuilt local candidate is a 72,482,659-byte DMG with SHA-256
`9d6a88b6c35f29a177dfb35a00f7f4d70e5d55ebd43f081e9cda5ec2a81b9780`.
Its 3,824-file, 190,788,604-byte application tree is
`325beebd7be4b98921082fd209c0ab9493ff3808d490d22e00a3747dcfcada2f`;
the runtime tree remains
`23adac429b1b7a5ae1dc943b8c8c53c3b5ad7f36001e2be8e8a55a50b59531b4`.
In the isolated guest, the image hash matched, mounted read-only, copied
without a byte difference, and passed strict deep installed verification. The
app reached the real empty-home product screen. A second launch retained the
same process, and normal terminate/relaunch produced a new working process and
window. Native accessibility exposed the application and window but not the
WebView contents, so the ordinary create-library/OCR product workflow remains
assigned to the deterministic packaged acceptance harness rather than brittle
coordinate input.

The full exact-source compliance rerun remains release-ready with zero
blockers, all 30 nested libraries reconciled, and 43 source archives totaling
290,777,483 bytes. Its 287,122,136-byte archive has SHA-256
`bcc9ee7aeb8d21d077c2c1c3a00fd6d1983933884769942fe493873cd32bf3be`
and is bound to the final application tree above. No signing credential,
remote, tag, notarization service, or publication surface was accessed.

The first deterministic product-workflow pass then found a release-blocking
fresh-library gap before the packaged harness could honestly claim usability:
native creation authorized a collection and created the managed database, but
the product exposed no inventory operation, so the workspace remained empty
unless the maintainer left the app and used the CLI. The backend half of that
gap is now closed through the existing durable execution boundary rather than
a Tauri-owned or ephemeral background task. Database schema 4 adds an explicit
inventory job kind while preserving extraction identities and history. An
inventory request coalesces in the shared queue, records its generation/run
identity before scanning, emits bounded progress, accepts cancellation, and
publishes through the atomic inactive-generation switch. Recovery promotes a
generation published just before a crash and marks an abandoned building
generation failed while retaining the prior active catalog. Focused
persistence, inventory, scheduler/recovery, authenticated API, contract-drift,
Ruff, and Pyright gates pass. React now queues the ordinary incremental scan
after native creation and actual collection changes, offers incremental and
confirmed full-hash settings actions, refreshes workspace consumers after
completion, and renders inventory safely in shared library activity. The
TypeScript, 35-test component, and production-build gates pass. The packaged
workflow harness remains the next checkpoint.

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
