# Contributing to auditview

Thanks for helping improve auditview. Bug reports, focused fixes, tests, and
documentation corrections are all welcome.

## Prerequisites

- Python 3.14+
- [uv](https://docs.astral.sh/uv/)
- Node.js 20.19+ or 22.12+
- pnpm 12.3.4 (the version pinned in `ui/package.json`)

Install dependencies from the repository root:

```bash
uv sync --group dev
pnpm --dir ui install --frozen-lockfile
```

## Checks

Run the relevant checks while developing, and all of them before opening a
pull request:

```bash
uv run --frozen pytest -q
pnpm --dir ui test
pnpm --dir ui lint
pnpm --dir ui build
```

`pnpm --dir ui lint:fix` applies safe lint fixes; `pnpm --dir ui format`
formats the frontend source explicitly.

## Project conventions

- Keep business logic under `auditview/core/`; it must not import Quart.
- Keep Vue components in Options API style.
- A reviewed line means a person read it. Agent integrations may create notes
  and issues, but must never mark lines reviewed.
- Update `API.md` in the same commit as any route, request/response shape,
  status-code, or error-code change.
- Add regression tests for bug fixes. Reconciler changes should also run the
  fuzz suite described in `CLAUDE.md`.
- Keep commits focused. Do not mix generated build output into source changes;
  `auditview/static/` is populated during packaging.

Please explain the user-visible behavior and verification performed in the
pull request. For security reports, follow `SECURITY.md` instead of opening a
public issue with exploit details.
