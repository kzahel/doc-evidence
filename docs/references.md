# References

## Reference Policy

Use sibling projects and external implementations to understand proven
boundaries, validation approaches, and failure modes. Do not copy code
mechanically or allow another product's domain model to dictate
`doc-evidence` architecture.

When a reference materially shapes a tactical, record the exact document or
source path, inspected revision, behavior adopted, and intentional difference.
Private documents and extracted private content are never reference fixtures
for this generic repository.

The continuing survey of adjacent document managers, research workbenches,
investigative and e-discovery systems, tax-workpaper products, and document
extraction platforms is maintained in
[Product landscape and use cases](topics/product-landscape-and-use-cases.md).
That topic records both verified public product behavior and explicit
uncertainty when a remembered product cannot be identified reliably.

## atpiano: Direct Application-Architecture Sibling

Repository: [kzahel/atpiano](https://github.com/kzahel/atpiano)  
Normal local checkout: `~/code/atpiano`  
Revision inspected for the initial application plan:
`87b77e9b0679f770a5f55e69546c7a1cb72fde46`

`atpiano` is the closest existing sibling because it has a shared React
application, Python domain/application core, local FastAPI composition,
generated TypeScript contracts, SQLite-backed features, a web/hosted path,
and a reviewed Tauri/Python-sidecar proof.

Read these before implementing the corresponding `doc-evidence` boundary:

- [Contracts and structure](https://github.com/kzahel/atpiano/blob/87b77e9b0679f770a5f55e69546c7a1cb72fde46/docs/tactical/015-contracts-and-structure.md)
  — Pydantic ownership, generated OpenAPI/TypeScript, checked drift, and a
  hand-owned frontend runtime interface.
- [Shared React application](https://github.com/kzahel/atpiano/blob/87b77e9b0679f770a5f55e69546c7a1cb72fde46/docs/tactical/016-shared-react-application.md)
  — React/Vite composition, TanStack Query versus Zustand ownership, fixture
  and local runtime adapters, and no transport knowledge in components.
- [Framework-independent Python core](https://github.com/kzahel/atpiano/blob/87b77e9b0679f770a5f55e69546c7a1cb72fde46/docs/tactical/017-python-application-core.md)
  — inward application services and thin filesystem, SQLite, HTTP, CLI, and
  worker adapters.
- [Durable worker isolation](https://github.com/kzahel/atpiano/blob/87b77e9b0679f770a5f55e69546c7a1cb72fde46/docs/tactical/022-durable-capture-worker-isolation.md)
  — bounded scheduler state, spawned worker isolation, prompt cancellation
  boundaries, explicit interruption, and restart-visible recovery. Tactical
  001 adopts those failure lessons for discrete document extraction jobs, not
  the sibling's streaming audio horizons or model lanes.
- [Early Tauri sidecar boundary](https://github.com/kzahel/atpiano/blob/87b77e9b0679f770a5f55e69546c7a1cb72fde46/docs/tactical/030-early-tauri-sidecar-boundary.md)
  — ephemeral loopback port, launch secret, exact-origin policy, authenticated
  handshake, thin Rust lifecycle ownership, and Python sidecar supervision.
- [Cross-platform artifact export](https://github.com/kzahel/atpiano/blob/87b77e9b0679f770a5f55e69546c7a1cb72fde46/docs/tactical/032-cross-platform-artifact-export.md)
  — streaming large authorized artifacts without platform branches in product
  components.
- [SQLite family authentication](https://github.com/kzahel/atpiano/blob/87b77e9b0679f770a5f55e69546c7a1cb72fde46/docs/tactical/033-sqlite-family-authentication.md)
  and [home-hosted family sharing](https://github.com/kzahel/atpiano/blob/87b77e9b0679f770a5f55e69546c7a1cb72fde46/docs/topics/home-hosted-family-sharing.md)
  — SQLAlchemy/Alembic migration precedent and a bounded local-hosted
  composition. These are later references, not first-slice scope.

The current `doc-evidence` application direction adopts the separation of
contracts, application services, runtime provider, and adapters. It does not
adopt the audio-session model, family authentication, model lifecycle, or
hosted deployment requirements.

For Tactical 001's supervised-attempt implementation, revision
`87b77e9b0679f770a5f55e69546c7a1cb72fde46` was inspected directly at
`docs/tactical/017-python-application-core.md`,
`docs/tactical/022-durable-capture-worker-isolation.md`,
`docs/tactical/032-cross-platform-artifact-export.md`,
`src/atpiano/model_worker.py`, `src/atpiano/corrected_export.py`, and
`src/atpiano/adapters/local_storage.py`. Adopted lessons are an inward
application boundary, spawned-worker isolation, bounded diagnostics,
cancellation that owns descendant processes, and fsync-backed atomic
publication. `doc-evidence` intentionally uses one discrete process group per
document/extractor attempt and a same-filesystem content-addressed rename; it
does not adopt streaming audio horizons, a long-lived model lane, or the
sibling's export destination model.

For Tactical 002's macOS desktop plan, the same pinned revision was inspected
at `docs/tactical/030-early-tauri-sidecar-boundary.md`,
`app/src-tauri/tauri.conf.json`, `app/src-tauri/src/lib.rs`,
`app/src/runtime/desktop-runtime.ts`, `src/atpiano/desktop.py`,
`src/atpiano/desktop_sidecar.py`, and `scripts/build-atpiano-desktop`. Adopted
lessons are a thin Tauri lifecycle/security shell, bounded ready and handshake
records, isolated standalone Python, exact-origin loopback authentication,
outside-repository execution, transitive native-library audit, final-byte
inventory, and complete child cleanup. Doc Evidence intentionally adds a
second Rust/Python-only credential for native folder authorization, packages a
small document-tool pack instead of ML transcription models, and defers all
heavy extractor packs.

## Yep Anywhere: Signed macOS Release Reference

Repository: [kzahel/yepanywhere](https://github.com/kzahel/yepanywhere)

Normal local checkout: `~/code/yepanywhere`

Revision inspected for Tactical 002:
`2610c24ad2c5abc3b6979a6913b0d5908404e975`

Yep Anywhere is the primary precedent for nested macOS signing and validation
of the application users actually receive. Inspect these exact files before
implementing or changing the Doc Evidence release lane:

- `topics/desktop-v0.md` — durable distribution, final-app smoke, data
  preservation, updater, and failure contracts;
- `.github/workflows/desktop-ci.yml` — tagged-release credential gates,
  temporary keychain and notarization setup, safe secret injection, explicit
  nested Mach-O signing, bounded Tauri/DMG retry, finalization, and
  `latest.json` validation;
- `scripts/release-desktop.sh` and `scripts/set-desktop-version.sh` — clean-tree
  version, changelog, commit, and tag convention;
- `packages/desktop/README.md` — local unsigned build lane versus signed
  release behavior and final signed-application runtime smoke;
- `docs/tactical/067-v0-desktop-baseline.md` — implementation and validation
  record for the stable distribution contract; and
- `docs/testing/desktop-release-qa-log.md` — checks against downloaded,
  installed, notarized releases and the real updater feed.

Adopt explicit inside-out signing and immediate verification of nested native
objects before Tauri seals the outer application, final signed-app smoke before
upload, fail-closed tagged credential gates, phase-aware diagnostics, and
installed-release QA. Doc Evidence must enumerate all Mach-O objects in its
Python and OCR runtime rather than copying Yep Anywhere's `.node`-only scan or
Bun-specific `allow-jit` entitlement.

## JSTorrent: Desktop Release and Publication Reference

Repository: [kzahel/jstorrent](https://github.com/kzahel/jstorrent)

Normal local checkout: `~/code/jstorrent`

Revision inspected for Tactical 002:
`9895410beeed6aff554053769bd006a3fbd373ef`

JSTorrent is the primary precedent for the ordinary tag-to-release mechanics:

- `docs/topics/releases.md` — current release map, preflight, recovery, and
  ownership of the Tauri release path;
- `scripts/release-tauri-app.sh` — clean-tree version/changelog commit, push,
  and tag entry point;
- `.github/workflows/tauri-app-ci.yml` — signing/notarization, Tauri release
  artifacts, updater output, `latest.json` validation, SHA-256 publication,
  and release download-table finalization;
- `desktop/README.md` — developer and release entry points; and
- `desktop/tauri-app/src/updater.ts` — installed-client updater behavior.

Adopt the synchronized version/tag convention, signed updater metadata,
release finalization, checksums, and explicit recovery rules. The first Doc
Evidence signed distribution targets macOS arm64 and Windows x86_64 and does
not copy JSTorrent's torrent sidecars, native-messaging host, extra platform
installers, or product update policy mechanically.

## Desktop Release Kit: Cross-Platform Release Reference

Repository: `kzahel/desktop-release-kit`

Normal local checkout: `~/code/desktop-release-kit`

Accepted public revision inspected for Tactical 003:
`32d7730556ff2cc92221293cf19d1c07201c0a78`

Desktop Release Kit is the primary precedent for the shared updater/feed
contract and for one signed release campaign spanning macOS and Windows. The
canary proves the infrastructure; Doc Evidence remains responsible for its own
application lifecycle, artifacts, updater key, route, repository, UI, and
acceptance.

Inspect these exact sources before implementing or changing Tactical 003's
release lane:

- `contract/desktop-update-v1.md` — platform identifiers, signed manifest
  shape, asset/signature requirements, cache behavior, failure contracts, and
  the distinction between release and product ownership;
- `.github/workflows/desktop.yml` — target matrix, signing/notarization,
  Authenticode, draft-release, updater asset, and finalization flow;
- `.github/scripts/validate-release.mjs` and its tests — exact target, version,
  asset, signature, checksum, and unexpected-entry validation;
- `.github/scripts/write-release-checksums.mjs` and its tests — deterministic
  checksum publication;
- `src/updater/` — shared policy, scheduling, and state precedent without
  requiring Doc Evidence to copy its UI mechanically;
- `docs/canary-testbed-runbook.md` — installed-candidate and old-to-new guest
  rehearsal; and
- `docs/evidence/desktop-v0.1.0-to-v0.1.1.md` — completed signed canary evidence
  across the supported contract.

Adopt `desktop-update-v1`, exact platform coverage, a draft-first release,
fail-closed finalization, signed updater metadata, and validation of downloaded
artifacts. Intentional differences are the Doc Evidence product identity, a
new per-application updater key/route, only `darwin-aarch64` and
`windows-x86_64` in the first feed, its standalone Python/extractor pack, and
its stricter source-immutability and descendant-cleanup gates. Machine Control,
not release-kit code, owns the guest-control mechanism.

## Machine Control: Desktop Testbed Reference

Repository: `kzahel/machine-control`

Normal local checkout: `~/code/machine-control`

Accepted public revision inspected for Tactical 003:
`2574469422a6859c80c65022351135d435fc199e`

Machine Control is the public source for cross-platform machine readiness,
workspace safety, guest execution, application lifecycle, semantic native UI,
capture, and input behavior. Private dotfiles may choose concrete targets at
runtime; those identities and connection details never enter this repository.

The planning inspection covered:

- `topics/unified-desktop-client.md` — the common target, workspace, desktop,
  OS, and testbed command surface;
- `topics/target-lifecycle-and-readiness.md` — readiness, startup, ownership,
  and safe-shutdown semantics;
- `topics/vm-workspaces-and-storage-policy.md` — guarded base, candidate,
  disposable/isolated workspace, acquire/release, and cleanup contracts;
- `platforms/macos/README.md` and
  `platforms/macos/skills/drive-macvm/SKILL.md` — Tart/macOS guest execution,
  native AX/resident/capture/input facilities, candidate workspaces, and
  Gatekeeper/installer/admin-flow testing;
- `platforms/windows/README.md` and
  `platforms/windows/skills/drive-winvm/SKILL.md` — UTM/QEMU Windows 11 guest
  execution, WinApp semantic UI, target-native resident/capture/input,
  candidate workspaces, and safe shutdown; and
- the accepted macOS/Windows common-client conformance and workspace evidence
  referenced by those topics.

Use deterministic application and packaged-runtime harnesses for React product
behavior. Use Machine Control where installed/native behavior matters:
installer and trust UI, native folder dialogs, focus and single instance,
sidecar lifecycle, updater restart, uninstall preservation, and final capture.
Tauri WebView accessibility may expose only the outer frame on Windows; that
is not a reason to substitute screen coordinates for product-DOM tests.

The read-only planning check on 2026-08-23 found the macOS target available
with persistent, candidate, and isolated workspace capabilities. The private
Windows target identity did not resolve, so its readiness and workspace gates
were unavailable. Tactical 003 begins by repairing or re-pinning that private
inventory and proving a disposable/candidate acquire/release cycle. This is a
current environment fact, not a limitation of the accepted Windows platform.
Do not commit the resolved identity or mutate a guarded base to bypass the
gate.

## Canonical Desktop-Signing Operations Runbook

Repository: `kzahel/dotfiles`

Normal local checkout: `~/code/dotfiles`

Revision inspected for Tactical 002:
`80546b0420f72156bee13660c065224a7b6d3542`

The canonical operational sources are:

- `runbooks/desktop-code-signing.md` — shared versus per-application
  credentials, source locations outside repositories, exact GitHub Actions
  secret names, setup and verification sequence, expiries, runner choice, and
  failure signatures; and
- `runbooks/validate-signing-secrets.sh` — fail-fast local validation followed
  by optional GitHub secret provisioning only when every credential passes.

Use that runbook when setting up Doc Evidence. Override the target repository,
desktop directory, and newly generated per-application Tauri updater key; do
not reuse another application's updater key. Secret values, credential files,
passwords, and private material remain outside this repository and must not be
copied into documentation, logs, manifests, CI arguments, or execution
evidence. If the runbook changes before implementation, inspect and pin its
then-current revision instead of relying on this summary.

## Extractor Spatial-Output References

The spatial capability inventory in
[Spatial provenance and regional OCR](topics/spatial-provenance-and-regional-ocr.md)
was checked on 2026-08-01 against the installed tools and these primary
references:

- [Tesseract command-line output formats](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html)
  for TSV hierarchy, word rectangles and confidence, hOCR, and box output;
- [Poppler `pdftotext` manual](https://manpages.debian.org/testing/poppler-utils/pdftotext.1.en.html)
  for word/layout bounding boxes, TSV, and page-box behavior;
- [Docling document-model reference](https://docling-project.github.io/docling/reference/docling_document/)
  for item provenance, bounding boxes, character spans, origins, and page
  geometry;
- [Marker](https://github.com/datalab-to/marker) for JSON block and table-cell
  boxes and optional retained OCR characters; and
- [OCRmyPDF cookbook](https://ocrmypdf.readthedocs.io/en/latest/cookbook.html)
  and [advanced documentation](https://ocrmypdf.readthedocs.io/en/stable/advanced.html)
  for the text-only sidecar, invisible text layer, renderer choices, and
  preprocessing transforms.

The adopted lesson is to normalize these different outputs into explicit
run-bound coordinate spaces and spans while preserving the raw artifacts. The
project does not assume that boxes measured on an OCR-derived, deskewed page
align directly with the immutable source page, and does not make the external
tool formats its public API.

## Documentation-Structure Siblings

The documentation roles and tactical numbering conventions were compared with
the normal local checkouts of:

- `~/code/rstorrent`;
- `~/code/yepanywhere`; and
- `~/code/mclone`.

They are style and process references, not runtime dependencies. The adopted
common vocabulary is:

- durable architecture/reference docs for long-lived system shape;
- `docs/topics/` for living focused truth; and
- `docs/tactical/` for numbered bounded implementation slices and execution
  records.
