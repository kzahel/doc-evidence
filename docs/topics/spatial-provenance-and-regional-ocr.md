# Spatial Provenance and Regional OCR

Topic: spatial-provenance-and-regional-ocr

**Status:** Researched and accepted as a product direction; contracts and
implementation tactical are not yet approved or implemented.

**Last researched:** 2026-08-01

## Scope

This topic owns the continuing product and engineering direction for:

- retaining page geometry supplied by text, OCR, and layout extractors;
- mapping displayed extraction text back to exact source-page regions;
- mapping page regions forward to the text and candidates they support;
- attaching spatial provenance to comparisons and candidate observations;
- focusing the review interface on local disagreements; and
- running bounded, higher-effort extraction on a disputed page region without
  replacing immutable full-page output or pretending that a machine choice is
  a reviewed fact.

The desired interaction is straightforward: selecting extracted text should
highlight where it came from on the page, and selecting or hovering a page
region should identify the corresponding extracted text. If two methods
disagree, the workspace should zoom to the implicated area, show each reading,
and optionally create a more focused OCR attempt on that area. A reviewer can
then accept, correct, reject, or defer the candidate with its source visible.

This is a living topic, not implementation authorization. A later tactical
must choose a bounded first slice, settle the proposed contracts below, and
define migration and validation gates. It must not be folded incidentally
into the Tauri packaging work: spatial provenance belongs to the shared
Python and React product, independent of its host shell.

## Why This Matters

Plain extracted text is useful for search and broad comparison, but it loses
the most important review affordance: showing why a value is believed. A
source-to-form or source-to-observation workflow needs a direct chain:

```text
provisional value or diff
  -> exact extractor span or reviewed correction
  -> page region and page representation
  -> immutable source content and extraction run
```

That chain supports the intended agent-assisted operating model. Agents can
find, compare, validate, and assemble provisional results; people can
spot-check consequential or uncertain values beside the relevant pixels
instead of manually rereading every page or trusting detached OCR text.

Spatial provenance also makes disagreement actionable. Rather than showing a
whole page because one digit differs, the application can focus on the amount,
date, checkbox, or table cell involved. It can spend extra computation only on
that bounded area and preserve all resulting alternatives for inspection.

## Current Repository Posture

Several extractors already produce enough information for a useful first
spatial layer, but the common normalization and API currently discard it.

- `tesseract_raster_adapter.py` requests both text and TSV output and preserves
  the raw `.tsv` artifact. Tesseract TSV includes hierarchical page, block,
  paragraph, line, and word identifiers plus word rectangles and confidence.
  The adapter currently normalizes only the plain text.
- `ocrmypdf_adapter.py` preserves OCRmyPDF's derived searchable PDF and text
  sidecar. It then calls `pdftotext -layout` on the derived PDF, which keeps
  approximate layout in text but no coordinates. The sidecar itself is text,
  not a geometry contract.
- `poppler.py` uses `pdftotext -layout`. The installed Poppler tool can also
  emit word boxes, layout boxes, or TSV from a PDF text layer, but the adapter
  does not currently request them.
- `structured.py` reads Docling page provenance to find page numbers but
  flattens page items into text. Docling provenance can retain page number,
  bounding box, and a character span within an item.
- The Marker normalizer traverses the block tree and flattens leaf HTML or
  text. Marker's structured output can carry block and table-cell boxes, and
  its OCR path can optionally preserve character boxes.
- `NormalizedPage` currently contains page number, text, and character counts
  only. API extractor representations expose `normalized_page_text`, and diff
  tokens carry text and change kind without source-span references.
- `schemas/observation.schema.json` already permits one optional rectangular
  region and identifies whether its coordinates are normalized, points, or
  pixels. That is a useful foothold, but it cannot yet identify the exact page
  representation, express polygons or disjoint regions, or reference the
  extractor spans that support an observation.

Consequently, the current UI is correct to avoid drawing boxes: it has no
normalized, run-bound spatial contract to consume. It must continue to avoid
inferring locations from whitespace, text order, or a string search alone.

## Verified Extractor Capabilities

The following capability inventory is based on the locally installed tools
and their official documentation. It describes possible input to a future
normalization layer, not behavior currently exposed by Doc Evidence.

