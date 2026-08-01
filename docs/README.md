# Documentation

Start with:

1. [Product vision and application architecture](product-vision-and-architecture.md)
2. [Living topics](topics/README.md)
3. [Durable job architecture](topics/job-architecture.md)
4. [Implementation tacticals](tactical/README.md)
5. [Master plan](master-plan.md)
6. [Architecture](architecture.md)
7. [Data contracts](data-contracts.md)
8. [Benchmarking](benchmarking.md)
9. [References](references.md)
10. [Development](development.md)
11. [Phase 1 operations](operations.md)

The documents are deliberately explicit about source immutability,
provenance, cache versioning, and review boundaries. Those constraints are
part of the product rather than implementation notes.

Documentation roles:

- Durable architecture and contract documents own accepted long-lived system
  shape.
- `topics/` owns current truth for focused concerns that span implementation
  slices.
- `tactical/` owns numbered bounded plans and completed execution records.
- `references.md` records the exact sibling or external material that shaped a
  decision and what was intentionally not adopted.
