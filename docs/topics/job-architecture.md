# Durable Job Architecture

Topic: job-architecture

**Last updated:** 2026-08-01

**Status:** Tactical 001 implementation complete. Unified persistence,
atomic catalog membership generations, extractor registration, supervised
attempt execution, atomic artifact publication, durable job persistence,
bounded per-library scheduling, authenticated API/runtime operations, document
execution controls, bounded batches, and the global activity/debug UI are
implemented. Fault/restart, isolated-browser, and authorized
private-integration gates pass; explicit maintainer interaction acceptance
remains. Tactical 002's unattended local lane now packages the first macOS
execution environment and baseline extractor pack; signing and publication
remain deliberately unstarted.

## Purpose

This topic owns the continuing architecture for durable local jobs, worker
processes, extractor execution, artifact publication, cancellation, recovery,
concurrency, and operational diagnostics.

The first implementation applies the architecture to explicit extraction
requests from the document workspace. Later tacticals may reuse it for
inventory, rendering, comparison materialization, candidate generation, and
exports without changing its reliability model.

The application remains local-first and single-user. Source collections are
read-only. Opening or browsing a document never starts expensive work.

Library creation, selection, application-home resolution, collection scope,
and managed-store ownership are defined in
[Desktop library management](library-management.md). Every job names an
explicit library and runs against that library's single database/artifact
store; changing the selected library cannot retarget existing work.

## Approved System Shape

```text
Desktop-shaped React application
        |
        | authenticated typed HTTP
        v
framework-independent job application service
        |
        +---- one active library scheduler
        |              |
        |              v
        |       resource-bounded subprocess workers
        |              |
        |              v
        |       staged attempt output
        |              |
        |              v
        |       validated atomic artifact publication
        |
        +---- per-library doc-evidence.sqlite
        |       stable content/run/page/FTS projections
        |       catalog membership generations
        |       jobs, attempts, and bounded events
        |       future durable review state
        |
        +---- content-addressed blob store
                immutable successful runs
                bounded attempt diagnostics
```

Python owns scheduling and worker supervision. React consumes application
contracts rather than worker or process details. Expensive and failure-prone
extractors run in operating-system subprocesses rather than the API process.

The implemented execution port launches a private worker protocol in a new
process group, drains bounded logs, emits heartbeats, enforces an absolute
deadline, and terminates the worker tree on cancellation. The worker accepts
only registered extractor IDs and validated settings; it verifies the exact
source size, modification time, and SHA-256 before invoking an adapter. Output
is written beneath an attempt workspace, contract-validated, hashed and
fsynced, then renamed on the same filesystem into the canonical run location.
Malformed or conflicting output is retained as attempt evidence and is never
shown as canonical success.

The macOS desktop composition preserves this protocol. Packaged mode resolves
worker and extractor executables only through versioned bundle
manifests and a minimal allowlisted environment, never ambient `PATH`,
Homebrew, checkout-relative heavy environments, or an anonymous model cache.
Graceful app close asks Python to reconcile schedulers and workers before the
Tauri host's bounded fallback terminates the complete descendant process tree.

Private worker protocol v2 also carries the exact run ID and run key planned at
enqueue. The worker checks its adapter result against that identity and the
supervisor independently repeats the check before publication. A
self-consistent staged run under any other key remains failed-attempt evidence;
it cannot become a canonical result for the job.

The implemented scheduler retains only active thread/cancellation handles in
memory. Queue intent, immutable execution snapshots, attempts, outcomes, and
bounded ordered events live in SQLite. An advisory store-local process lock
and persisted lease prevent two schedulers from claiming one library. Claims
use small `light`, `ocr`, and `model_heavy` limits, explicit document work has
higher base priority, and hourly aging prevents batch starvation. Enqueue
verifies a current source alias by SHA-256, resolves the exact run identity,
reuses a validated canonical artifact, or coalesces an identical active
request. At startup, stale process groups are terminated and active rows are
reconciled: a valid canonical publication wins, while missing successful
artifacts become integrity failures.

## One Active SQLite Database Per Library

Each configured library has one active application database:

```text
<store>/doc-evidence.sqlite
```

Logical durability classes remain separate by table and policy, not by
creating separate catalog, job, review, or collection databases:

- generation-independent content/run/page/FTS tables project reusable
  content-derived work;
- rebuildable catalog membership generations project collection scope and
  source occurrences;
- operational job tables survive browser and backend restarts but have a
  bounded diagnostic-retention policy; and
- future reviews, corrections, tags, and accepted observations are durable
  user-authored library state.

