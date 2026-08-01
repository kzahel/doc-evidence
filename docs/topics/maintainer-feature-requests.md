# Maintainer Feature Requests

Topic: maintainer-feature-requests

**Status:** Layout requests implemented; UI-triggered extraction execution is
the remaining open request from the first live review.

## Purpose

This topic records concrete maintainer requests that should survive chat
compaction and inform the next bounded tactical. It is an input to planning,
not authorization to expand Tactical 000 into write-enabled pipeline work.

Requests remain here after implementation so the original need, accepted
behavior, and implementation status remain traceable.

## Open Requests

### Trigger and monitor extraction from the application

**Status:** OPEN — requires a new tactical.

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

The next tactical should be chosen after live review. Extraction execution can
be a focused tactical before durable review events if it is now the higher
priority, but its job-state, cache, cancellation, and security contracts must
be designed explicitly.
