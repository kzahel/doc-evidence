# Maintainer Feature Requests

Topic: maintainer-feature-requests

**Status:** Focused review-workspace revision in progress; UI-triggered
extraction execution remains the next distinct product discussion.

## Purpose

This topic records concrete maintainer requests that should survive chat
compaction and inform the next bounded tactical. It is an input to planning,
not authorization to expand Tactical 000 into write-enabled pipeline work.

Requests remain here after implementation so the original need, accepted
behavior, and implementation status remain traceable.

## Open Requests

### Bounded focused, stacked, and comparison review modes

**Status:** IN PROGRESS — approved as a final Tactical 000 interaction
revision.

The source page must remain useful context while reviewing several extractor
representations. Full extraction bodies should no longer form one unbounded
document-height feed by default.

The approved interaction is:

- bound the source/extraction review area to the useful viewport and give each
  side its own overflow behavior;
- make Focused the default, with a compact representation selector and one
  complete extraction body;
- retain the current all-results flow as an explicit Stacked mode inside the
  extraction pane;
- move pairwise comparison into the extraction pane as a Compare mode instead
  of placing it beneath every representation;
- offer deterministic diff and raw two-up comparison views;
- place raw outputs side by side when space permits and stack them when it
  does not; and
- keep text-presentation controls effective in every mode.

### Prominent source-page navigation

**Status:** IN PROGRESS — approved as a final Tactical 000 interaction
revision.

Page navigation belongs directly above the rendered source page. Previous and
next controls must use prominent visible glyphs and labels, while the current
page remains directly typeable and clearly shows the total page count. The
control should stay available while the source pane scrolls.

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