The desktop-level known/last/default library registry is bounded atomic
`app-state.json` under the resolved application home, not another document
database. `DOC_EVIDENCE_HOME` provides the required isolated override for the
entire app-owned root in tests and development. The complete ownership and
path-resolution contract is in
[Desktop library management](library-management.md).

Large binaries, complete extractor output, page renders, and full logs remain
files in the artifact store. SQLite stores identities, relationships, states,
bounded event details, and artifact references.

The former `catalog.sqlite` active-file replacement has been replaced with
stable content-derived tables and catalog membership generations inside
`doc-evidence.sqlite`.
Inventory builds a new inactive membership generation, validates it, switches
the active generation in one short transaction, and garbage-collects older
membership separately. Job and future review tables are therefore not
endangered by catalog refreshes, and folder-scope expansion reuses existing
page/FTS projections rather than duplicating them.

During migration an untouched legacy `catalog.sqlite` may remain as rollback
material, but it is not a second active database and must never be kept in
dual-write synchronization.

SQLite uses WAL mode, a bounded busy timeout, foreign keys, explicit schema
migrations, and short transactions. No database transaction remains open
while waiting for a worker, filesystem operation, or network operation.

## Persistence Model

The initial job schema has four concepts.

### Job

A job is one logical user or policy request. It records at least:

- library ID;
- job ID and kind;
- stable document content identity;
- extractor and validated configuration identity;
- requested execution mode;
- derived run/cache key;
- priority and resource class;
- lifecycle state and outcome;
- creation, update, start, and completion times;
- active/latest attempt;
- resulting run and artifact identity when available; and
- a bounded failure or interruption summary.

Jobs reference content hashes rather than source paths or a particular catalog
generation.

### Attempt

An attempt is one actual execution or technical retry. It records at least:

- attempt ID, job ID, and attempt number;
- scheduler instance and worker/process identity;
- start, heartbeat, deadline, exit, and completion times;
- temporary attempt location and log references;
- exact extractor descriptor and execution environment;
- exit code or signal;
- validation and publication outcome; and
- structured failure classification.

A technical retry creates a new attempt without erasing earlier evidence.

### Event

Job events are an append-oriented, bounded operational timeline containing
stage transitions, coarse progress, warnings, cancellation, timeout, worker
exit, validation, publication, and recovery decisions.

Full stdout and stderr do not belong in SQLite. Workers write them to bounded
attempt files while the database retains summaries, tails, and references.
Progress persistence is throttled by meaningful stage change and time or
percentage intervals so a verbose extractor cannot create unbounded database
writes.

### Scheduler lease

Only one scheduler owns a library initially. A process-lifetime library lock
and persisted scheduler lease/heartbeat make that ownership observable
and prevent two accidentally launched local servers from independently
exceeding concurrency limits. The database does not contain live Python
objects or process handles.

## Lifecycle and Outcomes

The job lifecycle is:

```text
queued -> starting -> running -> succeeded
                           |-> failed
                           |-> cancelling -> cancelled
                           |-> interrupted
```

`Queued` may include a visible reason such as waiting for an OCR or heavy-model
slot. `Stalled` is a diagnostic observation, not a terminal state: a process
may remain alive in one legitimate long-running stage.

A request fulfilled from an existing exact cache entry is represented as:

```text
state: succeeded
outcome: cache_hit
```

Other success outcomes may distinguish newly executed work, a concurrent
publication won by another attempt, and a fresh verification that matched an
existing canonical run.

Invalid transitions are rejected centrally by the application service and
covered by a complete state-transition test table.

## Execution and Cache Semantics

The system provides explicit actions rather than an ambiguous **rerun**:

- **Use cached result** performs no extractor execution when the exact
  source/extractor/version/configuration/schema identity already exists.
- **Retry failed attempt** executes the same logical job identity in a new
  attempt.
- **Verify with fresh execution** deliberately recomputes the same identity in
  an attempt workspace and compares it with the canonical result.
- **Run with different settings** computes a distinct run key and therefore a
  distinct canonical artifact.

The delivery model is at-least-once and idempotent, not exactly-once. A crash
or retry may cause duplicate computation, but deterministic identity,
coalescing, staging, and atomic publication prevent duplicate execution from
corrupting state.

Concurrent requests with the same document, extractor, configuration, schema,
and execution mode coalesce behind one active logical job. API retries use an
idempotency key so a lost HTTP response does not enqueue another request.

If a fresh verification produces different normalized or raw output under an
identical deterministic identity, the attempt is retained and the run is
flagged as nondeterministic. It never silently overwrites the canonical run.
A genuinely nondeterministic adapter must include its seed, provider response
identity, or explicit attempt dimension in its declared artifact contract.

## Attempt and Artifact Protocol

Workers never write an in-progress result directly into the canonical
successful run directory.

