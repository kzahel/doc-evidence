# 001 — Durable Extraction Jobs and Operational UI

Topic: job-architecture

Topic: application-platform

Topic: maintainer-feature-requests

**Status:** Approved implementation plan; implementation not started.

## Motivation and User-Visible Outcome

The read-only application shows only extractor runs that already exist in the
artifact store. Most documents therefore expose native Poppler text only,
image-only PDFs can appear empty, and the user must leave the application to
run benchmark-oriented tooling.

After this tactical, a user can explicitly run a supported extractor for the
open document, request OCR for an image-only document, inspect the exact cache
decision, monitor work across the application, cancel or retry an attempt,
survive a browser or backend restart without ambiguous state, and inspect
detailed operational diagnostics. A bounded batch can enqueue missing OCR for
an explicitly reviewed set without unbounded fan-out.

Successful output remains content-addressed, versioned, immutable, and
traceable. Source documents remain unchanged. Merely opening a document never
starts extraction.

## Dependencies and References

- [Durable job architecture](../topics/job-architecture.md)
- [Product vision and application architecture](../product-vision-and-architecture.md)
- [Application platform](../topics/application-platform.md)
- [Comparison and review workspace](../topics/comparison-review-workspace.md)
- [Maintainer feature requests](../topics/maintainer-feature-requests.md)
- [Core architecture](../architecture.md)
- [Data contracts](../data-contracts.md)
- [Extractor benchmarking](../benchmarking.md)
- [Sibling and external references](../references.md)
- [Tactical 000 execution record](000-read-only-library-comparison.md)

Before implementing worker and application boundaries, inspect the pinned
`atpiano` framework-independent application-core and durable worker-isolation
tacticals recorded in `references.md`. Adopt their process-isolation,
bounded-state, restart, and thin-adapter lessons without importing their audio
session or streaming model.

## Entry Evidence

- Tactical 000 provides an authenticated loopback FastAPI application,
  generated TypeScript client, hand-owned runtime, React workspace, TanStack
  Query/Zustand split, and read-only catalog/artifact adapter.
- The current benchmark runner invokes selected extractors serially and
  synchronously. It is not a durable or resumable job service.
- Extractor adapters synchronously create their canonical run directory before
  invoking third-party tools. Cancellation or backend termination can
  therefore leave partial content at a path intended for cached success.
- `run_command` owns timeout cleanup but has no application cancellation,
  progress, attempt identity, or persistent worker lifecycle.
- The current `catalog.sqlite` is built in a temporary file and atomically
  replaces the previous database. Durable job or review tables cannot safely
  live in that replacement model.
- Exact successful extractor cache identity already includes source content,
  extractor descriptor/configuration, and normalized schema version.
- The external private calibration library demonstrates both exact cache reuse
  and documents that lack appropriate OCR/layout coverage.
- The maintainer explicitly approved one active SQLite database, a small local
  scheduler instead of Celery, process-group supervision, atomic artifact
  publication, watchdog recovery, a global activity surface, and an advanced
  concurrency/debug view.

## Frozen Decisions

### Persistence

- Introduce one active `<store>/doc-evidence.sqlite` database.
- Use explicit transactional schema migrations and a recorded schema version.
- Store catalog generations, jobs, attempts, bounded events, scheduler lease,
  and later durable review tables in the same database.
- Keep extractor payloads, renders, raw output, and full logs in the existing
  content-addressed filesystem store.
- Replace whole-file catalog rebuilds with inactive generation construction,
  validation, an atomic active-generation switch, and separately bounded
  generation cleanup.
- Import or rebuild the latest legacy `catalog.sqlite` snapshot into the first
  unified generation without modifying source documents or existing
  successful artifacts.
- A legacy `catalog.sqlite` may remain unchanged for rollback but is not an
  active second database and receives no dual writes.
- Use SQLite WAL mode, foreign keys, a bounded busy timeout, and short
  transactions. Never hold a transaction during worker execution.

### Delivery and execution

