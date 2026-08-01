# Topics

Focused living records of continuing product and engineering concerns live
here.

Architecture and reference documents own durable system shape and external
facts. Topics own the current truth for a concern that will evolve across
multiple implementation slices. Tactical documents under `../tactical/` own
bounded implementation plans and execution records.

Create or update a topic when:

- work will span multiple tacticals or commits;
- accepted decisions or invariants must survive the current session;
- new evidence changes an established direction;
- current status, gaps, or next work would otherwise be difficult to answer;
  or
- the user explicitly requests a living topic.

Do not create one topic per small change. A topic should normally include:

- a crisp scope;
- a `Topic: <slug>` line matching its filename;
- an honest status;
- current decisions and invariants;
- evidence, known gaps, and recommended next work; and
- links to implementing tacticals.

## Current Topics

- [Product landscape and use cases](product-landscape-and-use-cases.md) —
  project origin, adjacent document/evidence/tax products, intended agent and
  human operator model, source-to-form review interaction, promising use
  cases, and product claims that require stronger guarantees.
- [Application platform](application-platform.md) — Python application/API
  boundary, generated TypeScript contracts, React runtime ownership,
  localhost/Tauri deployment direction, and the pinned `atpiano`, Yep
  Anywhere, JSTorrent, and signing-runbook precedents.
- [Library management](library-management.md) — desktop-first library model,
  application-home discovery and isolation, known/default-library registry,
  per-library database and artifact ownership, explicit collections, and
  scope expansion without unnecessary re-extraction.
- [Durable job architecture](job-architecture.md) — unified SQLite job state,
  worker supervision, resource-bounded scheduling, atomic artifact
  publication, cancellation, restart recovery, and operational UI.
- [Comparison and review workspace](comparison-review-workspace.md) — document
  representation labels, equivalent-output grouping, versioned diffs,
  numeric discrepancy priority, review semantics, and the path from the
  generated calibration page to the first-class product interface.
- [Spatial provenance and regional OCR](spatial-provenance-and-regional-ocr.md)
  — extractor geometry, coordinate spaces and transforms, bidirectional
  page/text selection, spatial comparison, bounded regional reruns, and the
  boundary between machine-preferred candidates and reviewed corrections.
- [Maintainer feature requests](maintainer-feature-requests.md) — live-review
  requests, their status, and the accepted behavior that future tacticals must
  preserve.
