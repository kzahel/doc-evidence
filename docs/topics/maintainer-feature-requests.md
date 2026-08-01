# Maintainer Feature Requests

Topic: maintainer-feature-requests

**Status:** Review-workspace revisions, desktop library management, and
UI-triggered durable extraction operations are implemented. Tactical 001's
automated and private-integration gates pass; explicit maintainer interaction
acceptance remains.

## Purpose

This topic records concrete maintainer requests that should survive chat
compaction and inform the next bounded tactical. It is an input to planning,
not authorization to expand Tactical 000 into write-enabled pipeline work.

Requests remain here after implementation so the original need, accepted
behavior, and implementation status remain traceable.

## Open Requests

### Link extracted text to page regions and improve disputed regions

**Status:** RESEARCHED; accepted product direction, but no implementation
tactical has been authorized.

Selecting OCR or extracted text should highlight its genuine source rectangle,
and selecting a page rectangle should focus the corresponding extracted text.
Comparison differences should be able to zoom to their implicated regions. A
user or bounded automatic policy may then request higher-resolution or varied
OCR for that region, preserving every attempt and its coordinate transform.

Regional OCR results remain provisional machine candidates. They do not
overwrite the full-page extraction or source, and a machine-preferred result
does not become human-confirmed until an explicit review event says so.

[Spatial provenance and regional OCR](spatial-provenance-and-regional-ocr.md)
records the verified extractor capabilities, proposed spatial contracts,
bidirectional interaction, regional-job identity, safeguards, validation, and
possible implementation slices.

### Remember libraries without repeated command-line configuration

**Status:** IMPLEMENTED in
[Tactical 001](../tactical/001-durable-extraction-jobs.md); final acceptance in
progress.

The first-class product should behave like a desktop application rather than
require a configuration path at every launch. It should:

- show known libraries and remember a default or last-opened library;
- keep one SQLite database and artifact store per library;
- let one library contain multiple explicit read-only collections;
- adopt the existing external case configuration and artifact store without
  moving private documents or recomputing successful artifacts;
- avoid duplicate indexing when a requested parent collection covers an
  existing child collection by offering a deliberate replace/expand flow; and
- place all app-owned registry and managed-library state beneath the platform
  application-data directory.

`DOC_EVIDENCE_HOME` must override that complete app-owned data root for tests,
standalone development, and portable isolated runs. External source collection
paths remain external and unchanged. Automated tests and background Playwright
validation must use a fresh temporary override so they cannot disturb the
maintainer's normal library registry or stores.

### Trigger and monitor extraction from the application

**Status:** IMPLEMENTED in
[Tactical 001](../tactical/001-durable-extraction-jobs.md); final acceptance in
progress.

The application should let the user request missing extraction work and
revisit prior work without leaving the document view.

The interaction should support:

- running a selected extractor for the current document;
- running an appropriate OCR extractor for an image-only PDF or image;
- optionally running a bounded batch such as all image-only documents that
  lack OCR;
- visible queued, running, succeeded, failed, cancelled, and cached states;
- retrying a failed attempt;
- cancelling work when the underlying adapter supports safe cancellation;
- distinguishing **reuse/rerun with the same identity**, which should normally
  return the existing cache entry, from **force a fresh attempt**; and
- displaying the extractor name and version, configuration identity, output
  schema version, warnings, timing, and resulting run identity.

Opening a document must continue to be passive. Heavy extraction should start
only from an explicit user action or an explicitly configured batch policy.
Source documents remain immutable.

## Implemented or Clarified Requests

### Bounded focused, stacked, and comparison review modes

**Status:** IMPLEMENTED in `e5e3c04`.

The height-bounded source and extraction panes retain their own overflow.
Focused is the default and displays one representation selected from a compact
strip. Stacked keeps every card in the bounded extraction scroller. Compare
replaces the previous below-the-feed panel and offers deterministic Diff and
responsive Raw two-up views. Text-layout selection remains effective in every
mode.

### Prominent source-page navigation

**Status:** IMPLEMENTED in `e5e3c04`.

The sticky source toolbar now places visible Previous and Next buttons, a
directly typeable page field, and the total page count immediately above the
rendered page. Invalid direct entries revert to the current page.

### Collapsible navigation sidebar

**Status:** IMPLEMENTED in `797ddce`.

The expanded library collapses to a narrow labeled rail with an explicit
restore control. The state is session-local, keyboard accessible, expanded by
default, and becomes a compact horizontal rail at narrow widths.

### Extraction text presentation modes

**Status:** IMPLEMENTED in `797ddce`.

Auto, Reading, and Aligned modes apply to normalized output and pairwise diff
text. Reading uses a proportional font with wrapping. Aligned uses monospace,
preserves whitespace, disables wrapping, and exposes horizontal scrolling.
Auto uses bounded repeated-spacing and table-delimiter signals, displays its
resolved choice and reason, and always permits a manual override.

### Resizable source and extraction panes

**Status:** IMPLEMENTED in `797ddce`.

The desktop source/output divider supports pointer dragging, arrow-key
adjustment, a bounded 28–72% source share, and Home or double-click reset to
45%. The split is session-local. The handle disappears when the evidence panes
stack at narrow widths.

### Named global typography presets

**Status:** IMPLEMENTED in `5c77220`.

The application exposes Small, Normal, and Large rather than percentages.
Normal is the default 120% scale, Small is the previous 100% default, and
Large is 130%.

### Distinct baseline and comparison selections

**Status:** IMPLEMENTED in `a067754`.

The same representation cannot be selected on both comparison sides. The
workspace disables the conflicting option, repairs identical state
defensively, and provides a direction-swap action.

### Stable content identity and path reverse mapping

**Status:** CLARIFIED and surfaced in Tactical 000.

Deep links use a SHA-256 document identity rather than a path so links survive
renames and one content identity can represent duplicate source occurrences.
The document-detail view and catalog `sources` records provide the reverse
mapping to collection and relative paths.

### Extraction coverage is not automatic execution

**Status:** IMPLEMENTED in Tactical 001; automatic inventory routing remains
separate.

The current ordinary inventory creates the native Poppler extraction only.
The four-extractor calibration coverage was run only for the bounded benchmark
set. Image-only PDFs can therefore have an empty native-text result and no OCR
representation until OCR has been explicitly run and cached. The current UI
labels exact cached-run coverage and can explicitly enqueue the registered OCR
extractor without making browsing active.

## Planning Relationships

- [Application platform](application-platform.md) owns job orchestration,
  application state, and frontend/backend boundaries.
- [Library management](library-management.md) owns app-home discovery, stable
  library identity, per-library persistence, explicit collections, and
  collection-scope transitions.
- [Comparison and review workspace](comparison-review-workspace.md) owns the
  page-centered comparison interaction and extraction presentation.
- [Spatial provenance and regional OCR](spatial-provenance-and-regional-ocr.md)
  owns page-region contracts, overlay interaction, spatial diffs, and bounded
  targeted extraction.
- [Tactical 000](../tactical/000-read-only-library-comparison.md) remains the
  read-only implementation record and does not authorize UI-triggered jobs.

After live review, the maintainer selected extraction execution before durable
review events on 2026-08-01. Its job-state, cache, cancellation, security, and
recovery contracts now live in
[Durable job architecture](job-architecture.md), and Tactical 001 defines
their first end-to-end implementation. Its machine-verifiable gates now pass;
this topic remains the record of the originating request until explicit
maintainer interaction acceptance closes it.
