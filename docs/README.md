# Documentation

Start with:

1. [Product vision and application architecture](product-vision-and-architecture.md)
2. [Living topics](topics/README.md)
3. [Library management](topics/library-management.md)
4. [Durable job architecture](topics/job-architecture.md)
5. [Implementation tacticals](tactical/README.md)
6. [Master plan](master-plan.md)
7. [Architecture](architecture.md)
8. [Data contracts](data-contracts.md)
9. [Benchmarking](benchmarking.md)
10. [References](references.md)
11. [Development](development.md)
12. [Phase 1 operations](operations.md)

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
