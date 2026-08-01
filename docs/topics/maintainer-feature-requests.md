# Maintainer Feature Requests

Topic: maintainer-feature-requests

**Status:** Review-workspace revisions implemented; UI-triggered extraction
execution is approved and planned in Tactical 001 but not yet implemented.

## Purpose

This topic records concrete maintainer requests that should survive chat
compaction and inform the next bounded tactical. It is an input to planning,
not authorization to expand Tactical 000 into write-enabled pipeline work.

Requests remain here after implementation so the original need, accepted
behavior, and implementation status remain traceable.

## Open Requests

### Trigger and monitor extraction from the application

**Status:** PLANNED — approved in
[Tactical 001](../tactical/001-durable-extraction-jobs.md).

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

**Status:** CLARIFIED; execution remains open above.

The current ordinary inventory creates the native Poppler extraction only.
The four-extractor calibration coverage was run only for the bounded benchmark
set. Image-only PDFs can therefore have an empty native-text result and no OCR
representation until OCR has been explicitly run and cached. The current UI
now labels cached-run coverage and this image-only limitation.

## Planning Relationships

- [Application platform](application-platform.md) owns job orchestration,
  application state, and frontend/backend boundaries.
- [Comparison and review workspace](comparison-review-workspace.md) owns the
  page-centered comparison interaction and extraction presentation.
- [Tactical 000](../tactical/000-read-only-library-comparison.md) remains the
  read-only implementation record and does not authorize UI-triggered jobs.

After live review, the maintainer selected extraction execution before durable
review events on 2026-08-01. Its job-state, cache, cancellation, security, and
recovery contracts now live in
[Durable job architecture](job-architecture.md), and Tactical 001 defines
their first end-to-end implementation. This topic remains the record of the
originating request until acceptance evidence closes it.