```text
1. Resolve a source occurrence through configured collection policy.
2. Verify the source content hash still matches the requested document.
3. Create an attempt directory on the same filesystem as the blob store.
4. Run the extractor and continuously drain bounded logs.
5. Normalize and validate all required outputs.
6. Write a completion descriptor and fsync where the storage adapter requires.
7. Atomically promote the validated result to the canonical run directory.
8. Commit job success and resulting artifact identity.
9. Refresh the active catalog projection.
```

The ordering makes the validated artifact, rather than a database status
alone, the completion evidence. A catalog refresh failure does not discard a
successfully published artifact; it creates a visible repair condition.

Failed, cancelled, timed-out, and nondeterministic verification attempts may
retain bounded diagnostic output under an explicit byte/age policy. Temporary
directories are never treated as cached successful runs.

## Worker Supervision and Cancellation

The scheduler orchestrates work; extractor code executes in a subprocess or
subprocess group. Asynchronous Python tasks may coordinate workers but are
never the durable queue.

Every attempt has:

- an extractor-specific absolute timeout;
- a supervisor heartbeat independent of extractor progress;
- process liveness and process-group identity;
- bounded stdout/stderr draining;
- a cancellation token visible to the supervisor; and
- a grace period followed by forced process-group termination.

Cancellation targets the complete process group because OCR and model tools
may create descendants. A cancelled job does not remove a previously
successful canonical artifact.

Automatic continuation inside a partially completed third-party extractor is
not promised. After interruption, recovery normally starts a fresh attempt
while reusing any independently validated canonical prerequisites.

## Concurrency and Backpressure

Initial concurrency is conservative and organized by resource class rather
than one unbounded worker pool. Expected classes include:

- `light` for inexpensive PDF metadata, text, and bounded render operations;
- `ocr` for OCRmyPDF/Tesseract work;
- `model_heavy` for Docling, Marker, or comparable local models; and
- an exclusive accelerator slot when an adapter uses a GPU or similarly
  constrained device.

The default is one OCR attempt and one model-heavy attempt at a time. Light
work may use a small bounded parallelism selected from measured behavior.
Foreground work explicitly requested for the open document has priority over
background batches, while aging prevents indefinite starvation.

Each initial job acquires one resource class. Workers do not wait for other
workers and no general dependency graph is introduced. If later jobs require
multiple resources, they must acquire them in one global order or be split
into separately published stages.

Batches enqueue bounded child jobs rather than starting every extractor at
once. A preflight reports the number of cache hits, executions, unavailable
dependencies, and estimated resource classes before confirmation.

## Recovery and Reconciliation

Startup and the periodic watchdog reconcile persisted intent with external
reality:

- `starting` without a recorded live worker becomes `interrupted` after its
  lease expires;
- work whose supervisor disappeared becomes `interrupted` and retryable;
- an expired absolute deadline triggers process-group termination and a
  structured timeout failure;
- a validated canonical artifact published before the final database update
  reconciles the job to success;
- a database success record whose artifact is absent or invalid becomes an
  explicit integrity failure;
- a catalog publication failure becomes a repairable projection error; and
- abandoned attempt directories are retained or removed only under the
  documented diagnostic-retention policy.

Automatic retry is bounded. Input, configuration, validation, and missing
dependency failures do not retry automatically. A crash, temporary lock, or
other classified transient failure may receive at most one delayed automatic
retry initially. Further retries require an explicit user action.

## Application and API Boundary

The framework-independent job application service owns validation, state
transitions, cache decisions, deduplication, cancellation policy, retry policy,
and result publication. SQLite, process control, time, filesystem staging, and
extractor invocation are ports/adapters.

The authenticated localhost API exposes registered identities, never
arbitrary commands or filesystem paths. The initial resource-oriented surface
includes:

```text
GET  /api/v1/libraries
GET  /api/v1/libraries/{library_id}
GET  /api/v1/libraries/{library_id}/extractors
POST /api/v1/libraries/{library_id}/jobs/extractions
POST /api/v1/libraries/{library_id}/jobs/extraction-batches
GET  /api/v1/libraries/{library_id}/jobs
GET  /api/v1/libraries/{library_id}/jobs/{job_id}
GET  /api/v1/libraries/{library_id}/jobs/{job_id}/events
POST /api/v1/libraries/{library_id}/jobs/{job_id}/cancel
POST /api/v1/libraries/{library_id}/jobs/{job_id}/retry
```

These route and runtime operations are implemented, and their security
semantics remain stable. Extractor IDs and settings are resolved
through a server-owned typed registry. Client-provided executable paths,
commands, output paths, environment variables, and unbounded options are
rejected.

