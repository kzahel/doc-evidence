# Extractor Benchmarking

## Objective

Choose default and escalation extractors from reproducible results on the
documents that matter, rather than popularity or a single demo.

OCR preprocessing and document parsing are different stages. OCRmyPDF should
be evaluated as scan preparation; Poppler, Docling, Marker, and future adapters
can then be compared on the relevant input.

## Benchmark Suites

### Public regression suite

Small synthetic or redistributable fixtures committed intentionally to this
repository. It verifies adapter contracts, page numbering, Unicode, tables,
rotations, errors, and deterministic cache identities.

### Private representative suite

External documents selected in a case-local config by collection/path and
content hash. Private inputs, expected values, extracted text, renders, and run
artifacts are never committed here.

Representative categories should include:

- born-digital statement;
- wage or income statement;
- multi-page brokerage package;
- table-heavy accounting document;
- multilingual English/German document;
- clean and difficult scans;
- estate, inheritance, court, or administrative document;
- prior tax return;
- XFA-based form;
- duplicate or content-equivalent files; and
- misleading filename or date.

## Evaluation Dimensions

- text completeness;
- reading order;
- Unicode and numeric fidelity;
- table row/column structure;
- page and region provenance;
- key-field recall and precision;
- OCR rotation/skew behavior;
- repeatability;
- runtime and peak memory;
- artifact size;
- installation/model-download burden;
- failure diagnostics; and
- practical usefulness for review and downstream observations.

## Ground Truth

Do not attempt full transcription of every benchmark document. Create focused
assertions for important fields and structures, such as a statement period,
three exact balances, a table row count, or a known page location.

Every expected value should state whether it was manually verified and for
what purpose.

Extractor agreement is not ground truth. Two engines can repeat the same bad
text layer or the same OCR error. The runner therefore records both:

- automatic pairwise character, word-token, numeric-token, length, and page
  comparisons for triage; and
- manually verified assertions plus page-level human ratings for accuracy.

Calibration is stratified by document class. Review at least five
representative pages in a class before treating a role recommendation as more
than experimental. A small, carefully checked set is preferable to casually
rating every page.

The 0–4 human scale is:

- `0` — unusable or materially wrong;
- `1` — poor, extensive correction required;
- `2` — mixed, useful only with close review;
- `3` — good, minor correction or layout loss; and
- `4` — exact or fully useful for the stated dimension.

An invented or unsupported numeric value is separately flagged because an
otherwise readable result can still be unsafe for financial work.

## Expert Lifecycle

Score each extractor per document class and preserve the sample count. Roles
are explicit decisions:

- `candidate default` — strong reviewed accuracy with no invented values;
- `fallback / second opinion` — useful but not consistently best;
- `corroborating only` — output may flag omissions but needs close checking;
- `experimental` — too little reviewed support; and
- `retired for class` — explicit human decision after repeated failures.

The score command never retires an extractor. It can recommend reviewing
retirement only after at least five reviewed pages and weak results or repeated
invented-value flags.

## Reports

A comparison report should include:

- corpus and configuration hashes;
- machine/runtime information;
- exact extractor and model versions;
- pass/fail metrics and reviewer notes;
- per-document failures and warnings; and
- a recommendation for default, OCR, layout, and fallback policies.

Do not change the production default based only on aggregate scores when a
high-value document class regresses.

The first private calibration run deliberately keeps its source paths,
expected values, extracted text, renders, and report outside this repository.
Its ten sparse assertions per expert are a smoke test for the machinery, not a
replacement for the exported human review overlay.

The generated `review.html` is local and fully self-contained: selected page
renders are embedded as image data so the file also works in previews that
cannot read neighboring files. The separate PNG renders remain in the run
directory for inspection and provenance. The review page stores draft ratings
in browser local storage and exports a JSON review file for durable scoring.
