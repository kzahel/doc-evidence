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

Force canonical SHA-256 verification for every observed source instead of
using unchanged filesystem fingerprint hints:

```sh
uv run doc-evidence inventory --config /path/to/case.yaml --full-hash
```

The command:

1. traverses sources without following symlinks;
2. hashes readable files with SHA-256, reusing a prior digest only when path,
   device, inode, size, modification time, and change time all match;
3. groups byte-identical path aliases;
4. classifies common media types;
5. runs or reuses Poppler extraction for unique PDFs;
6. hashes non-empty whitespace-normalized text for content-equivalent
   duplicate detection;
7. writes timestamped manifests and reports; and
8. builds an inactive membership generation in `doc-evidence.sqlite` and
   atomically activates it after validation.

Stable content, extraction-run, page, and FTS rows are independent of an
inventory generation. Collection paths and visible membership belong to the
active generation. If construction is interrupted, the previous generation
remains active. An existing legacy `catalog.sqlite` is imported read-only on
first open and left byte-for-byte untouched for rollback; it is not kept in
dual-write synchronization.

Preflight a trusted CLI/native folder selection without changing scope:

```sh
uv run doc-evidence collection-preflight \
  --config /path/to/case.yaml --source /path/to/proposed/folder
```

The result distinguishes a normal sibling, a root already covered by the
library, a parent expansion that would replace child roots, and invalid
source/store overlap. The localhost browser API does not accept arbitrary
filesystem paths.

The current inventory composition always runs the Poppler baseline for PDFs.
`ocr_when: image_only` and `layout_when: complex` currently express intended
routing policy and participate in configuration/cache identity; inventory does
not yet execute those escalation jobs. Run the named experts through an
explicit benchmark suite. An image-only PDF is therefore classified
correctly but has no OCR text until an OCR run has separately been cached.
Standalone JPEG/PNG files are inventoried but not yet page-rendered or
extracted.

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

## Local Application

Build once from the repository root:

```sh
uv sync && npm ci --prefix web && npm run build --prefix web
```

Then launch against an existing configured/cataloged workspace:

```sh
uv run doc-evidence serve --config /path/to/case.yaml
```

Or register once and use ordinary desktop-shaped startup thereafter:

```sh
uv run doc-evidence library-register --config /path/to/case.yaml --name "My Library"
uv run doc-evidence serve
```

Ordinary startup opens the last/default library. If no library is registered,
the application still launches and shows the exact registration action rather
than failing before the library home appears. The shared UI lists known
libraries, scopes every new API request and query key by stable library ID,
shows collection availability, and retains that identity in document/page
deep links.

The server binds an ephemeral `127.0.0.1` port and opens the exact launch URL.
The credential is generated for that process, delivered in a URL fragment,
captured only in browser memory, removed immediately from visible/history
state, and required for every API, render, and raw-artifact request. It is not
printed, persisted, or placed in a query string.

The document and comparison workspace remains source-read-only. It can search
the rebuildable catalog, render requested PDF pages into versioned derived
cache entries, compare existing extractor runs, and preview bounded raw
artifacts. Tactical 001 also exposes registered extractor availability and
explicit document or confirmed-batch extraction requests through the
authenticated application. Merely selecting a document, page, representation,
or comparison never starts work.

Extraction requests are durable in the selected library's
`doc-evidence.sqlite`. A validated canonical result is fulfilled immediately
as a cache hit; identical active work is coalesced. Otherwise a process-locked
per-library scheduler dispatches a supervised attempt under the configured
resource limits. Closing the browser does not cancel queued work. Clean server
shutdown requests cancellation of active local workers while retaining queue
intent and attempt evidence for restart reconciliation. Source files are never
modified. Persistent review decisions remain a later slice.

The header activity center shows active, queued, and failed counts. Its
expanded view can pause or resume claims, cancel or retry one job, preflight a
bounded image-only/missing-OCR batch, and cancel pending batch children with a
separate confirmation before cancelling running children. Advanced detail
keeps process liveness, heartbeat age, and absolute deadline distinct and
shows only server-bounded log tails and safe environment versions—never source
paths, arbitrary commands, the complete environment, or the launch token.

A `published_projection_failed` job means the canonical artifact passed
validation and remains immutable, but its SQLite run/page projection did not
finish. Use **Repair catalog projection** from the selected job; the server
revalidates the exact artifact before rebuilding its projection. Do not delete
the run directory or retry extraction merely to repair this condition.

To stop cleanly, use Ctrl-C in the serving terminal. The scheduler stops new
claims, requests cancellation for local active workers, waits for their
process groups, releases its library lease, and leaves queued intent durable.
After an unclean exit, launch the same registered library normally. Startup
uses both persisted attempt PIDs and the attempt-owned `worker.json` fallback
to terminate a process group that outlived its backend, then reconciles active
rows. A valid artifact produced after a cache miss wins; a fresh-verification
job whose canonical artifact already predated the attempt requires explicit
attempt publication evidence and is otherwise marked interrupted rather than
falsely successful.

Run the production-like browser gate from the repository root:

```sh
npm run test:e2e --prefix web
```

It builds the frontend, creates a fresh temporary `DOC_EVIDENCE_HOME`,
registers two synthetic libraries, starts the authenticated Python host, and
runs headless Chromium through success, exact-cache reuse, cancellation,
timeout/retry, diagnostics, deep links, and library isolation. It verifies its
source hashes and the default production registry before removing the entire
temporary home. Install the matching Chromium binary after dependency setup
with `npm exec --prefix web playwright install chromium` when needed.

For an explicitly authorized real-library acceptance run, use the bounded
harness and name the configuration that must already be selected in the
platform-default registry:

```sh
uv run python scripts/run-private-integration.py \
  --expected-config /path/to/case/.doc-evidence.yaml
```

This command deliberately removes `DOC_EVIDENCE_HOME` from its child
environment. It refuses a different selected configuration, records aggregate
source hashes and registry bytes before and after, executes one missing OCR
identity through the UI, checks exact OCR and layout cache reuse, and stops at
broad OCR preflight without confirming it. Use it only when access to that
external collection and its derived store is explicitly in scope; ordinary
automated and development runs remain isolated under a fresh temporary home.

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
`review-template.json`, and a self-contained `review.html` with those selected
page renders embedded. Open the HTML locally, score a small representative set
closely, export its JSON, and then run:

```sh
uv run doc-evidence benchmark-score \
  --report /path/to/report.json \
  --review /path/to/exported-review.json
```

Scores are grouped by extractor and document class. Pairwise agreement only
creates review flags; no merged result is considered authoritative and no
extractor role changes automatically.