The first implementation uses bounded HTTP polling: frequent while jobs are
active and slower or disabled while idle. SQLite remains the source of truth.
A later authenticated event stream may improve notification latency without
changing job persistence or component ownership.

TanStack Query owns job, attempt, capability, and server-derived progress
state. Zustand owns only transient activity-panel visibility, filters,
selection, and layout preferences.

## User Interface

### Document execution controls

The application shell shows the active library identity, and its document
workspace shows:

- available extractors and dependency/capability status;
- exact cached coverage and cache identity;
- an image-only/OCR recommendation when justified;
- validated settings such as OCR languages;
- explicit cache reuse, retry, fresh verification, and changed-settings
  actions; and
- progress and outcome for jobs targeting the open document.

Opening a document remains passive. No extraction runs without an explicit
user request or separately confirmed batch policy.

### Global activity center

The application header exposes active, queued, and failed counts. Its activity
panel supports:

- running, queued, recent, failed, cancelled, and interrupted views;
- stage, coarse progress, elapsed time, cache outcome, and resource class;
- cancellation and retry;
- queue pause/resume where safe;
- batch grouping and preflight results; and
- automatic refresh of document runs after successful publication.

### Operational debug view

A developer-oriented job detail exposes:

- job, attempt, document, run, and cache identities;
- extractor version, schema, options, and environment descriptor;
- scheduler lease, resource class, worker PID/group, heartbeat, and deadline;
- stage/event timeline and bounded log tails;
- cache-hit or cache-miss reasoning;
- attempt, canonical artifact, and catalog-publication status;
- structured exit, cancellation, timeout, recovery, and integrity details;
- copyable diagnostic JSON; and
- server-bounded retained stdout/stderr tails without exposing filesystem
  paths.

Operational details do not overwhelm the ordinary document workspace, and the
launch credential is never present in diagnostics.

## Celery Decision and Replacement Boundary

The initial local application does not use Celery, Redis, RabbitMQ, or a
separate distributed worker service. Their deployment and lifecycle costs are
not justified for one local library and would not remove the need for
idempotent artifacts, process cleanup, or crash reconciliation.

The implementation must not recreate a general distributed task system. It
has one scheduler, a small fixed state machine, bounded priorities and resource
classes, discrete extraction jobs, and no general DAG or remote delivery.

Job application and execution ports remain explicit so a hosted composition
could later adapt execution to Celery or another durable broker without
changing artifact identity, extraction semantics, or the React runtime.

## Reliability Validation

Deterministic fake extractors and integration harnesses cover:

- isolated application homes and explicit library/job identity;
- selected-library changes that cannot retarget queued or running work;
- success, cache hit, changed configuration, and duplicate request;
- immediate crash and nonzero exit;
- indefinite hang and absolute timeout;
- graceful and ignored cancellation;
- descendant-process cleanup;
- very large stdout/stderr without pipe deadlock;
- malformed, incomplete, and nondeterministic output;
- database contention and publication races;
- insufficient-space and artifact-write failures;
- backend termination at every durable lifecycle boundary;
- restart recovery and catalog repair; and
- bounded queue, event, log, and diagnostic retention.

The core recovery invariant is:

> After restart, every accepted request is safely successful, explicitly
> failed, cancelled, interrupted, or retryable. No request remains silently
> running forever, and no partial attempt is presented as a canonical result.

## Known Gaps and Later Work

- Explicit maintainer interaction acceptance remains for Tactical 001; its
  machine-verifiable implementation gates pass.
- Resource defaults still need broader measurement on supported local
  environments; CPU count alone does not establish safe model concurrency.
- Cross-platform descendant cleanup must be revalidated when Tauri/Windows
  packaging begins.
- Tactical 002's Python sidecar shuts down its manager/schedulers on parent
  EOF, and the Tauri shell now closes that parent channel, waits up to the
  existing scheduler cleanup envelope, then applies a bounded kill. The
  forced-sidecar-exit and packaged OCR descendant cleanup gates remain and must
  not change persisted job semantics.
- A later topic may define hosted multi-scheduler leases and remote workers;
  they are not latent Tactical 001 requirements.
- Durable human review and observation history will share the unified database
  but require their own tactical and portable export contract.
- Long-term attempt/log retention defaults require measured library use.

## Implementing Tactical

[Tactical 001](../tactical/001-durable-extraction-jobs.md) owns the first
end-to-end implementation and validation of this architecture together with
the required platform-neutral foundation from
[Desktop library management](library-management.md).

[Tactical 002](../tactical/002-macos-tauri-desktop-application.md) owns the first
packaged macOS adapter over the same job and recovery contracts. Its local
baseline-pack and sidecar smokes are implemented; it does not authorize a new
scheduler, queue model, job state, or artifact protocol.
