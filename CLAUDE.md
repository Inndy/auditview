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

Auditview is a line-level code review/audit tool: a Flask JSON API backend with a Vue 3 SPA frontend, served as static files from the same Flask process. The frontend is built into `auditview/static/` and committed; the Python package includes it.

- auditview/core/ - business logic - no Flask imports here
- auditview/api/ - one Flask blueprint per resource (sessions, files, lines, …)
- auditview/db/ - SQLite wrapper: apsw preferred, sqlite3 fallback (see Dual SQLite)
- ui/src/api/ - fetch wrappers, file-per-resource mirrors backend

### Key Design Decisions

**Content-based line identity** - reviewed state is never tied to line numbers. Each `reviewed_lines` row stores `line_hash` (SHA-256 of content) + `context_hash` (SHA-256 of prev+curr+next) as a tiebreaker for duplicate lines. When a file changes, `reconciler.py` uses `difflib.SequenceMatcher` to map old line positions to new ones, migrating or deleting rows accordingly.

**Dual SQLite backend** - `open_db()` prefers `apsw` (enables checkpoint/undo via apsw session changesets) but falls back silently to stdlib `sqlite3`. The returned wrapper exposes a common interface; callers detect which is active via `conn._is_apsw` and index rows by position (`row[0]`) for apsw or by name (`row["col"]`) for sqlite3. Always handle both in new DB code.

**SSE for real-time** - no WebSockets. `WatcherService` holds one `queue.Queue` per connected client; `events.py` yields from the queue with a 15-second heartbeat. Client→server is always plain HTTP (mark, note, checkpoint actions).

**Vue Options API only** - Composition API is intentionally not used. Keep all new components in Options API style.

**`WatcherService` owns a persistent DB connection** for its reconcile thread. Each API request opens its own short-lived connection. Do not share connections across threads.

**Checkpoints** - Every `reconcile_file()` call wraps its DB mutations in an apsw session changeset stored in the `checkpoints` table (auto-pruned to 50 per session). Revert = apply the inverted changeset. When apsw is absent, `CheckpointManager.supports_checkpoints()` returns `False` and the UI surfaces a warning; core review functionality is unaffected.
