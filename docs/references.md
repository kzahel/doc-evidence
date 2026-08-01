# References

## Reference Policy

Use sibling projects and external implementations to understand proven
boundaries, validation approaches, and failure modes. Do not copy code
mechanically or allow another product's domain model to dictate
`doc-evidence` architecture.

When a reference materially shapes a tactical, record the exact document or
source path, inspected revision, behavior adopted, and intentional difference.
Private documents and extracted private content are never reference fixtures
for this generic repository.

## atpiano: Direct Application-Architecture Sibling

Repository: [kzahel/atpiano](https://github.com/kzahel/atpiano)  
Normal local checkout: `~/code/atpiano`  
Revision inspected for the initial application plan:
`87b77e9b0679f770a5f55e69546c7a1cb72fde46`

`atpiano` is the closest existing sibling because it has a shared React
application, Python domain/application core, local FastAPI composition,
generated TypeScript contracts, SQLite-backed features, a web/hosted path,
and a reviewed Tauri/Python-sidecar proof.

Read these before implementing the corresponding `doc-evidence` boundary:

- [Contracts and structure](https://github.com/kzahel/atpiano/blob/87b77e9b0679f770a5f55e69546c7a1cb72fde46/docs/tactical/015-contracts-and-structure.md)
  — Pydantic ownership, generated OpenAPI/TypeScript, checked drift, and a
  hand-owned frontend runtime interface.
- [Shared React application](https://github.com/kzahel/atpiano/blob/87b77e9b0679f770a5f55e69546c7a1cb72fde46/docs/tactical/016-shared-react-application.md)
  — React/Vite composition, TanStack Query versus Zustand ownership, fixture
  and local runtime adapters, and no transport knowledge in components.
- [Framework-independent Python core](https://github.com/kzahel/atpiano/blob/87b77e9b0679f770a5f55e69546c7a1cb72fde46/docs/tactical/017-python-application-core.md)
  — inward application services and thin filesystem, SQLite, HTTP, CLI, and
  worker adapters.
- [Durable worker isolation](https://github.com/kzahel/atpiano/blob/87b77e9b0679f770a5f55e69546c7a1cb72fde46/docs/tactical/022-durable-capture-worker-isolation.md)
  — bounded scheduler state, spawned worker isolation, prompt cancellation
  boundaries, explicit interruption, and restart-visible recovery. Tactical
  001 adopts those failure lessons for discrete document extraction jobs, not
  the sibling's streaming audio horizons or model lanes.
- [Early Tauri sidecar boundary](https://github.com/kzahel/atpiano/blob/87b77e9b0679f770a5f55e69546c7a1cb72fde46/docs/tactical/030-early-tauri-sidecar-boundary.md)
  — ephemeral loopback port, launch secret, exact-origin policy, authenticated
  handshake, thin Rust lifecycle ownership, and Python sidecar supervision.
- [Cross-platform artifact export](https://github.com/kzahel/atpiano/blob/87b77e9b0679f770a5f55e69546c7a1cb72fde46/docs/tactical/032-cross-platform-artifact-export.md)
  — streaming large authorized artifacts without platform branches in product
  components.
- [SQLite family authentication](https://github.com/kzahel/atpiano/blob/87b77e9b0679f770a5f55e69546c7a1cb72fde46/docs/tactical/033-sqlite-family-authentication.md)
  and [home-hosted family sharing](https://github.com/kzahel/atpiano/blob/87b77e9b0679f770a5f55e69546c7a1cb72fde46/docs/topics/home-hosted-family-sharing.md)
  — SQLAlchemy/Alembic migration precedent and a bounded local-hosted
  composition. These are later references, not first-slice scope.

The current `doc-evidence` application direction adopts the separation of
contracts, application services, runtime provider, and adapters. It does not
adopt the audio-session model, family authentication, model lifecycle, or
hosted deployment requirements.

For Tactical 001's supervised-attempt implementation, revision
`87b77e9b0679f770a5f55e69546c7a1cb72fde46` was inspected directly at
`docs/tactical/017-python-application-core.md`,
`docs/tactical/022-durable-capture-worker-isolation.md`,
`docs/tactical/032-cross-platform-artifact-export.md`,
`src/atpiano/model_worker.py`, `src/atpiano/corrected_export.py`, and
`src/atpiano/adapters/local_storage.py`. Adopted lessons are an inward
application boundary, spawned-worker isolation, bounded diagnostics,
cancellation that owns descendant processes, and fsync-backed atomic
publication. `doc-evidence` intentionally uses one discrete process group per
document/extractor attempt and a same-filesystem content-addressed rename; it
does not adopt streaming audio horizons, a long-lived model lane, or the
sibling's export destination model.

## Documentation-Structure Siblings

The documentation roles and tactical numbering conventions were compared with
the normal local checkouts of:

- `~/code/rstorrent`;
- `~/code/yepanywhere`; and
- `~/code/mclone`.

They are style and process references, not runtime dependencies. The adopted
common vocabulary is:

- durable architecture/reference docs for long-lived system shape;
- `docs/topics/` for living focused truth; and
- `docs/tactical/` for numbered bounded implementation slices and execution
  records.
