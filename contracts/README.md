# Generated application contracts

`openapi.v1.json` is generated from the Python contract models and FastAPI
route graph. The TypeScript wire types and transport client under
`web/src/api/generated/` are generated from it.

Regenerate with:

```sh
npm run contracts:generate --prefix web
```

Check for drift with:

```sh
npm run contracts:check --prefix web
```

Generated files are checked in and must not be edited by hand.
