# Data Contracts

## Contract Layers

The project separates five kinds of data:

1. **Source record** — where immutable bytes were observed.
2. **Extraction run** — the versioned output of a specific extractor.
3. **Normalized artifact** — common text, page, block, and table structures.
4. **Candidate observation** — a proposed semantic value with provenance.
5. **Review overlay** — a human/agent decision accepting, rejecting,
   correcting, or superseding an observation.

Downstream domain facts are outside the generic core.

## Manifest

[`schemas/manifest-record.schema.json`](../schemas/manifest-record.schema.json)
defines the initial content-oriented manifest. It keeps one document identity
separate from its path aliases and extraction status.

Each manifest source path is relative to its configured collection root. The
manifest records observed size and modification time but does not treat those
values as content identity. The SHA-256 digest remains canonical.

## Observations

[`schemas/observation.schema.json`](../schemas/observation.schema.json) defines
the initial candidate-observation envelope. A domain-specific schema may
constrain `field`, `raw_value`, and `normalized_value`, but may not remove
source provenance or review state.

## Review State

Initial states:

- `unreviewed` — produced but not checked;
- `accepted` — accepted for the stated downstream purpose;
- `rejected` — checked and not accepted;
- `corrected` — the candidate was wrong but a reviewed replacement exists;
- `superseded` — once useful, replaced by better evidence or analysis.

Review is purpose-specific. Accepting an account balance does not necessarily
accept document ownership, income classification, or tax treatment.

Review status, review actor, machine confidence, extractor agreement, and
deterministic validation are separate dimensions. A future durable review
event must identify whether its actor is a person, agent, or bounded policy and
must never present agent acceptance as human confirmation. The interface and
portable exports should be able to distinguish at least:

- unreviewed machine candidates;
- mechanically validated candidates;
- agent-assessed candidates that are not human-confirmed; and
- explicitly human-confirmed or human-corrected evidence.

A provisional calculation or form mapping must retain the review coverage of
every input and any unresolved conflict. Human confirmation of source
transcription does not by itself confirm the downstream interpretation or
calculation.

## Benchmark and Calibration Contracts

[`schemas/benchmark-suite.schema.json`](../schemas/benchmark-suite.schema.json)
defines a private suite by source content hash, document class, selected pages,
enabled experts, and sparse expected-value assertions. Every assertion says
whether a person manually verified it and why it matters.

[`schemas/review.schema.json`](../schemas/review.schema.json) records page-level
human ratings for text accuracy, numeric fidelity, reading order, optional
table structure, invented values, and notes. Ratings use a 0–4 scale and remain
separate from regenerable extraction runs.

Pairwise extractor agreement is stored in a benchmark report, not as a review
decision. A scorecard may recommend a role by document class, but it cannot
change adapter policy automatically.

## Page Coordinates

User-facing page numbers are one-based. Internal regions use normalized page
coordinates when possible:

```text
[left, top, right, bottom]
```

The observation must record the coordinate system when a region is present.

The current observation schema permits one rectangular region. The accepted
future direction adds explicit source/derived/crop coordinate spaces,
transform chains, extractor-span identities, polygons or multiple regions,
and normalized-text mappings without discarding the raw tool coordinates.
[Spatial provenance and regional OCR](topics/spatial-provenance-and-regional-ocr.md)
owns that proposed contract until a numbered tactical approves a schema
version and migration.

## Currency and Units

Keep raw and normalized values separate. A source amount should retain its
original currency and representation. Currency conversion is normally a
downstream domain calculation, not an extraction mutation.

## Versioning

Schemas have explicit integer versions. Backward-incompatible changes require
a new version and migration or parallel reader. An extractor upgrade does not
rewrite prior run output; it creates a new run identity.

The runtime configuration schema is packaged with the Python distribution and
tested for byte equality with the documented schema under `schemas/`.

## Durable Extraction Jobs

Operational extraction records are schema-versioned SQLite contracts inside
the owning library's `doc-evidence.sqlite`, not extractor artifacts. A job
retains stable library, document/content, extractor, settings, exact run/cache
identity, execution mode, priority/resource class, lifecycle, result, and
bounded failure fields. Its execution JSON is an immutable server-produced
snapshot; client requests cannot supply commands, paths, executables, or
environment variables.

Each technical attempt retains its number, scheduler and process identity,
deadline/heartbeat, execution snapshot, attempt/log location, exit and
publication outcome, manifest identity, and structured failure. Per-job event
sequence numbers increase monotonically even when the oldest diagnostic rows
are pruned. Full process logs remain bounded files. A `cache_hit` is a
successful job outcome without a worker attempt; a technical retry adds an
attempt to the same logical job; fresh verification is a distinct logical
request under the same deterministic run identity.
