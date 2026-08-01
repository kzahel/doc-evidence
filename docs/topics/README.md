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

- [Application platform](application-platform.md) — Python application/API
  boundary, generated TypeScript contracts, React runtime ownership,
  localhost/Tauri deployment direction, and lessons from the sibling
  `atpiano` implementation.
- [Comparison and review workspace](comparison-review-workspace.md) — document
  representation labels, equivalent-output grouping, versioned diffs,
  numeric discrepancy priority, review semantics, and the path from the
  generated calibration page to the first-class product interface.
- [Maintainer feature requests](maintainer-feature-requests.md) — live-review
  requests, their status, and the accepted behavior that future tacticals must
  preserve.
