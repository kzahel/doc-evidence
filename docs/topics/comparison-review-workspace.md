# Comparison and Review Workspace

Topic: comparison-review-workspace

**Status:** Tactical 000 read-only comparison workspace implemented and
validated; awaiting maintainer live acceptance.

## Scope

This topic owns the continuing user experience and contracts for inspecting
document representations, comparing extractor runs, focusing human attention,
and recording review decisions without confusing agreement with truth.

It does not own extractor implementation, domain-specific field schemas, or
downstream tax and accounting conclusions.

## Representation Vocabulary

Every displayed result must identify which layer it represents:

1. immutable source bytes;
2. rendered visual page;
3. native file primitives such as text objects and coordinates;
4. inferred OCR/layout blocks, tables, and reading order;
5. normalized page or block text;
6. candidate semantic observations; and
7. reviewed evidence decisions.

The current calibration page displays normalized page text. It does not map
form boxes, labels, or regions to semantic fields. The first-class interface
must say that explicitly.

## Current Problems in the Generated Review Page

- It renders every extractor as a separate large column even when outputs are
  identical.
- It does not identify whether output came from native text, OCR, a layout
  parser, or a semantic adapter.
- It hides complete output inside an understated fixed-height scroll area.
- It repeats broad disagreement labels on each extractor without showing the
  exact pair or changed tokens.
- It asks for ratings before explaining the page scope and representation.
- It flattens layout-aware output, discarding or hiding useful page regions.
- It does not distinguish text completeness from correctness of captured
  strings clearly enough.

The HTML remains useful as a portable benchmark artifact and regression
surface. It is not the product UI.

## Accepted Interaction Direction

### Equivalence first

- Group exact identical normalized page outputs.
- Name every contributing run in the group.
- Say “identical output” directly instead of asking for manual comparison.
- Never treat an equivalence group as evidence of correctness.

Later comparison versions may add visibly labeled whitespace- or
normalization-equivalent groups. Exact equality comes first.

### Pairwise comparison

- Let the user choose a baseline group and one comparison group.
- Default to differences only, with full output available on demand.
- Provide block, line, word/token, numeric, and character detail as the data
  supports it.
- Identify additions, omissions, substitutions, and reordering separately.
- Keep numeric discrepancies visible and navigable even inside otherwise
  noisy text.
- Preserve the exact input run IDs, normalization version, diff version, and
  options in every computed comparison.

### Page-centered evidence

- Keep the rendered source page visible beside extraction output.
- Show selected page and total document page count.
- Label raw versus normalized output.
- Show engine name, category, exact version, configuration, warnings, and
  timing.
- Add coordinate overlays only when provenance is genuinely available; do not
  fabricate locations from plain text.

### Review semantics

- Sparse verified assertions should appear as focused checks, not hidden
  benchmark metadata.
- Review state is purpose-specific and separate from regenerable output.
- Accept, reject, correct, defer/unresolved, and supersede remain distinct.
- A correction retains the original output and records its replacement.
- Ratings or decisions must state what was reviewed: transcription,
  numerical fidelity, reading order, structure, or a semantic candidate.

## Diff Contract Direction

The backend computes versioned comparison data. The frontend owns selection,
navigation, expansion, and presentation.

The first version should provide:

- exact text equivalence groups;
- deterministic token alignment;
- equal, insert, delete, and replace segments;
- numeric tokens carried as explicit typed segments;
- source and comparison run identities;
- page identity and one-based page number; and
- `comparison_algorithm_version`.

Spatial and reading-order diffs follow when normalized block/region contracts
retain enough information.

## Tactical Boundaries

[Tactical 000](../tactical/000-read-only-library-comparison.md) owns the first
read-only library and diff slice. It ends before persistent review writes,
pipeline execution, tags, broad spatial overlays, and semantic field review.

The expected next bounded tactical adds durable review events and portable
review export after the first interaction model has been used on real cached
documents.

## Known Gaps

- Current normalized Docling and Marker pages flatten block provenance.
- No durable workspace review database exists.
- No generic classification contract identifies hybrid image-background plus
  native-text pages.
- Calibration has too few human-reviewed pages to select extractor roles by
  document class.
- The `SequenceMatcher` alignment is directional: swapping baseline and
  comparison can change the number of numeric discrepancy segments even when
  the same two texts are selected. The UI presents a directional comparison,
  not a symmetric distance metric.
- Several historical runs of the same extractor/version can appear as
  similarly named representations when their output or failure status differs;
  cache identity and status disambiguate them, but the compact labels can be
  improved.

## Implementation Evidence

The first-class workspace now keeps a rendered source page beside explicitly
labeled normalized extractor output, collapses exact output, identifies every
contributing run, exposes raw artifacts in a sandboxed preview, and computes a
versioned word/numeric diff with differences-only/full modes and numeric
navigation.

All seven pages in the private calibration set loaded through this workspace.
On the known hybrid form, native Poppler and skip-existing-text OCR collapsed
as expected while Docling and Marker remained separately inspectable. These
checks establish product mechanics, not extractor correctness.

Maintainer review found that both selectors allowed the same representation,
which made the pairwise control look incoherent. The UI now disables the
opposite side's selected option, normalizes identical state defensively, and
provides an explicit direction-swap button. Representation headers also state
the cached run and unique-output counts and clarify that opening the view does
not launch missing extractors.

Image-only PDFs now receive a visible explanation that native text is empty
and OCR appears only when an OCR run has already been cached.

## Recommended Next Work

Use the [maintainer feature-request backlog](maintainer-feature-requests.md) to
finish the live interaction review and choose the next bounded slice. Current
open requests include collapsible navigation, resizable evidence panes,
proportional versus alignment-preserving extraction text modes, and explicit
extraction execution. Persistent review decisions and portable export remain
separate write-enabled work.