- Use an at-least-once, idempotent delivery model. Do not claim exactly-once
  extraction.
- Compute cache identity before execution and coalesce identical active
  requests.
- Treat cache reuse as successful fulfillment with a `cache_hit` outcome, not
  as a worker lifecycle state.
- Distinguish cache reuse, technical retry, fresh verification, and changed
  settings in contracts and UI.
- Run every expensive extractor in a supervised operating-system subprocess
  group with bounded logs, absolute timeout, cancellation, and forced cleanup.
- Stage every attempt outside the canonical successful run directory. Validate
  completely before atomic publication.
- Preserve bounded failed-attempt evidence and never promote malformed or
  partial output.
- If a fresh execution disagrees under an identical deterministic identity,
  preserve it as nondeterminism evidence and do not overwrite the canonical
  run.

### Scheduling

- One active scheduler owns a workspace through a process lock and persisted
  lease/heartbeat.
- Start with explicit `light`, `ocr`, and `model_heavy` resource classes plus
  an exclusive accelerator dimension where needed.
- Default to one OCR and one model-heavy execution at a time. Select a small
  light-work bound from measured local behavior.
- Prioritize explicit current-document work above confirmed batches while
  aging queued work to prevent starvation.
- Each Tactical 001 job acquires one resource class. There is no general DAG,
  worker-to-worker wait, or unbounded task graph.
- Batches enqueue bounded child jobs only after a cache/dependency/resource
  preflight.

### Recovery

- Persist job intent before launch and attempt/worker identity immediately
  after spawn.
- Track scheduler heartbeat, process liveness, and extractor progress as
  separate signals.
- Enforce extractor-specific absolute deadlines. Lack of progress alone does
  not prove a long-running extractor is hung.
- On startup, reconcile stale `starting`, `running`, and `cancelling` attempts,
  canonical artifacts, attempt directories, and active catalog projection.
- A published valid artifact wins over a missing final job-state update and
  reconciles to success.
- A success row with a missing/invalid artifact becomes an explicit integrity
  failure.
- A successful artifact whose catalog refresh failed remains valid and exposes
  a repair action.
- Permit at most one delayed automatic retry for failures classified as
  transient. Configuration, input, dependency, and validation errors require
  explicit correction or retry.

### Frontend ownership and updates

- TanStack Query owns extractor capabilities, jobs, attempts, events, and
  progress snapshots.
- Zustand owns activity-panel visibility, selected job, filters, and other
  transient presentation state only.
- Start with bounded polling: approximately once per second while relevant
  jobs are active and slower or disabled while idle. Do not make streaming
  transport a prerequisite for durable correctness.
- Completion invalidates the open document's run/page/group queries and
  highlights the newly available representation without resetting unrelated
  review layout.
- Preserve the accepted Focused, Stacked, Compare, typography, sidebar,
  resizable-pane, text-layout, and page-navigation behavior from Tactical 000.

## Durable Data Model

Exact column names may tighten during implementation, but the persisted model
must retain these semantics.

### Infrastructure and catalog

```text
schema_migrations
workspace_metadata
catalog_generations
documents                  # generation-scoped projection
sources                    # generation-scoped projection
extraction_runs            # generation-scoped projection
pages                      # generation-scoped projection
pages_fts                  # generation-scoped searchable projection
duplicate_members          # generation-scoped projection
scheduler_lease
```

The active catalog generation is one small durable pointer. All library and
search queries resolve through it. Jobs target stable content identity rather
than generation-scoped row identity.

### Operational tables

```text
job_batches
jobs
job_attempts
job_events
```

`jobs` retain request kind, document/extractor/configuration identity,
execution mode, run key, priority/resource class, lifecycle state, outcome,
timestamps, active attempt, result identity, and bounded error summary.

`job_attempts` retain attempt number, scheduler/worker identity, heartbeat and
deadline, exact execution descriptor, attempt/log paths, exit details,
validation/publication outcome, and structured failure classification.

`job_events` use a monotonically ordered per-job sequence and retain bounded
stage, progress, warning, timeout, cancellation, publication, and recovery
events. High-frequency process output remains in files.

