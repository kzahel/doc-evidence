# Comparison and Review Workspace

Topic: comparison-review-workspace

**Status:** Product direction accepted; generated Phase 2 calibration HTML is
an interim artifact; Tactical 000 is proposed.

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
- Current comparison flags are metrics, not user-navigable diff artifacts.
- No durable workspace review database exists.
- No generic classification contract identifies hybrid image-background plus
  native-text pages.
- Calibration has too few human-reviewed pages to select extractor roles by
  document class.

## Recommended Next Work

Use Tactical 000 to make equivalent outputs and numeric differences obvious
on the existing private calibration set. Update this topic with observed UX
failures before designing persistent review state.

