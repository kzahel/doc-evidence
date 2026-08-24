# Implementation Tactical Documents

Bounded implementation plans and execution records live here.

Use zero-padded numeric filenames:

```text
000-first-slice.md
001-next-slice.md
```

Keep one coherent implementation slice per tactical. It should be small enough
to have one falsifiable stopping condition while still producing an end-to-end
result.

Create a tactical before substantial implementation. It should normally
state:

- status;
- motivation and user-visible outcome;
- dependencies and references;
- scope and staged implementation direction;
- non-goals;
- contracts, ownership, and invariants;
- exact automated and manual validation;
- rollback or compatibility boundaries; and
- the stopping condition and next-slice boundary.

Update a tactical as implementation reveals new facts. When complete, record
what landed, what validation actually ran, known gaps, and the recommended
next slice. Completed tacticals remain as execution records; living direction
belongs in `../topics/`.

An implementation-ready tactical should settle routine direction so work does
not repeatedly stop for internal naming or module-layout choices. Stop for
human direction when evidence requires a materially different product
behavior, durable-data contract, security or network posture, destructive
action, new external service, or significant expansion beyond the tactical.

## Current Tacticals

- [000 — Read-only library and extractor comparison](000-read-only-library-comparison.md)
  — implemented first application walking skeleton awaiting explicit
  maintainer interaction acceptance: Python API, generated
  TypeScript client, React library/document workspace, exact output grouping,
  and word/numeric diff over existing cached artifacts.
- [001 — Durable extraction jobs and operational UI](001-durable-extraction-jobs.md)
  — implementation complete with automated, isolated-browser, and authorized
  private-library gates passing; explicit maintainer interaction acceptance
  remains. It provides the desktop library/app-home foundation, unified
  per-library SQLite state, durable jobs and attempts, supervised subprocesses,
  atomic artifact publication, recovery, document execution controls,
  activity center, bounded batch, and concurrency/debug UI.
- [002 — macOS Tauri desktop distribution](002-macos-tauri-desktop-application.md)
  — macOS arm64 unsigned foundation implemented and validated: Apache-2.0,
  thin Tauri shell, standalone Python sidecar, native library authorization,
  small Ghostscript-free baseline pack, strict final-byte audits, unsigned DMG,
  and fail-closed compliance preflight. Its planned macOS-only signed lane is
  superseded by Tactical 003.
- [003 — macOS and Windows signed desktop release](003-macos-windows-signed-desktop-release.md)
  — local implementation and validation authorized on 2026-08-24; external
  credentials, signing, tags, remotes, and publication remain unauthorized.
  The first Windows Machine Control disposable-workspace gate passes, with an
  ARM64 guest available for target-native Windows and x86_64-emulation work;
  final native-x86_64 acceptance remains required. The tactical closes
  compliance, makes the desktop boundary platform-aware, adds the Windows
  x86_64 runtime/pack/NSIS path, and defines a two-target signed updater/release
  gate. Linux and heavyweight extractor packs remain later tacticals.
