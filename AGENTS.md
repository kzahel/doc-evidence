# Instructions for Agents Working on doc-evidence

These instructions apply to this repository.

## Purpose and Boundary

Build a reusable local-first document inventory, extraction, benchmark,
search, and evidence-understanding pipeline. The system must preserve source
provenance and keep automated candidate observations distinct from reviewed
facts.

This repository contains generic code and public/synthetic fixtures only. Its
first downstream integration is the private tax workspace at
`/Users/kgraehl/Documents/taxes`, whose current case-side plan is
`docs/topics/document-evidence-pipeline.md` in that workspace.

Never copy, move, rename, commit, upload, or modify private source documents as
part of generic-tool development. Read an external collection only when the
task and an explicit configuration path place it in scope.

## Startup Routine

Before substantive work:

1. Read `README.md`.
2. Read `docs/master-plan.md`.
3. Read `docs/architecture.md`.
4. Read `docs/data-contracts.md`.
5. Read `docs/benchmarking.md` for extractor or evaluation work.
6. Check the current Git status and preserve unrelated changes.

## Architectural Rules

- Treat source files as immutable and read-only.
- Identify content using SHA-256; paths are aliases, not identities.
- Key cached extraction runs by source hash, extractor name/version,
  configuration hash, and output-schema version.
- Store inspectable sidecars as well as a rebuildable SQLite catalog.
- Keep human review decisions outside regenerable extractor output.
- Every observation must retain file and page provenance. Page regions should
  be retained when an extractor supplies them.
- Never promote a model or OCR guess directly into an accepted downstream
  fact.
- Keep tax logic and other domain mappings in downstream adapters or case
  workspaces, not the generic extraction core.
- Add heavy extractors as optional adapters. The core package should remain
  useful with only standard local tools.
- Do not add a vector database without a measured retrieval problem that exact
  text search or SQLite full-text search cannot solve.

## Development Rules

- Target Python 3.12 unless compatibility testing supports widening the range.
- Prefer small typed modules and stable JSON-serializable contracts.
- Add or update tests with behavior changes.
- Record extractor and schema versions in output; never overwrite incompatible
  cached output in place.
- Benchmark quality and operational cost before changing the default
  extraction policy.
- Preserve raw extractor output when writing a normalization layer so failures
  can be diagnosed.
- Do not introduce a network service or transmit document contents without an
  explicit user request and a clearly documented adapter boundary.

## Private Data and Git

Common private document extensions and runtime stores are ignored. Do not use
`git add -f` for a private document. Public fixtures require an explicit
repository decision and should document their source and redistribution terms.

Local case configuration, model caches, extracted text, databases, rendered
pages, and benchmark runs remain untracked.

## Current Phase

Phase 1 implements the read-only Poppler-backed inventory, content-addressed
artifacts, duplicate detection, schema-valid manifests, rebuildable SQLite/FTS
catalog, and search commands. It reconciled successfully against the initial
private 2023 tax corpus on 2026-08-01 and is operationally validated. The next
development phase is the OCR and layout-extractor benchmark; do not select a
heavyweight default without measured results.