`job_batches` retain preflight identity, explicit selection/policy, aggregate
status, and child job relationships. They do not store copies of document
content.

## State and Retry Contract

The job lifecycle is:

```text
queued -> starting -> running -> succeeded
                           |-> failed
                           |-> cancelling -> cancelled
                           |-> interrupted
```

Waiting for a resource remains `queued` with a reason. A stale heartbeat or
long-running stage is surfaced diagnostically without inventing a terminal
state before the deadline or process exit.

Retry behavior is explicit:

- a technical retry adds an attempt to the same logical job;
- a repeated user request creates or coalesces a new logical request and may
  resolve immediately from cache;
- a fresh verification executes into a new attempt workspace even when the
  canonical cache exists; and
- changed settings produce a new deterministic run key.

Invalid state transitions fail centrally and are never repaired ad hoc by an
HTTP route or React component.

## Artifact Layout and Publication

Preserve the successful canonical layout:

```text
blobs/<hash-prefix>/<sha256>/runs/<extractor>/<run-key>/
```

Add attempt-scoped staging on the same filesystem, for example:

```text
blobs/<hash-prefix>/<sha256>/attempts/<attempt-id>/
```

The exact staging name may tighten, but it must be distinguishable from a
successful run and support atomic same-filesystem publication.

An attempt directory contains bounded stdout/stderr, a versioned execution
descriptor, raw tool output, normalized candidate output, validation result,
and completion/failure metadata. Successful publication either atomically
creates the canonical run or validates that a concurrent publisher already
created the same run. It never merges partial directories.

Run descriptors continue to record source hash, extractor/version/options,
normalization and output schema, timestamps, warnings, raw artifact map, and
runtime. Add the originating job/attempt or verification references without
making transient queue state necessary to read a successful artifact.

## Python Scope

### 1. Unified persistence and migrations

- Add framework-independent repositories and transactional schema migrations
  for `doc-evidence.sqlite`.
- Import/rebuild the current catalog as the first active generation.
- Update inventory to construct and activate catalog generations without
  replacing the unified database.
- Preserve literal/FTS search, duplicate, document, page, run, and source-path
  behavior through the new projection.
- Add integrity, migration, generation-switch, interrupted-build, and legacy
  rollback tests.

### 2. Extractor registry and preflight

- Introduce a typed server-owned extractor registry declaring identifier,
  version/descriptor, supported media types, required dependencies, resource
  class, settings schema, default timeout, determinism, and output kinds.
- Expose capability and dependency diagnostics without launching extraction.
- Resolve source occurrence by document identity and verify its current hash
  before enqueue or execution.
- Support current PDF adapters and an explicit OCR path for supported
  image-only PDFs and standalone raster images. If a raster path requires a
  new adapter or deterministic conversion prerequisite, version and preserve
  it rather than hiding conversion inside an unrelated run.
- Do not accept executable or filesystem paths from the client.

### 3. Supervised attempts and atomic artifacts

- Refactor synchronous command execution behind an attempt supervisor with
  cancellation, process-group ownership, deadlines, heartbeats, bounded log
  draining, and structured exit details.
- Make adapters write only to attempt-owned locations supplied by the
  execution port.
- Validate and atomically publish successful output.
- Reconcile concurrent publication and fresh-verification disagreement.
- Add a retention service for failed/cancelled attempt diagnostics with byte
  and age caps; do not delete diagnostics during the job that produced them.

### 4. Job application service and scheduler

- Implement job creation, cache resolution, idempotency, coalescing, claim,
  transitions, retry, cancellation, timeout, priority aging, and result
  publication as framework-independent services.
- Add one workspace scheduler lease and a bounded resource-class dispatcher.
- Keep scheduling data bounded: queue rows and aggregate counters replace
  unbounded in-memory task lists.
- Add startup and periodic reconciliation for stale workers, published
  artifacts, projection failures, and abandoned attempt state.
