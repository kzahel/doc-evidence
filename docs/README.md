# Documentation

Start with:

1. [Product vision and application architecture](product-vision-and-architecture.md)
2. [Living topics](topics/README.md)
3. [Implementation tacticals](tactical/README.md)
4. [Master plan](master-plan.md)
5. [Architecture](architecture.md)
6. [Data contracts](data-contracts.md)
7. [Benchmarking](benchmarking.md)
8. [References](references.md)
9. [Development](development.md)
10. [Phase 1 operations](operations.md)

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