| Extractor path | Spatial output available | Useful granularity | Important limitation |
| --- | --- | --- | --- |
| Poppler `pdftotext` | `-bbox`, `-bbox-layout`, and `-tsv` | word; layout mode adds blocks and lines | Locates text objects in the PDF text layer; it does not OCR missing image text |
| Tesseract | TSV, hOCR, and box outputs | word with confidence in TSV; block/line hierarchy; character boxes when requested | Coordinates refer to the raster submitted to Tesseract and require its exact dimensions and orientation |
| OCRmyPDF | aligned invisible text in a derived searchable PDF; text-only sidecar; hOCR-capable renderer/plugin boundary | normally word boxes can be recovered from the derived PDF or retained hOCR | rotation, deskew, rasterization, or other preprocessing may make derived-page coordinates differ from the immutable source page |
| Docling | item provenance with page number, bounding box, and character span | text item, block, table, cell, and other document items as supported by the conversion | item coordinates must be converted from Docling's declared origin and page geometry rather than copied as assumed top-left pixels |
| Marker | JSON block polygons/boxes, table cell boxes, and optional OCR character boxes | block and cell by default; character when configured | normalized text currently loses the block tree, and optional character retention has cost and version/config implications |

Relevant primary documentation:

- [Tesseract command-line output formats](https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html)
  documents TSV hierarchy, rectangles, confidence, and hOCR output.