- Allow clean API shutdown to stop claiming work, request cancellation where
  policy allows, preserve queue intent, and leave remaining attempts explicitly
  recoverable.

### 5. Application contracts and local API

The bounded v1 surface may include:

```text
GET  /api/v1/extractors
POST /api/v1/jobs/extractions
POST /api/v1/jobs/extraction-batches
GET  /api/v1/jobs
GET  /api/v1/jobs/{job_id}
GET  /api/v1/jobs/{job_id}/events
POST /api/v1/jobs/{job_id}/cancel
POST /api/v1/jobs/{job_id}/retry
```

- Add Pydantic contracts, OpenAPI, generated TypeScript wire types/client, and
  hand-owned `DocEvidenceRuntime` operations.
- Require the existing launch authentication and allowed-origin policy for
  every mutation and read.
- Support an idempotency key on enqueue mutations.
- Bound list/event pagination, settings size, batch size, retained log tails,
  and diagnostic payloads.
- Map typed application failures to stable API problem codes.
- Do not expose arbitrary commands, environment, executable paths, source
  paths, destination paths, or unrestricted artifact reads.

## User Interface Scope

### Document extraction panel

Add a compact execution surface integrated with the existing document
workspace:

- available extractors grouped by representation role;
- dependency availability and an actionable unavailable reason;
- exact cached/not-cached coverage, version, settings, schema, and run key;
- an image-only recommendation for OCR where supported;
- primary **Use cached result** or **Run extraction** action chosen from the
  actual cache state;
- advanced **Verify fresh**, changed-settings, and retry actions;
- current-document queue/running progress and cancellation; and
- completion behavior that loads and highlights the new representation.

No execution starts on document selection, page navigation, representation
selection, or comparison-mode entry.

### Global activity center

Add an application-level activity affordance showing active, queued, and
failed counts. The expanded view includes:

- active, queued, recent, failed, cancelled, and interrupted filters;
- job target, extractor, resource class, stage, progress, elapsed time, and
  outcome;
- cache-hit explanation;
- cancel and retry controls with clear disabled reasons;
- queue pause/resume and bounded batch grouping; and
- recovery/integrity alerts that require attention.

Clearing completed items from the visual recent list does not delete
successful artifacts or historical attempt evidence outside retention policy.

### Batch preflight

Support at least the bounded policy **documents classified image-only that
lack an exact OCR run**. Before enqueue, show:

- selected document count;
- cache hits versus actual executions;
- unsupported media and missing dependencies;
- expected resource class/concurrency; and
- the explicit maximum batch size.

Confirmation creates a batch and child jobs. Cancelling a batch cancels
pending children and separately asks whether already running children should
be cancelled.

### Concurrency and debug view

Provide an advanced operational view with:

- resource lanes and configured/current concurrency;
- queue order, priority, wait reason, aging, and coalesced requests;
- scheduler lease and heartbeat;
- selected job/attempt state and event timeline;
- worker PID/process group, liveness, heartbeat, deadline, and exit details;
- extractor/version/config/schema/environment and cache decision;
- bounded stdout/stderr tails and registered artifact/log links;
- staging, validation, canonical publication, and catalog projection status;
- retry, cancel, catalog-repair, and copy-diagnostics actions; and
- conspicuous distinction between a live process with no recent progress and
  a dead or expired worker.

Do not expose the launch credential, unrestricted file paths, arbitrary
commands, or controls that exceed server-enforced safe concurrency caps.

## Failure Reduction and Watchdog Requirements

The implementation must close these crash windows explicitly:

| Failure window | Required recovery |
| --- | --- |
| Enqueued before claim | Remains queued after restart |
| Claimed before spawn | Lease expiry marks interrupted/retryable |
| Spawned before PID update | Process-group cleanup plus interrupted attempt |
| Running worker crashes | Failed attempt with logs and exit classification |
| Worker hangs | Absolute timeout, graceful then forced group termination |
| Cancellation races with success | One serialized transition; valid published artifact is retained |
| Artifact published before DB success | Reconcile valid canonical artifact to success |
| DB says success but artifact is invalid | Explicit integrity failure; never display as usable |
| Artifact valid but catalog update fails | Successful job with visible projection-repair condition |
| Backend exits while worker runs | No silent permanent running state; startup reconciliation |
| Identical jobs race | One canonical artifact; other request coalesces or records concurrent cache win |

