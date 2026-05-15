# CLAUDE.md

## Development Commands

**Backend** (Python, managed with `uv`):
```bash
uv run auditview [--debug] <path> # run server against a directory
```

**Frontend** (Vue 3, use `pnpm`):
```bash
cd ui
pnpm run build
pnpm run lint
pnpm run dev
```

**Dev server (for AI agent):**
- To pick up code changes, run `./scripts/dev-restart.sh`. It signals the running supervisors to relaunch in place.
- If it errors with "not running", start your own background server - do **not** invoke `./scripts/dev-start.sh`. That script is for a human in tmux only; it splits the current pane and would hijack your terminal.

## Architecture

### Overview

Auditview is a line-level code review/audit tool: a Quart (async) JSON API backend with a Vue 3 SPA frontend, served as static files from the same process. The frontend is built into `auditview/static/` and committed; the Python package includes it.

- auditview/core/ - business logic - no Quart imports here
- auditview/api/ - one Quart blueprint per resource (sessions, files, lines, …)
- auditview/db/ - aiosqlite wrapper (`open_db` async context manager)
- ui/src/api/ - fetch wrappers, file-per-resource mirrors backend

### Key Design Decisions

**Content-based line identity** - reviewed state is never tied to line numbers. Each `reviewed_lines` row stores `line_hash` (SHA-256 of content) + `context_hash` (SHA-256 of prev+curr+next) as a tiebreaker for duplicate lines. When a file changes, `reconciler.py` uses `difflib.SequenceMatcher` to map old line positions to new ones, migrating or deleting rows accordingly.

**aiosqlite with autocommit** - `open_db()` opens a connection with `isolation_level=None` (autocommit). Code that needs atomic writes uses explicit `await conn.execute("BEGIN")` / `await conn.commit()` / `await conn.rollback()`. All rows are `aiosqlite.Row` (dict-accessible by column name).

**SSE for real-time** - no WebSockets. `WatcherService` holds one `asyncio.Queue` per connected client; `events.py` yields from the queue with a 15-second heartbeat. Client→server is always plain HTTP (mark, note actions).

**Vue Options API only** - Composition API is intentionally not used. Keep all new components in Options API style.

**`WatcherService` uses asyncio.Queue for thread→async bridging** - watchdog runs file observer threads that post paths via `loop.call_soon_threadsafe`. An async worker task consumes and does all DB work. Each operation opens its own short-lived aiosqlite connection.

**MCP endpoint** - `/mcp` serves JSON-RPC 2.0. Tool handlers call existing REST endpoints internally via Quart's async test client.
