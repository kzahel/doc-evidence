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
