# Changelog

All notable user-facing changes to Doc Evidence are recorded here. Desktop
release tags use the form `desktop-vMAJOR.MINOR.PATCH`.

## [0.5.1] - 2026-08-27

- Prevent Windows extraction workers from inheriting the sidecar's parent-EOF
  pipe, which could stall the worker launcher before Python initialization.
- Exercise the complete signed Windows packaged workflow during every release
  build, including OCR, rendering, search, restart, long-path, and source-hash
  preservation checks.

## [0.5.0] - 2026-08-27

- Add the first paired macOS arm64 and Windows x86_64 signed desktop release
  pipeline.
- Add signed in-application update checks while preserving the local-first,
  source-read-only product boundary.
- Package the standalone Python runtime and baseline Poppler, Tesseract, and
  OCRmyPDF extractor pack for both supported platforms.
- Publish exact checksums, updater metadata, and dependency compliance
  evidence with each desktop release.
