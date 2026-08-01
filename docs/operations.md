# Operations

## Configure a Collection

Keep the configuration file in the external case workspace. Paths are resolved
relative to that file:

```yaml
schema_version: 1

collections:
  - id: records-2023
    source: documents/2023
    include:
      - "**/*"
    exclude:
      - "**/.DS_Store"

store:
  path: working/document-index

extraction:
  baseline: poppler
  ocr_when: image_only
  layout_when: complex
  normalized_text_duplicates: true

search:
  sqlite_fts: true
  vector_index: false
```

The store and every source collection must be disjoint. Symlink files and
directories are skipped rather than followed.

## Validate

```sh
uv run doc-evidence config-check --config /path/to/case.yaml
```

Validation checks the versioned JSON schema, unique collection IDs, existing
source directories, supported Phase 1 options, and non-overlapping source and
store paths.

## Inventory

Inventory every configured collection:

```sh
uv run doc-evidence inventory --config /path/to/case.yaml
```

Inventory selected collections:

```sh
uv run doc-evidence inventory --config /path/to/case.yaml records-2023
```

The command:

1. traverses sources without following symlinks;
2. hashes readable files with SHA-256;
3. groups byte-identical path aliases;
4. classifies common media types;
5. runs or reuses Poppler extraction for unique PDFs;
6. hashes non-empty whitespace-normalized text for content-equivalent
   duplicate detection;
7. writes timestamped manifests and reports; and
8. atomically replaces the rebuildable SQLite catalog snapshot.

Exit status is zero when the run completes without path or PDF-extraction
errors. A nonzero status does not imply that all derived output was discarded;
inspect `errors.jsonl` and `summary.json` in the reported manifest directory.

## Search

Literal substring search:

```sh
uv run doc-evidence search --config /path/to/case.yaml "account number"
```

SQLite FTS5 query:

```sh
uv run doc-evidence search --config /path/to/case.yaml Evidence --mode fts
```

Results identify the content hash, one-based page number, and all collection
paths associated with the document.

Use the `doc-evidence` command for FTS queries. A system `sqlite3` shell may be
linked against a different SQLite build that cannot load the FTS5 table even
when the Python runtime reported by `doc-evidence doctor` supports it.

## Duplicates

```sh
uv run doc-evidence duplicates --config /path/to/case.yaml
```

`byte` groups contain multiple paths with the same SHA-256 content.
`normalized_text` groups contain distinct PDF byte hashes whose extracted text
is identical after Unicode and whitespace normalization. Image-only PDFs are
not grouped merely because they all contain no embedded text.

## Cache Behavior

Successful Poppler output is reused only when all of these match:

- source SHA-256;
- Poppler tool versions;
- extraction configuration hash;
- Poppler invocation options; and
- output-schema version.

Failures are retained under timestamped failure directories and retried on a
later inventory. Original sources are never replaced with searchable copies.

## Phase 2 Dependencies

Keep heavy parser environments isolated from the core package. On macOS, the
tested setup is:

```sh
brew install ocrmypdf tesseract-lang llama.cpp
./scripts/bootstrap-phase2-extractors.sh
```

The `.extractors/` directory is ignored. The adapters also accept executables
on `PATH`; exact tool versions and invocation options are recorded in run
descriptors and cache identities.

Marker 2.0 uses local Surya helper services and `llama-server` for OCR on pages
that need it. The benchmark reuses those helpers across its selected documents
and stops the services belonging to the isolated Marker environment when the
run ends.

## Private Benchmark Suite

Keep suite YAML, rendered pages, extracted text, expected values, and reviews
in the external case store. Validate before running:

```sh
uv run doc-evidence benchmark-check --suite /path/to/suite.yaml
uv run doc-evidence benchmark-run \
  --config /path/to/case.yaml \
  --suite /path/to/suite.yaml
```

The suite chooses content hashes, document classes, review pages, extractors,
and sparse assertions. The run writes `report.json`, page renders,
`review-template.json`, and `review.html`. Open the HTML locally, score a small
representative set closely, export its JSON, and then run:

```sh
uv run doc-evidence benchmark-score \
  --report /path/to/report.json \
  --review /path/to/exported-review.json
```

Scores are grouped by extractor and document class. Pairwise agreement only
creates review flags; no merged result is considered authoritative and no
extractor role changes automatically.