- [Poppler `pdftotext` manual](https://manpages.debian.org/testing/poppler-utils/pdftotext.1.en.html)
  documents bounding-box, layout bounding-box, TSV, and crop-box modes.
- [Docling document model](https://docling-project.github.io/docling/reference/docling_document/)
  documents `ProvenanceItem`, `BoundingBox`, page geometry, and origin
  conversion.
- [Marker](https://github.com/datalab-to/marker) documents JSON blocks,
  bounding boxes, table-cell boxes, debug output, and optional retained OCR
  characters.
- [OCRmyPDF cookbook](https://ocrmypdf.readthedocs.io/en/latest/cookbook.html)
  explains the text-only sidecar, while its
  [advanced documentation](https://ocrmypdf.readthedocs.io/en/stable/advanced.html)
  describes the invisible OCR text layer, renderer choices, and transforms
  caused by preprocessing.

The versions inspected locally on 2026-08-01 were Tesseract 5.5.3, OCRmyPDF
17.8.1, Poppler 26.03.0, Docling 2.117.0 with Docling Core 2.89.0, and Marker
2.0.0. Capability identity must use the exact runtime version and settings;
these observations are not a promise that every older or future version emits
the same shape.

## Accepted Invariants

### Geometry is provenance, not decoration

A rectangle may be displayed only when it came from extractor output or from
an explicit, recorded transform of that output. The product must never invent
a location by searching for the same string on a page, estimating from line
breaks, or stretching a box over text that lacks spatial provenance.

Every region is bound to:

- the immutable source content identity;
- the exact extraction run and extractor configuration;
- a one-based page identity;
- the exact visual representation and coordinate space on which it was
  measured; and
- enough page dimensions, origin, rotation, and transform metadata to render
  it correctly.

### Sources and extractor output remain immutable

Regional OCR does not edit the source PDF, replace the OCR text layer, or
rewrite a full-page extraction. It creates another derived attempt with its
own run identity, artifacts, spatial input, result, warnings, and cost.

A human correction also does not modify extractor output. It is durable review
state that cites the original candidate and region and records a replacement.

### Evidence states remain distinct

The interface and data model must distinguish at least:

- raw extractor output;
- normalized extractor spans;
- an automatically preferred candidate;
- deterministic validation results;
- extractor agreement or disagreement;
- agent assessment;
- human-confirmed, corrected, rejected, or unresolved review state.

Higher-resolution OCR, agreement among reruns, or a clean checksum can improve
a machine proposal. None of them is human confirmation.

### Spatial contracts remain rebuildable projections

Raw tool output and a schema-versioned normalized spatial artifact remain the
inspectable source of truth for an extraction run. SQLite may project spans,
regions, and searchable associations for interactive access, but the catalog
must remain rebuildable without rerunning the extractor.

### The client receives bounded resources, never arbitrary paths

API operations identify a library, document, run, page, span, or approved
region. They do not accept a filesystem path, shell command, executable, or
unbounded pixel request from the browser. Existing loopback authentication,
origin checks, and library authorization continue to apply.

## Proposed Canonical Spatial Contract

The first contract should normalize common geometry without destroying raw
extractor-specific detail. Names below are illustrative and require approval
in an implementation tactical.

```text
CoordinateSpace
  coordinate_space_id
  document_id
  page_number
  basis: source_pdf | source_raster | derived_pdf | page_render | crop
  width
  height
  unit: points | pixels | normalized
  origin: top_left | bottom_left
  rotation_degrees
  parent_coordinate_space_id?
  transform_to_parent?
  representation_artifact?

SpatialRegion
  coordinate_space_id
  shape: rectangle | polygon
  coordinates
  normalized_top_left_box
  mapping_quality: exact | transformed | approximate

SpatialTextSpan
  spatial_span_id
  extraction_run_id
  page_number
  kind: character | word | line | block | cell
  raw_text
  normalized_text
  reading_order?
  confidence?
  regions[]
  raw_locator
  normalized_text_mapping?
```

The canonical UI coordinate convention should be top-left normalized page
coordinates:

```text
[left, top, right, bottom] where every value is within [0, 1]
```

The contract must also retain the raw coordinates, raw unit, origin, page
dimensions, and transform chain. A normalized box is convenient for rendering;
it is not enough for auditing or lossless round trips.

### Coordinate spaces and transforms

`source_pdf`, `derived_pdf`, `source_raster`, and a rendered page are not
automatically the same plane.

- Poppler boxes read from the source PDF text layer can align with a render of
  that exact source page after applying its media/crop box and rotation.
- Tesseract boxes align with the exact input raster. The artifact must retain
  its pixel dimensions and how that raster was produced from a page.
- OCRmyPDF boxes align honestly with its derived searchable PDF. If OCRmyPDF
  rotated, deskewed, or rasterized a source page, those boxes must initially be
  shown over the derived page unless a recorded invertible transform maps them
  to the source rendering.
- A regional OCR crop adds another coordinate space. Its translation, scale,
  margin, render DPI, and parent page space must be recorded so a crop word can
  be projected back to the page.

An initial UI should prefer an exact overlay on the correct derived
representation over an apparently convenient but misleading overlay on the
original. The viewer should label `source`, `derived OCR page`, `render`, and
`crop` explicitly. When a transform is approximate or unavailable, the UI
must say so and avoid exact-looking selection behavior.

### Span identity and text normalization

Stable spatial-span identity should derive from the extraction run and a raw
tool locator such as page/block/line/word indices or a block-tree path. It
should not depend only on mutable normalized character offsets.

Whitespace folding, Unicode normalization, dehyphenation, reading-order
repair, and table reconstruction can all break a naive character-offset map.
Normalization should therefore produce an explicit mapping from displayed
tokens or character ranges to one or more raw spatial-span IDs. One displayed
segment may cover several source regions, and a source region may contribute
to more than one normalized view.

Multiple regions and polygons should be allowed even if the first UI renders
only rectangles. They are needed for wrapped phrases, reordered content,
non-axis-aligned blocks, and values assembled from multiple cells. The current
observation schema's single optional rectangle should eventually evolve to a
region reference or list while retaining backward-compatible readers.

## Artifact and Persistence Shape

Each spatially capable extraction run should retain:

1. the raw tool output, such as TSV, hOCR, structured JSON, or a searchable
   derived PDF;
2. the existing normalized page text;
3. a schema-versioned normalized spatial sidecar, such as `spatial.json` or
   per-page span artifacts; and
4. manifest fields that state the spatial schema version, coordinate spaces,
   page geometry, output granularity, and whether locations are exact,
   transformed, partial, or unavailable.

The sidecar belongs to the content-addressed extraction run and follows the
same staged validation and atomic publication rules as other artifacts. A run
must not claim spatial capability simply because a raw format usually contains
boxes; publication validation should verify page bounds, finite coordinates,
declared origins, span references, and artifact hashes.

SQLite can add a rebuildable projection for:

- run/page-to-span lookup;
- span-to-region and region-to-span lookup;
- observation-to-supporting-span references;
- comparison segment-to-left/right-span references; and
- region-attempt discovery and current review projection.

Large raw geometry need not become one database row per character initially.
The first tactical should measure page-load, artifact size, query latency, and
the actual granularity needed by the interface before choosing word-level
projection, page-level JSON streaming, or a hybrid.

## API and Runtime Direction

Python-owned contracts should expose bounded resources similar to:

- spatial capabilities for an extractor run;
- the coordinate spaces and spans for one document/run/page;
- an authorized page representation or bounded rendered crop;
- the regions supporting one comparison segment or candidate observation;
- creation and status of a bounded regional extraction request; and
- durable review actions over a candidate and its region.

The OpenAPI and TypeScript contracts remain generated from Python. The
hand-owned `DocEvidenceRuntime` should expose behavioral operations such as
`getPageSpatialSpans`, `getComparisonRegions`, and
`requestRegionalExtraction`, rather than endpoint paths or local filesystem
details. React components continue to avoid Tauri and platform imports.

Page spatial data should be paged or streamed within explicit limits. Crop
requests must enforce server-owned maximum area, output dimensions, DPI,
attempt count, and source representations. A browser cannot use the endpoint
as a general local-file or arbitrary-resolution renderer.

## Bidirectional Review Interaction

### Extraction text to page

Displayed extraction output should be rendered as semantic spans associated
with spatial-span IDs. When a user selects text across one or more displayed
spans, the workspace unions their page regions, highlights them on the page,
and offers `focus source` without changing evidence state.

The selection layer must handle:

- partial words and selections that cross line or block boundaries;
- one normalized token backed by several source spans;
- duplicate text elsewhere on the page without jumping to a string match;
- spans with no geometry mixed into a selection; and
- exact, transformed, and approximate mapping labels.

### Page to extraction text

Hovering, clicking, or keyboard-focusing a genuine overlay should identify the
run, span kind, text, confidence when supplied, and corresponding location in
the displayed extraction. Overlapping runs need stable colors plus labels or
line patterns so color is not the only cue. A user should be able to isolate
one run, show agreement, or compare implicated spans without rendering all
page boxes continuously.

### Navigation and accessibility

The workspace should support:

- fit, zoom, and `focus region` actions;
- previous/next spatial disagreement, with numeric differences prioritized;
- keyboard focus between a diff segment, extraction span, and source overlay;
- accessible text describing page, region, run, and mapping quality; and
- an explicit label for the displayed visual representation and coordinate
  relationship.

The default view should remain quiet. Boxes appear for selection, focus,
comparison, or a chosen layer rather than covering the entire page in a dense
debug overlay.

## Spatial Comparison Direction

The existing deterministic text diff should remain the first alignment layer.
It can be extended so every equal, insert, delete, or replace segment carries
the left and right spatial-span IDs that produced it.

- A substitution can highlight both competing regions.
- An insertion has a region only on the side that produced text.
- An omission has no source box on the omitted side. The other side's region,
  plus nearby aligned spans, can seed a focus crop without falsely claiming a
  location for the absence.
- Reordering can be shown as linked regions when both sides retain reading
  order and block provenance.
- Numeric differences can zoom directly to the relevant word or table cell.

Spatial overlap and reading order may later improve alignment, especially for
tables and columns, but they should not silently replace the existing versioned
text comparison. A new spatial alignment algorithm needs its own version and
must preserve the input run IDs and options.

## Bounded Regional OCR Escalation

A selected or disputed region can seed a new extraction attempt. This is an
escalation path for improving a candidate, not an in-place correction.

### Proposed flow

1. Resolve the page region in a declared parent coordinate space.
2. Add a bounded context margin so character edges, neighboring labels, and
   layout cues are not lost.
3. Render the crop at a higher but capped DPI.
4. Run one or more server-approved OCR variants.
5. Normalize each result while retaining word or character geometry in crop
   coordinates and the transform back to the page.
6. Compare the regional candidates with the full-page readings and any typed
   validators.
7. Present the alternatives, costs, warnings, provenance, and any machine
   recommendation.
8. Allow a reviewer to accept, correct, reject, or leave the result unresolved.

Useful bounded variants may include:

- higher render DPI;
- grayscale, threshold, contrast, denoise, sharpen, or inversion variants;
- small-angle deskew when the transform is retained;
- a different declared language set;
- Tesseract page-segmentation modes appropriate to a word, line, sparse text,
  or table cell;
- domain-approved character whitelists for a known field type; and
- a registered alternate OCR engine or layout-aware method.

Too-tight crops often reduce OCR quality by removing baselines and neighboring
context. The product should retain both the user's or diff's seed region and
the expanded execution crop. It may try a small bounded set of margins rather
than treating the first rectangle as an exact segmentation truth.

### Job and cache identity

Regional attempts should reuse Tactical 001's durable job, attempt,
supervision, cancellation, recovery, bounded-log, and atomic-publication
machinery. They are a distinct resource and artifact type, not a special
untracked subprocess.

Their deterministic identity should include at least:

- source content hash and one-based page number;
- parent coordinate-space identity and canonical normalized seed region;
- expanded execution region and transform;
- page-renderer identity, render DPI, and page-box/rotation policy;
- preprocessing pipeline and exact options;
- OCR engine, version, language data identity, and segmentation settings;
- normalization and spatial-output schema versions; and
- any typed field constraint or character policy.

Equivalent requests should reuse an exact cached regional run. A request for a
new technical attempt under the same identity follows the existing explicit
fresh-attempt semantics. Limits should cover crop pixel area, DPI, variants,
wall time, retries, concurrent resource lanes, and total artifacts retained.

### Machine preference is not automatic truth

A regional pipeline can rank candidates using extractor confidence, agreement,
image quality, expected type, checksum, date/currency parsing, arithmetic
relationships, or cross-document consistency. The result may be labeled
`machine preferred` with reasons. It must not overwrite the original span or
become `human confirmed`.

If an automated policy selects a preferred candidate for downstream
provisional work, that promotion is an explicit versioned policy event with an
agent or mechanical status. A later human correction remains an append-only
review event and survives extractor upgrades and cache rebuilds.

## Relationship to Observations and Domain Mapping

Spatial spans are generic evidence primitives. Domain adapters may use them to
propose a named value, map it to a numbered form field, or support a
calculation, but the generic core should not contain Swiss, US, or other tax
rules.

A candidate observation should be able to cite:

- one or more supporting spatial spans;
- conflicting spans or regional attempts;
- the raw and normalized proposed value;
- deterministic validations;
- mapping quality and visual representation; and
- current human/agent review state.

This supports the source-to-form interaction described in
[Product landscape and use cases](product-landscape-and-use-cases.md): a form
field and value can sit beside a highlighted source region, while the reviewer
can see whether the value is unreviewed OCR, mechanically checked,
agent-assessed, or human-confirmed.

## Proposed Implementation Slices

These are sequencing guidance, not approved tacticals.

### Slice A: spatial artifact and extractor normalization

- Approve coordinate-space, region, span, and normalization-map schemas.
- Add spatial capability metadata to extractor descriptors and manifests.
- Normalize one native-text path and one OCR path while preserving raw output.
- Project page-level spatial data for bounded API access.
- Keep existing normalized text and cache readers backward compatible.

A useful first pairing would be Poppler word boxes for source PDF text and
Tesseract TSV for an exact raster. OCRmyPDF derived-page mapping, Docling, and
Marker can follow through the same contract once the two coordinate-space
cases are proven.

### Slice B: bidirectional page and text selection

- Add generated contracts and runtime operations for one run/page.
- Render an overlay layer over the existing page viewer.
- Link displayed word/token spans to source overlays in both directions.
- Label exact versus transformed coordinates and source versus derived page.
- Validate keyboard navigation, screen-reader descriptions, and headless
  browser interactions.

### Slice C: spatial comparison navigation

- Add left/right span references to versioned diff segments.
- Focus substitutions and numeric discrepancies on the page.
- Handle one-sided omissions honestly.
- Add bounded previous/next disagreement navigation.

### Slice D: regional OCR escalation

- Add a server-owned regional-extraction capability and resource limits.
- Reuse durable job scheduling and atomic artifact publication.
- Implement one high-DPI Tesseract path before adding preprocessing matrices
  or alternate engines.
- Present immutable alternatives and machine preference separately from
  review decisions.

### Slice E: durable review and source-to-form use

- Attach corrections and decisions to candidate/spatial provenance.
- Add purpose-specific review queues and evidence-coverage summaries.
- Let downstream domain packs reference reviewed generic evidence without
  placing their form schemas or calculation rules in the core.

Durable review may begin before all regional OCR slices, but its contract
should allow spatial references from the start so corrections are not forced
to cite only detached page text.

## Validation Requirements

A tactical implementing this direction should include public or synthetic
fixtures with known geometry. Private documents can remain an explicitly
authorized acceptance lane, not test fixtures.

At minimum, validation should cover:

- a born-digital PDF with known word boxes;
- a raster or image-only page with Tesseract word boxes and confidence;
- crop boxes, page rotation, and top-left/bottom-left origin conversion;
- a transformed or deskewed derived OCR page;
- multi-column text, wrapped phrases, duplicate strings, and reordered blocks;
- table cells and numeric substitutions;
- a crop round trip from page space to raster space and back within a declared
  tolerance;
- cached regional request reuse and explicit fresh-attempt behavior;
- cancellation, crash/restart reconciliation, invalid staged geometry, and
  atomic publication;
- unchanged source bytes and no source-file writes;
- browser selection-to-overlay and overlay-to-selection behavior;
- keyboard navigation, non-color cues, and accessible region descriptions;
  and
- backward compatibility for runs without spatial artifacts.

Visual checks must confirm that boxes align at multiple zoom levels and device
pixel ratios. Contract tests must reject non-finite, inverted, out-of-bounds,
wrong-page, or undeclared-coordinate regions. Transformed mappings should be
tested against their recorded matrix rather than accepted by visual
inspection alone.

## Non-Goals

- Editing, annotating, replacing, or redacting the immutable source file.
- Treating OCR confidence, majority vote, or a regional rerun as truth.
- Inferring a precise box when an extractor emitted text only.
- Exposing a general filesystem image editor or arbitrary high-resolution crop
  endpoint through the local API.
- Building a full visual pipeline graph or general annotation platform in the
  first slice.
- Embedding tax forms, accounting calculations, or jurisdiction-specific
  validation rules in the generic spatial core.
- Moving document geometry, regional-job, or review logic into Tauri/Rust.

## Open Decisions and Risks

- Whether word-level spans plus block hierarchy are sufficient for the first
  UI or character boxes are required for convincing partial-word selection.
- Whether page spatial artifacts should be streamed directly, projected into
  SQLite, or use a measured hybrid.
- How much normalized character mapping is needed before word-token references
  are sufficient.
- Whether a shared polygon representation should land immediately or follow a
  rectangle-only first reader with a versioned extension.
- How to record and invert OCRmyPDF deskew/rotation transforms reliably across
  renderer versions; until then, its overlay may need to use the derived PDF.
- How to expose partial spatial coverage when only some page content or
  extractor blocks have geometry.
- Storage and load-time cost for Marker character boxes and large Docling
  documents.
- How to prevent overlapping multi-run overlays from becoming visually noisy.
- Which field-aware validators belong in generic typed primitives versus
  downstream domain packs.
- How regional attempts are retained, compacted, or superseded without
  erasing review history.

## Recommended Next Work

Keep this direction visible while choosing the durable-review and desktop
sequence. The next write-enabled review contract should permit one or more
spatial-span or region references even if the initial reviewer still works
mostly from page-level text.

Before implementing overlays or regional OCR, create a numbered tactical that
selects one native and one OCR geometry path, fixes the schema and coordinate
conventions, defines backward compatibility, and proves exact bidirectional
selection on synthetic fixtures. Regional reruns should follow only after the
base coordinate and span mapping survive that proof.

The falsifiable stopping condition for that future first tactical should be:
given a fixture with known source text and OCR geometry, a user can select a
displayed extracted token and land on its correct visible source region, and
can select that region and land back on the correct token, with provenance and
coordinate representation stated and no source mutation.