The watchdog observes scheduler heartbeat, process liveness, progress age,
deadline, and artifact state independently. It never retries forever or calls
an alive but quiet model failed merely because it has not emitted progress.

## Automated Validation

### Persistence and application services

- Fresh database creation and every migration path pass SQLite integrity and
  foreign-key checks.
- A legacy catalog becomes the first active unified generation without source
  or artifact changes.
- Interrupted generation construction leaves the prior generation active.
- Successful generation activation is atomic and retains jobs/events.
- State-transition table tests reject every invalid transition.
- Idempotency and concurrent identical enqueue tests produce one intended
  execution.
- Cache hits start no worker process.
- Retry, fresh verification, changed settings, and nondeterministic output
  preserve distinct intended histories.
- Scheduler ownership, resource bounds, priority aging, batch bounds, and
  queue pause/resume are deterministic under fake time.

### Worker and artifact fault injection

Deterministic fake extractors cover:

- normal success;
- immediate crash/nonzero exit;
- indefinite hang;
- cooperative and ignored cancellation;
- a spawned descendant process;
- large stdout/stderr without pipe deadlock;
- malformed and incomplete output;
- deterministic-identity disagreement;
- publication collision;
- temporary database contention;
- simulated insufficient space and artifact write failure; and
- catalog projection failure after successful artifact publication.

Terminate the backend at each durable boundary from enqueue through catalog
refresh. Restart must produce only successful, failed, cancelled, interrupted,
or retryable work—never a permanently silent `running` job. Process and
temporary-directory accounting must show no unowned descendants or unbounded
attempt accumulation.

### API, contracts, and frontend

- Authentication, allowed origin, idempotency, pagination, settings bounds,
  batch bounds, capability validation, and path/command injection tests pass.
- OpenAPI and generated TypeScript/client drift checks pass.
- Representative job, attempt, event, extractor-capability, batch, and error
  payloads validate in Python and TypeScript.
- TanStack Query tests cover active polling, idle backoff, completion
  invalidation, restart/interrupted state, and cache-hit fulfillment.
- Component tests cover document execution, unavailable dependencies,
  activity filters/counts, cancellation/retry, batch preflight, resource lanes,
  live-but-quiet versus dead workers, diagnostics, and narrow layouts.
- TypeScript typecheck, frontend tests, production build, Ruff, Pyright, Python
  tests, package build, and generated-contract checks pass.
- Background/headless Playwright—not the maintainer's interactive browser—runs
  the real application against deterministic fake extractors and validates
  success, cache reuse, cancellation, timeout, restart recovery, activity
  updates, document refresh, and the debug timeline without console errors.

### External private integration

Run against the configured private tax workspace without copying or modifying
source documents:

- record a full source hash baseline before and after;
- enqueue one missing OCR extraction for an image-only PDF through the UI;
- observe queue, worker, publication, document refresh, and subsequent cache
  reuse;
- run or reuse one selected layout extractor where dependencies are available;
- preflight the image-only/missing-OCR batch without automatically confirming
  broad work; and
- record only counts, versions, timings, states, safe diagnostics, and
  non-sensitive UI evidence in this repository.

Optional model availability or performance does not turn a dependency absence
into an application failure; the UI must represent it accurately.

## Manual Acceptance

The maintainer reviews:

- explicit extraction from the current document;
- passive browsing with no accidental work;
- cache reuse versus fresh verification wording;
- current-document progress and cancellation;
- global activity and advanced concurrency/debug views;
- one failed/interrupted attempt and successful retry;
- backend restart recovery;
- image-only batch preflight; and
- how new output appears in Focused, Stacked, and Compare modes.

The review also confirms that ordinary document inspection remains focused and
that advanced worker detail is available without dominating the primary UI.

