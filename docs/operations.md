# Phase 1 Operations

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
