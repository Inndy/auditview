# auditview frontend

The frontend is a Vue 3 single-page application served by the auditview Python
process. See the [project README](../README.md) for product usage.

## Development

From the repository root:

```bash
pnpm --dir ui install --frozen-lockfile
pnpm --dir ui dev
```

Vite proxies `/api` to the backend at `http://localhost:5000`. In another
terminal, run the backend against a working directory:

```bash
uv run auditview /path/to/project
```

## Checks and build

```bash
pnpm --dir ui test
pnpm --dir ui lint
pnpm --dir ui build
```

`lint` is non-mutating. Use `lint:fix` for safe lint fixes and `format` for an
explicit formatting pass. Production output goes to `ui/dist/`; packaging
copies it into the ignored `auditview/static/` directory.

Components use the Vue Options API. Backend resource modules under `ui/src/api/`
mirror the REST blueprints, while `ui/src/input/actions.js` is the shared action
registry for keyboard and gamepad input.