## Security and Resource Bounds

- Preserve loopback-only binding, per-launch bearer authentication, exact
  allowed-origin policy, credential redaction, and no remote assets.
- Register extractors and settings server-side; reject arbitrary executables,
  commands, paths, environments, and unbounded configurations.
- Verify source content before execution and open source collections read-only.
- Keep remote extractors disabled and outside this tactical.
- Bound concurrent resource use, queued batch size, event rows, diagnostic
  payloads, log files, attempt retention, and temporary disk usage.
- Check usable storage before expensive work and fail visibly before the
  artifact store cannot safely stage and publish an attempt.
- Do not let cancellation, retry, or cleanup remove a valid canonical artifact
  or source file.

## Explicit Non-goals

- No Celery, Redis, RabbitMQ, distributed scheduler, remote worker, hosted
  queue, or multi-machine lease protocol.
- No general pipeline DAG, visual pipeline editor, cron scheduler, collection
  watcher, or automatic extraction merely from browsing.
- No promise to resume an interrupted third-party extractor mid-command.
- No unlimited automatic retries, speculative execution, or unconstrained
  user concurrency.
- No durable reviews, corrections, tags, semantic candidates, accepted facts,
  or domain packs.
- No Tauri packaging, installer, updater, signing, or Windows-specific process
  integration beyond keeping portable boundaries.
- No remote model fallback, upload, analytics, telemetry, or diagnostic
  transmission.
- No source mutation, OCR replacement of originals, document moves, renames,
  deletion, or unrestricted file access.
- No mechanical migration of every existing module merely to match the
  proposed long-term package tree.

## Rollback and Compatibility

Existing successful artifact paths and run descriptors remain readable.
Current source collections, manifests, benchmark suites, generated review
packs, and CLI cache identities are not rewritten.

The unified database is additive. Migration leaves the legacy rebuildable
catalog untouched as rollback material during this tactical and never
dual-writes it. An older release may continue reading that prior snapshot;
newly published artifacts remain content-addressed and can be rediscovered by
its existing inventory path.

Rolling back the UI/API ignores queued operational state but does not remove
source documents or successful artifacts. Before Tactical 001 is accepted,
the handoff documents how to stop workers cleanly and how to identify any
interrupted attempts.

## Planned Commit Slices

1. Add unified SQLite migrations, catalog generations, and legacy catalog
   import/rebuild with search and inventory parity.
2. Add the typed extractor registry, attempt workspace, supervised process
   execution, cancellation, validation, and atomic publication.
3. Add framework-independent jobs, attempts, events, scheduler lease,
   resource dispatch, cache/coalescing, watchdog, and restart reconciliation.
4. Add authenticated job/capability API contracts, generated TypeScript, and
   runtime operations.
5. Add document extraction controls, progress, cache/fresh semantics, and
   post-publication representation refresh.
6. Add the global activity center, batch preflight, concurrency lanes, and
   operational debug view.
7. Add crash-window/fault-injection validation, headless Playwright evidence,
   private integration, operations documentation, and final acceptance packet.

Each implementation commit for this tactical uses the trailer:

```text
Topic: job-architecture
```

## Falsifiable Stopping Condition

Tactical 001 is complete only when one production-like localhost session can
start extraction from the document UI, distinguish cache reuse from fresh
execution, expose bounded activity/debug state, safely cancel and retry,
recover from forced backend termination at every persisted lifecycle boundary,
publish only validated immutable artifacts, refresh the document workspace,
and pass the complete automated, private-integration, and explicit maintainer
acceptance gates above.

Any request left silently `running` after its lease/deadline and a restart, any
orphan descendant process, any partial attempt displayed as canonical success,
any source mutation, or any lost valid canonical artifact falsifies completion.

## Next-Slice Boundary

Durable human review events, corrections, tags, and portable review export
remain the likely next tactical after the job system is accepted. Hosted
workers and Tauri packaging remain separate decisions driven by measured need.

## Execution Record

Not started.
