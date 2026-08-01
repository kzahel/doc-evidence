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

## Page Coordinates

User-facing page numbers are one-based. Internal regions use normalized page
coordinates when possible:

```text
[left, top, right, bottom]
```

The observation must record the coordinate system when a region is present.

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
