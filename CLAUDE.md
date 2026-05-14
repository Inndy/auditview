# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

**Backend** (Python, managed with `uv`):
```bash
uv run auditview <path>          # run server against a directory
uv run auditview --debug <path>  # enable debug/request logging
uv run python -m auditview <path>
```

**Frontend** (Vue 3, managed with `pnpm`):
```bash
cd ui
pnpm install
pnpm dev        # Vite dev server (proxies to backend at :5000 during development)
pnpm build      # build static assets into auditview/static/
pnpm lint       # oxlint + eslint (both with --fix)
pnpm format     # oxfmt formatter
```

**Publish:**
```bash
cd ui && pnpm build    # must run first — static/ is bundled into the Python package
uv build
make publish           # uv publish --username __token__
```

## Architecture

### Overview

Auditview is a line-level code review/audit tool: a Flask JSON API backend with a Vue 3 SPA frontend, served as static files from the same Flask process. The frontend is built into `auditview/static/` and committed; the Python package includes it.

```
auditview/          Python package
  __main__.py       CLI entry point (argparse → waitress)
  app.py            Flask factory: registers blueprints, starts WatcherService
  api/              Flask blueprints (one per resource: sessions, files, lines, notes, checkpoints, events, coverage, config)
  core/             Business logic (no Flask imports)
    reconciler.py   Migrates reviewed_lines/notes when files change
    watcher.py      watchdog-based file watcher; broadcasts SSE events
    scanner.py      Folder scan with gitignore exclusion (pathspec)
    coverage.py     Countable-line detection (heuristic per extension)
    hashing.py      line_hash / context_hash (SHA-256)
  db/
    connection.py   open_db(): returns apsw or sqlite3 wrapper with identical interface
    schema.py       DDL + incremental migrations (_MIGRATIONS list)
    checkpoint.py   apsw session extension for undo changesets

ui/src/
  views/            SessionListView, SessionView (top-level pages)
  components/       FileTree, CodeViewer, NotePanel, OrphanPanel, CheckpointPanel, …
  api/              Thin fetch wrappers (one file per resource, mirrors backend)
  App.vue           Global CSS variables, dark mode, typography
```

### Key Design Decisions

**Content-based line identity** — reviewed state is never tied to line numbers. Each `reviewed_lines` row stores `line_hash` (SHA-256 of content) + `context_hash` (SHA-256 of prev+curr+next) as a tiebreaker for duplicate lines. When a file changes, `reconciler.py` uses `difflib.SequenceMatcher` to map old line positions to new ones, migrating or deleting rows accordingly.

**Dual SQLite backend** — `open_db()` prefers `apsw` (enables checkpoint/undo via apsw session changesets) but falls back silently to stdlib `sqlite3`. The returned wrapper exposes a common interface; callers detect which is active via `conn._is_apsw` and index rows by position (`row[0]`) for apsw or by name (`row["col"]`) for sqlite3. Always handle both in new DB code.

**SSE for real-time** — no WebSockets. `WatcherService` holds one `queue.Queue` per connected client; `events.py` yields from the queue with a 15-second heartbeat. Client→server is always plain HTTP (mark, note, checkpoint actions).

**Vue Options API only** — Composition API is intentionally not used. Keep all new components in Options API style.

**`WatcherService` owns a persistent DB connection** for its reconcile thread. Each API request opens its own short-lived connection. Do not share connections across threads.

### Request / Update Flow

1. User drags line gutter → selects a range → presses `m`
2. `CodeViewer` calls `POST /api/sessions/:id/lines/mark` with `{file_path, lines: [{line_hash, context_hash, line_no}], reviewed: true}`
3. Backend inserts/deletes rows in `reviewed_lines`, returns `{updated: N}`
4. Frontend emits `lines-marked` → `SessionView` calls `fileTree.updateFile()` to recompute status/coverage locally (no refetch)
5. If a watched file changes on disk: watchdog → `WatcherService._process_change` → `reconcile_file` (DB transaction + apsw checkpoint) → SSE `file_changed` event → frontend refetches that file's lines

### Coverage Computation

`files.status` is computed per request in `api/files.py` by joining `files` with an aggregate of `reviewed_lines`:
- `reviewed` = `reviewed_lines >= countable_lines`
- `partial` = `0 < reviewed_lines < countable_lines`
- `not_viewed` = `reviewed_lines == 0`
- `empty` = `countable_lines == 0`

`countable_lines` is cached in the `files` table and recomputed by `reconciler.py` on every file change. The frontend also recomputes it locally in `FileTree.updateFile()` after marking to avoid a round-trip.

### Checkpoints

Every `reconcile_file()` call wraps its DB mutations in an apsw session changeset stored in the `checkpoints` table (auto-pruned to 1000 per session). Revert = apply the inverted changeset. When apsw is absent, `CheckpointManager.supports_checkpoints()` returns `False` and the UI surfaces a warning; core review functionality is unaffected.
