# doc-evidence

`doc-evidence` is a local-first pipeline for indexing documents, comparing
extractors, preserving provenance, and promoting reviewed observations into
downstream structured-data systems.

The project is intentionally domain-neutral. Its first real downstream case is
a private U.S.–Swiss tax workspace, but private documents and case-specific
facts do not belong in this Git repository.

## Status

Phase 0 scaffold. The repository currently defines the architecture, schemas,
benchmark method, safety boundary, and a minimal diagnostic command. It does
not yet index documents.

Read these first:

1. [Master plan](docs/master-plan.md)
2. [Architecture](docs/architecture.md)
3. [Data contracts](docs/data-contracts.md)
4. [Benchmark plan](docs/benchmarking.md)

## Core Principles

- Source documents are read-only.
- Every document is identified by a cryptographic content hash.
- Extraction outputs are derived, versioned, and reproducible.
- Candidate observations retain document and page provenance.
- Automated observations are never silently promoted to accepted facts.
- SQLite is a rebuildable catalog, not the sole home of review decisions.
- Extractors are adapters behind a stable contract.
- Use a fast deterministic baseline and escalate only difficult documents.
- Keep private datasets outside the Git repository.

## Development

This project targets Python 3.12 because current document/ML libraries may lag
the newest Python release. With `uv` installed:

```sh
uv sync
uv run doc-evidence doctor
uv run python -m unittest discover -s tests
```

The diagnostic command reports which external tools are currently available:

```sh
uv run doc-evidence doctor --json
```

## Intended Commands

The exact CLI is still a contract under development. The intended shape is:

```text
doc-evidence doctor
doc-evidence inventory --config PATH [COLLECTION]
doc-evidence extract --config PATH [COLLECTION]
doc-evidence benchmark --config PATH --suite NAME
doc-evidence search --config PATH QUERY
doc-evidence observations --config PATH [COLLECTION]
```

Only `doctor` and version reporting exist in the initial scaffold.

## Configuration

Case configuration stays with the case, not this repository. See
[`config.example.yaml`](config.example.yaml) and
[`schemas/config.schema.json`](schemas/config.schema.json).

Relative paths are resolved relative to the configuration file, making a case
workspace movable without teaching this tool its layout.
